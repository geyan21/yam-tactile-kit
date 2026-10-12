#!/usr/bin/python3
"""Locate possible paired air-channel sections inside the actual ENPIRE soft insert."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT/"build/engineering/tools/pneumatic-matplotlib"))
sys.path.insert(0, str(ROOT/"src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon as PatchPolygon
import numpy as np
from shapely.geometry import LineString, Point
from tactile_kit.records import execution
from analyze_b1_interfaces import original_profile
from analyze_baseline_meshes import PARTS
from f1_surfaces import load_surfaces
from screen_f1_feedback import digest

CONFIG = ROOT/"engineering/designs/pneumatic_channel_screen.json"


def main():
    config = json.loads(CONFIG.read_text())
    basis = ROOT/config["surface_basis"]
    stack, _, _, surfaces = load_surfaces(basis)
    mesh, profile, _ = original_profile()
    volume_error = abs(profile.area*15-mesh.volume)
    if volume_error > mesh.volume*1e-5:
        raise ValueError("Source cross-section does not reproduce the constant-width TPU")
    depths = np.arange(*config["depth_range_mm"], config["depth_step_mm"])
    folder = ROOT/"build/engineering/prototypes/pneumatic/channel_space"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Survey channel room within the original TPU material and existing holes; keep ports, material behavior and physical force qualification outside this geometric result") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        cases = []
        for site in config["sites"]:
            surface = surfaces[site]
            station = surface.length/2
            point, _, normal = surface.frame(station)
            centers = point-depths[:, None]*normal
            available = [(float(depth), center, profile.boundary.distance(Point(center[1:])))
                         for depth, center in zip(depths, centers) if profile.contains(Point(center[1:]))]
            for diameter in config["candidate_channel_diameters_mm"]:
                radius = diameter/2
                valid = [(depth, center, clearance) for depth, center, clearance in available
                         if clearance >= radius+config["minimum_source_wall_mm"]]
                pair = None
                for first_index, first in enumerate(valid):
                    for second in valid[first_index+1:]:
                        separation = second[0]-first[0]
                        if separation < diameter+config["minimum_between_channel_web_mm"]:
                            continue
                        # Require a material web between the two circles,
                        # rather than joining candidates across an existing void.
                        direction = (second[1]-first[1])/separation
                        a = first[1]+radius*direction
                        b = second[1]-radius*direction
                        web = LineString([a[1:], b[1:]]).buffer(config["minimum_between_channel_web_mm"]/2)
                        if not profile.covers(web):
                            continue
                        pair = {
                            "outer_center_native_mm": first[1].tolist(), "inner_center_native_mm": second[1].tolist(),
                            "outer_depth_mm": first[0], "inner_depth_mm": second[0],
                            "outer_wall_lower_bound_mm": first[2]-radius,
                            "inner_wall_lower_bound_mm": second[2]-radius,
                            "between_circles_mm": separation-diameter,
                        }
                        break
                    if pair is not None:
                        break
                cases.append({"site": site, "station_s_mm": station, "source_surface_point_native_mm": point.tolist(),
                              "diameter_mm": diameter, "single_channel_possible": bool(valid),
                              "paired_sections_possible": pair is not None, "pair": pair,
                              "nominal_volume_each_mm3": float(np.pi*radius**2*config["nominal_transverse_channel_length_mm"]),
                              "single_depth_interval_mm": [valid[0][0], valid[-1][0]] if valid else None})
        fig, axes = plt.subplots(2, 2, figsize=(12, 9), layout="constrained")
        for axis, site in zip(axes.flat, config["sites"]):
            axis.add_patch(PatchPolygon(np.asarray(profile.exterior.coords), fc="#c3cec0", ec="#617169", lw=.7))
            for ring in profile.interiors:
                axis.add_patch(PatchPolygon(np.asarray(ring.coords), fc="white", ec="#617169", lw=.7))
            rows = [row for row in cases if row["site"] == site]
            chosen = next((row for row in reversed(rows) if row["paired_sections_possible"]), rows[0])
            point = np.asarray(chosen["source_surface_point_native_mm"])[1:]
            axis.plot(*point, "ko", ms=4)
            if chosen["pair"]:
                for key, color in (("outer_center_native_mm", "#327f9a"), ("inner_center_native_mm", "#805b95")):
                    center = np.asarray(chosen["pair"][key])[1:]
                    axis.add_patch(Circle(center, chosen["diameter_mm"]/2, fc=color, ec=color, alpha=.8))
                    axis.add_patch(Circle(center, chosen["diameter_mm"]/2+config["minimum_source_wall_mm"],
                                          fill=False, ec=color, ls="--", lw=.8))
                title = f"CH{site}: paired Ø{chosen['diameter_mm']:g} mm sections fit"
            else:
                title = f"CH{site}: no paired section meets this screen"
            axis.set(xlim=(point[0]-10, point[0]+10), ylim=(point[1]-5, point[1]+17),
                     xlabel="Native Y (mm)", ylabel="Native Z (mm)", title=title)
            axis.set_aspect("equal")
            axis.grid(alpha=.15)
        fig.suptitle("P1 channel-space survey in the original TPU\n"
                     "Blue/purple circles: candidate voids; dashed circles: 0.6 mm wall assumption · no pressure/force result", fontsize=12)
        for extension in ("png", "pdf"):
            fig.savefig(folder/("channel_space."+extension), dpi=160)
        plt.close(fig)
        inputs = [CONFIG, basis, Path(__file__), ROOT/"engineering/scripts/analyze_b1_interfaces.py",
                  ROOT/"engineering/scripts/analyze_baseline_meshes.py", ROOT/"engineering/scripts/f1_surfaces.py",
                  ROOT/stack["basis"]["r1_manifest"], ROOT/stack["basis"]["nail_coordinates"], PARTS["soft_insert"]]
        report = {"schema": "yam-pneumatic-channel-space-result/1", "physical_specimens_tested": 0,
                  "source_volume_error_mm3": volume_error, "cases": cases,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": config["limits"]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "cases": len(cases),
                            "paired_cases": sum(row["paired_sections_possible"] for row in cases)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
