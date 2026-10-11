#!/usr/bin/python3
"""Freeze B3's checked digital package and verify every retained earlier release."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/prototypes/recessed"
TARGET = ROOT / "engineering/prototypes/recessed"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root, entries):
    for name, expected in entries.items():
        if digest(root / name) != expected:
            raise ValueError("Input or checked artifact changed: " + str(root / name))


def main():
    with execution(ROOT / "build/records", "Freeze B3 separate CAD, readout, visuals and stated magnetic/clearance evidence; preserve previous packages") as record:
        release = ROOT / "engineering/release"
        baseline = json.loads((release / "release_manifest.json").read_text())
        verify(ROOT, baseline["source_hashes"]); verify(release, baseline["files"])
        for path in sorted((ROOT / "engineering/prototypes").glob("*/prototype_snapshot.json")):
            if path.parent == TARGET:
                continue
            previous = json.loads(path.read_text())
            verify(ROOT, previous["source_hashes"]); verify(path.parent, previous["files"])
        cfg = json.loads((ROOT / "engineering/designs/recessed.json").read_text())
        plan = json.loads((OUTPUT / "recessed_manifest.json").read_text())
        field = json.loads((OUTPUT / "recessed_magnetic_review.json").read_text())
        clearance = json.loads((OUTPUT / "recessed_clearance_review.json").read_text())
        packet = json.loads((OUTPUT / "packet_inputs.json").read_text())
        visuals = json.loads((OUTPUT / "visual_inputs.json").read_text())
        for report in (plan, field, clearance, packet, visuals):
            verify(ROOT, report["source_hashes"])
        for report in (packet, visuals):
            verify(OUTPUT, report["files"])
        if len(plan["parts"]) != 5:
            raise ValueError("Expected four B3 fabricated parts and one PCB reference")
        for part in plan["parts"]:
            if not all(part["checks"].values()):
                raise ValueError("B3 CAD checks incomplete")
            for suffix in ("step", "stl"):
                if digest(OUTPUT / part[suffix]) != part["sha256_" + suffix]:
                    raise ValueError("B3 CAD changed after checking")
        if any(abs(loss) > 1e-5 for loss in plan["protected_material_removed_mm3"].values()):
            raise ValueError("Protected frame regions changed")
        if max(plan["rigid_overlap_mm3"].values()) > 1e-5 or any(
                row["missing_seat_support_mm3"] > .005 for row in plan["supports"]):
            raise ValueError("B3 seating or rigid geometry failed")
        if plan["minimum_front_package_frame_gap_mm"] < cfg["mechanical"]["frame_component_clearance_mm"] - .002:
            raise ValueError("B3 front clearance is inadequate")
        if max(clearance["rigid_overlaps_mm3"].values()) > 1e-5 or clearance[
                "minimum_moving_to_electronics_and_support_gap_bound_mm"] < .5:
            raise ValueError("Declared B3 clearance envelope failed")
        recessed_field = field["planes"][1]
        if (not field["quadrature_check"]["passed"] or not recessed_field["imc_screen_met"]
                or recessed_field["highest_gain_passing_sampled_screen"] != cfg["readout"]["gain_sel"]
                or recessed_field["pcb_plane_native_x_mm"] != plan["pcb_component_plane_x_mm"]):
            raise ValueError("B3 magnetic settings or numerical check do not match")
        firmware = json.loads((OUTPUT / "firmware/firmware_manifest.json").read_text())
        verify(OUTPUT / "firmware", firmware["files"])
        for name, source in firmware["source_paths"].items():
            if digest(ROOT / source) != firmware["files"][name]:
                raise ValueError("B3 firmware package is stale")
        if firmware["gain_sel"] != cfg["readout"]["gain_sel"] or firmware["protocol"] != "yam-b3/1":
            raise ValueError("Wrong B3 firmware configuration")
        with zipfile.ZipFile(OUTPUT / "recessed_firmware.zip") as archive:
            for name, expected in firmware["files"].items():
                if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                    raise ValueError("Firmware ZIP does not match its files")
        TARGET.mkdir(parents=True, exist_ok=True)
        for name in ("cad", "firmware"):
            shutil.copytree(OUTPUT / name, TARGET / name, dirs_exist_ok=True)
        names = (
            "recessed_manifest.json", "models.json", "recessed_assembly.png", "recessed_exploded.png",
            "recessed_placement.svg", "recessed_stack.svg", "recessed_stack.png",
            "recessed_review_drawings.pdf", "recessed_bom.csv", "recessed-wiring.svg",
            "recessed_sensor_placement.csv", "recessed_firmware.zip",
            "recessed_clearance_review.json", "recessed_magnetic_review.json",
            "recessed_magnetic_screen.svg", "recessed_magnetic_screen.png",
            "visual_inputs.json", "packet_inputs.json",
        )
        for name in names:
            shutil.copyfile(OUTPUT / name, TARGET / name)
        (TARGET / "NOTICE.md").write_text(
            "# B3.1 experimental recessed prototype\n\n"
            "Original ENPIRE geometry: Wenli Xiao / NVIDIA ENPIRE. Source provenance and pinned meshes "
            "are documented in engineering/docs/GEOMETRY.md. This frame is a faceted derivative of the "
            "source STL, not the author's original analytic CAD.\n\n"
            "B3 supplies a separately recessed PETG frame and tapered locating spacers. It retains "
            "the B2.1 PCB and removable backer shape, B1 TPU/magnets and R1 N0 nail cells. "
            "Its firmware uses gain 5 and protocol yam-b3/1; physical calibration is separate.\n\n"
            "The package verifies digital solid geometry, stated clearances and a sampled magnetic "
            "range model. It has no structural force prediction, physical build, installed-drive "
            "qualification, measured contact/force performance or production-yield result. "
            "The +2 mm side-motion scenario is not a permitted-travel or 20 N rating.\n")
        sources = [
            ROOT / "engineering/designs/recessed.json", ROOT / "engineering/designs/recessed_field_screen.json",
            ROOT / "engineering/scripts/source_brep.py", ROOT / "engineering/scripts/prototype_cad.py",
            ROOT / "engineering/scripts/model_b1_field.py", ROOT / "engineering/scripts/draw_l1.py",
            ROOT / "engineering/firmware/b1/main.py", ROOT / "engineering/firmware/b1/mlx90393.py",
            ROOT / "engineering/software/b1_protocol.py", ROOT / "engineering/software/raw_capture.py",
            ROOT / "engineering/prototypes/b2/prototype_snapshot.json",
            ROOT / "engineering/release/b1/b1_manifest.json", ROOT / "engineering/release/b1/models.json",
            ROOT / "engineering/release/models.json", ROOT / "engineering/b2_bom.csv",
            ROOT / "engineering/web/b2-wiring.svg",
        ]
        sources += list((ROOT / "engineering/scripts").glob("*recessed*.py"))
        sources += list((ROOT / "engineering/software").glob("recessed_*.py"))
        sources += [path for path in (ROOT / "engineering/firmware/recessed").iterdir() if path.is_file()]
        snapshot = {
            "schema": "yam-prototype-snapshot/1", "id": "RECESSED", "revision": "B3.1",
            "status": "digital prototype; physical assembly and qualification pending",
            "physical_specimens_tested": 0,
            "shared_release_sha256": digest(release / "release_manifest.json"),
            "shared_b2_snapshot_sha256": digest(ROOT / "engineering/prototypes/b2/prototype_snapshot.json"),
            "source_hashes": {str(path.relative_to(ROOT)): digest(path) for path in sorted(set(sources))},
            "files": {str(path.relative_to(TARGET)): digest(path) for path in sorted(TARGET.rglob("*"))
                      if path.is_file() and path.name != "prototype_snapshot.json"},
            "checks": {"cad_parts": 5, "reserved_hardware_checks": len(clearance["rigid_overlaps_mm3"]),
                       "gain_sel": cfg["readout"]["gain_sel"], "sampled_magnetic_range_check": True,
                       "installed_drive_verified": False, "structural_force_prediction": False,
                       "physical_qualification": False},
        }
        (TARGET / "prototype_snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        record["snapshot"] = {"files": len(snapshot["files"]), **snapshot["checks"]}
        print(json.dumps(record["snapshot"], indent=2))


if __name__ == "__main__":
    main()
