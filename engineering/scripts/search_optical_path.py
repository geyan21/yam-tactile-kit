#!/usr/bin/python3
"""Search a bounded neutral O1 folded path over the actual ENPIRE contact profile."""

import argparse
from datetime import datetime, timezone
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT/"build/engineering/tools/optical-matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/optical-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PatchPolygon
import numpy as np
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import Polygon
from analyze_b1_interfaces import original_profile
from build_b1_parts import vertical_intervals, side_outline
from analyze_baseline_meshes import PARTS
import trimesh
from screen_f1_feedback import digest
from tactile_kit.records import execution

CONFIG = ROOT/"engineering/designs/optical_path_search.json"


def surfaces(profile, cfg):
    y = np.arange(cfg["gel_y_extent_mm"][0], cfg["gel_y_extent_mm"][1]+.01, cfg["profile_sampling_mm"])
    z = np.asarray([vertical_intervals(profile, value)[0][0] for value in y])
    z = gaussian_filter1d(z, cfg["smoothing_sigma_mm"]/cfg["profile_sampling_mm"], mode="nearest")
    z += cfg["outer_surface_z_offset_mm"]
    slope = np.gradient(z, y)
    normals = np.column_stack((-slope, np.ones(len(y))))
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    outer = np.column_stack((y, z))
    inner = outer+cfg["gel_normal_thickness_mm"]*normals
    polygon = Polygon(np.vstack((outer, inner[::-1])))
    if not polygon.is_valid or not np.all(np.diff(inner[:, 0]) > 0):
        raise ValueError("Smoothed gel section folds over itself; revise its curvature/thickness")
    stations = np.arange(outer[0, 0]+1., outer[-1, 0]-.5, cfg["target_pitch_mm"])
    target = np.column_stack((np.interp(stations, y, inner[:, 0]), np.interp(stations, y, inner[:, 1])))
    normal = np.column_stack((np.interp(stations, y, normals[:, 0]), np.interp(stations, y, normals[:, 1])))
    normal /= np.linalg.norm(normal, axis=1)[:, None]
    return outer, inner, polygon, target, normal


def rays_clear(starts, ends, inner, cfg, target_ends=False):
    fraction = np.linspace(0, 1, cfg["ray_samples_per_leg"])
    points = starts[:, None, :]+fraction[None, :, None]*(ends-starts)[:, None, :]
    valid = (points[:, :, 0] >= inner[0, 0]) & (points[:, :, 0] <= inner[-1, 0])
    if target_ends:
        valid &= np.linalg.norm(points-ends[:, None, :], axis=2) >= .5
    surface_z = np.interp(points[:, :, 0], inner[:, 0], inner[:, 1])
    gaps = points[:, :, 1]-surface_z
    minimum = float(np.min(gaps[valid])) if np.any(valid) else 1e6
    return minimum >= cfg["ray_to_gel_gap_mm"], minimum


def evaluate(camera, slope, intercept, target, normals, inner, cfg):
    normal = np.array([-slope, 1.])
    unit = normal/np.linalg.norm(normal)
    distance = (camera@normal-intercept)/np.linalg.norm(normal)
    if distance >= 0:
        return {"failed": "camera_wrong_mirror_side"}
    virtual = camera-2*distance*unit
    denominator = (target-virtual)@normal
    if np.any(np.abs(denominator) < 1e-9):
        return {"failed": "parallel_ray"}
    fraction = (intercept-virtual@normal)/denominator
    if np.any((fraction <= 0) | (fraction >= 1)):
        return {"failed": "target_wrong_mirror_side"}
    mirror = virtual+fraction[:, None]*(target-virtual)
    margin = cfg["mirror_edge_extension_mm"]
    low, high = mirror[:, 0].min()-margin, mirror[:, 0].max()+margin
    max_z = max(slope*low+intercept, slope*high+intercept)
    if low < cfg["mirror_y_limits_mm"][0] or high > cfg["mirror_y_limits_mm"][1] or max_z > cfg["mirror_max_z_mm"]:
        return {"failed": "mirror_envelope", "mirror_y_mm": [float(low), float(high)], "mirror_max_z_mm": float(max_z)}
    observed = mirror-target
    observed /= np.linalg.norm(observed, axis=1)[:, None]
    incidence_cos = np.sum(observed*normals, axis=1)
    if np.min(incidence_cos) < math.cos(math.radians(cfg["maximum_gel_incidence_deg"])):
        return {"failed": "gel_grazing_or_backface", "minimum_incidence_cos": float(np.min(incidence_cos))}
    incoming = mirror-camera
    root_floor = None
    if "root_ray_minimum_z_mm" in cfg:
        probes = camera+np.linspace(0, 1, cfg["ray_samples_per_leg"])[None, :, None]*incoming[:, None, :]
        zone = cfg["root_ray_y_zone_mm"]
        within = (probes[:, :, 0] >= zone[0]) & (probes[:, :, 0] <= zone[1])
        root_floor = float(np.min(probes[:, :, 1][within])) if np.any(within) else None
        if root_floor is not None and root_floor < cfg["root_ray_minimum_z_mm"]:
            return {"failed": "root_aperture_floor", "minimum_root_ray_z_mm": root_floor}
    pitch = np.arctan2(incoming[:, 1], -incoming[:, 0])
    if np.any(incoming[:, 0] >= 0):
        return {"failed": "mirror_behind_camera"}
    low_angle, high_angle = float(pitch.min()), float(pitch.max())
    bore = (low_angle+high_angle)/2
    if math.degrees(high_angle-low_angle) > cfg["usable_horizontal_vertical_fov_deg"][1]:
        return {"failed": "vertical_fov", "span_deg": math.degrees(high_angle-low_angle)}
    # Reflection from a plane independent of X shrinks target X by the
    # same virtual-camera intersection fraction.
    mirror_half_x = fraction*cfg["active_half_width_mm"]
    forward = -incoming[:, 0]*math.cos(bore)+incoming[:, 1]*math.sin(bore)
    horizontal = np.degrees(np.arctan2(mirror_half_x, forward))
    if np.max(horizontal) > cfg["usable_horizontal_vertical_fov_deg"][0]/2 or np.max(mirror_half_x)+.5 > cfg["mirror_width_mm"]/2:
        return {"failed": "horizontal_fov_or_mirror_edge"}
    clear_a, gap_a = rays_clear(np.broadcast_to(camera, mirror.shape), mirror, inner, cfg)
    clear_b, gap_b = rays_clear(mirror, target, inner, cfg, target_ends=True)
    if not clear_a or not clear_b:
        return {"failed": "gel_occludes_folded_path", "camera_leg_gap_mm": gap_a, "target_leg_gap_mm": gap_b}
    first = camera-mirror
    second = target-mirror
    first /= np.linalg.norm(first, axis=1)[:, None]
    second /= np.linalg.norm(second, axis=1)[:, None]
    tangent = np.array([1., slope])/np.sqrt(1+slope*slope)
    residual = float(np.max(np.abs((first+second)@tangent)))
    if residual > 1e-8:
        raise ValueError("Specular reflection control failed")
    paths = np.linalg.norm(mirror-camera, axis=1)+np.linalg.norm(target-mirror, axis=1)
    return {"failed": None, "camera_yz_mm": camera.tolist(), "virtual_camera_yz_mm": virtual.tolist(),
            "mirror_slope": slope, "mirror_intercept_mm": intercept, "mirror_y_mm": [float(low), float(high)],
            "mirror_max_z_mm": float(max_z), "mirror_length_mm": float((high-low)*np.sqrt(1+slope*slope)),
            "camera_pitch_above_distal_deg": math.degrees(bore),
            "vertical_ray_span_deg": math.degrees(high_angle-low_angle),
            "horizontal_ray_max_abs_deg": float(np.max(horizontal)),
            "maximum_gel_incidence_deg": math.degrees(math.acos(float(np.min(incidence_cos)))),
            "minimum_camera_leg_gap_mm": gap_a, "minimum_target_leg_gap_mm": gap_b,
            "minimum_root_ray_z_mm": root_floor,
            "path_length_range_mm": [float(paths.min()), float(paths.max())],
            "reflection_tangent_residual": residual, "mirror_points_yz_mm": mirror.tolist()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    config_path = args.config.resolve()
    if not config_path.is_relative_to(ROOT/"engineering/designs"):
        parser.error("Use a versioned optical search configuration")
    cfg = json.loads(config_path.read_text())
    folder = ROOT/"build/engineering/prototypes/optical/path_searches"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Search bounded neutral camera/PET-mirror poses over the real smoothed contact profile; distinguish geometric visibility from frame integration and optical/force qualification") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [config_path, ROOT/cfg["source_review"], Path(__file__), PARTS["hard_frame"], PARTS["soft_insert"],
                  ROOT/"engineering/scripts/analyze_b1_interfaces.py", ROOT/"engineering/scripts/build_b1_parts.py"]
        for path in inputs:
            copied = folder/"inputs"/path.relative_to(ROOT)
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, copied)
        _, profile, _ = original_profile()
        outer, inner, gel, target, normals = surfaces(profile, cfg)
        trials, passing = [], []
        for y, z, slope, intercept in itertools.product(cfg["camera_pupil_y_candidates_mm"],
                cfg["camera_pupil_z_candidates_mm"], cfg["mirror_slope_candidates"], cfg["mirror_intercept_candidates_mm"]):
            result = evaluate(np.array([y, z], dtype=float), slope, intercept, target, normals, inner, cfg)
            row = {"camera_yz_mm": [y, z], "mirror_slope": slope, "mirror_intercept_mm": intercept, **result}
            trials.append(row)
            if not row["failed"]:
                passing.append(row)
        passing.sort(key=lambda row: (row["mirror_max_z_mm"], row["camera_yz_mm"][0], row["mirror_length_mm"]))
        chosen = passing[0] if passing else None
        failures = {}
        for trial in trials:
            if trial["failed"]:
                failures[trial["failed"]] = failures.get(trial["failed"], 0)+1
        (folder/"geometry_result.json").write_text(json.dumps({
            "cases": len(trials), "passing_candidates": len(passing), "failure_counts": failures,
            "selected": chosen, "trials": trials, "physical_specimens_tested": 0,
            "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs}
        }, indent=2)+"\n")
        fig, axis = plt.subplots(figsize=(13, 6), layout="constrained")
        hard = side_outline(trimesh.load_mesh(PARTS["hard_frame"], process=True))
        axis.add_patch(PatchPolygon(np.asarray(hard.exterior.coords), fill=False, ec="#9da9a1", lw=1, label="Original frame outline"))
        axis.add_patch(PatchPolygon(np.asarray(profile.exterior.coords), fc="#d9e2d5", ec="#96ac94", alpha=.45))
        for ring in profile.interiors:
            axis.add_patch(PatchPolygon(np.asarray(ring.coords), fc="white", ec="#b2c2ad", alpha=.7))
        axis.add_patch(PatchPolygon(np.asarray(gel.exterior.coords), fc="#82bfb7", ec="#377d77", label="Candidate gel section"))
        if chosen:
            c = np.array(chosen["camera_yz_mm"])
            m = np.asarray(chosen["mirror_points_yz_mm"])
            yy = np.array(chosen["mirror_y_mm"])
            axis.plot(yy, yy*chosen["mirror_slope"]+chosen["mirror_intercept_mm"], color="#845fa7", lw=4, label="Neutral reflective PET plane")
            for index in range(0, len(target), 3):
                path = np.vstack((c, m[index], target[index]))
                axis.plot(path[:, 0], path[:, 1], color="#4b85a2", lw=.8, alpha=.65)
            axis.plot(*c, "o", ms=8, color="#215d80", label="Candidate camera ray origin")
            axis.annotate("Base camera", c, xytext=(c[0]-5, c[1]+12), ha="center", arrowprops={"arrowstyle": "-"})
        axis.set(xlim=(-122, 23), ylim=(-8, 65), xlabel="Native Y (mm)", ylabel="Native Z (mm)",
                 title="O1 neutral optical-path search · current opaque structure is not yet modified")
        axis.set_aspect("equal")
        axis.grid(alpha=.15)
        axis.legend(fontsize=9, loc="upper left")
        for extension in ("png", "svg", "pdf"):
            fig.savefig(folder/("optical_path."+extension), dpi=170)
        plt.close(fig)
        report = {"schema": "yam-o1-neutral-path-result/1", "physical_specimens_tested": 0,
                  "configuration": str(config_path.relative_to(ROOT)),
                  "cases": len(trials), "passing_candidates": len(passing), "failure_counts": failures, "selected": chosen,
                  "source_frame_and_ribs_cleared": False, "physical_optics_validated": False,
                  "outer_gel_profile_yz_mm": outer.tolist(), "inner_gel_profile_yz_mm": inner.tolist(),
                  "optical_targets_inner_yz_mm": target.tolist(), "gel_inner_normals_yz": normals.tolist(),
                  "trials": trials, "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": cfg["limits"]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "cases": len(trials),
                            "passing": len(passing), "failures": failures, "selected": chosen}
        print(json.dumps(record["result"], indent=2))
        if not chosen:
            raise ValueError("No neutral folded path meets this bounded screen")


if __name__ == "__main__":
    main()
