#!/usr/bin/python3
"""Package an independently checked F1 wrist module as unfinished development."""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--check", type=Path, required=True)
    parser.add_argument("--visuals", type=Path, required=True)
    parser.add_argument("--mating", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / "engineering/development/f1/wrist")
    args = parser.parse_args()
    board, checked, visuals, mating, destination = (p.resolve() for p in
        (args.board, args.check, args.visuals, args.mating, args.destination))
    if not all(path.is_relative_to(ROOT) for path in (board, checked, visuals, mating, destination)):
        parser.error("Use repository-owned inputs and destination")
    if destination.exists():
        parser.error("Preserve checkpoints; choose a new destination for a revision")
    summary = json.loads((checked / "summary.json").read_text())
    data = json.loads((board / "f1_wrist.json").read_text())
    view = json.loads((visuals / "visual_review.json").read_text())
    cable = json.loads((mating / "report.json").read_text())
    if not summary["passed"] or summary["violations"] or summary["unconnected"]:
        raise ValueError("Every independent DRC/connectivity finding must be resolved")
    if digest(board / "f1_wrist.kicad_pcb") != summary["source_pcb_sha256"]:
        raise ValueError("Board differs from the independent check")
    if digest(board / "f1_wrist.json") != summary["source_manifest_sha256"]:
        raise ValueError("Geometry differs from the independent check")
    if view["independent_check_sha256"] != digest(checked / "summary.json"):
        raise ValueError("Visuals use a different check")
    for name, expected in view["files"].items():
        if digest(visuals / name) != expected:
            raise ValueError("A reviewed visual changed")
    if not cable["passed"] or cable["wrist_source_sha256"] != data["pcb_sha256"]:
        raise ValueError("Mating correspondence uses another wrist board")
    source_spec = board / "generation_inputs/specification.json"
    specification = json.loads(source_spec.read_text())
    config_path = ROOT / "engineering/designs/f1_wrist_development.json"
    config_hash = specification["input_hashes"]["engineering/designs/f1_wrist_development.json"]
    if digest(config_path) != config_hash:
        raise ValueError("Current wrist configuration differs from the generated board")
    firmware_dir = ROOT / "engineering/firmware/f1"
    firmware_config = json.loads((firmware_dir / "config.json").read_text())
    if firmware_config["wrist_configuration_sha256"] != config_hash:
        raise ValueError("Regenerate the matching firmware configuration")
    with execution(ROOT / "build/records", "Package the checked F1 wrist PCB, drawings, pin map and experimental code without claiming an assembled or qualified tactile finger") as record:
        destination.mkdir(parents=True, exist_ok=False)
        pcb_dir, check_dir, art, images, code, cables = (destination / name for name in
                                                       ("pcb", "checks", "artwork", "visuals", "code", "cable"))
        for folder in (pcb_dir, check_dir, art, images, code, cables):
            folder.mkdir()
        for name in ("f1_wrist.kicad_pcb", "f1_wrist.kicad_dru", "f1_wrist.json", "f1_wrist_pins.csv", "fp-lib-table"):
            shutil.copyfile(board / name, pcb_dir / name)
        shutil.copytree(checked / "F1.pretty", pcb_dir / "F1.pretty")
        shutil.copyfile(source_spec, pcb_dir / "specification.json")
        for name in ("summary.json", "drc.json"):
            shutil.copyfile(checked / name, check_dir / name)
        shutil.copyfile(checked / "f1_wrist.kicad_pcb", check_dir / "checked_f1_wrist.kicad_pcb")
        for name, expected in summary["development_exports_sha256"].items():
            path = checked / "development_files" / name
            if digest(path) != expected:
                raise ValueError("Changed fabrication export")
            shutil.copyfile(path, art / name)
        for path in visuals.iterdir():
            if path.is_file():
                shutil.copyfile(path, images / path.name)
        for name in ("front_assembly.svg", "rear_assembly.svg", "inner_ground.svg"):
            shutil.copyfile(checked / name, images / name)
        for path in mating.iterdir():
            if path.is_file():
                shutil.copyfile(path, cables / path.name)
        for name in ("main.py", "hardware.py", "scan.py", "config.json"):
            shutil.copyfile(firmware_dir / name, code / name)
        shutil.copyfile(ROOT / "engineering/docs/F1_WRIST_CAPTURE.md", code / "CAPTURE_GUIDE.md")
        configs = destination / "configuration"; configs.mkdir()
        for name in ("f1_wrist_development.json", "f1_feedback_screen.json", "f1_adc_stage.json",
                     "f1_row_stage.json", "f1_wrist_manufacturing_targets.json"):
            shutil.copyfile(ROOT / "engineering/designs" / name, configs / name)
        with (destination / "components.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["reference", "part_or_value", "library_footprint", "face", "source", "selection_status"])
            for part in data["parts"]:
                writer.writerow([part["reference"], part["value"], part["library"], part["side"], part.get("source", ""),
                                 "candidate device/connector" if part.get("source") else "value/package; purchasing MPN and derating still require review"])
        readme = (
            "# F1 wrist readout — development module\n\n"
            "**This is one board of an unfinished F1 tactile finger. No physical board or sensor has been tested.**\n\n"
            f"The checked layout has {len(data['parts'])} components, {len(data['pads'])} pads, "
            f"{len(data['tracks'])} track segments and {len(data['vias'])} vias. "
            "Independent KiCad checking reports zero rule violations and zero missing connections.\n\n"
            "![Checked wrist copper and component envelopes](visuals/wrist_faces.png)\n\n"
            "The sensor film and flexible electrodes remain on the two nail and four TPU patches. "
            "This wrist board contains the row drivers, separate column current/sense multiplexers, "
            "gain/parking circuit, ADC, reference and Pico sockets. No rigid ADC package goes in a flexible contact pad.\n\n"
            "- `pcb/`: editable native board, library, exact pin table and placement specification.\n"
            "- `artwork/`: four copper layers, both populated faces and drill exports.\n"
            "- `checks/`: complete DRC report, hashes and checked board.\n"
            "- `visuals/`: board-face, assembly and inner-ground drawings.\n"
            "- `cable/`: native fifty-pin correspondence and blank unpowered continuity checklist.\n"
            "- `code/`: four-file experimental Pico firmware and capture instructions.\n"
            "- `configuration/`: current candidate circuit and manufacturing targets.\n"
            "- `components.csv`: exact active parts plus passive values/packages; passive purchasing choices remain.\n\n"
            "The selected cable contract gives wrist pin n to fanout pin 51−n. It does not establish actual "
            "continuity, seating, strain relief or installed geometry. The column electrical test can pass "
            "with the sensor foils unplugged; it is not a tactile or whole-wiring qualification.\n\n"
            "From the repository root, recheck without changing this checkpoint:\n\n"
            "```sh\n/usr/bin/python3 engineering/scripts/verify_f1_checkpoint.py engineering/development/f1/wrist\n"
            "/usr/bin/python3 engineering/scripts/check_f1_wrist.py engineering/development/f1/wrist/pcb --export\n```\n\n"
            "Prepare the isolated KiCad tool with `engineering/scripts/prepare_b1_eda.py --extract` if needed. "
            "Fresh check/export results go under `build/`. Read "
            "`engineering/docs/F1_WRIST_CAPTURE.md` for GPIO, ADC sequencing and raw capture. "
            "The main source also includes the recorder, protocol validator and tests; firmware emits no calibrated force.\n\n"
            "Complete the full-array/reference/layout review, formed flex, carrier, actual YAM fit, passive "
            "component/derating review and physical experiments before treating F1 as an integrated result. "
            "Retain the earlier readout and ADC/row studies with their failed attempts and model limits. "
            "These files establish no contact-error probability, force accuracy, bending life or 20 N rating.\n"
        )
        (destination / "README.md").write_text(readme)
        checkpoint = {
            "schema": "yam-f1-wrist-development-checkpoint/1", "created_utc": datetime.now(timezone.utc).isoformat(),
            "integrated_f1_completed": False, "physical_specimens_tested": 0,
            "independent_check": summary,
            "source_locations": {"board": str(board.relative_to(ROOT)), "check": str(checked.relative_to(ROOT)),
                                 "visuals": str(visuals.relative_to(ROOT)), "mating": str(mating.relative_to(ROOT))},
            "files_sha256": {str(path.relative_to(destination)): digest(path)
                             for path in sorted(destination.rglob("*")) if path.is_file()},
            "archiver_sha256": digest(Path(__file__)),
        }
        (destination / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2)+"\n")
        record["checkpoint"] = {"directory": str(destination.relative_to(ROOT)), "files": len(checkpoint["files_sha256"]),
                                "sha256": digest(destination / "checkpoint.json")}
        print(json.dumps(record["checkpoint"], indent=2))


if __name__ == "__main__":
    main()
