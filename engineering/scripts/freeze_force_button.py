#!/usr/bin/python3
"""Freeze an FB1 digital prototype only after its matched checks pass."""

import argparse
import csv
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def check_files(base, files):
    for name, expected in files.items():
        if digest(base / name) != expected:
            raise ValueError("Changed checked file: "+str(base / name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cad", "fit", "board", "screen", "numerics", "visuals", "structure"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / "engineering/prototypes/force_button")
    args = parser.parse_args()
    paths = {n: getattr(args, n).resolve() for n in ("cad", "fit", "board", "screen", "numerics", "visuals", "structure")}
    target = args.destination.resolve()
    if target.exists() or not all(p.is_relative_to(ROOT) for p in (*paths.values(), target)):
        parser.error("Use repository-owned inputs and a new prototype destination")
    plan = json.loads((paths["cad"] / "manifest.json").read_text())
    check_files(ROOT, plan["input_sha256"])
    fit = json.loads((paths["fit"] / "report.json").read_text())
    if (not fit["passed_declared_checks"] or not fit["sensor_contact"]["passed"]
            or fit["source_manifest_sha256"] != digest(paths["cad"] / "manifest.json")):
        raise ValueError("Unresolved or mismatched geometry")
    native = json.loads((paths["board"] / "fb1_sensor.json").read_text())
    latest = json.loads((paths["board"] / "latest_check.json").read_text())
    checked = paths["board"] / latest["directory"]
    pcb = json.loads((checked / "pcb_checks.json").read_text())
    if (pcb["violations"] or pcb["unconnected"] or latest["source_sha256"] != native["pcb_sha256"]
            or pcb["source_sha256"] != digest(paths["board"] / "fb1_sensor.kicad_pcb")
            or pcb["checked_pcb_sha256"] != digest(checked / "fb1_sensor.kicad_pcb")
            or native["specification_sha256"] != digest(ROOT / "engineering/designs/force_button_electronics.json")):
        raise ValueError("Unresolved or stale PCB")
    check_files(checked / "manufacturing", pcb["files"])
    numerical = json.loads((paths["numerics"] / "report.json").read_text())
    if not numerical["passed"]:
        raise ValueError("Numerical checks failed")
    check_files(ROOT, numerical["source_sha256"])
    screen = json.loads((paths["screen"] / "report.json").read_text())
    check_files(ROOT, screen["input_sha256"])
    structural = json.loads((paths["structure"] / "report.json").read_text())
    if not structural["convergence"]["passed"] or not structural["motion_screen_met"]:
        raise ValueError("Complete the structural mesh and provisional motion checks")
    if not {.0001, .0005} <= set(structural["sensor_compliance_cases_mm_per_n"]):
        raise ValueError("Retain both declared sensor-compliance endpoint scenarios")
    visual = json.loads((paths["visuals"] / "report.json").read_text())
    check_files(ROOT, visual["input_sha256"])
    check_files(paths["visuals"], visual["files_sha256"])
    with execution(ROOT / "build/records", "Freeze the matched FB1.1 CAD, native PCB, raw firmware, physical-test tools and structural checks; preserve the earlier marginal design and every physical-evidence limitation") as record:
        target.mkdir(parents=True, exist_ok=False)
        for name in ("cad", "pcb", "firmware", "software", "visuals", "checks", "history", "provenance"):
            (target / name).mkdir()
        for part in plan["parts"]:
            for suffix in ("step", "stl"):
                source = paths["cad"] / part[suffix]
                if digest(source) != part["sha256_"+suffix]:
                    raise ValueError("Part changed: "+part["id"])
                shutil.copyfile(source, target / part[suffix])
        shutil.copyfile(paths["cad"] / "manifest.json", target / "force_button_manifest.json")
        shutil.copyfile(paths["visuals"] / "models.json", target / "models.json")
        for name in visual["files_sha256"]:
            if name != "models.json":
                shutil.copyfile(paths["visuals"] / name, target / "visuals" / name)
        for source in paths["structure"].glob("fb1_structural_screen.*"):
            shutil.copyfile(source, target / "visuals" / source.name)
        for label, source in (("fit", paths["fit"]), ("beam_screen", paths["screen"]),
                              ("numerics", paths["numerics"]), ("visuals", paths["visuals"]),
                              ("structure", paths["structure"])):
            shutil.copyfile(source / "report.json", target / "checks" / (label+".json"))
        for name in ("fb1_sensor.kicad_dru", "fb1_sensor.json", "fb1_sensor_pins.csv", "specification.json", "fp-lib-table"):
            shutil.copyfile(paths["board"] / name, target / "pcb" / name)
        shutil.copyfile(paths["board"] / "fb1_sensor.kicad_pcb", target / "pcb/fb1_sensor.source.kicad_pcb")
        for name in ("fb1_sensor.kicad_pcb", "drc.json", "pcb_checks.json", "fb1_sensor_fabrication.zip"):
            shutil.copyfile(checked / name, target / "pcb" / name)
        shutil.copytree(paths["board"] / "FB1.pretty", target / "pcb/FB1.pretty")
        shutil.copytree(checked / "manufacturing", target / "pcb/manufacturing")
        for source in (ROOT / "engineering/firmware/force_button").iterdir():
            if source.is_file() and source.suffix in (".py", ".json"):
                shutil.copyfile(source, target / "firmware" / source.name)
        with zipfile.ZipFile(target / "fb1_firmware.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for source in sorted((target / "firmware").iterdir()):
                archive.write(source, source.name)
        for name in ("force_button_protocol.py", "force_button_record.py", "force_button_force.py"):
            shutil.copyfile(ROOT / "engineering/software" / name, target / "software" / name)
        for name in ("force_button_fb1.json", "force_button_electronics.json"):
            shutil.copyfile(ROOT / "engineering/designs" / name, target / "provenance" / name)
        shutil.copyfile(ROOT / "engineering/designs/force_button_bom.csv", target / "bom.csv")
        with (target / "bom.csv").open() as stream:
            if any(len(row) != 6 for row in csv.reader(stream)):
                raise ValueError("Malformed bill of materials")
        shutil.copyfile(ROOT / "engineering/templates/force_button_force_trials.json", target / "force_trials.template.json")
        with (target / "parts.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["id", "kind", "purpose", "material", "STEP", "STL"])
            for part in plan["parts"]:
                writer.writerow([part["id"], part["kind"], part["purpose"], part["material"], part["step"], part["stl"]])
        with zipfile.ZipFile(target / "fb1_structural_inputs.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for index, entry in enumerate(structural["inputs"]):
                source = ROOT / entry["directory"]
                if digest(source / "report.json") != entry["report_sha256"]:
                    raise ValueError("Structural result changed")
                for name in ("mesh.inp", "fb1.inp", "preload.inp", "report.json"):
                    archive.write(source / name, f"run_{index}/{name}")
                for path in sorted((source / "inputs").rglob("*")):
                    if path.is_file():
                        archive.write(path, f"run_{index}/inputs/"+str(path.relative_to(source / "inputs")))
            archive.writestr("README.txt",
                "FB1.1 linear bonded-metal structural inputs. Units N, mm, MPa.\n"
                "Run the documented CalculiX 2.23 executable with -i fb1, then -i preload, in each run directory.\n"
                "The full repository's run_force_button_fea.py provides generation and postprocessing.\n"
                "Large raw solver outputs remain in the working build directories and can be regenerated.\n"
                "No physical accuracy, fatigue or moving-robot qualification is represented.\n")
        for name in ("force_button_fb1_040.json", "force_button_fb1_040_history.md"):
            shutil.copyfile(ROOT / "engineering/designs" / name, target / "history" / name)
        old_root = ROOT / "build/engineering/prototypes/force_button/fea"
        for name, run in (("guide040_sensor2um", "20261011T193850.271464Z"),
                          ("guide040_sensor10um", "20261011T194319.440476Z")):
            shutil.copyfile(old_root / run / "report.json", target / "history" / (name+".json"))
        stopped = old_root / "STOPPED_SESSION_67979.md"
        shutil.copyfile(stopped, target / "history" / stopped.name)
        shutil.copytree(paths["cad"] / "reference_tessellation", target / "reference_tessellation")
        (target / "provenance/source_runs.json").write_text(json.dumps(
            {"source_runs": {n: str(p.relative_to(ROOT)) for n, p in paths.items()},
             "cad_manifest_sha256": digest(paths["cad"] / "manifest.json"),
             "native_pcb_receipt_sha256": digest(checked / "pcb_checks.json")}, indent=2)+"\n")
        shutil.copyfile(ROOT / "engineering/development/f1/r3/SOURCE_GEOMETRY_LICENSE", target / "SOURCE_GEOMETRY_LICENSE")
        (target / "SOURCE_ATTRIBUTION.md").write_text(
            "# Source geometry and libraries\n\n"
            "The reference frame and TPU come from Open-ENPIRE-Gripper (pgeedh/Open-ENPIRE-Gripper), "
            "which credits Wenli Xiao's ENPIRE finger and MakerWorld model 2984746. The pinned source repository "
            "declares Apache-2.0; its license is included. The new FB1 carriers, guide mechanism, board and code "
            "are kit development. The bench receiver is reused from this kit's C1 design.\n\n"
            "KiCad passive footprints retain their library license and attribution under pcb/FB1.pretty. "
            "The FMA package is our functional envelope from published manufacturer dimensions; vendor STEP "
            "files and complete proprietary data sheets are not redistributed. Gmsh and CalculiX tool "
            "versions/provenance are recorded; their executables are not bundled.\n")
        (target / "README.md").write_text(
            "# FB1.1 force-button root prototype\n\n"
            "**54 CAD parts/references, checked sensor PCB, raw firmware and physical calibration tools. "
            "Physical specimens tested: 0.**\n\n"
            "Sensor: Honeywell FMAMSDXX025WC2C3, 25 N, 3.3 V, I2C 0x28. It sits at the root, with its "
            "sphere facing a flat adjustable plunger. Four 0.50 mm steel guides locate the floating carrier. "
            "The original nail and TPU retain their contact geometry; root reach increases 50 mm.\n\n"
            "Use the separate force-button.html page, build-force-button.html and force-button-testing.html "
            "on the published site. In the complete source repository, the matching documents are "
            "engineering/docs/BUILD_FORCE_BUTTON.md and FORCE_BUTTON_TESTING.md.\n\n"
            "CAD-stage readiness in force_button_manifest.json describes mechanical generation alone. "
            "The final package checks are recorded in prototype_snapshot.json. Hardware envelopes are "
            "references, not printable functional sensors or screws. Helical threads are manufacturing callouts.\n\n"
            "The earlier 0.40 mm guide study is retained in history/; its softer-sensor scenario exceeded "
            "the provisional 0.1 mm motion target. Current structural results are in checks/structure.json "
            "and visuals/fb1_structural_screen.png. Their scope is a bonded, linear model, not real-joint "
            "or physical force qualification.\n\n"
            "Firmware ZIP: four files for one Pico. Software scripts preserve raw data, failures and "
            "held-out sessions. Run host capture/calibration commands from the complete repository, "
            "which supplies src/tactile_kit/records.py. No physical force model or contact rule is bundled.\n\n"
            "Set preload and all three overload gaps by independent measurement. Verify the actual "
            "drive interface, bolt lengths, cable loops, clamp slip, loaded clearances and tip motion. "
            "Factory nominal sensor newtons do not equal calibrated finger force.\n")
        sources = [ROOT / "engineering/designs" / n for n in ("force_button_fb1.json", "force_button_electronics.json", "force_button_bom.csv")]
        sources += list((ROOT / "engineering/scripts").glob("*force_button*.py"))
        sources += list((ROOT / "engineering/firmware/force_button").glob("*.py"))
        sources += [ROOT / "engineering/firmware/force_button/config.json"]
        sources += list((ROOT / "engineering/software").glob("force_button_*.py"))
        sources += [ROOT / "engineering/web/fb1_stack.svg", ROOT / "engineering/web/fb1_wiring.svg"]
        snapshot = {"schema": "yam-prototype-snapshot/1", "id": "FORCE_BUTTON", "revision": "FB1.1",
                    "design_label": "FB1", "design_page": "force-button.html",
                    "status": "Digital prototype build files; fabrication and physical qualification pending",
                    "physical_specimens_tested": 0,
                    "shared_release_sha256": digest(ROOT / "engineering/release/release_manifest.json"),
                    "source_hashes": {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(sources))},
                    "files": {str(p.relative_to(target)): digest(p) for p in sorted(target.rglob("*")) if p.is_file()},
                    "checks": {"cad_parts": len(plan["parts"]),
                               "declared_geometry_checks": len(fit["checks"])+len(fit["stop_faces"])+len(fit["vent_checks"])+1,
                               "sphere_plunger_contact": True, "drc_violations": 0, "unconnected_items": 0,
                               "numerical_verification": True, "structural_convergence": True,
                               "motion_screen_with_mesh_allowance_mm": structural["motion_screen_with_mesh_allowance_mm"],
                               "physical_qualification": False}}
        (target / "prototype_snapshot.json").write_text(json.dumps(snapshot, indent=2)+"\n")
        record["result"] = {"directory": str(target.relative_to(ROOT)), "files": len(snapshot["files"]), **snapshot["checks"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
