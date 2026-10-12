#!/usr/bin/python3
"""Trace the selected neutral rays through the clear gel using bounded Snell optics."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT/"build/engineering/tools/optical-matplotlib"))
sys.path.insert(0, str(ROOT/"src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from inspect_optical_obstructions import segments
from screen_f1_feedback import digest
from tactile_kit.records import execution


def refract(direction, into_medium, index):
    cosine = float(np.dot(direction, into_medium))
    if cosine <= 0:
        raise ValueError("The ray is not entering the gel")
    tangent = direction-cosine*into_medium
    result = tangent/index+math.sqrt(1-float(tangent@tangent)/(index*index))*into_medium
    if abs(np.linalg.norm(result)-1) > 1e-8:
        raise ValueError("Snell direction is not a unit vector")
    return result


def exit_point(start, direction, outer, inner, x_bounds):
    polygon = np.vstack((outer, inner[::-1], outer[:1]))
    candidates = []
    for i, (a, b) in enumerate(zip(polygon, polygon[1:])):
        matrix = np.column_stack((direction[1:], -(b-a)))
        if abs(np.linalg.det(matrix)) < 1e-12:
            continue
        distance, fraction = np.linalg.solve(matrix, a-start[1:])
        if distance > 1e-5 and -1e-8 <= fraction <= 1+1e-8:
            candidates.append((float(distance), "object_surface" if i < len(outer)-1 else "gel_end_or_rear"))
    if abs(direction[0]) > 1e-12:
        for x in x_bounds:
            distance = (x-start[0])/direction[0]
            if distance > 1e-5:
                candidates.append((float(distance), "gel_side"))
    if not candidates:
        raise ValueError("Ray has no gel boundary intersection")
    distance, boundary = min(candidates)
    return start+distance*direction, distance, boundary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("search", type=Path)
    args = parser.parse_args()
    source = args.search.resolve()
    if not source.is_relative_to(ROOT/"build"):
        parser.error("Use the selected generated path")
    path = source/"report.json"
    plan = json.loads(path.read_text())
    cfg_path = ROOT/plan["configuration"]
    cfg = json.loads(cfg_path.read_text())
    materials_path = ROOT/"engineering/designs/optical_materials.json"
    materials = json.loads(materials_path.read_text())
    index = materials["gel"]["manufacturer_refractive_index_at_20c"]
    folder = ROOT/"build/engineering/prototypes/optical/refraction_screens"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Trace zero-width neutral rays through the selected Solaris gel with n=1.41, reporting edge exits and model limits without claiming measured optical coverage") as record:
        folder.mkdir(parents=True)
        outer, inner = np.asarray(plan["outer_gel_profile_yz_mm"]), np.asarray(plan["inner_gel_profile_yz_mm"])
        rays = segments(plan["selected"], np.asarray(plan["optical_targets_inner_yz_mm"]), cfg["active_half_width_mm"], cfg["camera_x_mm"])
        results = []
        for ray in rays:
            if ray["leg"] != "mirror_to_gel":
                continue
            start, mirror = ray["end"], ray["start"]
            incoming = start-mirror; incoming /= np.linalg.norm(incoming)
            normal = -np.r_[0., np.asarray(plan["gel_inner_normals_yz"])[ray["station"]]]
            inside = refract(incoming, normal, index)
            end, distance, boundary = exit_point(start, inside, outer, inner, [cfg["camera_x_mm"]-6.5, cfg["camera_x_mm"]+6.5])
            results.append({"station": ray["station"], "x_offset_mm": ray["x_offset_mm"], "entry_mm": start.tolist(),
                            "exit_mm": end.tolist(), "gel_distance_mm": distance, "boundary": boundary,
                            "incidence_deg": math.degrees(math.acos(float(incoming@normal))),
                            "refracted_deg": math.degrees(math.acos(float(inside@normal)))})
        # Analytic control: normal incidence is unchanged; a 30° incident ray
        # in the X/Z plane must satisfy n_air sin(a) = n_gel sin(b).
        flat_normal = np.array([0., 0., -1.])
        normal_control = float(np.linalg.norm(refract(flat_normal, flat_normal, index)-flat_normal))
        test = refract(np.array([.5, 0., -math.sqrt(.75)]), flat_normal, index)
        snell_residual = abs(index*test[0]-.5)
        if normal_control > 1e-12 or snell_residual > 1e-12:
            raise ValueError("Analytic optics control failed")
        edge_exits = [row for row in results if row["boundary"] != "object_surface"]
        report = {"schema": "yam-o1-neutral-refraction/1", "physical_specimens_tested": 0,
                  "refractive_index": index, "rays": results, "ray_count": len(results), "edge_exits": edge_exits,
                  "normal_incidence_residual": normal_control, "snell_residual": snell_residual,
                  "all_sampled_rays_reach_object_surface": not edge_exits,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in (path, cfg_path, materials_path, Path(__file__), ROOT/"engineering/scripts/inspect_optical_obstructions.py")},
                  "limits": ["Neutral undeformed gel only; zero-width rays and an assumed camera entrance pupil.",
                             "Bulk refractive index is a supplier value at 20C, not a measured dispersion curve for this casting.",
                             "Finite lens aperture, distortion, focus, coating opacity, scatter, glare and deformed visibility are unqualified.",
                             "This is a visibility screen, not camera-to-millimetre or force calibration."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        fig, ax = plt.subplots(figsize=(11, 4))
        ax.fill(np.r_[outer[:, 0], inner[::-1, 0]], np.r_[outer[:, 1], inner[::-1, 1]], color="#add8c5", alpha=.6)
        for row in results:
            if row["x_offset_mm"] == 0:
                a, b = row["entry_mm"], row["exit_mm"]
                ax.plot([a[1], b[1]], [a[2], b[2]], color="#287ead" if row["boundary"] == "object_surface" else "#b84142", linewidth=.8)
        ax.set(xlabel="Source finger Y (mm)", ylabel="Z (mm)",
               title=f"O1 neutral gel rays · n={index} · {len(edge_exits)}/{len(results)} exit an edge\nModel only; focus, pupil, deformation and physical coverage unqualified")
        ax.set_aspect("equal", adjustable="datalim"); ax.grid(alpha=.2); fig.tight_layout()
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(folder/("o1_refraction."+suffix), dpi=160)
        plt.close(fig)
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "rays": len(results), "edge_exits": len(edge_exits)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
