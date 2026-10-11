#!/usr/bin/python3
"""Independently check K1 flex connectivity, native lands and exported material stack."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_native_pcb import pcb, mm, digest


def audit(board_path, data):
    board = pcb.LoadBoard(str(board_path))
    if board.GetCopperLayerCount() != 2:
        raise ValueError("K1 flex must have exactly two copper layers")
    thickness = pcb.ToMM(board.GetDesignSettings().GetBoardThickness())
    if abs(thickness-data["stack_total_mm"]) > 1e-6:
        raise ValueError("Native board thickness differs from the flex contract")
    footprints = list(board.GetFootprints())
    if len(footprints) != 1 or footprints[0].GetReference() != "FOIL":
        raise ValueError("Unexpected K1 foil component identities")
    pads = {pad.GetNumber(): pad for pad in footprints[0].Pads()}
    expected_names = {r["id"]+"_COPPER" for r in data["regions"]} | {"1", "2", "SHIELD_TRANSITION"}
    if set(pads) != expected_names:
        raise ValueError("Native pad inventory changed")
    for row in data["regions"]:
        pad = pads[row["id"]+"_COPPER"]
        if pad.GetNetname() != row["net"] or not pad.IsOnLayer(board.GetLayerID(row["layer"])):
            raise ValueError("Sensing/guard copper identity changed")
        if pad.IsOnLayer(pcb.F_Mask) or pad.IsOnLayer(pcb.B_Mask) or pad.IsOnLayer(pcb.F_Paste):
            raise ValueError("Active copper must remain covered")
    for row in data["pads"]:
        pad = pads[str(row["pin"])]
        if pad.GetNetname() != row["net"] or max(abs(a-b) for a, b in zip(mm(pad.GetPosition()), row["center"])) > 1e-6:
            raise ValueError("Termination net or position changed")
        if not pad.IsOnLayer(pcb.F_Mask) or pad.IsOnLayer(pcb.F_Paste) or pad.IsOnLayer(pcb.B_Mask):
            raise ValueError("Only the two top hand-solder lands may be opened")
    via = pads["SHIELD_TRANSITION"]
    if (via.GetNetname() != "SHLD" or via.GetAttribute() != pcb.PAD_ATTRIB_PTH
            or abs(mm(via.GetDrillSize())[0]-data["via"]["drill_mm"]) > 1e-6
            or not via.IsOnLayer(pcb.F_Cu) or not via.IsOnLayer(pcb.B_Cu)):
        raise ValueError("The backed plated shield transition is incorrect")
    return {"native_pad_count": len(pads), "native_copper_layers": 2, "native_thickness_mm": thickness,
            "only_terminal_lands_open": True, "native_pin_map": {"1": "CIN", "2": "SHLD"},
            "shield_transition": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("native_set", type=Path)
    parser.add_argument("--kicad-cli", type=Path, default=ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/kicad-cli")
    args = parser.parse_args()
    source = args.native_set.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/capacitive"):
        parser.error("Use a generated K1 native flex set")
    plan = json.loads((source / "report.json").read_text())
    folder = source / "independent_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check each K1 flex board using native KiCad DRC, independently read its pad/net contract and verify actual Gerber-job materials before exporting artwork") as record:
        folder.mkdir(parents=True, exist_ok=False)
        results = []
        environment = dict(os.environ)
        for category in ("CONFIG", "CACHE", "DATA"):
            environment["XDG_"+category+"_HOME"] = str(ROOT / "build/engineering/tools/k1-flex-kicad" / category.lower())

        def run(command, log):
            child_environment = dict(environment)
            if str(command[0]) == "/usr/bin/python3":
                # KiCad's portable launcher owns a Python 3.11 runtime.
                # Do not pass that runtime prefix to the system interpreter.
                for name in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH"):
                    child_environment.pop(name, None)
            with log.open("w") as stream:
                process = subprocess.Popen(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT, env=child_environment)
                entry = {"argv": list(map(str, command)), "pid": process.pid}
                record.setdefault("commands", []).append(entry)
                try:
                    code = process.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    entry["intentional_stop"] = "50 second limit on this owned PCB check/export process"
                    process.terminate(); process.wait(timeout=5); raise
                entry["returncode"] = code
                if code:
                    raise RuntimeError(log.read_text()[-3000:])

        for item in plan["boards"]:
            name = item["name"]
            if not re.fullmatch(r"k1_(ch[0-5]|ref)_flex", name):
                raise ValueError("Unexpected board name")
            board_dir = source / item["directory"]
            data = json.loads((board_dir / (name+".json")).read_text())
            if item["pcb_sha256"] != digest(board_dir / (name+".kicad_pcb")):
                raise ValueError("Unreviewed board modification")
            run(["/usr/bin/python3", ROOT / "engineering/scripts/check_prototype_pcb.py", board_dir,
                 "--name", name, "--kicad-cli", args.kicad_cli], folder / (name+"_drc.log"))
            latest = json.loads((board_dir / "latest_check.json").read_text())
            checked = board_dir / latest["directory"]
            row = {"name": name, "directory": str(checked.relative_to(ROOT)),
                   "violations": latest["violations"], "unconnected": latest["unconnected"],
                   "source_pcb_sha256": item["pcb_sha256"], "physical_boards_tested": 0}
            if row["violations"] or row["unconnected"]:
                results.append(row)
                (folder / "partial.json").write_text(json.dumps(results, indent=2)+"\n")
                print((folder / (name+"_drc.log")).read_text()[-5000:], flush=True)
                raise ValueError("Unresolved native findings; fabrication export refused")
            row.update(audit(checked / (name+".kicad_pcb"), data))
            manufacture = checked / "manufacturing"; manufacture.mkdir()
            run([args.kicad_cli, "pcb", "export", "gerbers", "--output", str(manufacture)+"/",
                 "--layers", "F.Cu,B.Cu,F.Mask,B.Mask,Edge.Cuts", checked / (name+".kicad_pcb")], folder / (name+"_gerbers.log"))
            run([args.kicad_cli, "pcb", "export", "drill", "--output", str(manufacture)+"/", "--format", "excellon",
                 checked / (name+".kicad_pcb")], folder / (name+"_drill.log"))
            job = json.loads((manufacture / (name+"-job.gbrjob")).read_text())
            if (job["GeneralSpecs"]["LayerNumber"] != 2
                    or job["GeneralSpecs"].get("ImpedanceControlled", False)
                    or abs(job["GeneralSpecs"]["BoardThickness"]-data["stack_total_mm"]) > 1e-6):
                raise ValueError("Gerber job stack thickness differs")
            materials = job["MaterialStackup"]
            copper = [r for r in materials if r["Type"] == "Copper"]
            dielectric = [r for r in materials if r["Type"] == "Dielectric"]
            coverings = [r for r in materials if r["Type"] in ("SolderMask", "Coverlay")]
            if (len(copper) != 2 or len(dielectric) != 1 or len(coverings) != 2
                    or any(abs(r["Thickness"]-data["stack"]["copper_each_mm"]) > 1e-6 for r in copper)
                    or dielectric[0].get("Material") != "Polyimide"
                    or abs(dielectric[0]["Thickness"]-data["stack"]["polyimide_core_mm"]) > 1e-6
                    or any(abs(r["Thickness"]-data["stack"]["coverlay_each_mm"]) > 1e-6 for r in coverings)):
                raise ValueError("Native exported materials do not match the requested flex stack")
            row.update({"checked_pcb_sha256": digest(checked / (name+".kicad_pcb")),
                        "native_material_stack_checked": True, "material_stack": materials,
                        "files_sha256": {p.name: digest(p) for p in manufacture.iterdir() if p.is_file()},
                        "status": "Native copper, terminations and material stack checked; formed fit and physical qualification remain"})
            (checked / "pcb_checks.json").write_text(json.dumps(row, indent=2)+"\n")
            with zipfile.ZipFile(checked / (name+"_fabrication.zip"), "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(manufacture.iterdir()):
                    archive.write(path, path.name)
                archive.write(board_dir / "FABRICATION.md", "FABRICATION.md")
                archive.write(checked / "pcb_checks.json", "pcb_checks.json")
            results.append(row)
            (folder / "partial.json").write_text(json.dumps(results, indent=2)+"\n")
            print(name+": native copper, pins and stack passed", flush=True)
        report = {"schema": "yam-k1-native-flex-checks/1", "source_set_sha256": digest(source / "report.json"),
                  "boards": results, "passed": True, "physical_boards_tested": 0,
                  "limits": "Native board and fabrication contract checks; not installed fit, material capability, capacitance, force or contact qualification."}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "boards": len(results),
                            "violations": 0, "unconnected": 0, "physical_boards_tested": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
