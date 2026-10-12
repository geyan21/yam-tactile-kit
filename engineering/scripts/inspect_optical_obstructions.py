#!/usr/bin/python3
"""Locate original-frame and TPU obstructions for the passing O1 ray candidates."""

import argparse
from datetime import datetime, timezone
import csv
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/optical-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import numpy as np
import trimesh
from analyze_baseline_meshes import PARTS
from screen_f1_feedback import digest
from tactile_kit.records import execution


def segments(candidate, targets, half_width, camera_x):
    c = np.asarray(candidate["camera_yz_mm"])
    v = np.asarray(candidate["virtual_camera_yz_mm"])
    m = np.asarray(candidate["mirror_points_yz_mm"])
    delta = targets-v
    fractions = np.sum((m-v)*delta, axis=1)/np.sum(delta*delta, axis=1)
    rows = []
    for index, target in enumerate(targets):
        for offset in (-half_width, 0, half_width):
            start = np.r_[camera_x, c]
            reflection = np.r_[camera_x+fractions[index]*offset, m[index]]
            end = np.r_[camera_x+offset, target]
            for leg, a, b in (("camera_to_mirror", start, reflection), ("mirror_to_gel", reflection, end)):
                rows.append({"station": index, "x_offset_mm": offset, "leg": leg, "start": a, "end": b})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("search", type=Path)
    args = parser.parse_args()
    source = args.search.resolve()
    if not source.is_relative_to(ROOT/"build"):
        parser.error("Use the generated optical path search")
    result = json.loads((source/"report.json").read_text())
    verify = result["input_sha256"]
    for name, expected in verify.items():
        if digest(ROOT/name) != expected:
            raise ValueError("Search input changed: "+name)
    cfg_path = ROOT/"engineering/designs/optical_path_search.json"
    cfg = json.loads(cfg_path.read_text())
    candidates = [(index, row) for index, row in enumerate(result["trials"]) if row["failed"] is None]
    targets = np.asarray(result["optical_targets_inner_yz_mm"])
    meshes = {name: trimesh.load_mesh(PARTS[name], process=True) for name in ("hard_frame", "soft_insert")}
    folder = ROOT/"build/engineering/prototypes/optical/obstruction_reviews"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Intersect all passing neutral optical paths with the actual original frame/TPU, identifying where a hollow insert or frame revision is needed without changing source geometry") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [Path(__file__), source/"report.json", cfg_path, *[PARTS[name] for name in meshes]]
        for path in inputs:
            copy = folder/"inputs"/path.relative_to(ROOT)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, copy)
        reports, all_hits = [], []
        for index, candidate in candidates:
            lines = segments(candidate, targets, cfg["active_half_width_mm"], cfg["camera_x_mm"])
            starts, ends = np.asarray([row["start"] for row in lines]), np.asarray([row["end"] for row in lines])
            lengths = np.linalg.norm(ends-starts, axis=1)
            directions = (ends-starts)/lengths[:, None]
            counts = {}
            for material, mesh in meshes.items():
                locations, ray_indices, face_indices = mesh.ray.intersects_location(
                    starts, directions, multiple_hits=True)
                valid = []
                for point, ray, face in zip(locations, ray_indices, face_indices):
                    distance = np.dot(point-starts[ray], directions[ray])
                    if not .01 < distance < lengths[ray]-.05:
                        continue
                    region = "proximal_y_ge_minus15" if point[1] >= -15 else "nail_y_le_minus96" if point[1] <= -96 else "body"
                    hit = {"candidate": index, "material": material, "ray": int(ray), "leg": lines[ray]["leg"],
                           "station": lines[ray]["station"], "x_offset_mm": lines[ray]["x_offset_mm"],
                           "face": int(face), "region": region, "x_mm": float(point[0]), "y_mm": float(point[1]),
                           "z_mm": float(point[2]), "distance_from_ray_start_mm": float(distance)}
                    valid.append(hit); all_hits.append(hit)
                counts[material] = {"rays_blocked": len({row["ray"] for row in valid}), "surface_hits": len(valid),
                                    "hits_by_region": {region: sum(row["region"] == region for row in valid)
                                                      for region in ("proximal_y_ge_minus15", "nail_y_le_minus96", "body")},
                                    "hit_bounds_mm": [np.min([[row["x_mm"], row["y_mm"], row["z_mm"]] for row in valid], axis=0).tolist(),
                                                       np.max([[row["x_mm"], row["y_mm"], row["z_mm"]] for row in valid], axis=0).tolist()] if valid else None}
            reports.append({"candidate": index, "camera_yz_mm": candidate["camera_yz_mm"],
                            "mirror_slope": candidate["mirror_slope"], "mirror_intercept_mm": candidate["mirror_intercept_mm"],
                            "mirror_max_z_mm": candidate["mirror_max_z_mm"], "segments_checked": len(lines), "original_material_hits": counts})
            print(f"Candidate {index}: {counts['hard_frame']['rays_blocked']} frame-blocked, {counts['soft_insert']['rays_blocked']} TPU-blocked segments", flush=True)
        if all_hits:
            with (folder/"hits.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, list(all_hits[0]), lineterminator="\n")
                writer.writeheader(); writer.writerows(all_hits)
        report = {"schema": "yam-o1-original-obstructions/1", "physical_specimens_tested": 0,
                  "candidates": reports, "source_frame_modified": False,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": ["Zero-width ray centre lines on the original meshes; no aperture/body-clearance or manufacturing tolerance proof.",
                             "Coordinate regions locate obstructions. They are not an identification or strength qualification of the actual drive mount.",
                             "An integrated hollow structure, retention, illumination, camera mount and physical optical/force tests remain."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "candidates": len(reports), "surface_hits": len(all_hits)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
