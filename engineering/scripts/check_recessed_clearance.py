#!/usr/bin/python3
"""Check B3 head/solder envelopes and a declared conservative TPU motion bound."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["XDG_CACHE_HOME"] = str(ROOT / "build/engineering/tools/cache")
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cadquery as cq
import numpy as np
from prototype_cad import x_cylinder, digest
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/prototypes/recessed"


def main():
    cfg_path = ROOT / "engineering/designs/recessed.json"
    manifest = OUTPUT / "recessed_manifest.json"
    model_path = ROOT / "engineering/release/b1/models.json"
    cfg = json.loads(cfg_path.read_text())
    plan = json.loads(manifest.read_text())
    m = cfg["mechanical"]
    for name, expected in plan["source_hashes"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Stale B3 geometry: " + name)
    with execution(ROOT / "build/records", "Check reserved B3 hardware and rear solder volumes; derive a conservative X-separation bound for assumed TPU motion") as record:
        shapes = {part["id"]: cq.importers.importStep(str(OUTPUT / part["step"])).val()
                  for part in plan["parts"]}
        heads = []
        for row in plan["supports"]:
            y, z = row["center_yz_mm"]
            heads.append(x_cylinder(plan["backer_outer_x_mm"],
                         m["reserved_head_height_mm"], y, z,
                         m["reserved_head_diameter_mm"] / 2))
        overlaps = {}
        for i, head in enumerate(heads):
            for name, shape in shapes.items():
                overlaps[f"head_{i}_vs_{name}"] = head.intersect(shape).Volume()
        for item in plan["front_solder_envelopes"]:
            y, z = item["center_yz_mm"]
            rear = x_cylinder(plan["pcb_component_plane_x_mm"] + m["pcb_thickness_mm"],
                              1.0, y, z, .8)
            for name in ("recessed_removable_backer", "recessed_hard_frame"):
                overlaps[f"rear_{item['reference']}_{item['pad']}_vs_{name}"] = rear.intersect(shapes[name]).Volume()
            for i, head in enumerate(heads):
                overlaps[f"rear_{item['reference']}_{item['pad']}_vs_head_{i}"] = rear.intersect(head).Volume()
        moving = [row for row in json.loads(model_path.read_text())[0]["components"]
                  if row["group"] in ("b1tpu", "magnet", "plug")]
        if not moving:
            raise ValueError("No moving TPU/magnet/plug geometry")
        vertices = np.concatenate([np.asarray(row["vertices"]) for row in moving])
        original_max_x = float(vertices[:, 0].max())
        side = max(cfg["motion_screen"]["side_bulge_native_x_mm"])
        model_allowance = .05
        bound = original_max_x + side + model_allowance
        # X separation proves no collision with these parts for *any* Y/Z
        # movement satisfying the declared pointwise X bound. It does not
        # establish TPU movement under a force or clearance to its own anchors.
        clearances = []
        for name, shape in shapes.items():
            if name == "recessed_hard_frame":
                continue
            clearances.append({"part": name, "fixed_min_native_x_mm": shape.BoundingBox().xmin,
                               "separation_lower_bound_mm": shape.BoundingBox().xmin - bound})
        for item in plan["component_envelopes"] + plan["front_solder_envelopes"]:
            height = item.get("height_mm", item.get("height_allowance_mm"))
            x = plan["pcb_component_plane_x_mm"] - height
            clearances.append({"part": item["reference"] + ("_" + item["pad"] if "pad" in item else ""),
                               "fixed_min_native_x_mm": x,
                               "separation_lower_bound_mm": x - bound})
        for i, head in enumerate(heads):
            clearances.append({"part": f"reserved_head_{i}", "fixed_min_native_x_mm": head.BoundingBox().xmin,
                               "separation_lower_bound_mm": head.BoundingBox().xmin - bound})
        frame_xmax = shapes["recessed_hard_frame"].BoundingBox().xmax
        before_heads = max(0, plan["backer_outer_x_mm"] - frame_xmax)
        with_heads = before_heads + m["reserved_head_height_mm"]
        result = {
            "schema": "yam-b3-clearance/1", "evidence_kind": "geometry_and_prescribed_motion_bound",
            "physical_specimens_tested": 0, "installed_drive_verified": False,
            "rigid_overlaps_mm3": overlaps, "source_moving_geometry_max_native_x_mm": original_max_x,
            "pointwise_positive_x_displacement_bound_mm_assumed": side,
            "model_coordinate_allowance_mm_assumed": model_allowance,
            "moving_geometry_max_native_x_mm_assumed": bound,
            "moving_to_fixed_separation_bounds": clearances,
            "minimum_moving_to_electronics_and_support_gap_bound_mm": min(row["separation_lower_bound_mm"] for row in clearances),
            "rear_solder_envelope": {"radius_mm": .8, "height_behind_pcb_mm": 1.0},
            "added_width_mm_before_heads_excluding_wires": before_heads,
            "added_width_mm_with_reserved_heads_excluding_wires": with_heads,
            "added_reach_mm": 0,
            "limits": [
                "This is not a measured 20 N displacement or a permissible-travel rating.",
                "Every moving TPU/magnet/plug point is assumed to stay within +2 mm of its unloaded native X; arbitrarily large deformation is not covered.",
                "The source frame and intended TPU attachments are excluded from the moving-to-electronics separation test.",
                "Rear solder envelopes fit the retained backer exits. Actual cable loops, strain relief, jaw drive, opposite jaw and tool access need physical checks through full opening and closing.",
                "The 6 mm diameter by 2.4 mm head reservation is an envelope, not a selected screw length or a clamp strength rating."
            ],
            "source_hashes": {str(path.relative_to(ROOT)): digest(path)
                              for path in (cfg_path, manifest, model_path, Path(__file__))},
        }
        (OUTPUT / "recessed_clearance_review.json").write_text(json.dumps(result, indent=2) + "\n")
        record["summary"] = {"checked_overlaps": len(overlaps), "maximum_overlap_mm3": max(overlaps.values()),
                            "minimum_motion_gap_bound_mm": result["minimum_moving_to_electronics_and_support_gap_bound_mm"],
                            "added_width_with_heads_mm": with_heads, "physical_tests": 0}
        print(json.dumps(record["summary"], indent=2))
        if max(overlaps.values()) > 1e-5 or min(row["separation_lower_bound_mm"] for row in clearances) < .5:
            raise ValueError("B3 declared geometric envelope fails its clearance check")


if __name__ == "__main__":
    main()
