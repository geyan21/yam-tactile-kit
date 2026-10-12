#!/usr/bin/python3
"""Integrate the checked O1 light board, camera-mounted carrier and thin N0 nails."""

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
from shapely.geometry import Polygon
import trimesh
from prototype_cad import block, yz_prism, packed
from optical_cad import export_part
from build_pneumatic_ported_assembly import cyl, overlap
from inspect_optical_obstructions import segments
from screen_f1_feedback import digest
from tactile_kit.records import execution

CONFIG = ROOT/"engineering/designs/optical_light_mount.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cartridge", type=Path, required=True)
    parser.add_argument("--board", type=Path, required=True)
    args = parser.parse_args()
    source, electronics = args.cartridge.resolve(), args.board.resolve()
    if not all(p.is_relative_to(ROOT/"build") for p in (source, electronics)):
        parser.error("Use checked O1 runs from this checkout")
    cartridge = json.loads((source/"report.json").read_text())
    board = json.loads((electronics/"o1_blue_ring.json").read_text())
    native = json.loads((electronics/"latest_check.json").read_text())
    for report in (cartridge, board):
        for name, expected in report["input_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError("An assembly input changed: "+name)
    if (not cartridge["passed_nominal_checks"] or native["violations"] or native["unconnected"]
            or native["source_sha256"] != digest(electronics/"o1_blue_ring.kicad_pcb")):
        raise ValueError("Require passing unchanged cartridge and light board")
    cfg = json.loads(CONFIG.read_text())
    led_cfg_path = ROOT/"engineering/designs/optical_led_board.json"
    led_cfg = json.loads(led_cfg_path.read_text())
    root_report_path = ROOT/next(name for name in cartridge["input_sha256"] if "/root_bays/" in name and name.endswith("report.json"))
    root_report = json.loads(root_report_path.read_text())
    camera_plane = root_report["camera_plane"]
    plane = cq.Plane(origin=tuple(camera_plane["origin"]), xDir=tuple(camera_plane["x_axis"]), normal=tuple(camera_plane["normal"]))
    search_path = ROOT/next(name for name in cartridge["input_sha256"] if "/path_searches/" in name and name.endswith("report.json"))
    plan = json.loads(search_path.read_text())
    search_cfg = json.loads((ROOT/plan["configuration"]).read_text())
    r1_path = ROOT/"engineering/release/r1/r1_manifest.json"
    nail_path = ROOT/"engineering/release/contact_regions/contact_report.json"
    r1, nail = json.loads(r1_path.read_text()), json.loads(nail_path.read_text())
    folder = ROOT/"build/engineering/prototypes/optical/assemblies"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Integrate the camera-mounted O1 blue ring, explicit longer screws, coating envelope and retained N0 nail cells; check every nominal material pair and optical ray") as record:
        folder.mkdir(parents=True)
        inputs = [CONFIG, led_cfg_path, Path(__file__), ROOT/"engineering/scripts/optical_cad.py",
                  ROOT/"engineering/scripts/prototype_cad.py", ROOT/"engineering/scripts/inspect_optical_obstructions.py",
                  source/"report.json", electronics/"o1_blue_ring.json", electronics/"o1_blue_ring.kicad_pcb",
                  electronics/"latest_check.json", root_report_path, search_path, ROOT/plan["configuration"], r1_path, nail_path]
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        # Mount IDs 0/1 are the two camera holes at v = -0.1 mm.
        omitted = {f"o1_camera_mount_{i}_{kind}" for i in (0, 1) for kind in ("screw", "washer")}
        items = []
        for part in cartridge["parts"]:
            if part["id"] in omitted:
                continue
            path = source/part["step"]
            if digest(path) != part["sha256_step"]:
                raise ValueError("Changed cartridge CAD")
            shape = cq.importers.importStep(str(path)).val()
            group = "o1_gel" if "gel_blank" in part["id"] else "o1_frame" if part["kind"] == "fabricate" else "o1_reference"
            color = "#83b9ae" if group == "o1_gel" else "#849e93" if group == "o1_frame" else "#8c9aa4"
            items.append((part["id"], shape, part["purpose"], part["material"], part["kind"], group, color))
        def add(name, shape, purpose, material, kind="reference_only", group="o1_lighting", color="#557da3", local=True):
            items.append((name, shape.moved(plane.location) if local else shape, purpose, material, kind, group, color))
        floor0, floor1 = cfg["carrier_floor_n_mm"]
        half = cfg["carrier_outer_uv_half_mm"]
        holder = block(-half, half, -half, half, floor0, floor1).cut(
            cyl(cfg["carrier_aperture_diameter_mm"]/2, floor1-floor0+.2, [0, 0, floor0-.1], [0, 0, 1]))
        for sign in (-1, 1):
            lower, upper = sorted((sign*(8+cfg["pcb_edge_clearance_mm"]), sign*half))
            holder = holder.fuse(block(lower, upper, *cfg["clip_v_mm"], floor1, cfg["clip_lip_n_mm"][1]))
            lower, upper = sorted((sign*cfg["clip_lip_inner_abs_u_mm"], sign*half))
            holder = holder.fuse(block(lower, upper, *cfg["clip_v_mm"], *cfg["clip_lip_n_mm"]))
        for index, (u, v) in enumerate(cfg["camera_front_mount_uv_mm"]):
            holder = holder.fuse(cyl(cfg["post_diameter_mm"]/2, cfg["post_n_mm"][1]-cfg["post_n_mm"][0],
                                     [u, v, cfg["post_n_mm"][0]], [0, 0, 1]),
                                 block(min(u, 0), max(u, 0), *cfg["bridge_v_mm"], floor0, floor1))
            holder = holder.cut(cyl(cfg["mount_clear_hole_mm"]/2, 7, [u, v, -.1], [0, 0, 1]))
            holder = holder.cut(cyl(2.25+cfg["washer_radial_clearance_mm"],
                                   cfg["clip_lip_n_mm"][1]-floor1+.2,
                                   [u, v, floor1], [0, 0, 1]))
            washer_total = cfg["washer_count_per_light_mount"]*cfg["washer_thickness_mm"]
            seat = floor1+washer_total
            screw = cyl(1, cfg["replacement_screw_length_mm"], [u, v, seat-cfg["replacement_screw_length_mm"]], [0, 0, 1]).fuse(
                cyl(1.9, 2, [u, v, seat], [0, 0, 1]))
            for washer_index in range(cfg["washer_count_per_light_mount"]):
                base = floor1+washer_index*cfg["washer_thickness_mm"]
                washer = cyl(2.25, cfg["washer_thickness_mm"], [u, v, base], [0, 0, 1]).cut(
                    cyl(1.1, cfg["washer_thickness_mm"], [u, v, base], [0, 0, 1]))
                add(f"o1_light_mount_{index}_washer_{washer_index}", washer,
                    "One of three M2 washers on the carrier; stack provides screw-tip clearance", "Measured M2 washer, 0.5 mm")
            add(f"o1_light_mount_{index}_screw", screw, "M2x14 replaces the front camera M2x8; original nut remains", "Measured M2x14 screw")
        # The bridges must also leave the barrel's independent aperture clear.
        holder = holder.cut(cyl(cfg["carrier_aperture_diameter_mm"]/2, 7, [0, 0, -.1], [0, 0, 1]))
        holder = holder.cut(block(*cfg["lead_exit_u_mm"], *cfg["lead_exit_v_mm"], floor0-.1, floor1+.1)).clean()
        add("o1_led_carrier", holder, "Rigid carrier on existing camera screws, lens aperture and two PCB edge lips",
            "Opaque PETG/PA12 print; actual snap retention unqualified", "fabricate", color="#b19879")
        face = led_cfg["camera_local_component_face_n_mm"]
        pcb_shape = block(-8, 8, -8, 8, face-board["thickness_mm"], face)
        for hole in board["holes"]:
            pcb_shape = pcb_shape.cut(cyl(hole["diameter_mm"]/2, board["thickness_mm"]+.2,
                                          [hole["center_mm"][0]-8, 8-hole["center_mm"][1], face-board["thickness_mm"]-.1], [0, 0, 1]))
        for pad in board["pads"]:
            if pad["drill"]:
                pcb_shape = pcb_shape.cut(cyl(pad["drill"]/2, board["thickness_mm"]+.2,
                                              [pad["center"][0]-8, 8-pad["center"][1], face-board["thickness_mm"]-.1], [0, 0, 1]))
        add("o1_led_pcb_reference", pcb_shape.clean(), "16x16x0.8 mm two-layer ring; component face toward mirror", "FR4; order the checked fabrication ZIP", color="#3c8272")
        for part in board["parts"]:
            width, height, depth = part["body_mm"]
            shape = block(-width/2, width/2, -height/2, height/2, 0, depth).rotate((0, 0, 0), (0, 0, 1), part["rotation_deg"])
            shape = shape.translate((part["center_mm"][0]-8, 8-part["center_mm"][1], face))
            add("o1_"+part["reference"]+"_body_reference", shape, "Nominal body: "+part["value"],
                "Purchased component or solder-wire clearance reference", color="#608bd4" if part["reference"].startswith("D") else "#bb9864")
        reach = cartridge["added_reach_mm"]; shift = np.array([0., -reach, 0.])
        outer = np.asarray(plan["outer_gel_profile_yz_mm"])
        coat = Polygon(np.vstack((outer-[0, cfg["white_coating_vertical_thickness_target_mm"]], outer[::-1])))
        add("o1_white_coating_reference", yz_prism(coat, search_cfg["camera_x_mm"]-6.5, 13).translate(tuple(shift)),
            "Nominal 0.1 mm white coating over black marker dots; cured thickness/opacity must be measured",
            "Psycho Paint / Silc Pig White", group="o1_gel", color="#e4e2d4", local=False)
        u, v = np.asarray(nail["nail_plane_u_axis_native"]), np.asarray(nail["nail_plane_v_axis_native"])
        normal = np.cross(u, v); origin = np.asarray(nail["nail_plane_origin_native_mm"])+shift
        for cell in r1["nail_active_cells"]:
            for suffix, low, high, material in (("mount", 0, .1, "0.1 mm conformal mounting adhesive target"),
                                                ("n0_laminate", .1, .4, "0.3 mm R1 N0 pressure-film laminate target")):
                nail_plane = cq.Plane(origin=tuple(origin+low*normal), xDir=tuple(u), normal=tuple(normal))
                shape = cq.Workplane(nail_plane).polyline(cell["outer"][:-1]).close().extrude(high-low).val()
                add(f"o1_ch{cell['id']}_{suffix}", shape, "Retained R1 CH0/CH1 thin nail construction; separate 100k continuity resistor at each cell",
                    material, group="o1_nails", color="#c29a5a", local=False)
        parts, models, checks = [], [], []
        for index, (name, shape, purpose, material, kind, group, color) in enumerate(items):
            mesh = export_part(shape, name, folder, parts, purpose, material, kind)
            models.append(packed(mesh, name, group, color))
            for other_name, other, *_ in items[index+1:]:
                checks.append({"a": name, "b": other_name, "overlap_mm3": overlap(shape, other)})
        failures = [row for row in checks if row["overlap_mm3"] > .001]
        rays = segments(plan["selected"], np.asarray(plan["optical_targets_inner_yz_mm"]),
                        search_cfg["active_half_width_mm"], search_cfg["camera_x_mm"])
        origins = np.asarray([row["start"] for row in rays])+shift
        ends = np.asarray([row["end"] for row in rays])+shift
        lengths = np.linalg.norm(ends-origins, axis=1); directions = (ends-origins)/lengths[:, None]
        blocked = []
        for part in parts:
            if part["id"] in ("o1_retained_gel_blank", "o1_mirror_sheet_witness", "o1_mirror_bond_witness", "o1_camera_lens_reference"):
                continue
            mesh = trimesh.load_mesh(folder/part["stl"], process=True)
            points, indices, _ = mesh.ray.intersects_location(origins, directions, multiple_hits=True)
            for point, index in zip(points, indices):
                distance = np.dot(point-origins[index], directions[index])
                if .01 < distance < lengths[index]-.05:
                    blocked.append({"part": part["id"], "ray": int(index), "point": point.tolist()})
        report = {"schema": "yam-o1-assembled-prototype/1", "parts": parts, "checks": checks,
                  "failures": failures, "opaque_ray_blockers": blocked, "ray_segments": len(rays),
                  "passed_nominal_checks": not failures and not blocked, "physical_specimens_tested": 0,
                  "added_reach_mm": reach, "nominal_nail_addition_mm": .4,
                  "camera_plane": camera_plane, "led_pcb_mapping": "u=KiCad x-8; v=8-KiCad y; component face n=5.6",
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": cfg["limits"]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "checks": len(checks),
                            "failures": failures, "opaque_ray_blockers": blocked}
        print(json.dumps(record["result"], indent=2))
        if failures or blocked:
            raise ValueError("Resolve final assembly findings")


if __name__ == "__main__":
    main()
