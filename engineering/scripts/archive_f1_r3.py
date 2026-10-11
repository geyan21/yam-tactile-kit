#!/usr/bin/python3
"""Publish the checked R3 interface board and its matching nominal fit files."""

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

NAMES = ("board", "check", "copper", "ground", "mating", "visuals", "placement",
         "carrier", "fit", "fit_check", "stack", "tail_routes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in NAMES:
        parser.add_argument("--"+name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / "engineering/development/f1/r3")
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in NAMES}
    destination = args.destination.resolve()
    if not all(path.is_relative_to(ROOT) for path in [*paths.values(), destination]):
        parser.error("Use repository-owned inputs and destination")
    if destination.exists():
        parser.error("Preserve checkpoints; use a separate destination for a revision")
    data = json.loads((paths["board"] / "f1_fanout_r3.json").read_text())
    summary = json.loads((paths["check"] / "summary.json").read_text())
    copper = json.loads((paths["copper"] / "report.json").read_text())
    ground = json.loads((paths["ground"] / "report.json").read_text())
    mating = json.loads((paths["mating"] / "report.json").read_text())
    visual = json.loads((paths["visuals"] / "visual_review.json").read_text())
    fit_check = json.loads((paths["fit_check"] / "report.json").read_text())
    carrier = json.loads((paths["carrier"] / "carrier_manifest.json").read_text())
    fit = json.loads((paths["fit"] / "fit_manifest.json").read_text())
    stack = json.loads((paths["stack"] / "stack_manifest.json").read_text())
    if not summary["passed"] or summary["stage"] != "routed_board" or summary["violations"] or summary["unconnected"]:
        raise ValueError("Use a completely clean routed board")
    if digest(paths["board"] / "f1_fanout_r3.kicad_pcb") != summary["source_pcb_sha256"]:
        raise ValueError("Board/check mismatch")
    if digest(paths["board"] / "f1_fanout_r3.json") != summary["source_manifest_sha256"]:
        raise ValueError("Native manifest/check mismatch")
    check_hash = digest(paths["check"] / "summary.json")
    if not copper["passed"] or copper["independent_check_sha256"] != check_hash:
        raise ValueError("Local copper review is missing or uses another board")
    if copper["source_pcb_sha256"] != data["pcb_sha256"]:
        raise ValueError("Local path review does not match the native board")
    if (ground["checked_pcb_sha256"] != summary["checked_pcb_sha256"]
            or ground["independent_check_sha256"] != check_hash or ground["total_signal_length_mm"] != 0):
        raise ValueError("R3 requires its checked reserved ground plane")
    if not mating["passed"] or mating["fanout_source_sha256"] != data["pcb_sha256"]:
        raise ValueError("Cable correspondence uses another board")
    if visual["independent_check_sha256"] != check_hash:
        raise ValueError("Board drawings use another check")
    if not fit_check["passed_declared_checks"] or not carrier["passed_declared_static_checks"]:
        raise ValueError("Resolve nominal mechanical findings")
    specification = json.loads((paths["board"] / "generation_inputs/specification.json").read_text())
    placement_spec = json.loads((paths["placement"] / "specification.json").read_text())
    if specification != placement_spec:
        raise ValueError("Routing and fit use different component placements")
    placement_path = paths["placement"] / "specification.json"
    placement_key = str(placement_path.relative_to(ROOT))
    if carrier["input_sha256"].get(placement_key) != digest(placement_path):
        raise ValueError("Carrier uses another component placement")
    tail_report_path = paths["tail_routes"] / "report.json"
    tail_report = json.loads(tail_report_path.read_text())
    if tail_report["input_sha256"].get(placement_key) != digest(placement_path):
        raise ValueError("Tail routes use another component placement")
    if fit["input_sha256"].get(str(tail_report_path.relative_to(ROOT))) != digest(tail_report_path):
        raise ValueError("Fit patterns use another route study")
    for key, name in (("fit", "fit_manifest.json"), ("carrier", "carrier_manifest.json")):
        path = paths[key] / name
        if fit_check["input_sha256"].get(str(path.relative_to(ROOT))) != digest(path):
            raise ValueError("Mechanical review uses another geometry revision")
    with execution(ROOT / "build/records", "Archive the clean R3 PCB, reserved-ground/local-path evidence and matching complete nominal fit packet while retaining unfinished sensor/physical status") as record:
        destination.mkdir(parents=True, exist_ok=False)
        for name in ("pcb", "checks", "artwork", "visuals", "cad", "patterns", "configuration", "cable", "provenance"):
            (destination / name).mkdir()
        for name in ("f1_fanout_r3.kicad_pcb", "f1_fanout_r3.kicad_dru",
                     "f1_fanout_r3.json", "f1_fanout_r3_pins.csv", "fp-lib-table"):
            shutil.copyfile(paths["board"] / name, destination / "pcb" / name)
        shutil.copytree(paths["check"] / "F1.pretty", destination / "pcb/F1.pretty")
        shutil.copyfile(paths["board"] / "generation_inputs/specification.json", destination / "pcb/specification.json")
        shutil.copyfile(paths["check"] / "f1_fanout_r3.kicad_pcb",
                        destination / "checks/checked_f1_fanout_r3.kicad_pcb")
        for name, expected in summary["development_exports_sha256"].items():
            original = paths["check"] / "development_files" / name
            if digest(original) != expected:
                raise ValueError("Changed manufacturing export")
            shutil.copyfile(original, destination / "artwork" / name)
        for source, name in (
                (paths["check"] / "summary.json", "pcb_summary.json"),
                (paths["check"] / "drc.json", "pcb_drc.json"),
                (paths["copper"] / "report.json", "local_copper.json"),
                (paths["ground"] / "report.json", "ground_plane.json"),
                (paths["placement"] / "placement_check.json", "placement.json"),
                (paths["carrier"] / "carrier_manifest.json", "carrier.json"),
                (paths["fit"] / "fit_manifest.json", "fit_patterns.json"),
                (paths["fit_check"] / "report.json", "nominal_3d.json"),
                (paths["tail_routes"] / "report.json", "tail_routes.json"),
                (paths["stack"] / "stack_manifest.json", "stack.json")):
            shutil.copyfile(source, destination / "checks" / name)
        for name, expected in visual["files"].items():
            if digest(paths["visuals"] / name) != expected:
                raise ValueError("Changed board drawing")
            shutil.copyfile(paths["visuals"] / name, destination / "visuals" / name)
        for name in ("outer_assembly.svg", "inner_assembly.svg"):
            shutil.copyfile(paths["check"] / name, destination / "visuals" / name)
        for source, stem in ((paths["ground"], "inner_ground"),
                             (paths["fit_check"], "nominal_assembly"),
                             (paths["carrier"], "carrier_assembly"),
                             (paths["placement"], "placement"),
                             (paths["tail_routes"], "tail_routes")):
            for suffix in ("png", "pdf"):
                shutil.copyfile(source / (stem+"."+suffix), destination / "visuals" / (stem+"."+suffix))
        # Keep the actual 3D meshes and compact PNG/PDF reviews. The large
        # triangle-by-triangle SVGs remain in their preserved generated runs.
        base = ROOT / "engineering/development/f1/mechanics"
        for suffix in ("png", "pdf"):
            shutil.copyfile(base / ("visuals/sensor_placement."+suffix),
                            destination / ("visuals/sensor_placement."+suffix))
        shutil.copyfile(base / "SOURCE_GEOMETRY_LICENSE", destination / "SOURCE_GEOMETRY_LICENSE")
        shutil.copyfile(base / "SOURCE_ATTRIBUTION.md", destination / "SOURCE_ATTRIBUTION.md")
        parts = []
        for source, manifest in ((paths["stack"], stack), (paths["carrier"], carrier), (paths["fit"], fit)):
            for part in manifest["parts"]:
                if not all(part["checks"].values()):
                    raise ValueError("A CAD part has unresolved export checks")
                for kind in ("step", "stl"):
                    path = source / part[kind]
                    if digest(path) != part["sha256_"+kind]:
                        raise ValueError("Changed CAD master")
                    shutil.copyfile(path, destination / "cad" / path.name)
                parts.append(part)
        for pattern in fit["patterns"]:
            for suffix in ("svg", "pdf"):
                name = pattern["name"]+"."+suffix
                shutil.copyfile(paths["fit"] / "patterns" / name, destination / "patterns" / name)
        for file in paths["mating"].iterdir():
            if file.is_file():
                shutil.copyfile(file, destination / "cable" / file.name)
        for name in ("f1_fanout_r3.json", "f1_carrier_r3.json", "f1_tail_r3.json",
                     "f1_formed_stack.json", "f1_exit_spaced_candidate.json",
                     "f1_fanout_manufacturing_targets.json"):
            shutil.copyfile(ROOT / "engineering/designs" / name, destination / "configuration" / name)
        shutil.copyfile(paths["board"] / "generation_inputs/routing.json", destination / "provenance/final_routing.json")
        components = json.loads((paths["fit_check"] / "assembly_models.json").read_text())
        for item in components:
            group = item["group"]
            if group == "source":
                item["group"] = "frame" if item["name"] == "original_hard_frame" else "tpu"
            elif group.startswith("CH"):
                item["group"] = "f1_stacks"
            else:
                item["group"] = "f1_"+group
            item["explosion"] = {"f1_board": [5, 0, 0], "f1_components": [5, 0, 0],
                                 "f1_carrier": [2, 0, 0], "f1_tails": [0, 0, -5],
                                 "f1_stacks": [0, 0, -5], "f1_fastener_envelopes": [7, 0, 0]}.get(item["group"], [0, 0, 0])
        model = {"id": "f1_r3_assembly_reference", "title": "F1 R3 checked interface and nominal fit",
                 "coordinates": "native_mm", "assembly": True, "components": components,
                 "note": "Partial integration references for R3. Fitted sensor copper, connector cavities/stiffeners, sealing, motion slack and physical qualification remain."}
        (destination / "models.json").write_text(json.dumps([model], separators=(",", ":"))+"\n")
        with (destination / "components.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["reference", "part_or_value", "package", "side", "source", "status"])
            for part in data["parts"]:
                writer.writerow([part["reference"], part["value"], part.get("library", "custom Hirose land pattern"),
                                 part["side"], part.get("source", ""),
                                 "selected development IC/connector" if part.get("source") else "passive value/package; supplier/lot and derating review remain"])
        with (destination / "parts.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["id", "kind", "purpose", "material", "STEP", "STL"])
            for part in parts:
                writer.writerow([part["id"], part["kind"], part["purpose"], part["material"], part["step"], part["stl"]])
        shutil.copyfile(base / "fit_observations.csv", destination / "fit_observations.csv")
        readme = f"""# F1 R3 interface board and nominal fit packet

**R3 has a checked, routed PCB. It is still one module of an unfinished F1
tactile finger. No physical board, complete finger or measured 20 N result
is claimed.**

The board has {len(data['parts'])} components, {len(data['pads'])} pads,
{len(data['tracks'])} track segments and {len(data['vias'])} vias. Independent
KiCad checking reports zero violations and zero missing connections.
`artwork/` contains the corresponding four copper layers, both assembly faces
and drills. Use the supplied manufacturing targets and a fabricator's stack,
copper and outline review before ordering.

![R3 board](visuals/fanout_faces.png)

R3 moves the test mux and its two bypass capacitors together, checks the
actual library courtyards, fixes the microscopic edge segment and labels,
and prohibits unfilled vias inside the solder-paste lands. The final copper
retains all sixteen direct sensor pickoffs, both short VDD paths and both
nearby bypass-ground paths. The nominal minimum via-to-paste gap is 0.115 mm.

The inner In1.Cu layer is reserved for ground: no signal tracks cross it.
The earlier clean-copper candidate's 581.25 mm of ground-layer signal routing
is preserved in its generated review. Ground continuity and the drawing do
not establish analog return impedance or EMC performance.

![Reserved ground layer](visuals/inner_ground.png)

## Matching mechanical files

This packet also contains {len(parts)} STEP/STL reference/tooling solids and
twelve SVG/PDF fit patterns matched to R3. The 654 declared static pair
comparisons pass. These are nominal hardware-to-hardware checks; they do
not qualify swept object/contact envelopes or loaded TPU deformation.
Twelve connector cavity/mating interfaces remain
unqualified. Label cut patterns **R3** when preparing the fit trial; do not
mix them with the older R2 packet.

Print the carrier and six forming mandrels. The electrode-body, tail and
PCB solids are references, not functional printed sensors. Paper/polyester
patterns contain no electrode copper. Fitted copper, finished stiffeners,
verified mating datums, sealing, own-layer joins and inextensible motion
slack remain before the complete sensor can be fabricated.

![R3 fit](visuals/nominal_assembly.png)

## Exact interfaces

The twelve sensing-foil connectors are Hirose FH12-6S-1SH(1)(98).
Rows are on the outer face; columns are on the inner face. Each upper pair
faces toward the back. The source nail and TPU sensing locations are retained.

| Site | Connector pair | Global column nets |
| --- | --- | --- |
| CH0, left nail | J0R / J0C | C0, C1 |
| CH1, right nail | J1R / J1C | C2, C3 |
| CH2, distal TPU | J2R / J2C | C4, C5, C6 |
| CH3 | J3R / J3C | C7, C8, C9 |
| CH4 | J5R / J5C | C13, C14, C15 |
| CH5, proximal TPU | J4R / J4C | C10, C11, C12 |

Every row connector has pins 1–4 = R3, R2, R1, R0; pins 5–6 are unused.
Column pins 1, 3, 5 carry the site's columns in descending numerical order,
using only pins 1 and 3 for the nail pairs. The native pin CSV is authoritative.
Fitted electrode artwork and its spatial column direction remain to be completed.

JW connects to the preserved checked wrist module. The stated cable mating
pose gives fanout pin n to wrist pin 51−n. The fifty native correspondences
pass; `cable/continuity_checklist.csv` is blank for the student's unpowered
physical check. Installed cable routing and actual YAM housing fit remain.

Use `engineering/firmware/f1/` and `engineering/software/f1_record.py` from the
complete source. These record raw matrix/test observations, not calibrated
force. The switched 10 kΩ electrical test can pass with the sensing foils
unplugged; it is not a whole-sensor or contact-reliability test.

## Files and scope

- `pcb/`, `artwork/`, `checks/`: native board, fabrication exports and full evidence.
- `cad/`, `patterns/`, `parts.csv`: matching geometry and fit-only cut sheets.
- `components.csv`: active ordering codes and passive values/packages.
- `configuration/`, `provenance/`: reproduction inputs and final route.
- `visuals/`, `models.json`: board/ground/fit drawings and the actual viewer meshes.

The rejected R2 route remains in `engineering/development/f1/r2-routing-study/`.
No R2 findings were suppressed to make R3 pass. The full F1 coupled-array,
reference, copper/contact resistance, bending, wear, calibration and held-out
contact/force comparison remain unfinished. No measured winner is available.
"""
        (destination / "README.md").write_text(readme)
        checkpoint = {"schema": "yam-f1-r3-development-checkpoint/1",
                      "created_utc": datetime.now(timezone.utc).isoformat(),
                      "status": "Checked R3 interface PCB and nominal fit; complete F1/physical qualification unfinished",
                      "integrated_f1_completed": False, "physical_specimens_tested": 0,
                      "independent_check": summary, "cad_solids": len(parts), "fit_patterns": len(fit["patterns"]),
                      "source_locations": {key: str(path.relative_to(ROOT)) for key, path in paths.items()},
                      "archiver_sha256": digest(Path(__file__)),
                      "files_sha256": {str(path.relative_to(destination)): digest(path)
                                       for path in sorted(destination.rglob("*")) if path.is_file()}}
        (destination / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2)+"\n")
        record["result"] = {"directory": str(destination.relative_to(ROOT)), "files": len(checkpoint["files_sha256"]),
                            "tracks": len(data["tracks"]), "vias": len(data["vias"]),
                            "cad_solids": len(parts), "sha256": digest(destination / "checkpoint.json")}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
