#!/usr/bin/python3
"""Build an O1 windowed-frame/fixed-mirror core and check protected source regions."""

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
from prototype_cad import yz_prism, block, export_part, packed
from source_brep import load as source_solid
from build_b1_parts import side_outline, vertical_intervals
from analyze_baseline_meshes import PARTS
from build_pneumatic_ported_assembly import cyl, overlap
from inspect_optical_obstructions import segments
from screen_f1_feedback import digest
from tactile_kit.records import execution

CONFIG = ROOT/"engineering/designs/optical_core_witness.json"


def band(a, b, normal, low, high):
    return Polygon([a+low*normal, b+low*normal, b+high*normal, a+high*normal])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("search", type=Path)
    args = parser.parse_args()
    source = args.search.resolve()
    if not source.is_relative_to(ROOT/"build"):
        parser.error("Use the generated optical path report")
    plan = json.loads((source/"report.json").read_text())
    if not plan["selected"]:
        raise ValueError("No passing optical path")
    for name, expected in plan["input_sha256"].items():
        if digest(ROOT/name) != expected:
            raise ValueError("Path-search input changed: "+name)
    cfg = json.loads(CONFIG.read_text())
    search_cfg = json.loads((ROOT/plan["configuration"]).read_text())
    chosen = plan["selected"]
    folder = ROOT/"build/engineering/prototypes/optical/core_witnesses"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Build the first fixed-optics O1 core, preserve source nail/mount regions, and check actual material/ray obstructions; keep unfinished manufacturing/physical interfaces explicit") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [CONFIG, Path(__file__), source/"report.json", ROOT/plan["configuration"],
                  ROOT/"engineering/scripts/prototype_cad.py", ROOT/"engineering/scripts/source_brep.py",
                  ROOT/"engineering/scripts/build_pneumatic_ported_assembly.py",
                  ROOT/"engineering/scripts/inspect_optical_obstructions.py"]
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        original, original_receipt = source_solid("hard_frame")
        outer, inner = np.asarray(plan["outer_gel_profile_yz_mm"]), np.asarray(plan["inner_gel_profile_yz_mm"])
        gel_profile = Polygon(np.vstack((outer, inner[::-1])))
        gel = yz_prism(gel_profile, search_cfg["camera_x_mm"]-search_cfg["gel_width_mm"]/2, search_cfg["gel_width_mm"])
        yy = np.linspace(*cfg["window_y_mm"], 500)
        floor = np.interp(yy, inner[:, 0], inner[:, 1])-cfg["window_body_floor_inset_mm"]
        transition = np.clip((yy-inner[-1, 0])/(cfg["root_floor_starts_y_mm"]-inner[-1, 0]), 0, 1)
        floor = (1-transition)*floor+transition*cfg["root_floor_z_mm"]
        window_profile = Polygon([*zip(yy, floor), (yy[-1], 100), (yy[0], 100)])
        window = yz_prism(window_profile, cfg["window_x_mm"][0], cfg["window_x_mm"][1]-cfg["window_x_mm"][0])
        clearance = cfg["gel_frame_clearance_mm"]
        gel_room = yz_prism(gel_profile.buffer(clearance), search_cfg["camera_x_mm"]-search_cfg["gel_width_mm"]/2-clearance,
                            search_cfg["gel_width_mm"]+2*clearance)
        frame = original.cut(window).cut(gel_room).clean()
        print("Source frame optical opening cut.", flush=True)
        slope, intercept = chosen["mirror_slope"], chosen["mirror_intercept_mm"]
        normal = np.array([-slope, 1.])/np.sqrt(1+slope*slope)
        y0, y1 = chosen["mirror_y_mm"]
        a, b = np.array([y0, slope*y0+intercept]), np.array([y1, slope*y1+intercept])
        mirror_top = cfg["mirror_thickness_mm"]
        bond_top = mirror_top+cfg["mirror_bond_thickness_mm"]
        backing_top = bond_top+cfg["rigid_backing_thickness_mm"]
        mirror = yz_prism(band(a, b, normal, 0, mirror_top),
                          search_cfg["camera_x_mm"]-search_cfg["mirror_width_mm"]/2, search_cfg["mirror_width_mm"])
        bond = yz_prism(band(a, b, normal, mirror_top, bond_top),
                        search_cfg["camera_x_mm"]-search_cfg["mirror_width_mm"]/2, search_cfg["mirror_width_mm"])
        mirror_room = yz_prism(band(a, b, normal, -.02, bond_top),
                               search_cfg["camera_x_mm"]-search_cfg["mirror_width_mm"]/2-.1,
                               search_cfg["mirror_width_mm"]+.2)
        frame = frame.cut(mirror_room).clean()
        backing = yz_prism(band(a, b, normal, bond_top, backing_top), cfg["rigid_backing_x_mm"][0],
                           cfg["rigid_backing_x_mm"][1]-cfg["rigid_backing_x_mm"][0])
        silhouette = side_outline(trimesh.load_mesh(PARTS["hard_frame"], process=True))
        sy = np.linspace(y0, y1, 160)
        upper = slope*sy+intercept+backing_top*np.sqrt(1+slope*slope)
        lower = np.asarray([vertical_intervals(silhouette, y)[-1][1]-cfg["side_web_source_overlap_mm"] for y in sy])
        lower = np.minimum(lower, upper-.5)
        web_profile = Polygon(np.vstack((np.column_stack((sy, lower)), np.column_stack((sy, upper))[::-1])))
        webs = [yz_prism(web_profile, limits[0], limits[1]-limits[0]) for limits in cfg["side_web_x_mm"]]
        frame = frame.fuse(backing, *webs).clean()
        if not frame.isValid() or len(frame.Solids()) != 1:
            raise ValueError("Windowed frame and backing do not form one valid connected body")
        print("Fixed mirror backing and side webs joined.", flush=True)
        guards = [("nail", block(-40, 20, -150, cfg["nail_protection_y_max_mm"], -20, 60))]
        for index, center in enumerate(cfg["mount_guard_xz_centers_mm"]):
            guards.append(("mount_"+str(index), cyl(cfg["mount_guard_radius_mm"], cfg["mount_guard_y_mm"][1]-cfg["mount_guard_y_mm"][0],
                                                    [center[0], cfg["mount_guard_y_mm"][0], center[1]], [0, 1, 0])))
        preservation = []
        for name, guard in guards:
            before, after = original.intersect(guard), frame.intersect(guard)
            common = overlap(before, after)
            difference = abs(abs(before.Volume())+abs(after.Volume())-2*common)
            preservation.append({"region": name, "symmetric_material_difference_mm3": difference,
                                 "passed": difference < .001})
        objects = [("o1_frame_core_witness", frame, "Rigid frame/backing reference; complete retention and camera mount remain",
                    "PETG/PA12 frame candidate; physical stiffness unqualified", "fabricate", "o1_frame", "#91a5a0"),
                   ("o1_gel_core_witness", gel, "Candidate transparent gel section; chemistry/retention still to be completed",
                    "Optical silicone material not yet qualified", "reference_only", "o1_gel", "#78b9ae"),
                   ("o1_mirror_sheet_witness", mirror, "Reflective PET plane on a fixed backing", "0.2 mm reflective PET reference",
                    "reference_only", "o1_mirror", "#9d8ac2"),
                   ("o1_mirror_bond_witness", bond, "Nominal thin mirror adhesive layer", "0.05 mm adhesive reference",
                    "reference_only", "o1_bond", "#c6a06e")]
        parts, models, checks = [], [], []
        for index, (name, shape, purpose, material, kind, group, color) in enumerate(objects):
            mesh = export_part(shape, name, folder, parts, purpose, material, kind)
            models.append(packed(mesh, name, group, color))
            for other_name, other, *_ in objects[index+1:]:
                checks.append({"a": name, "b": other_name, "overlap_mm3": overlap(shape, other)})
        material_failures = [row for row in checks if row["overlap_mm3"] > .001]
        frame_part = parts[0]
        mesh = trimesh.load_mesh(folder/frame_part["stl"], process=True)
        rays = segments(chosen, np.asarray(plan["optical_targets_inner_yz_mm"]), search_cfg["active_half_width_mm"], search_cfg["camera_x_mm"])
        starts = np.asarray([r["start"] for r in rays]); ends = np.asarray([r["end"] for r in rays])
        lengths = np.linalg.norm(ends-starts, axis=1)
        directions = (ends-starts)/lengths[:, None]
        hits, indices, _ = mesh.ray.intersects_location(starts, directions, multiple_hits=True)
        blockers = []
        for hit, index in zip(hits, indices):
            along = float(np.dot(hit-starts[index], directions[index]))
            if .01 < along < lengths[index]-.05:
                blockers.append({"ray": int(index), "leg": rays[index]["leg"], "point": hit.tolist()})
        report = {"schema": "yam-o1-core-witness/1", "physical_specimens_tested": 0, "parts": parts,
                  "protected_regions": preservation, "material_checks": checks, "material_failures": material_failures,
                  "ray_segments": len(rays), "frame_ray_blockers": blockers,
                  "passed_core_checks": all(row["passed"] for row in preservation) and not material_failures and not blockers,
                  "source_frame_conversion": original_receipt,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": cfg["limits"]+["Ray checks are centre lines only; actual pupil/aperture and body tolerances remain."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "preservation": preservation,
                            "material_failures": material_failures, "frame_blocked_segments": len({row["ray"] for row in blockers})}
        print(json.dumps(record["result"], indent=2))
        if not report["passed_core_checks"]:
            raise ValueError("Resolve the core geometry findings before adding the remaining assembly")


if __name__ == "__main__":
    main()
