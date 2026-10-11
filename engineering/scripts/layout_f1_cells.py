#!/usr/bin/python3
"""Develop F1 taxel locations on the actual nail and R1 saddle surfaces."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PlotPolygon
import numpy as np
from shapely.geometry import LineString, Polygon, box
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/prototypes/f1"


def cross_bounds(polygon, v):
    section = polygon.intersection(LineString([(-100, v), (100, v)]))
    if section.is_empty or section.geom_type != "LineString":
        raise ValueError("F1 nail section is empty or has multiple branches")
    return section.bounds[0], section.bounds[2]


def fan_cell(active, v0, v1, column, count, sample_mm):
    # Follow the real tapered prong. A rectangular global-X grid would leave
    # some distal pixels entirely outside its narrow leading end.
    ys = np.linspace(v0, v1, max(3, int(np.ceil((v1 - v0) / sample_mm)) + 1))
    sides = [cross_bounds(active, v) for v in ys]
    left = [(lo + (hi - lo) * column / count, v) for (lo, hi), v in zip(sides, ys)]
    right = [(lo + (hi - lo) * (column + 1) / count, v) for (lo, hi), v in zip(sides, ys)]
    return Polygon(left + right[::-1]).intersection(active)


def main():
    cfg = json.loads((ROOT / "engineering/designs/f1.json").read_text())
    r1 = json.loads((ROOT / cfg["basis"]["contact_geometry"]).read_text())
    basis = json.loads((ROOT / "engineering/release/contact_regions/contact_report.json").read_text())
    a = cfg["array"]
    with execution(ROOT / "build/records", "Develop 64 F1 contact pixels against actual tapered nail and saddle geometry; no routed flex or physical sensor is claimed") as record:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        run = OUTPUT / "layout_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        run.mkdir(parents=True, exist_ok=False)
        inputs = (ROOT / "engineering/designs/f1.json", ROOT / cfg["basis"]["contact_geometry"],
                  ROOT / "engineering/release/contact_regions/contact_report.json", Path(__file__))
        for path in inputs:
            shutil.copyfile(path, run / path.name)
        sites = []; column_base = 0
        for entry in r1["nail_active_cells"]:
            active = Polygon(entry["active"])
            lower, upper = active.bounds[1] + .01, active.bounds[3] - .01
            pixels = []
            for row in range(a["rows"]):
                v1 = upper - row * (upper - lower) / a["rows"]
                v0 = upper - (row + 1) * (upper - lower) / a["rows"]
                for column in range(a["nail_columns_per_prong"]):
                    cell = fan_cell(active, v0, v1, column, a["nail_columns_per_prong"],
                                    a["development_sampling_mm"]).buffer(-a["electrode_gap_mm"] / 2)
                    if cell.geom_type != "Polygon" or cell.area < a["minimum_taxel_area_mm2_for_layout"]:
                        raise ValueError("A proposed F1 nail pixel has insufficient connected area")
                    u, v = cell.centroid.coords[0]
                    native = (np.asarray(basis["nail_plane_origin_native_mm"])
                              + u * np.asarray(basis["nail_plane_u_axis_native"])
                              + v * np.asarray(basis["nail_plane_v_axis_native"]))
                    pixels.append({"row": row, "column": column_base + column,
                                   "outline_local_mm": list(cell.exterior.coords),
                                   "nominal_overlap_area_mm2": cell.area,
                                   "contact_surface_center_native_mm": native.tolist()})
            sites.append({"id": "CH" + str(entry["id"]), "kind": "nail",
                          "coordinates": "Original nail-plane U/V millimeters",
                          "outer_local_mm": entry["outer"], "pixels": pixels})
            column_base += a["nail_columns_per_prong"]
        for entry in r1["pads"]:
            curve = np.asarray(entry["front_curve_native_yz_mm"])
            arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))]
            width = entry["width_mm"]
            active = box(-width / 2 + .6, .6, width / 2 - .6, arc[-1] - .6)
            lo_x, lo_s, hi_x, hi_s = active.bounds
            pixels = []
            for row in range(a["rows"]):
                s0 = lo_s + row * (hi_s - lo_s) / a["rows"]
                s1 = lo_s + (row + 1) * (hi_s - lo_s) / a["rows"]
                for column in range(a["tpu_columns_per_region"]):
                    x0 = lo_x + column * (hi_x - lo_x) / a["tpu_columns_per_region"]
                    x1 = lo_x + (column + 1) * (hi_x - lo_x) / a["tpu_columns_per_region"]
                    cell = box(x0, s0, x1, s1).buffer(-a["electrode_gap_mm"] / 2)
                    x, s = cell.centroid.coords[0]
                    if cell.area < a["minimum_taxel_area_mm2_for_layout"]:
                        raise ValueError("An F1 TPU pixel is too small")
                    native = [float(x - 7.5), float(np.interp(s, arc, curve[:, 0])),
                              float(np.interp(s, arc, curve[:, 1]))]
                    pixels.append({"row": row, "column": column_base + column,
                                   "outline_local_mm": list(cell.exterior.coords),
                                   "nominal_overlap_area_mm2": cell.area,
                                   "contact_surface_center_native_mm": native})
            sites.append({"id": "CH" + str(entry["id"]), "kind": "tpu",
                          "coordinates": "Local X from pad center and arc length from distal end; millimeters",
                          "outer_local_mm": list(box(-width / 2, 0, width / 2, arc[-1]).exterior.coords),
                          "minimum_sampled_saddle_radius_mm": entry["minimum_sampled_radius_mm"],
                          "pixels": pixels})
            column_base += a["tpu_columns_per_region"]
        pixels = [pixel for site in sites for pixel in site["pixels"]]
        if len(pixels) != a["nominal_taxels"] or column_base != a["columns_total"]:
            raise ValueError("F1 matrix dimensions do not match the patch mapping")
        if len({(pixel["row"], pixel["column"]) for pixel in pixels}) != len(pixels):
            raise ValueError("F1 electrical pixel mapping is not unique")
        report = {"schema": "yam-f1-layout-development/1", "status": "contact-allocation study only",
                  "physical_specimens_tested": 0, "fabrication_ready": False,
                  "rows": a["rows"], "columns": column_base, "taxels": len(pixels), "sites": sites,
                  "minimum_nominal_overlap_area_mm2": min(pixel["nominal_overlap_area_mm2"] for pixel in pixels),
                  "source_hashes": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in inputs},
                  "limits": [
                      "Pixel polygons allocate contact locations; they are not routed copper or Gerbers.",
                      "Native centers lie on the existing contact/saddle surfaces. Layer offsets and separate flex neutral planes remain to be designed.",
                      "Feed-trace routing, coverlay, edge seals, connectors and tails may change the final active areas.",
                      "No electrical crosstalk, force response, contact reliability or bending fatigue is established."
                  ]}
        (OUTPUT / "f1_layout_development.json").write_text(json.dumps(report, indent=2) + "\n")
        (run / "layout.json").write_text(json.dumps(report, indent=2) + "\n")
        fig, axes = plt.subplots(2, 3, figsize=(12, 9), layout="constrained")
        for ax, site in zip(axes.flat, sites):
            ax.add_patch(PlotPolygon(site["outer_local_mm"], facecolor="#e7ede6", edgecolor="#73877e"))
            for pixel in site["pixels"]:
                poly = Polygon(pixel["outline_local_mm"])
                ax.add_patch(PlotPolygon(list(poly.exterior.coords), facecolor=plt.cm.viridis((pixel["column"] % 4) / 4 + .1),
                                         edgecolor="white", alpha=.7))
                x, y = poly.centroid.coords[0]
                ax.text(x, y, f'{pixel["row"]},{pixel["column"]}', ha="center", va="center", fontsize=7)
            ax.autoscale_view(); ax.set_aspect("equal"); ax.grid(alpha=.15)
            ax.set_title(site["id"] + " · " + site["kind"] + " · row,column")
        fig.suptitle("F1 proposed 4 × 16 contact allocation\nDevelopment only · copper routing and complete layer stack remain", fontsize=14)
        fig.savefig(OUTPUT / "f1_layout_development.svg")
        fig.savefig(OUTPUT / "f1_layout_development.png", dpi=150)
        plt.close(fig)
        for name in ("f1_layout_development.svg", "f1_layout_development.png"):
            shutil.copyfile(OUTPUT / name, run / name)
        record["run"] = str(run.relative_to(ROOT))
        record["layout"] = {key: report[key] for key in ("rows", "columns", "taxels", "minimum_nominal_overlap_area_mm2", "fabrication_ready")}
        print(json.dumps(record["layout"], indent=2))


if __name__ == "__main__":
    main()
