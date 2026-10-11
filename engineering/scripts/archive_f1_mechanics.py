#!/usr/bin/python3
"""Publish the checked F1 mechanical fit work as an explicitly partial module."""

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
    for name in ("stack", "surface", "carrier", "fit", "check", "placement", "routes", "exits", "visual"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--failed-check", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / "engineering/development/f1/mechanics")
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in
             ("stack", "surface", "carrier", "fit", "check", "placement", "routes", "exits", "visual", "failed_check", "destination")}
    if not all(path.is_relative_to(ROOT) for path in paths.values()):
        parser.error("Use repository-owned source and destination paths")
    destination = paths["destination"]
    if destination.exists():
        parser.error("Preserve prior checkpoints; select a fresh destination")
    stack = json.loads((paths["stack"] / "stack_manifest.json").read_text())
    carrier = json.loads((paths["carrier"] / "carrier_manifest.json").read_text())
    fit = json.loads((paths["fit"] / "fit_manifest.json").read_text())
    check = json.loads((paths["check"] / "report.json").read_text())
    route = json.loads((paths["routes"] / "report.json").read_text())
    placement = json.loads((paths["placement"] / "placement_check.json").read_text())
    if not (carrier["passed_declared_static_checks"] and check["passed_declared_checks"]
            and route["nominal_lanes_passed"] == 12 and placement["passed"]):
        raise ValueError("Resolve the declared static findings before archiving this fit module")
    for source in (paths["fit"] / "fit_manifest.json", paths["carrier"] / "carrier_manifest.json"):
        if check["input_sha256"].get(str(source.relative_to(ROOT))) != digest(source):
            raise ValueError("The final collision report uses another geometry revision")
    with execution(ROOT / "build/records", "Archive F1 fit CAD, twelve actual-size patterns, surface data, source-matched static checks and the preserved crossing failure; keep the integrated finger status incomplete") as record:
        destination.mkdir(parents=True, exist_ok=False)
        for folder in ("cad", "patterns", "checks", "visuals", "configuration", "surface-data", "placement"):
            (destination / folder).mkdir()
        parts = []
        for source, manifest in ((paths["stack"], stack), (paths["carrier"], carrier), (paths["fit"], fit)):
            for part in manifest["parts"]:
                if not all(part["checks"].values()):
                    raise ValueError("A CAD export has unresolved round-trip checks")
                for field in ("step", "stl"):
                    original = source / part[field]
                    if digest(original) != part["sha256_"+field]:
                        raise ValueError("CAD artifact changed: "+part["id"])
                    target = destination / "cad" / original.name
                    if target.exists():
                        raise ValueError("Duplicate CAD identifier")
                    shutil.copyfile(original, target)
                parts.append(part)
        for pattern in fit["patterns"]:
            for suffix in ("svg", "pdf"):
                name = pattern["name"]+"."+suffix
                shutil.copyfile(paths["fit"] / "patterns" / name, destination / "patterns" / name)
        reports = [
            (paths["stack"] / "stack_manifest.json", "stack.json"),
            (paths["carrier"] / "carrier_manifest.json", "carrier.json"),
            (paths["fit"] / "fit_manifest.json", "fit_patterns.json"),
            (paths["check"] / "report.json", "nominal_3d.json"),
            (paths["routes"] / "report.json", "tail_routes.json"),
            (paths["exits"] / "report.json", "source_exit_sections.json"),
            (paths["failed_check"] / "report.json", "previous_crossing_failure.json"),
        ]
        for source, name in reports:
            shutil.copyfile(source, destination / "checks" / name)
        history = destination / "history" / "previous_crossing"
        history.mkdir(parents=True)
        failed = json.loads((paths["failed_check"] / "report.json").read_text())
        old_manifest_key = next(key for key in failed["input_sha256"] if key.endswith("/fit_manifest.json"))
        old_manifest_path = ROOT / old_manifest_key
        if digest(old_manifest_path) != failed["input_sha256"][old_manifest_key]:
            raise ValueError("The preserved crossing geometry changed")
        old_fit = json.loads(old_manifest_path.read_text())
        involved = {row[key] for row in failed["findings"] for key in ("a", "b")}
        for part in old_fit["parts"]:
            if part["id"] not in involved:
                continue
            for field in ("step", "stl"):
                original = old_manifest_path.parent / part[field]
                if digest(original) != part["sha256_"+field]:
                    raise ValueError("Changed predecessor CAD")
                shutil.copyfile(original, history / original.name)
        shutil.copyfile(old_manifest_path, history / "original_fit_manifest.json")
        (history / "README.md").write_text(
            "# Preserved crossing example\n\n"
            "These are the two exact tail solids involved in the earlier CH2-column / CH3-row crossing. "
            "Their common volume was 0.03376448474123263 mm³. The complete earlier report is "
            "`../../checks/previous_crossing_failure.json`. The original manifest retains provenance "
            "for that older run; only its two involved CAD parts are copied into this example. "
            "Current fit files are under `../../cad/` and `../../patterns/`.\n")
        for source in paths["surface"].glob("*"):
            if source.suffix in (".csv", ".json"):
                shutil.copyfile(source, destination / "surface-data" / source.name)
        for source, stem in (
                (paths["check"], "nominal_assembly"), (paths["visual"], "sensor_placement"),
                (paths["routes"], "tail_routes"), (paths["stack"], "stack_bodies"),
                (paths["surface"], "stack_surfaces"), (paths["carrier"], "carrier_assembly"),
                (paths["placement"], "tab_placement"), (paths["exits"], "exit_sections")):
            for suffix in ("png", "svg", "pdf"):
                shutil.copyfile(source / (stem+"."+suffix), destination / "visuals" / (stem+"."+suffix))
        shutil.copyfile(paths["visual"] / "sensor_placement.json", destination / "surface-data" / "sensor_placement.json")
        for name in ("specification.json", "placement_check.json"):
            shutil.copyfile(paths["placement"] / name, destination / "placement" / name)
        for name in ("f1_formed_stack.json", "f1_carrier_development.json", "f1_fanout_r2.json",
                     "f1_tail_route_development.json", "f1_exit_spaced_candidate.json"):
            shutil.copyfile(ROOT / "engineering/designs" / name, destination / "configuration" / name)
        source_license = ROOT / "build/engineering/sources/pgeedh__Open-ENPIRE-Gripper/LICENSE"
        shutil.copyfile(source_license, destination / "SOURCE_GEOMETRY_LICENSE")
        (destination / "SOURCE_ATTRIBUTION.md").write_text(
            "# Original finger geometry\n\n"
            "The reference frame/TPU meshes come from "
            "[Open-ENPIRE-Gripper](https://github.com/pgeedh/Open-ENPIRE-Gripper), "
            "which credits Wenli Xiao's original ENPIRE fingertip and its "
            "[MakerWorld profile](https://makerworld.com/en/models/2984746-gripper-finger-for-robot-arm#profileId-3349177). "
            "The source repository declares Apache-2.0; its pinned license is copied alongside this notice. "
            "Hashes of the exact source geometry used here are retained in the check reports. "
            "The original frame and TPU remain reference geometry. The F1 laminate, tails, carrier, "
            "forming tools and accompanying studies are new development work in this kit.\n")
        components = json.loads((paths["check"] / "assembly_models.json").read_text())
        for component in components:
            if component["group"] == "source":
                component["group"] = "frame" if component["name"] == "original_hard_frame" else "tpu"
            elif component["group"].startswith("CH"):
                component["group"] = "f1_stacks"
            else:
                component["group"] = "f1_"+component["group"]
            component["explosion"] = {
                "f1_board": [5, 0, 0], "f1_components": [5, 0, 0],
                "f1_carrier": [2, 0, 0], "f1_tails": [0, 0, -5],
                "f1_stacks": [0, 0, -5], "f1_fastener_envelopes": [7, 0, 0],
            }.get(component["group"], [0, 0, 0])
        model = {
            "id": "f1_assembly_reference", "title": "F1 nominal mechanical fit study",
            "coordinates": "native_mm", "assembly": True, "components": components,
            "note": "Partial integration references: exact connector cavities, stiffeners, fitted copper, seal, motion slack and physical qualification remain. No complete or physically validated F1 finger is claimed.",
        }
        (destination / "models.json").write_text(json.dumps([model], separators=(",", ":"))+"\n")
        with (destination / "parts.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["part", "kind", "material", "purpose", "STEP", "STL"])
            for part in parts:
                writer.writerow([part["id"], part["kind"], part["material"], part["purpose"], part["step"], part["stl"]])
        with (destination / "fit_observations.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["specimen_id", "operator", "date", "site", "role", "connector",
                             "scale_bar_measured_mm", "seated_tip_local_y_mm", "contact_plane_height_mm",
                             "rubbing_or_pinch", "passive_motion_mm", "photo_path", "notes"])
            for pattern in fit["patterns"]:
                writer.writerow(["", "", "", "CH"+str(pattern["site"]), pattern["role"], pattern["connector"],
                                 "", "", "", "", "", "", ""])
        readme = f"""# F1 mechanics — fit development module

This module contains **{len(parts)} checked CAD solids and twelve actual-size
fit patterns**. It is a reproducible mechanical fit experiment, not a
completed tactile finger or a functional flex fabrication release.
There are zero physical specimens and no measured 20 N result.

![Sensor choice and location](visuals/sensor_placement.png)

The sensor is a separate pressure-film island between row and column
electrodes at each of two nail and four TPU sites. The rigid electronics
stay on the fixed finger side and at the wrist.

- `cad/`: six forming mandrels, one carrier, and separately labeled material,
  PCB and tail reference solids. Print the tools/carrier; reference foils
  do not become sensors when printed.
- `patterns/`: twelve SVG/PDF patterns. Print at 100% and measure the 50 mm bar.
  Cut paper or approximately 0.1 mm polyester for the fit trial.
- `placement/`: R2 component/connector locations and their placement check.
  This is not routed PCB artwork.
- `surface-data/`: each conductor reference's developed length and the
  proposed contact allocation.
- `checks/`: source, stack, carrier, route and final 3D checks, plus the
  preserved earlier crossing failure.
- `configuration/`: candidate dimensions used in this module.
- `fit_observations.csv`: blank student observations; it contains no measurements.

![Nominal integration](visuals/nominal_assembly.png)

The final static comparison checks {len(check['pairs'])} pairs against the
source frame/TPU, carrier, PCB, other tails and closed component/head
envelopes. The declared checks pass. **Twelve connector cavity/mating
interfaces remain explicitly unqualified.** The earlier 0.03376 mm³
CH2-column/CH3-row crossing is retained in `checks/previous_crossing_failure.json`.

The two back M2 fasteners retain the removable R2 board; the unused front
holes have been removed. The two original frame side-fastener axes locate
the carrier. Actual screw engagement, nut fit, printed shrinkage, board
bending and installed drive clearance remain.

The nominal conductor bend radius is 2.5 mm. Its inner material surface is
smaller by the relevant layer offset. These are geometric references, not
fatigue limits. Do not crease the marked bends. A static fitted shape does
not establish an inextensible 3 mm motion solution.

Row and column lengths differ on the curved surfaces. The largest nominal
body cut-length difference in the archived surface study is about 0.130 mm.
The paper pattern also includes a new body-end extension. Seal retention,
own-layer joins, contact preload and loaded behavior require physical work.

Read `engineering/docs/BUILD_F1.md` in the complete source for the student
procedure and `engineering/docs/F1_WRIST_CAPTURE.md` for electronics/code.
The preserved original fanout has different upper connector orientations;
do not combine that PCB with these R2 patterns.

Fitted electrode copper, connector stiffeners and verified mating datums,
full resistance/coupled-array checks, sealing and tail slack remain before
an integrated F1 build. Then perform physical contact, held-out force,
bending, wear and precision-task comparisons across independent specimens.
"""
        (destination / "README.md").write_text(readme)
        checkpoint = {
            "schema": "yam-f1-mechanics-development-checkpoint/1",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Static fit references and tools; integrated F1 incomplete",
            "integrated_f1_completed": False, "physical_specimens_tested": 0,
            "cad_solids": len(parts), "fit_patterns": len(fit["patterns"]),
            "independent_check": {"passed": True, "kind": "nominal_static_geometry",
                                  "pairs": len(check["pairs"]), "unqualified_connector_interfaces": 12,
                                  "scope": "Declared static reference checks only; no copper, motion or physical qualification"},
            "source_locations": {key: str(value.relative_to(ROOT)) for key, value in paths.items() if key != "destination"},
            "archiver_sha256": digest(Path(__file__)),
            "files_sha256": {str(p.relative_to(destination)): digest(p)
                             for p in sorted(destination.rglob("*")) if p.is_file()},
        }
        (destination / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2)+"\n")
        record["result"] = {"directory": str(destination.relative_to(ROOT)), "files": len(checkpoint["files_sha256"]),
                            "cad_solids": len(parts), "patterns": len(fit["patterns"]),
                            "sha256": digest(destination / "checkpoint.json")}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
