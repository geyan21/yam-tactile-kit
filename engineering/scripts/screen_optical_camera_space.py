#!/usr/bin/python3
"""Place the documented camera body and size a root bay from explicit envelopes."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/optical-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import cadquery as cq
import numpy as np
from prototype_cad import block, export_part, packed
from build_pneumatic_ported_assembly import overlap
from screen_f1_feedback import digest
from tactile_kit.records import execution

CONFIG = ROOT/"engineering/designs/optical_camera_space.json"
REVIEW = ROOT/"engineering/research/optical_source_review.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    args = parser.parse_args()
    search, core = args.search.resolve(), args.core.resolve()
    if not all(path.is_relative_to(ROOT/"build") for path in (search, core)):
        parser.error("Use this checkout's generated optical inputs")
    path_plan, core_plan = (json.loads((path/"report.json").read_text()) for path in (search, core))
    if not core_plan["passed_core_checks"]:
        raise ValueError("Use a passing protected-frame core")
    for report in (path_plan, core_plan):
        for name, expected in report["input_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError("Optical input changed: "+name)
    if core_plan["input_sha256"].get(str((search/"report.json").relative_to(ROOT))) != digest(search/"report.json"):
        raise ValueError("The core belongs to another optical path")
    cfg, review = json.loads(CONFIG.read_text()), json.loads(REVIEW.read_text())["camera_candidate"]
    path_cfg = json.loads((ROOT/path_plan["configuration"]).read_text())
    pose = path_plan["selected"]
    angle = np.radians(pose["camera_pitch_above_distal_deg"])
    axis = np.array([0, -np.cos(angle), np.sin(angle)])
    optical_origin = np.r_[path_cfg["camera_x_mm"], pose["camera_yz_mm"]]
    pcb_origin = optical_origin-cfg["ray_origin_in_front_of_pcb_mm"]*axis
    rotation = cfg["rotation_about_optical_axis_deg"]
    if rotation not in (0, 180):
        raise ValueError("This prototype supports the two explicitly modeled camera orientations")
    plane = cq.Plane(origin=tuple(pcb_origin), xDir=(1 if rotation == 0 else -1, 0, 0), normal=tuple(axis))
    width, height, _ = review["drawing_board_dimensions_mm"]
    lens_u, lens_v = review["drawing_lens_axis_from_top_left_mm"]
    def slab(z0, z1):
        return block(-lens_u, width-lens_u, -lens_v, height-lens_v, z0, z1)
    pcb = slab(-cfg["pcb_thickness_mm"], 0)
    for u, v in review["drawing_holes_from_top_left_mm"]:
        hole = cq.Solid.makeCylinder(review["drawing_hole_diameter_mm"]/2, cfg["pcb_thickness_mm"]+.2,
                                     cq.Vector(u-lens_u, v-lens_v, -cfg["pcb_thickness_mm"]-.1), cq.Vector(0, 0, 1))
        pcb = pcb.cut(hole)
    fw, fh = cfg["front_housing_plan_mm"]
    housing = block(-fw/2, fw/2, -fh/2, fh/2, 0, cfg["front_housing_height_mm"])
    barrel = cq.Solid.makeCylinder(cfg["lens_envelope_diameter_mm"]/2,
                                   cfg["lens_front_height_mm"]-cfg["front_housing_height_mm"],
                                   cq.Vector(0, 0, cfg["front_housing_height_mm"]), cq.Vector(0, 0, 1))
    back = slab(-cfg["pcb_thickness_mm"]-cfg["rear_electronics_envelope_mm"], -cfg["pcb_thickness_mm"])
    # The drawing's mounting lands are reserved for the standoffs.
    # Actual component clearance under these lands is an incoming check.
    for u, v in review["drawing_holes_from_top_left_mm"]:
        keepout = cq.Solid.makeCylinder(cfg["rear_mount_land_clearance_diameter_mm"]/2,
                                        cfg["rear_electronics_envelope_mm"]+.2,
                                        cq.Vector(u-lens_u, v-lens_v, -cfg["pcb_thickness_mm"]-cfg["rear_electronics_envelope_mm"]-.1),
                                        cq.Vector(0, 0, 1))
        back = back.cut(keepout)
    local = [("o1_camera_pcb_reference", pcb, "PCB outline and mounting holes", "#426f5e"),
             ("o1_camera_focus_housing_reference", housing, "Nominal autofocus-housing envelope", "#3d535e"),
             ("o1_camera_lens_reference", barrel, "Nominal lens barrel; actual aperture and pupil require acceptance", "#5483a0"),
             ("o1_camera_rear_clearance_reference", back, "Conservative full-board rear-electronics clearance box", "#9cadad")]
    shapes = [(name, shape.moved(plane.location), purpose, color) for name, shape, purpose, color in local]
    frame_part = next(part for part in core_plan["parts"] if part["id"] == "o1_frame_core_witness")
    frame_path = core/frame_part["step"]
    if digest(frame_path) != frame_part["sha256_step"]:
        raise ValueError("Frame STEP changed")
    frame = cq.importers.importStep(str(frame_path)).val()
    folder = ROOT/"build/engineering/prototypes/optical/camera_space_screens"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Place the camera's drawing-based envelopes relative to the optical ray origin, check the core, and bound the added reach needed for a retained original root cap") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [CONFIG, REVIEW, Path(__file__), search/"report.json", core/"report.json", frame_path,
                  ROOT/"engineering/scripts/prototype_cad.py", ROOT/"engineering/scripts/build_pneumatic_ported_assembly.py"]
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        parts, models, checks = [], [], []
        for name, shape, purpose, color in shapes:
            mesh = export_part(shape, name, folder, parts, purpose, "Purchased Camera Module 3 Wide reference", "reference_only")
            models.append(packed(mesh, name, "o1_camera_references", color))
            checks.append({"part": name, "core_overlap_mm3": overlap(shape, frame)})
        minimum = np.min([part["bounds_mm"][0] for part in parts], axis=0)
        maximum = np.max([part["bounds_mm"][1] for part in parts], axis=0)
        cases = []
        for reach in cfg["reach_extension_candidates_mm"]:
            gap = cfg["retained_root_cap_front_y_mm"]-(maximum[1]-reach)
            cases.append({"added_reach_mm": reach, "camera_to_root_cap_y_gap_mm": float(gap),
                          "passed": bool(gap >= cfg["camera_to_root_cap_clearance_mm"])})
        passing = [row for row in cases if row["passed"]]
        selected = passing[0] if passing else None
        report = {"schema": "yam-o1-camera-space-result/1", "physical_specimens_tested": 0,
                  "parts": parts, "optical_ray_origin_native_mm": optical_origin.tolist(),
                  "pcb_front_lens_axis_native_mm": pcb_origin.tolist(), "camera_axis_native": axis.tolist(),
                  "camera_rotation_about_optical_axis_deg": rotation,
                  "camera_envelope_bounds_native_mm": [minimum.tolist(), maximum.tolist()],
                  "camera_core_checks": checks, "cases": cases, "selected_root_bay": selected,
                  "passed_space_screen": selected is not None and all(row["core_overlap_mm3"] <= .001 for row in checks),
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs}, "limits": cfg["limits"]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "camera_core_checks": checks,
                            "camera_envelope_bounds": report["camera_envelope_bounds_native_mm"], "selected_root_bay": selected}
        print(json.dumps(record["result"], indent=2))
        if not report["passed_space_screen"]:
            raise ValueError("Resolve camera/core or root-space findings")


if __name__ == "__main__":
    main()
