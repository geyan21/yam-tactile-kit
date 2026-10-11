#!/usr/bin/python3
"""Check proposed narrow F1 lateral exits against sampled source-mesh sections."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import numpy as np
from shapely.geometry import Polygon, LineString, box
import trimesh

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_surfaces import load_surfaces, layer_offsets
from screen_f1_feedback import digest
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PlotPolygon

EXITS = ROOT / "engineering/designs/f1_exit_development.json"


def section_polygon(mesh, y):
    section = mesh.section(plane_origin=[0, y, 0], plane_normal=[0, 1, 0])
    result = Polygon()
    if section is None:
        return result
    for loop in section.discrete:
        if np.linalg.norm(loop[0]-loop[-1]) > 1e-5:
            raise ValueError("Source cross-section has an open loop")
        polygon = Polygon(loop[:, [0, 2]])
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        result = result.symmetric_difference(polygon)
    return result


def polygons(shape):
    if shape.is_empty:
        return []
    if shape.geom_type == "Polygon":
        return [shape]
    return [p for p in shape.geoms if p.geom_type == "Polygon"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--x-end-mm", type=float, default=8)
    parser.add_argument("--exit-config", type=Path, default=EXITS)
    args = parser.parse_args()
    cfg, r1, nail, surfaces = load_surfaces()
    exit_path = args.exit_config.resolve()
    if not exit_path.is_relative_to(ROOT):
        parser.error("Use a repository-owned exit configuration")
    exit_config = json.loads(exit_path.read_text())
    source_paths = [ROOT / cfg["basis"][key] for key in ("hard_frame", "soft_insert")]
    meshes = [trimesh.load_mesh(path, process=True) for path in source_paths]
    if not all(mesh.is_watertight for mesh in meshes):
        raise ValueError("Use the retained closed source meshes")
    folder = ROOT / "build/engineering/prototypes/f1/exit_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Inspect six proposed F1 lateral neck exits using actual closed frame/TPU mesh sections; preserve collisions and sampling limits") as record:
        folder.mkdir(parents=True, exist_ok=False)
        fig, axes = plt.subplots(3, 2, figsize=(13, 11), layout="constrained")
        results = []
        for surface, target_y, ax in zip(surfaces, exit_config["exit_native_y_mm_by_site"], axes.flat):
            offsets = layer_offsets(surface.site, cfg)
            edge = exit_config.get("edge_by_site", ["proximal"]*6)[surface.site]
            end_s = surface.body.bounds[1] if edge == "distal" else surface.body.bounds[3]
            p, t, n = surface.frame(end_s)
            inner, outer = offsets["mount_outer"], offsets["row_outer"]
            origin = p+(inner+outer)/2*n
            advance = (target_y-origin[1])/t[1]
            center = origin+advance*t
            # Combined row/film/column neck envelope is deliberately larger
            # than either single foil; this is an initial corridor screen.
            width, thickness = cfg["tails"]["row_neck_width_mm"], outer-inner
            corners = [center+u*t+d*n for u, d in
                       ((-width/2, -thickness/2), (width/2, -thickness/2),
                        (width/2, thickness/2), (-width/2, thickness/2))]
            yz = Polygon(np.asarray(corners)[:, 1:])
            ys = np.linspace(yz.bounds[0]+1e-5, yz.bounds[2]-1e-5, max(5, int((yz.bounds[2]-yz.bounds[0])/.1)+1))
            overlaps = []
            if surface.kind == "nail":
                section_s = end_s+(.03 if edge == "distal" else -.03)
                side_edge = surface.body.intersection(LineString([(-100, section_s), (100, section_s)]))
                x_start = float(surface.points(side_edge.bounds[2]-.2, end_s, (inner+outer)/2)[0])
            else:
                x_start = -1.0
            for y in ys:
                section = yz.intersection(LineString([(y, -100), (y, 100)]))
                if section.is_empty:
                    continue
                zlo, zhi = section.bounds[1], section.bounds[3]
                neck = box(x_start, zlo, args.x_end_mm, zhi)
                hard = section_polygon(meshes[0], float(y))
                soft = section_polygon(meshes[1], float(y))
                overlaps.append({"y_mm": float(y), "hard_overlap_mm2": hard.intersection(neck).area,
                                 "soft_overlap_mm2": soft.intersection(neck).area})
            hard, soft = (section_polygon(mesh, target_y) for mesh in meshes)
            for shape, color in ((hard, "#697c87"), (soft, "#9fbb63")):
                for part in polygons(shape):
                    ax.add_patch(PlotPolygon(list(part.exterior.coords), facecolor=color, edgecolor="#445", alpha=.6))
                    for hole in part.interiors:
                        ax.add_patch(PlotPolygon(list(hole.coords), facecolor="white", edgecolor="#445"))
            cut = yz.intersection(LineString([(target_y, -100), (target_y, 100)]))
            zlo, zhi = cut.bounds[1], cut.bounds[3]
            ax.add_patch(PlotPolygon(list(box(x_start, zlo, args.x_end_mm, zhi).exterior.coords),
                                    facecolor="#d05c45", edgecolor="#a33026"))
            ax.set(title=f"CH{surface.site} exit · native Y={target_y:g} mm", xlim=(-26, 15), ylim=(-8, 30),
                   aspect="equal", xlabel="Native X (mm)", ylabel="Native Z (mm)")
            ax.grid(alpha=.15)
            result = {"site": f"CH{surface.site}", "edge": edge, "exit_y_mm": target_y, "center_native_mm": center.tolist(),
                      "tangent": t.tolist(), "normal": n.tolist(), "tangent_extension_mm": advance,
                      "x_span_mm": [x_start, args.x_end_mm], "neck_width_mm": width,
                      "combined_envelope_thickness_mm": thickness, "sampled_sections": len(overlaps),
                      "maximum_hard_overlap_mm2": max(p["hard_overlap_mm2"] for p in overlaps),
                      "maximum_soft_overlap_mm2": max(p["soft_overlap_mm2"] for p in overlaps),
                      "samples": overlaps}
            results.append(result)
        fig.suptitle("F1 lateral-neck corridor screen · red is the candidate tail envelope\n"
                     "Actual mesh sections; sampled static intersections are not a full assembly or motion proof")
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(folder / f"exit_sections.{suffix}", dpi=170)
        plt.close(fig)
        report = {"schema": "yam-f1-exit-sections/1", "physical_evidence": False,
                  "source_sha256": {str(path.relative_to(ROOT)): digest(path) for path in source_paths+[exit_path]},
                  "results": results,
                  "limits": "Combined neck envelope and sampled native-Y sections only. Elbows, folds, full mesh clearance bounds, assembled tails and dynamic motion remain."}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["summary"] = {"directory": str(folder.relative_to(ROOT)), "exits": [
            {key: row[key] for key in ("site", "exit_y_mm", "center_native_mm",
                                      "maximum_hard_overlap_mm2", "maximum_soft_overlap_mm2")} for row in results]}
        print(json.dumps(record["summary"], indent=2))


if __name__ == "__main__":
    main()
