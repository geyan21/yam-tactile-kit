#!/usr/bin/python3
"""Add the retained gel, removable side clips and opaque chamber walls to O1."""

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
from source_brep import load as source_solid
from build_pneumatic_ported_assembly import cyl, overlap
from build_optical_root_bay import hex_prism
from build_b1_parts import side_outline, vertical_intervals
from analyze_baseline_meshes import PARTS
from inspect_optical_obstructions import segments
from screen_f1_feedback import digest
from tactile_kit.records import execution

CONFIG = ROOT/"engineering/designs/optical_gel_cartridge.json"
MATERIALS = ROOT/"engineering/designs/optical_materials.json"


def profile_band(y, z, low, high):
    return Polygon(np.vstack((np.column_stack((y, z+low)), np.column_stack((y, z+high))[::-1])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bay", type=Path)
    args = parser.parse_args()
    source = args.bay.resolve()
    if not source.is_relative_to(ROOT/"build"):
        parser.error("Use the checked root bay")
    bay = json.loads((source/"report.json").read_text())
    if not bay["passed_nominal_checks"]:
        raise ValueError("Resolve the root-bay checks first")
    for name, expected in bay["input_sha256"].items():
        if digest(ROOT/name) != expected:
            raise ValueError("Bay input changed: "+name)
    cfg, materials = json.loads(CONFIG.read_text()), json.loads(MATERIALS.read_text())
    search_path = ROOT/next(name for name in bay["input_sha256"] if "/path_searches/" in name and name.endswith("/report.json"))
    plan = json.loads(search_path.read_text())
    search_cfg = json.loads((ROOT/plan["configuration"]).read_text())
    root_cfg = json.loads((ROOT/"engineering/designs/optical_root_bay.json").read_text())
    core_cfg = json.loads((ROOT/"engineering/designs/optical_core_witness.json").read_text())
    reach = bay["added_reach_mm"]
    shift = (0, -reach, 0)
    outer, inner = np.asarray(plan["outer_gel_profile_yz_mm"]), np.asarray(plan["inner_gel_profile_yz_mm"])
    y, z = inner[:, 0], inner[:, 1]
    cx = search_cfg["camera_x_mm"]
    gel_profile = Polygon(np.vstack((outer, inner[::-1])))
    flange_profile = profile_band(y, z, -cfg["gel_rear_flange_vertical_thickness_mm"], 0)
    folder = ROOT/"build/engineering/prototypes/optical/gel_cartridges"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Build O1's retained gel and removable side clips, close the optical chamber and check complete material/optical interfaces without inventing physical sensing results") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [CONFIG, MATERIALS, Path(__file__), source/"report.json", search_path, ROOT/plan["configuration"],
                  ROOT/"engineering/designs/optical_root_bay.json", ROOT/"engineering/designs/optical_core_witness.json",
                  ROOT/"engineering/scripts/prototype_cad.py", ROOT/"engineering/scripts/optical_cad.py",
                  ROOT/"engineering/scripts/build_optical_root_bay.py",
                  ROOT/"engineering/scripts/inspect_optical_obstructions.py"]
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        loaded = {}
        for part in bay["parts"]:
            path = source/part["step"]
            if digest(path) != part["sha256_step"]:
                raise ValueError("Bay CAD changed")
            loaded[part["id"]] = cq.importers.importStep(str(path)).val()
        # Work in original finger coordinates, then translate the new pieces
        # into the drive-referenced frame used by the root-bay package.
        frame = loaded["o1_frame_with_camera_bay"].translate((0, reach, 0))
        gel = yz_prism(gel_profile, cx-cfg["gel_main_width_mm"]/2, cfg["gel_main_width_mm"])
        gel = gel.fuse(yz_prism(flange_profile, cx-cfg["gel_rear_flange_width_mm"]/2,
                                cfg["gel_rear_flange_width_mm"])).clean()
        sil = side_outline(trimesh.load_mesh(PARTS["hard_frame"], process=True))
        roof = plan["selected"]
        my0, my1 = roof["mirror_y_mm"]
        bay_front = root_cfg["front_bay_attach_source_y_mm"]
        start_bridge = my1-cfg["hood_bridge_overlap_y_mm"]
        bond_top = core_cfg["mirror_thickness_mm"]+core_cfg["mirror_bond_thickness_mm"]
        m, b = roof["mirror_slope"], roof["mirror_intercept_mm"]
        bridge_front_z = m*my1+b+bond_top*np.sqrt(1+m*m)
        yy = np.linspace(float(y[0]), bay_front, 350)
        bottom = np.interp(yy, outer[:, 0], outer[:, 1])+cfg["side_wall_front_recess_z_mm"]
        blend = np.clip((yy-y[-1])/(core_cfg["root_floor_starts_y_mm"]-y[-1]), 0, 1)
        bottom = (1-blend)*bottom+blend*core_cfg["root_floor_z_mm"]
        original_top = np.asarray([vertical_intervals(sil, val)[-1][1] for val in yy])
        mirror_top = m*yy+b+(bond_top+core_cfg["rigid_backing_thickness_mm"])*np.sqrt(1+m*m)
        bridge_low = bridge_front_z+(yy-my1)*(root_cfg["wall_top_z_mm"]-bridge_front_z)/(bay_front-my1)
        upper = np.maximum(original_top, np.where(yy < my0, original_top,
                              np.where(yy <= my1, mirror_top, bridge_low+cfg["hood_bridge_thickness_mm"])))
        chamber = Polygon(np.vstack((np.column_stack((yy, bottom)), np.column_stack((yy, upper))[::-1])))
        additions = [yz_prism(chamber, limits[0], limits[1]-limits[0]) for limits in cfg["side_wall_x_mm"]]
        bridge_y = np.linspace(start_bridge, bay_front, 100)
        bridge_z = bridge_front_z+(bridge_y-my1)*(root_cfg["wall_top_z_mm"]-bridge_front_z)/(bay_front-my1)
        bridge_profile = profile_band(bridge_y, bridge_z, 0, cfg["hood_bridge_thickness_mm"])
        additions.append(yz_prism(bridge_profile, cfg["side_wall_x_mm"][0][0],
                                 cfg["side_wall_x_mm"][1][1]-cfg["side_wall_x_mm"][0][0]))
        for limits in cfg["seat_x_mm"]:
            additions.append(yz_prism(profile_band(y, z, *cfg["seat_vertical_offsets_from_inner_mm"]),
                                      limits[0], limits[1]-limits[0]))
        frame = frame.fuse(*additions).clean()
        clearance = cfg["frame_pocket_clearance_mm"]
        frame = frame.cut(yz_prism(gel_profile.buffer(clearance), cx-cfg["gel_main_width_mm"]/2-clearance,
                                  cfg["gel_main_width_mm"]+2*clearance))
        flange_room = profile_band(y, z, -cfg["gel_rear_flange_vertical_thickness_mm"]-cfg["seat_bond_vertical_thickness_mm"],
                                    clearance)
        frame = frame.cut(yz_prism(flange_room, cx-cfg["gel_rear_flange_width_mm"]/2-clearance,
                                  cfg["gel_rear_flange_width_mm"]+2*clearance)).clean()
        clips, clip_pockets, stations = [], [], []
        fast = cfg["clip_fastener"]
        for side in range(2):
            limits = cfg["clip_lip_x_mm"][side]
            lip = yz_prism(profile_band(y, z, *cfg["clip_lip_vertical_offsets_mm"]), limits[0], limits[1]-limits[0])
            pocket_profile = profile_band(y, z, 0, cfg["clip_lip_vertical_offsets_mm"][1]+clearance)
            pockets = [yz_prism(pocket_profile, limits[0]-clearance, limits[1]-limits[0]+2*clearance)]
            for index, station in enumerate(cfg["clip_stations_y_mm"]):
                level = float(np.interp(station, y, z))
                x = cfg["clip_boss_x_mm"][side]
                boss_low, boss_high = [level+value for value in cfg["clip_boss_vertical_offsets_mm"]]
                frame = frame.fuse(cyl(cfg["clip_boss_diameter_mm"]/2, boss_high-boss_low, [x, station, boss_low], [0, 0, 1])).clean()
                tab_low, tab_high = [level+value for value in cfg["clip_tab_vertical_offsets_mm"]]
                tab = cyl(cfg["clip_boss_diameter_mm"]/2, tab_high-tab_low, [x, station, tab_low], [0, 0, 1])
                bridge_x = cfg["clip_bridge_x_mm"][side]
                web = block(*bridge_x, station-cfg["clip_arm_half_width_y_mm"], station+cfg["clip_arm_half_width_y_mm"],
                            level+cfg["clip_lip_vertical_offsets_mm"][0], tab_high)
                arm = block(min(x, *bridge_x), max(x, *bridge_x), station-cfg["clip_arm_half_width_y_mm"],
                            station+cfg["clip_arm_half_width_y_mm"], tab_low, tab_high)
                lip = lip.fuse(tab, web, arm).clean()
                pockets += [block(bridge_x[0]-clearance, bridge_x[1]+clearance,
                                   station-cfg["clip_arm_half_width_y_mm"]-clearance,
                                   station+cfg["clip_arm_half_width_y_mm"]+clearance, level, tab_high+clearance),
                            block(min(x, *bridge_x)-clearance, max(x, *bridge_x)+clearance,
                                  station-cfg["clip_arm_half_width_y_mm"]-clearance,
                                  station+cfg["clip_arm_half_width_y_mm"]+clearance, tab_low, tab_high+clearance),
                            cyl(cfg["clip_boss_diameter_mm"]/2+clearance, tab_high-tab_low+clearance,
                                [x, station, tab_low], [0, 0, 1])]
                bore = cyl(fast["clear_hole_mm"]/2, 8, [x, station, level-1.1], [0, 0, 1])
                lip = lip.cut(bore).clean()
                frame = frame.cut(bore).clean()
                p0, p1 = [level+value for value in cfg["clip_nut_pocket_vertical_offsets_mm"]]
                frame = frame.cut(hex_prism(x, station, p0, p1, fast["nut_pocket_af_mm"]))
                radius = cfg["clip_boss_diameter_mm"]/2
                a, c = (x-radius-.1, x) if side == 0 else (x, x+radius+.1)
                frame = frame.cut(block(a, c, station-fast["nut_pocket_af_mm"]/2,
                                        station+fast["nut_pocket_af_mm"]/2, p0, p1)).clean()
                stations.append({"id": f"o1_gel_clip_{side}_{index}", "x": x, "y": station, "inner_z": level, "tab_top": tab_high})
            clips.append(lip)
            clip_pockets.extend(pockets)
        for pocket in clip_pockets:
            frame = frame.cut(pocket).clean()
        if not frame.isValid() or len(frame.Solids()) != 1 or any(not clip.isValid() or len(clip.Solids()) != 1 for clip in clips):
            cq.exporters.export(frame, str(folder/"failed_cartridge_frame.step"))
            for i, clip in enumerate(clips):
                cq.exporters.export(clip, str(folder/f"failed_clip_{i}.step"))
            raise ValueError("Cartridge frame or removable clip is invalid/disconnected")
        items = [("o1_retained_gel_frame", frame.translate(shift), "Fixed-optics frame with retained root bay, closed side walls and gel seats",
                  "Opaque rigid PETG/PA12 prototype", "fabricate", "o1_frame", "#849e93"),
                 ("o1_retained_gel_blank", gel.translate(shift), "Cast clear silicone gel with rear flanges; use its mold, not a rigid printed substitution",
                  materials["gel"]["part"], "reference_only", "o1_gel", "#83b9ae")]
        for index, clip in enumerate(clips):
            items.append((f"o1_gel_retaining_clip_{index}", clip.translate(shift), "Removable side clip retaining the gel's rear flange",
                          "Opaque rigid PETG/PA12 prototype", "fabricate", "o1_gel_clips", "#829d9f"))
        for side, limits in enumerate(cfg["seat_x_mm"]):
            overlap_x = [max(limits[0], cx-cfg["gel_rear_flange_width_mm"]/2),
                         min(limits[1], cx+cfg["gel_rear_flange_width_mm"]/2)]
            bond = yz_prism(profile_band(y, z, -cfg["gel_rear_flange_vertical_thickness_mm"]-cfg["seat_bond_vertical_thickness_mm"],
                                         -cfg["gel_rear_flange_vertical_thickness_mm"]), overlap_x[0], overlap_x[1]-overlap_x[0])
            items.append((f"o1_gel_seat_bond_{side}", bond.translate(shift), "Nominal thin seating bond; qualify adhesion and cured thickness",
                          "Silicone-compatible bond/process reference", "reference_only", "o1_bonds", "#c6a16f"))
        for part in bay["parts"]:
            if part["id"] in ("o1_frame_with_camera_bay", "o1_gel_core_witness"):
                continue
            items.append((part["id"], loaded[part["id"]], part["purpose"], part["material"], part["kind"],
                          "o1_camera_bay_parts", "#859fa9"))
        for station in stations:
            x, sy, level = station["x"], station["y"], station["inner_z"]
            washer_low = station["tab_top"]
            washer = cyl(fast["washer_od_mm"]/2, fast["washer_thickness_mm"], [x, sy, washer_low], [0, 0, 1]).cut(
                cyl(fast["washer_id_mm"]/2, fast["washer_thickness_mm"], [x, sy, washer_low], [0, 0, 1]))
            seat = washer_low+fast["washer_thickness_mm"]
            screw = cyl(fast["shaft_diameter_mm"]/2, fast["length_mm"], [x, sy, seat-fast["length_mm"]], [0, 0, 1]).fuse(
                cyl(fast["head_diameter_mm"]/2, fast["head_height_mm"], [x, sy, seat], [0, 0, 1]))
            low, high = [level+v for v in cfg["clip_nut_vertical_offsets_mm"]]
            nut = hex_prism(x, sy, low, high, fast["nut_af_mm"]).cut(cyl(fast["shaft_diameter_mm"]/2, high-low, [x, sy, low], [0, 0, 1]))
            for suffix, shape in (("washer", washer), ("screw", screw), ("nut", nut)):
                items.append((station["id"]+"_"+suffix, shape.translate(shift), "Gel-clip M2 dimensional hardware; thread form not modeled",
                              "Measured M2 hardware", "reference_only", "o1_gel_hardware", "#8f9da4"))
        parts, models, checks = [], [], []
        for index, (name, shape, purpose, material, kind, group, color) in enumerate(items):
            mesh = export_part(shape, name, folder, parts, purpose, material, kind)
            models.append(packed(mesh, name, group, color))
            for other_name, other, *_ in items[index+1:]:
                checks.append({"a": name, "b": other_name, "overlap_mm3": overlap(shape, other)})
        failures = [row for row in checks if row["overlap_mm3"] > .001]
        rays = segments(plan["selected"], np.asarray(plan["optical_targets_inner_yz_mm"]),
                        search_cfg["active_half_width_mm"], search_cfg["camera_x_mm"])
        origins = np.asarray([row["start"] for row in rays])+np.asarray(shift)
        ends = np.asarray([row["end"] for row in rays])+np.asarray(shift)
        lengths = np.linalg.norm(ends-origins, axis=1)
        directions = (ends-origins)/lengths[:, None]
        blocked = []
        for part in parts:
            if part["id"] in ("o1_retained_gel_blank", "o1_mirror_sheet_witness", "o1_mirror_bond_witness", "o1_camera_lens_reference"):
                continue
            mesh = trimesh.load_mesh(folder/part["stl"], process=True)
            locations, indices, _ = mesh.ray.intersects_location(origins, directions, multiple_hits=True)
            for point, index in zip(locations, indices):
                distance = np.dot(point-origins[index], directions[index])
                if .01 < distance < lengths[index]-.05:
                    blocked.append({"part": part["id"], "ray": int(index), "point": point.tolist()})
        original, _ = source_solid("hard_frame")
        preserved = []
        regions = [("leading_nail", original.translate(shift), block(-50, 30, -190, -96-reach, -20, 80)),
                   ("drive_interface", original, block(-50, 30, root_cfg["protected_interface_y_min_mm"], 10, -20, 80))]
        for index, xz in enumerate(root_cfg["mount_guard_xz_centers_mm"]):
            guard = cyl(root_cfg["mount_guard_radius_mm"], root_cfg["mount_guard_y_mm"][1]-root_cfg["mount_guard_y_mm"][0],
                        [xz[0], root_cfg["mount_guard_y_mm"][0], xz[1]], [0, 1, 0])
            regions.append(("mount_"+str(index), original, guard))
        frame_global = items[0][1]
        for name, reference, guard in regions:
            first, second = reference.intersect(guard), frame_global.intersect(guard)
            error = abs(abs(first.Volume())+abs(second.Volume())-2*overlap(first, second))
            preserved.append({"region": name, "symmetric_material_difference_mm3": error, "passed": error <= .001})
        report = {"schema": "yam-o1-retained-gel-result/1", "physical_specimens_tested": 0,
                  "parts": parts, "checks": checks, "failures": failures, "opaque_ray_blockers": blocked,
                  "preserved_regions": preserved, "clip_stations": stations, "added_reach_mm": reach,
                  "passed_nominal_checks": not failures and not blocked and all(row["passed"] for row in preserved),
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs}, "limits": cfg["limits"]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "checks": len(checks),
                            "failures": failures, "opaque_ray_blockers": blocked, "preservation": preserved}
        print(json.dumps(record["result"], indent=2))
        if not report["passed_nominal_checks"]:
            raise ValueError("Resolve gel-cartridge findings before fabrication")


if __name__ == "__main__":
    main()
