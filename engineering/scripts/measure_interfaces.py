#!/usr/bin/python3
"""Measure nail wall thickness and mounting bores from the pinned baseline mesh."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import Point, Polygon
import trimesh

from analyze_baseline_meshes import PARTS
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/interfaces"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with execution(ROOT / "build/records", "Measure local nail wall thickness and mount-hole centers before designing printable interfaces") as record:
        mesh = trimesh.load_mesh(PARTS["hard_frame"], process=True)
        contact = json.loads((ROOT / "build/engineering/contact_regions/contact_report.json").read_text())
        footprint = Polygon(contact["nail_footprint"]["outer"])
        normal = np.asarray(contact["nail_plane_outward_normal_native"])
        origin = np.asarray(contact["nail_plane_origin_native_mm"])
        u = np.asarray(contact["nail_plane_u_axis_native"])
        v = np.asarray(contact["nail_plane_v_axis_native"])
        grid = np.asarray([
            [a, b]
            for a in np.arange(footprint.bounds[0], footprint.bounds[2], .3)
            for b in np.arange(footprint.bounds[1], footprint.bounds[3], .3)
            if footprint.buffer(-.1).contains(Point(a,b))
        ])
        starts = origin + grid[:, :1]*u + grid[:, 1:]*v + .02*normal
        locations, ray_indices, _ = mesh.ray.intersects_location(
            ray_origins=starts, ray_directions=np.tile(-normal, (len(starts),1)), multiple_hits=True,
        )
        thickness = []
        for index in range(len(starts)):
            distances = np.sort((starts[index]-locations[ray_indices==index]) @ normal)
            distances = distances[distances>.001]
            if len(distances)<2:
                continue
            thickness.append([*grid[index], float(distances[1]-distances[0])])
        thickness = np.asarray(thickness)
        if len(thickness)<.99*len(starts):
            raise RuntimeError("Nail ray coverage below 99%; inspect geometry")
        circles = []
        for y in (-5.5, -6.5, -8, -10, -12, -13.5, -14.5):
            section = mesh.section(plane_origin=[-7.5,y,14], plane_normal=[0,1,0])
            if section is None:
                continue
            for curve in section.discrete:
                points = np.asarray(curve)[:-1, [0,2]]
                if len(points)<8:
                    continue
                # Fitted circle over full closed loop; removes loop starting-point bias.
                centered = points - points.mean(axis=0)
                solved, *_ = np.linalg.lstsq(
                    np.column_stack((2*centered[:,0],2*centered[:,1],np.ones(len(points)))),
                    np.sum(centered**2,axis=1), rcond=None,
                )
                center = solved[:2] + points.mean(axis=0)
                radii = np.linalg.norm(points-center,axis=1)
                if radii.max()-radii.min() < .02 and 1 < radii.mean() < 4:
                    circles.append({
                        "native_y":float(y), "center_xz":center.tolist(),
                        "radius_mm":float(np.mean(radii)),
                        "radial_error_mm":float(np.ptp(radii)),
                    })
        result = {
            "source":"Same pinned mesh as baseline audit; manufacturing and fastener fit unverified.",
            "nail_thickness_sampling_pitch_mm":.3,
            "nail_thickness_contact_edge_inset_mm":.1,
            "nail_min_thickness_mm":float(thickness[:,2].min()),
            "nail_max_thickness_mm":float(thickness[:,2].max()),
            "nail_samples":len(thickness),
            "ray_measurement_note":"First solid interval inward from the contact plane, not total material along a ray.",
            "mount_circle_sections":circles,
            "decision":"Use removable surface laminates for the first nail prototype; do not machine a recess into the thin tip.",
        }
        (OUTPUT / "interface_report.json").write_text(json.dumps(result,indent=2)+"\n")
        np.savetxt(OUTPUT/"nail_thickness.csv", thickness, delimiter=",", header="u_mm,v_mm,thickness_mm", comments="")
        fig, ax=plt.subplots(figsize=(7,6),constrained_layout=True)
        sc=ax.scatter(thickness[:,0],thickness[:,1],c=thickness[:,2],s=7,cmap="viridis")
        ax.set_aspect("equal");ax.set_xlabel("Nail local U (mm)");ax.set_ylabel("Nail local V (mm)")
        ax.set_title("Measured PETG nail wall thickness")
        fig.colorbar(sc,ax=ax,label="Thickness (mm)")
        fig.savefig(OUTPUT/"nail_thickness.png",dpi=180)
        fig.savefig(OUTPUT/"nail_thickness.svg")
        record["measurements"]=result
        print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
