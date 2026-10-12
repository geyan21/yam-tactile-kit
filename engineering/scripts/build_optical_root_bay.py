#!/usr/bin/python3
"""Integrate the O1 camera bay, retained mount cap, camera supports and removable lid."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/optical-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import cadquery as cq
import numpy as np
import trimesh
from prototype_cad import block, export_part, packed
from source_brep import load as source_solid
from build_pneumatic_ported_assembly import cyl, overlap
from screen_f1_feedback import digest
from tactile_kit.records import execution
from inspect_optical_obstructions import segments

CONFIG = ROOT/"engineering/designs/optical_root_bay.json"


def hex_prism(u, v, z0, z1, across_flats):
    radius = across_flats/math.sqrt(3)
    points = [(u+radius*math.cos(math.pi/6+i*math.pi/3), v+radius*math.sin(math.pi/6+i*math.pi/3)) for i in range(6)]
    return cq.Workplane("XY", origin=(0, 0, z0)).polyline(points).close().extrude(z1-z0).val()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--camera", type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ("core", "camera")}
    if not all(path.is_relative_to(ROOT/"build") for path in paths.values()):
        parser.error("Use this checkout's generated optical core/camera inputs")
    reports = {name: json.loads((path/"report.json").read_text()) for name, path in paths.items()}
    for report in reports.values():
        for name, expected in report["input_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError("Input changed: "+name)
    if not reports["core"]["passed_core_checks"] or not reports["camera"]["passed_space_screen"]:
        raise ValueError("Resolve the core and camera screens first")
    if reports["camera"]["input_sha256"].get(str((paths["core"]/"report.json").relative_to(ROOT))) != digest(paths["core"]/"report.json"):
        raise ValueError("Mixed camera and core revisions")
    cfg = json.loads(CONFIG.read_text())
    search_key = next(name for name in reports["core"]["input_sha256"] if "/path_searches/" in name and name.endswith("/report.json"))
    search = json.loads((ROOT/search_key).read_text())
    search_cfg = json.loads((ROOT/search["configuration"]).read_text())
    fast = cfg["fastener"]
    source_review = json.loads((ROOT/"engineering/research/optical_source_review.json").read_text())["camera_candidate"]
    cam_cfg = json.loads((ROOT/"engineering/designs/optical_camera_space.json").read_text())
    reach = reports["camera"]["selected_root_bay"]["added_reach_mm"]
    shift = np.array([0., -reach, 0.])
    original, receipt = source_solid("hard_frame")
    folder = ROOT/"build/engineering/prototypes/optical/root_bays"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Build the O1 camera bay with a duplicated source root cap, explicit M2 hardware and unchanged translated nail; check interfaces and all assembled material envelopes") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [CONFIG, Path(__file__), ROOT/"engineering/designs/optical_camera_space.json",
                  ROOT/"engineering/research/optical_source_review.json", *[path/"report.json" for path in paths.values()],
                  ROOT/"engineering/scripts/prototype_cad.py", ROOT/"engineering/scripts/source_brep.py",
                  ROOT/"engineering/scripts/inspect_optical_obstructions.py", ROOT/search_key, ROOT/search["configuration"]]
        for path in inputs:
            out = folder/"inputs"/path.relative_to(ROOT)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out)
        loaded = {}
        for module in paths:
            for part in reports[module]["parts"]:
                path = paths[module]/part["step"]
                if digest(path) != part["sha256_step"]:
                    raise ValueError("A CAD input changed")
                loaded[part["id"]] = cq.importers.importStep(str(path)).val().translate(tuple(shift))
        core_name = "o1_frame_core_witness"
        forward = loaded[core_name]
        root_cap = original.intersect(block(-50, 30, cfg["root_cap_source_y_min_mm"], 10, -20, 70))
        lo = reports["camera"]["camera_envelope_bounds_native_mm"][0]
        hi = reports["camera"]["camera_envelope_bounds_native_mm"][1]
        inner_x0, inner_x1 = lo[0]-cfg["camera_side_clearance_mm"], hi[0]+cfg["camera_side_clearance_mm"]
        outer_x0, outer_x1 = inner_x0-cfg["wall_thickness_mm"], inner_x1+cfg["wall_thickness_mm"]
        y0, y1 = cfg["front_bay_attach_source_y_mm"]-reach, cfg["rear_bay_attach_y_mm"]
        floor0, floor1 = cfg["floor_z_mm"]
        top = cfg["wall_top_z_mm"]
        walls = [block(outer_x0, outer_x1, y0, y1, floor0, floor1),
                 block(outer_x0, inner_x0, y0, y1, floor1, top),
                 block(inner_x1, outer_x1, y0, y1, floor1, top)]
        mount_guards = [cyl(cfg["mount_guard_radius_mm"], cfg["mount_guard_y_mm"][1]-cfg["mount_guard_y_mm"][0],
                            [xz[0], cfg["mount_guard_y_mm"][0], xz[1]], [0, 1, 0])
                       for xz in cfg["mount_guard_xz_centers_mm"]]
        for index, wall in enumerate(walls):
            for guard in mount_guards:
                wall = wall.cut(guard)
            walls[index] = wall.clean()
        pcb_origin = np.asarray(reports["camera"]["pcb_front_lens_axis_native_mm"])+shift
        axis = np.asarray(reports["camera"]["camera_axis_native"])
        rotation = reports["camera"]["camera_rotation_about_optical_axis_deg"]
        if rotation != 180:
            raise ValueError("This bay layout uses the documented 180-degree camera orientation")
        plane = cq.Plane(origin=tuple(pcb_origin), xDir=(-1, 0, 0), normal=tuple(axis))
        lens_u, lens_v = source_review["drawing_lens_axis_from_top_left_mm"]
        camera_holes = [(u-lens_u, v-lens_v) for u, v in source_review["drawing_holes_from_top_left_mm"]]
        post_top = -cam_cfg["pcb_thickness_mm"]
        post_bottom = post_top-cfg["camera_standoff_length_mm"]
        bar_bottom = post_bottom-cfg["camera_support_bar_thickness_mm"]
        bars = []
        for v in sorted({v for _, v in camera_holes}):
            bars.append(block(-cfg["camera_support_half_width_u_mm"], cfg["camera_support_half_width_u_mm"],
                              v-cfg["camera_support_bar_half_width_v_mm"], v+cfg["camera_support_bar_half_width_v_mm"],
                              bar_bottom, post_bottom).moved(plane.location))
        posts = [cyl(cfg["camera_standoff_outer_diameter_mm"]/2, post_top-post_bottom, [u, v, post_bottom], [0, 0, 1]).moved(plane.location)
                 for u, v in camera_holes]
        frame = forward.fuse(root_cap, *walls, *bars, *posts).clean()
        for u, v in camera_holes:
            frame = frame.cut(cyl(fast["clear_hole_mm"]/2, 10, [u, v, bar_bottom-1], [0, 0, 1]).moved(plane.location)).clean()
        boss_r = cfg["lid_boss_diameter_mm"]/2
        boss_x = (lo[0]-cfg["lid_boss_camera_x_clearance_mm"]-boss_r,
                  hi[0]+cfg["lid_boss_camera_x_clearance_mm"]+boss_r)
        lid_centres = [(x, y) for x in boss_x for y in cfg["lid_boss_y_mm"]]
        lid = block(outer_x0, outer_x1, y0, y1, top, top+cfg["lid_thickness_mm"])
        for x, y in lid_centres:
            boss = cyl(boss_r, cfg["lid_boss_z_mm"][1]-cfg["lid_boss_z_mm"][0], [x, y, cfg["lid_boss_z_mm"][0]], [0, 0, 1])
            frame = frame.fuse(boss).clean()
            lid = lid.fuse(cyl(boss_r, cfg["lid_thickness_mm"], [x, y, top], [0, 0, 1])).clean()
            frame = frame.cut(cyl(fast["clear_hole_mm"]/2, 12, [x, y, cfg["lid_boss_z_mm"][0]-.1], [0, 0, 1]))
            pocket0, pocket1 = cfg["lid_nut_pocket_z_mm"]
            frame = frame.cut(hex_prism(x, y, pocket0, pocket1, fast["nut_pocket_af_mm"]))
            # Slide the nut in from the outside of its boss.
            left = x < (outer_x0+outer_x1)/2
            slot_x0, slot_x1 = (x-boss_r-.1, x) if left else (x, x+boss_r+.1)
            frame = frame.cut(block(slot_x0, slot_x1, y-fast["nut_pocket_af_mm"]/2, y+fast["nut_pocket_af_mm"]/2,
                                    pocket0, pocket1)).clean()
            lid = lid.cut(cyl(fast["clear_hole_mm"]/2, cfg["lid_thickness_mm"]+.2, [x, y, top-.1], [0, 0, 1])).clean()
        lid = lid.fuse(block(inner_x0, inner_x1, *cfg["rear_lid_baffle_y_mm"],
                            cfg["rear_lid_baffle_z_min_mm"], top)).clean()
        lid = lid.cut(block(*cfg["cable_slot_x_mm"], *cfg["cable_slot_y_mm"], top-.1, top+cfg["lid_thickness_mm"]+.1)).clean()
        if not frame.isValid() or len(frame.Solids()) != 1 or not lid.isValid() or len(lid.Solids()) != 1:
            cq.exporters.export(frame, str(folder/"failed_frame.step"))
            cq.exporters.export(lid, str(folder/"failed_lid.step"))
            raise ValueError("Root bay/frame or lid is not one valid connected solid")
        print("Root cap, bay and integral camera supports joined.", flush=True)
        items = [("o1_frame_with_camera_bay", frame, "Windowed optical frame, retained root cap, 32 mm bay and camera support bosses",
                  "Rigid opaque PETG/PA12 prototype; stiffness unqualified", "fabricate", "o1_frame", "#809b90"),
                 ("o1_camera_bay_lid", lid, "Removable opaque bay lid with captive-nut access and a baffled cable opening",
                  "Opaque PETG prototype", "fabricate", "o1_lid", "#a8bab0")]
        for module in paths:
            for part in reports[module]["parts"]:
                if part["id"] == core_name:
                    continue
                items.append((part["id"], loaded[part["id"]], part["purpose"], part["material"], part["kind"],
                              "o1_camera" if module == "camera" else "o1_optical_core", "#638caa" if module == "camera" else "#b59bd0"))
        def hardware(prefix, u, v, washer_low, nut_low, nut_high, local_plane=None):
            w = cyl(fast["washer_od_mm"]/2, fast["washer_thickness_mm"], [u, v, washer_low], [0, 0, 1]).cut(
                cyl(fast["washer_id_mm"]/2, fast["washer_thickness_mm"], [u, v, washer_low], [0, 0, 1]))
            seat = washer_low+fast["washer_thickness_mm"]
            s = cyl(fast["shaft_diameter_mm"]/2, fast["length_mm"], [u, v, seat-fast["length_mm"]], [0, 0, 1]).fuse(
                cyl(fast["head_diameter_mm"]/2, fast["head_height_mm"], [u, v, seat], [0, 0, 1]))
            n = hex_prism(u, v, nut_low, nut_high, fast["nut_af_mm"]).cut(
                cyl(fast["shaft_diameter_mm"]/2, nut_high-nut_low, [u, v, nut_low], [0, 0, 1]))
            for suffix, shape in (("washer", w), ("screw", s), ("nut", n)):
                if local_plane is not None:
                    shape = shape.moved(local_plane.location)
                items.append((prefix+"_"+suffix, shape, "M2 dimensional hardware reference; thread form is not modeled",
                              "Measured M2 metal hardware", "reference_only", "o1_hardware", "#8b969d"))
        for index, (u, v) in enumerate(camera_holes):
            hardware(f"o1_camera_mount_{index}", u, v, 0, bar_bottom-fast["nut_thickness_mm"], bar_bottom, plane)
        for index, (x, y) in enumerate(lid_centres):
            hardware(f"o1_lid_mount_{index}", x, y, top+cfg["lid_thickness_mm"], *cfg["lid_nut_z_mm"])
        parts, models, checks = [], [], []
        for index, (name, shape, purpose, material, kind, group, color) in enumerate(items):
            mesh = export_part(shape, name, folder, parts, purpose, material, kind)
            models.append(packed(mesh, name, group, color))
            for other_name, other, *_ in items[index+1:]:
                checks.append({"a": name, "b": other_name, "overlap_mm3": overlap(shape, other)})
        source_shifted = original.translate(tuple(shift))
        guard_regions = [("leading_nail", source_shifted, block(-50, 30, -180-reach, -96-reach, -20, 80)),
                         ("drive_interface", original, block(-50, 30, cfg["protected_interface_y_min_mm"], 10, -20, 80))]
        guard_regions += [("mount_"+str(index), original, guard) for index, guard in enumerate(mount_guards)]
        preservation = []
        for name, reference, guard in guard_regions:
            before, after = reference.intersect(guard), frame.intersect(guard)
            difference = abs(abs(before.Volume())+abs(after.Volume())-2*overlap(before, after))
            preservation.append({"region": name, "symmetric_material_difference_mm3": difference, "passed": difference <= .001})
        failures = [row for row in checks if row["overlap_mm3"] > .001]
        rays = segments(search["selected"], np.asarray(search["optical_targets_inner_yz_mm"]),
                       search_cfg["active_half_width_mm"], search_cfg["camera_x_mm"])
        ray_starts = np.asarray([ray["start"] for ray in rays])+shift
        ray_ends = np.asarray([ray["end"] for ray in rays])+shift
        ray_lengths = np.linalg.norm(ray_ends-ray_starts, axis=1)
        ray_directions = (ray_ends-ray_starts)/ray_lengths[:, None]
        ray_blockers = []
        for part in parts:
            if part["id"] in ("o1_gel_core_witness", "o1_mirror_sheet_witness", "o1_mirror_bond_witness", "o1_camera_lens_reference"):
                continue
            mesh = trimesh.load_mesh(folder/part["stl"], process=True)
            positions, indices, _ = mesh.ray.intersects_location(ray_starts, ray_directions, multiple_hits=True)
            for point, index in zip(positions, indices):
                distance = np.dot(point-ray_starts[index], ray_directions[index])
                if .01 < distance < ray_lengths[index]-.05:
                    ray_blockers.append({"part": part["id"], "ray": int(index), "leg": rays[index]["leg"], "point": point.tolist()})
        report = {"schema": "yam-o1-root-bay-result/1", "physical_specimens_tested": 0, "parts": parts,
                  "added_reach_mm": reach, "finger_to_drive_translation_mm": shift.tolist(),
                  "protected_regions": preservation, "checks": checks, "failures": failures,
                  "ray_segments": len(rays), "opaque_ray_blockers": ray_blockers,
                  "passed_nominal_checks": not failures and not ray_blockers and all(row["passed"] for row in preservation),
                  "source_frame_conversion": receipt,
                  "camera_plane": {"origin": pcb_origin.tolist(), "x_axis": list(plane.xDir.toTuple()), "normal": axis.tolist()},
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": cfg["limits"]+["The original mount geometry is retained at the drive; the sensing core and camera move distally.",
                                         "Install the drive fasteners before the camera where tool access requires it.",
                                         "Camera optical cavities and component details are not validated by these dimensional references."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "checks": len(checks),
                            "added_reach_mm": reach, "preservation": preservation, "failures": failures,
                            "opaque_ray_blockers": ray_blockers}
        print(json.dumps(record["result"], indent=2))
        if not report["passed_nominal_checks"]:
            raise ValueError("Resolve the bay/frame/hardware findings")


if __name__ == "__main__":
    main()
