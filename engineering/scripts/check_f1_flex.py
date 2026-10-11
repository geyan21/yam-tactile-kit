#!/usr/bin/python3
"""Check F1 flex copper and preserve unsuppressed coverlay findings explicitly."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artwork", type=Path, help="Timestamped F1 artwork directory")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    source_run = args.artwork.resolve()
    if not source_run.is_relative_to(ROOT / "build/engineering/prototypes/f1/artwork_runs"):
        parser.error("Select an owned F1 artwork run")
    plan = json.loads((source_run / "artwork.json").read_text())
    for name, expected in plan["source_hashes"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Artwork inputs have changed; regenerate before checking: " + name)
    output = source_run / "independent_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    cli = ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/kicad-cli"
    environment = dict(os.environ)
    for category in ("CONFIG", "CACHE", "DATA"):
        environment["XDG_" + category + "_HOME"] = str(ROOT / "build/engineering/tools/f1-kicad" / category.lower())
    with execution(ROOT / "build/records", "Independently check each F1 flex with and without its explicit unsoldered-coverlay rule; retain every report and block unreviewed findings") as record:
        output.mkdir(parents=True, exist_ok=False)
        record["commands"] = []

        def run(arguments, cwd, label):
            command = [str(cli), *map(str, arguments)]
            with (cwd / (label + ".log")).open("w") as log:
                process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT)
                entry = {"command": command, "pid": process.pid}
                record["commands"].append(entry)
                try:
                    code = process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    record["intentional_stop_requests"].append(f"Stop owned F1 KiCad process {process.pid}: timeout")
                    process.kill(); process.wait()
                    raise RuntimeError("F1 KiCad check timed out")
            entry["exit_code"] = code
            if code:
                raise RuntimeError((cwd / (label + ".log")).read_text()[-2000:])

        run(["--version"], output, "version")
        results = []
        for board in plan["boards"]:
            name = board["name"]; source = (ROOT / board["directory"]).resolve()
            if not source.is_relative_to(source_run) or not re.fullmatch(r"f1_ch[0-5]_(rows|columns)", name):
                raise ValueError("Unexpected F1 board directory")
            data = json.loads((source / (name + ".json")).read_text())
            pcb_path = source / (name + ".kicad_pcb")
            rule_path = source / (name + ".kicad_dru")
            if digest(pcb_path) != data["pcb_sha256"] or digest(rule_path) != data["rules_sha256"]:
                raise ValueError("PCB or rules changed after generation")
            if not data["geometry_checks"]["passed"]:
                raise ValueError("Resolve the source geometry findings first")
            pcb_text = pcb_path.read_text()
            if re.search(r'\(layers?[^)]*"[FB]\.Paste"[^)]*\)', pcb_text):
                raise ValueError("The unsoldered foil allowance cannot be used with solder-paste objects")
            pad_ids = re.findall(r'\(pad "([^"]+)"', pcb_text)
            if len(pad_ids) != len(set(pad_ids)) or "net_tie_pad_groups" in pcb_text or "pad_jumper_groups" in pcb_text:
                raise ValueError("F1 connectivity must be physical copper, without implicit jumper/net-tie connections")
            rules = rule_path.read_text()
            pattern = r"# BEGIN_FPC_SHARED_COVERLAY\n[\s\S]*?# END_FPC_SHARED_COVERLAY\n"
            blocks = re.findall(pattern, rules)
            if len(blocks) != 1 or "(constraint bridged_mask)" not in blocks[0]:
                raise ValueError("Expected one explicit shared-coverlay rule block")
            if (blocks[0].count("(rule ") != 1 or blocks[0].count("(constraint ") != 1
                    or blocks[0].count("(severity ignore)") != 1
                    or '(condition "A.memberOfFootprint(\'FOIL\')")' not in blocks[0]):
                raise ValueError("The allowance must affect only the FOIL bridged-mask constraint")
            baseline_rules = re.sub(pattern, "", rules)
            if "(severity ignore)" in baseline_rules or "(severity exclusion)" in baseline_rules:
                raise ValueError("Unexpected rule suppression outside the reviewed coverlay block")
            checked = output / name; checked.mkdir()
            reports = {}
            for kind in ("unsuppressed", "manufacturing_intent"):
                case = checked / kind; case.mkdir()
                shutil.copyfile(pcb_path, case / pcb_path.name)
                shutil.copyfile(source / "fp-lib-table", case / "fp-lib-table")
                shutil.copytree(source / "F1.pretty", case / "F1.pretty")
                (case / rule_path.name).write_text(baseline_rules if kind == "unsuppressed" else rules)
                run(["pcb", "drc", "--format", "json", "--all-track-errors", "--save-board",
                     "--output", case / "drc.json", case / pcb_path.name], case, "drc")
                reports[kind] = json.loads((case / "drc.json").read_text())
            raw = reports["unsuppressed"]; intent = reports["manufacturing_intent"]
            raw_unreviewed = [item for item in raw["violations"] if item["type"] != "solder_mask_bridge"]
            # All aperture and affected copper members must belong to the one
            # unsoldered foil footprint. Never classify a soldered component.
            if any("of FOIL" not in item["description"]
                   for finding in raw["violations"] if finding["type"] == "solder_mask_bridge"
                   for item in finding.get("items", [])):
                raise ValueError("A coverlay finding reaches an object outside FOIL")
            result = {
                "name": name, "source_pcb_sha256": digest(pcb_path), "source_rules_sha256": digest(rule_path),
                "source_metadata_sha256": digest(source / (name + ".json")),
                "physical_copper_layers": data["physical_layers"],
                "unsuppressed_coverlay_findings": len(raw["violations"]) - len(raw_unreviewed),
                "unsuppressed_other_findings": len(raw_unreviewed),
                "manufacturing_intent_findings": len(intent["violations"]),
                "unconnected": len(raw["unconnected_items"]) + len(intent["unconnected_items"]),
                "scope": "Copper/connectivity plus explicitly reviewed, unsoldered shared coverlay windows",
                "physical_specimens_tested": 0, "installed_finger_qualified": False,
            }
            result["passed"] = not any(result[key] for key in
                ("unsuppressed_other_findings", "manufacturing_intent_findings", "unconnected"))
            (checked / "checks.json").write_text(json.dumps(result, indent=2) + "\n")
            results.append(result)
            print(json.dumps(result), flush=True)
            if not result["passed"]:
                continue
            if args.export:
                case = checked / "manufacturing_intent"
                manufacture = checked / "development_fabrication"; manufacture.mkdir()
                raw_export = checked / "raw_exports"; raw_export.mkdir()
                layers = ["F.Cu", "F.Mask", "F.SilkS", "Edge.Cuts", "Dwgs.User", "F.Fab", "B.Fab"]
                if data["physical_layers"] == 2:
                    layers.extend(["B.Cu", "B.Mask"])
                run(["pcb", "export", "gerbers", "--layers", ",".join(layers),
                     "--output", str(raw_export) + "/", case / pcb_path.name], case, "gerbers")
                run(["pcb", "export", "drill", "--format", "excellon",
                     "--output", str(raw_export) + "/", case / pcb_path.name], case, "drill")
                for path in raw_export.iterdir():
                    # KiCad keeps an even number of copper slots. Its generic
                    # job stack is not this physical polyimide flex stack.
                    if path.is_file() and path.suffix != ".gbrjob":
                        shutil.copyfile(path, manufacture / path.name)
                (manufacture / "FPC_STACK.json").write_text(json.dumps({
                    "physical_copper_layers": data["physical_layers"],
                    "covered_nominal_thickness_mm": data["covered_thickness_mm"],
                    "polyimide_core_nominal_mm": .025,
                    "copper_nominal_mm_per_layer": .035,
                    "coverlay_nominal_mm_where_present": .05,
                    "note": "Development target only. Exposed and stiffened regions have different thickness. Do not use a generic FR4/even-layer job stack; finish the complete manufacturing drawing before ordering."
                }, indent=2) + "\n")
                (manufacture / "DEVELOPMENT_ONLY.txt").write_text(
                    "Flat F1 routing-development output; not the completed installed-finger package.\n"
                    "No solder paste is used on this flex. Shared coverlay windows expose separate sensing/connector nets.\n"
                    "Copper clearances and connectivity are independently checked; both DRC reports are preserved.\n"
                    "Tail routing, physical stack, resistance, assembly and sensor performance still require completion/validation.\n")
                file_hashes = {path.name: digest(path) for path in sorted(manufacture.iterdir()) if path.is_file()}
                (checked / "development_export.json").write_text(json.dumps(
                    {"files": file_hashes, "physical_layers": data["physical_layers"], "release_ready": False}, indent=2) + "\n")
                with zipfile.ZipFile(checked / (name + "_development.zip"), "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(manufacture.iterdir()):
                        if path.is_file():
                            archive.write(path, path.name)
                    archive.write(checked / "checks.json", "checks.json")
                    archive.write(checked / "development_export.json", "development_export.json")
        summary = {"tool": (output / "version.log").read_text().strip(), "boards": results,
                   "all_passed": bool(results) and all(row["passed"] for row in results),
                   "artwork_manifest_sha256": digest(source_run / "artwork.json"),
                   "checker_source_sha256": digest(Path(__file__)),
                   "physical_specimens_tested": 0, "complete_f1_package": False}
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        (source_run / "latest_independent_check.json").write_text(json.dumps(
            {"directory": str(output.relative_to(ROOT)), "all_passed": summary["all_passed"]}, indent=2) + "\n")
        record["result"] = summary
        if not summary["all_passed"]:
            raise ValueError("F1 artwork has unresolved independent findings")
        print(json.dumps({"all_passed": True, "boards": len(results),
                          "directory": str(output.relative_to(ROOT)), "complete_f1_package": False}, indent=2))


if __name__ == "__main__":
    main()
