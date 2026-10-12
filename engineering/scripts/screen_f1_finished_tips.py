#!/usr/bin/python3
"""Check a finished F1 connector-stack proposal against all twelve routed foils."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from tactile_kit.records import execution
from screen_f1_feedback import digest

SOURCE = ROOT / "engineering/development/f1/fitted-foils-r3"
PLAN = ROOT / "engineering/designs/f1_finished_tip_r4.json"
STACK = ROOT / "engineering/development/f1/r3/configuration/f1_formed_stack.json"


def main():
    cfg = json.loads(PLAN.read_text())
    stack = json.loads(STACK.read_text())
    artwork = json.loads((SOURCE / "provenance/artwork.json").read_text())
    checkpoint = json.loads((SOURCE / "checkpoint.json").read_text())
    folder = ROOT / "build/engineering/prototypes/f1/finished_tip_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Compare the proposed F1 plated/stiffened terminal stack and local back-coverlay relief against all twelve actual R3 foil geometries; do not alter or release new artwork") as record:
        folder.mkdir(parents=True)
        inputs = [PLAN, STACK, Path(__file__), SOURCE / "checkpoint.json", SOURCE / "provenance/artwork.json"]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        cases = []
        for entry in artwork["boards"]:
            name = entry["name"]
            relative = f"foils/{name}/{name}.json"
            path = SOURCE / relative
            if digest(path) != checkpoint["files_sha256"][relative]:
                raise ValueError("Frozen foil changed")
            data = json.loads(path.read_text())
            stiffener = unary_union([Polygon(p) for p in data["stiffeners_mm"]])
            x0, y0, x1, y1 = stiffener.bounds
            if abs(stiffener.symmetric_difference(box(x0, y0, x1, y1)).area) > 1e-6:
                raise ValueError("Review a nonrectangular terminal separately")
            center_y = sum(f["center"][1] for f in data["fingers"])/len(data["fingers"])
            setback_to_center = data["fingers"][0]["length"]/2+stack["tails"]["gold_contact_tip_setback_mm"]
            if abs(y1-center_y-setback_to_center) < 1e-5:
                tip_y = y1
            elif abs(center_y-y0-setback_to_center) < 1e-5:
                tip_y = y0
            else:
                raise ValueError("The contact fingers do not identify a consistent terminal tip")
            direction = -1 if tip_y == y1 else 1
            end = tip_y+direction*cfg["back_coverlay_relief_from_tip_mm"]
            relief = box(x0, min(tip_y, end), x1, max(tip_y, end))
            back_regions = [Polygon(r["outline_mm"]) for r in data["regions"] if r["layer"] == "B.Cu"]
            # Plated annuli are separate native pads, not members of the
            # routed-region list. Their outer edge also limits the relief.
            back_regions += [Point(via["center"]).buffer(via["pad_mm"]/2, quad_segs=64)
                             for via in data["plated_connections"]]
            back = unary_union(back_regions)
            front_mask = unary_union([Polygon(r["outline_mm"]) for r in data["coverlay_openings"] if r["layer"] == "F.Mask"])
            back_mask = unary_union([Polygon(r["outline_mm"]) for r in data["coverlay_openings"] if r["layer"] == "B.Mask"])
            fingers = [box(f["center"][0]-f["width"]/2, f["center"][1]-f["length"]/2,
                           f["center"][0]+f["width"]/2, f["center"][1]+f["length"]/2) for f in data["fingers"]]
            contacts = unary_union(fingers)
            pitch = sorted(f["center"][0] for f in data["fingers"])
            nominal = (stack["materials_mm"]["polyimide"]+stack["materials_mm"]["copper"]
                       +cfg["nickel_nominal_mm"]+cfg["gold_minimum_mm"]
                       +cfg["selected_stiffener_mm"]+cfg["selected_stiffener_bond_mm"])
            two_layer = data["physical_layers"] == 2
            gap = None if back.is_empty else relief.distance(back)
            current_back_open = relief.difference(back_mask).area < 1e-6
            findings = []
            if not cfg["allowed_tongue_width_mm"][0] <= x1-x0 <= cfg["allowed_tongue_width_mm"][1]:
                findings.append("tongue_width")
            if abs(x1-x0-cfg["nominal_tongue_width_mm"]) > 1e-5 or y1-y0 < cfg["minimum_supported_length_mm"]:
                findings.append("support_dimensions")
            if any(abs(b-a-cfg["contact_pitch_mm"]) > 1e-5 for a, b in zip(pitch, pitch[1:])):
                findings.append("pitch")
            if len(data["fingers"]) != 6 or any(f["layer"] != "F.Cu" or f["length"] < cfg["minimum_exposed_contact_length_mm"] for f in data["fingers"]):
                findings.append("contact_geometry")
            if contacts.difference(front_mask).area > 1e-5:
                findings.append("front_contact_not_exposed")
            if gap is not None and gap < cfg["minimum_relief_to_back_copper_mm"]:
                findings.append("proposed_relief_too_close_to_back_copper")
            if not cfg["required_finished_thickness_mm"][0] <= nominal <= cfg["required_finished_thickness_mm"][1]:
                findings.append("proposed_finished_thickness")
            cases.append({"foil": name, "site": entry["metadata"]["site"], "role": entry["metadata"]["role"],
                          "physical_copper_layers": data["physical_layers"], "terminal_tip_flat_mm": [(x0+x1)/2, tip_y],
                          "tip_inward_y_sign": direction, "stiffener_bounds_mm": list(stiffener.bounds),
                          "proposed_back_relief_polygon_mm": list(relief.exterior.coords),
                          "minimum_relief_to_back_copper_mm": gap,
                          "plated_annuli_included_in_clearance": True,
                          "existing_back_window_covers_proposal": current_back_open,
                          "needs_back_coverlay_change": two_layer and not current_back_open,
                          "proposed_tip_nominal_mm": nominal,
                          "tip_with_unrelieved_back_coverlay_mm": nominal+(stack["materials_mm"]["coverlay"] if two_layer else 0),
                          "nominal_covered_transition_with_stiffener_mm": data["covered_thickness_mm"]+cfg["selected_stiffener_mm"]+cfg["selected_stiffener_bond_mm"],
                          "findings": findings, "geometry_source_sha256": digest(path)})
        report = {"schema": "yam-f1-finished-tip-review/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "cases": cases, "proposed_contract_checks_pass": all(not row["findings"] for row in cases),
                  "requires_new_artwork": any(row["needs_back_coverlay_change"] for row in cases),
                  "scope": "Stack and nominal window planning only. No new copper/mask manufacturing set or physical connector fit is qualified."}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "checks_pass": report["proposed_contract_checks_pass"],
                            "cases": [{key: row[key] for key in ("foil", "minimum_relief_to_back_copper_mm", "needs_back_coverlay_change", "proposed_tip_nominal_mm", "tip_with_unrelieved_back_coverlay_mm", "findings")} for row in cases]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
