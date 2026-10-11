#!/usr/bin/python3
"""Independently check the separate F1 R2 fanout and export both faces."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

CLI = ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/kicad-cli"
TARGETS = ROOT / "engineering/designs/f1_fanout_manufacturing_targets.json"
LIBRARY_LICENSE = ROOT / "engineering/third_party/kicad_library_LICENSE.md"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board_directory", type=Path)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    source = args.board_directory.resolve()
    if not source.is_relative_to(ROOT):
        parser.error("Use a repository-owned F1 fanout directory")
    name = "f1_fanout_r2"
    pcb_path = source / (name + ".kicad_pcb")
    manifest_path = source / (name + ".json")
    manifest = json.loads(manifest_path.read_text())
    if digest(pcb_path) != manifest["pcb_sha256"]:
        raise ValueError("Board differs from its native placement/routing manifest")
    if not manifest["tracks"] or not manifest["vias"]:
        raise ValueError("Use a fully routed development board")
    rules = source / (name + ".kicad_dru")
    if "ignore" in rules.read_text().lower() or "exclusion" in rules.read_text().lower():
        raise ValueError("F1 rigid board has no authorized rule exclusions")
    # Rechecking a distributed source snapshot must not add generated results
    # to that versioned directory.
    output = ROOT / "build/engineering/prototypes/f1/fanout_r2_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check F1 rigid-board copper, drill spacing and connectivity; export both populated faces only after clean KiCad DRC") as record:
        output.mkdir(parents=True, exist_ok=False)
        for path in (pcb_path, manifest_path, rules, source / "fp-lib-table", TARGETS, Path(__file__)):
            shutil.copyfile(path, output / path.name)
        for library in source.glob("*.pretty"):
            shutil.copytree(library, output / library.name)
            shutil.copyfile(LIBRARY_LICENSE, output / library.name / "LICENSE.md")
        env = dict(os.environ)
        for category in ("CONFIG", "CACHE", "DATA"):
            env["XDG_"+category+"_HOME"] = str(ROOT / "build/engineering/tools/f1-kicad" / category.lower())
        record["commands"] = []

        def run(arguments, label):
            command = [str(CLI), *arguments]
            with (output / (label + ".log")).open("w") as stream:
                process = subprocess.Popen(command, cwd=output, env=env,
                                           stdout=stream, stderr=subprocess.STDOUT)
                receipt = {"argv": command, "pid": process.pid}
                record["commands"].append(receipt)
                try:
                    code = process.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    receipt["intentional_stop"] = "50 s limit on this owned KiCad export/check"
                    process.terminate(); process.wait(timeout=10)
                    raise
                receipt["returncode"] = code
                if code:
                    print((output / (label + ".log")).read_text()[-5000:])
                    raise RuntimeError(f"KiCad {label} exited {code}")

        checked_pcb = output / pcb_path.name
        run(["--version"], "version")
        run(["pcb", "drc", "--refill-zones", "--save-board", "--format", "json",
             "--all-track-errors", "--output", str(output / "drc.json"), str(checked_pcb)], "drc")
        drc = json.loads((output / "drc.json").read_text())
        findings = drc.get("violations", []) + drc.get("unconnected_items", [])
        summary = {
            "schema": "yam-f1-fanout-r2-check/1",
            "tool": (output / "version.log").read_text().strip(),
            "violations": len(drc.get("violations", [])),
            "unconnected": len(drc.get("unconnected_items", [])),
            "source_pcb_sha256": digest(pcb_path),
            "source_manifest_sha256": digest(manifest_path),
            "rules_sha256": digest(rules), "targets_sha256": digest(TARGETS),
            "library_license_sha256": digest(LIBRARY_LICENSE),
            "checked_pcb_sha256": digest(checked_pcb),
            "physical_boards_tested": 0, "passed": not findings,
            "scope": "Native copper/outline/drill/silkscreen rules and PCB connectivity. Circuit operation, cable mating, carrier/tail fit, sensor behavior and force performance are outside this result."
        }
        (output / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
        record["checks"] = summary
        print(json.dumps({"directory": str(output.relative_to(ROOT)), **summary}, indent=2))
        for item in findings[:20]:
            print(item["type"], item["description"], " | ".join(p["description"] for p in item.get("items", [])))
        if findings:
            raise ValueError("Resolve every preserved DRC/connectivity finding before exporting")
        if not args.export:
            return
        raw = output / "raw_exports"
        raw.mkdir()
        run(["pcb", "export", "gerbers", "--output", str(raw)+"/",
             "--layers", "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Mask,B.Mask,F.SilkS,B.SilkS,Edge.Cuts",
             str(checked_pcb)], "gerbers")
        run(["pcb", "export", "drill", "--format", "excellon", "--output", str(raw)+"/",
             str(checked_pcb)], "drills")
        for label, layers, mirror in (
                ("outer_assembly", "F.Fab,F.SilkS,F.Cu,Edge.Cuts", []),
                ("inner_assembly", "B.Fab,B.SilkS,B.Cu,Edge.Cuts", ["--mirror"])):
            run(["pcb", "export", "svg", "--mode-single", "--output", str(output / (label+".svg")),
                 "--layers", layers, "--page-size-mode", "2", "--sketch-pads-on-fab-layers",
                 "--exclude-drawing-sheet", *mirror, str(checked_pcb)], label)
        manufacture = output / "development_files"
        manufacture.mkdir()
        for path in sorted(raw.iterdir()):
            # Default job files can imply a dielectric/copper stack that was
            # never selected. Preserve them raw, not as purchasing authority.
            if path.is_file() and path.suffix != ".gbrjob":
                shutil.copyfile(path, manufacture / path.name)
        required = ("F_Cu", "In1_Cu", "In2_Cu", "B_Cu", "F_Paste", "B_Paste",
                    "F_Mask", "B_Mask", "F_Silkscreen", "B_Silkscreen", "Edge_Cuts")
        filenames = [p.name for p in manufacture.iterdir()]
        missing = [layer for layer in required if not any(layer in filename for filename in filenames)]
        if missing:
            raise ValueError(f"Expected both PCB faces and all copper layers; absent exports: {missing}")
        shutil.copyfile(TARGETS, manufacture / TARGETS.name)
        (manufacture / "DEVELOPMENT_ONLY.txt").write_text(
            "F1 fanout revision 2 development artwork. Independent copper/connectivity DRC passed.\n"
            "This is one board of an unfinished tactile finger, not a complete fabrication release.\n"
            "Request 1 oz copper on ALL FOUR layers; default 0.5 oz inner copper is not this target.\n"
            "The physical dielectric stack and finished copper minima require supplier review.\n"
            "Carrier, formed flex, cable mating, analog loop stability, firmware and force/contact tests remain.\n"
            "No physical specimen or measured performance result exists in this package.\n")
        files = {p.name: digest(p) for p in sorted(manufacture.iterdir()) if p.is_file()}
        summary["development_exports_sha256"] = files
        (output / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
        with zipfile.ZipFile(output / (name + "_development.zip"), "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(manufacture.iterdir()):
                archive.write(path, path.name)
            archive.write(output / "summary.json", "summary.json")
        print("Both-face development artwork exported after clean independent DRC.")


if __name__ == "__main__":
    main()
