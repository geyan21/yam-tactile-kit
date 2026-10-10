#!/usr/bin/python3
"""Measure and render the retrieved ENPIRE meshes; do not alter their geometry."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
from shapely.geometry import LineString, Polygon
import trimesh

sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

SOURCES = ROOT / "build/engineering/sources"
OUTPUT = ROOT / "build/engineering/baseline"
PARTS = {
    "hard_frame": SOURCES / "pgeedh__Open-ENPIRE-Gripper/grippers-stl/enpire_i2rt_yam_stl/i2rt_UCG_Hard.stl",
    "soft_insert": SOURCES / "pgeedh__Open-ENPIRE-Gripper/grippers-stl/enpire_i2rt_yam_stl/I2RT_UCG_Soft.stl",
    "nvidia_sim_finger": SOURCES / "NVlabs__ENPIRE/enpire/env/forge/robot/models/station/assets/gripper_finger.stl",
}


def outer_profile(mesh, axis, coordinate):
    origin = mesh.bounds.mean(axis=0)
    origin[axis] = coordinate
    section = mesh.section(plane_origin=origin, plane_normal=np.eye(3)[axis])
    if section is None:
        raise ValueError("No section at the requested plane")
    keep = [i for i in range(3) if i != axis]
    curves = [np.asarray(curve)[:, keep] for curve in section.discrete]
    closed = [curve for curve in curves if len(curve) >= 4 and np.linalg.norm(curve[0]-curve[-1]) < 1e-5]
    if not closed:
        raise ValueError("No closed profile in mesh section")
    profile = max(closed, key=lambda curve: Polygon(curve).area)
    return profile, curves


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with execution(ROOT / "build/records", "Measure actual baseline meshes and compare cross-sections for developable contact-surface screening") as record:
        models, stats = {}, {}
        for name, path in PARTS.items():
            mesh = trimesh.load_mesh(path, process=True)
            if not np.isfinite(mesh.vertices).all():
                raise ValueError("Non-finite mesh coordinates")
            models[name] = mesh
            stats[name] = {
                "source_file": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "vertices": len(mesh.vertices), "triangles": len(mesh.faces),
                "native_bounds": mesh.bounds.tolist(), "native_extents": mesh.extents.tolist(),
                "is_watertight": bool(mesh.is_watertight), "native_volume": float(mesh.volume),
                "units": "mm per baseline source catalog" if name != "nvidia_sim_finger" else "native units; simulation transform/scale still to verify",
            }
        soft = models["soft_insert"]
        width_axis = int(np.argmin(soft.extents))
        other = [i for i in range(3) if i != width_axis]
        profiles = []
        for fraction in (.15, .3, .5, .7, .85):
            coordinate = float(soft.bounds[0, width_axis]+fraction*soft.extents[width_axis])
            profile, curves = outer_profile(soft, width_axis, coordinate)
            profiles.append({"fraction": fraction, "coordinate": coordinate, "outer": profile, "curves": curves})
        reference = LineString(profiles[2]["outer"])
        distances = [
            float(reference.hausdorff_distance(LineString(profile["outer"]))) for profile in profiles
        ]
        section_info = {
            "width_axis_native": width_axis, "profile_axes_native": other,
            "fractions_across_width": [profile["fraction"] for profile in profiles],
            "hausdorff_distances_to_middle_mm": distances,
            "maximum_distance_mm": max(distances),
            "claim": "Cross-section similarity is a static geometry observation, not proof of FPC survival during compliant deformation.",
        }
        with (OUTPUT / "outer_profile.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["point_index", f"native_axis_{other[0]}_mm", f"native_axis_{other[1]}_mm"])
            writer.writerows((i, *point) for i, point in enumerate(profiles[2]["outer"]))

        fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
        for ax, (a, b) in zip(axes, ((0,1),(0,2),(1,2))):
            for name, color in (("hard_frame", "#425b67"), ("soft_insert", "#75b33f")):
                mesh = models[name]
                triangles = mesh.triangles[:, :, [a,b]]
                ax.add_collection(PolyCollection(triangles, facecolors=color, edgecolors="none", alpha=.18))
            both = np.vstack([models["hard_frame"].vertices, soft.vertices])
            ax.set_xlim(both[:,a].min()-3, both[:,a].max()+3)
            ax.set_ylim(both[:,b].min()-3, both[:,b].max()+3)
            ax.set_aspect("equal")
            ax.set_xlabel(f"Native axis {a} (mm)"); ax.set_ylabel(f"Native axis {b} (mm)")
            ax.grid(alpha=.2)
        fig.suptitle("Retrieved ENPIRE/YAM baseline meshes — PETG frame and TPU insert")
        fig.savefig(OUTPUT / "baseline_projections.png", dpi=170)
        fig.savefig(OUTPUT / "baseline_projections.svg")
        plt.close(fig)

        fig = plt.figure(figsize=(10,7))
        ax = fig.add_subplot(projection="3d")
        for name, color in (("hard_frame", "#536a77"), ("soft_insert", "#83b34c")):
            mesh = models[name]
            ax.add_collection3d(Poly3DCollection(mesh.triangles, facecolor=color, edgecolor=None, alpha=.85))
        both = np.vstack([models["hard_frame"].vertices, soft.vertices])
        ax.set_xlim(both[:,0].min(), both[:,0].max())
        ax.set_ylim(both[:,1].min(), both[:,1].max())
        ax.set_zlim(both[:,2].min(), both[:,2].max())
        ax.set_box_aspect(np.ptp(both,axis=0))
        ax.view_init(elev=20,azim=35)
        ax.set_xlabel("native X");ax.set_ylabel("native Y");ax.set_zlabel("native Z")
        fig.tight_layout()
        fig.savefig(OUTPUT / "baseline_assembly.png",dpi=180)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10,6))
        for entry in profiles:
            curve = entry["outer"]
            ax.plot(curve[:,0],curve[:,1],label=f"{entry['fraction']:.2f} width fraction")
        for curve in profiles[2]["curves"]:
            ax.plot(curve[:,0],curve[:,1],color="gray",linestyle=":",linewidth=.6)
        ax.set_aspect("equal");ax.grid(alpha=.3);ax.legend()
        ax.set_xlabel(f"Native axis {other[0]} (mm)");ax.set_ylabel(f"Native axis {other[1]} (mm)")
        ax.set_title("Measured outer profiles: extrusion/developability screening")
        fig.tight_layout()
        fig.savefig(OUTPUT / "section_profiles.png",dpi=180)
        fig.savefig(OUTPUT / "section_profiles.svg")
        plt.close(fig)
        result = {"parts": stats, "cross_sections": section_info}
        (OUTPUT / "geometry_report.json").write_text(json.dumps(result,indent=2)+"\n")
        record["analysis"] = result
        print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
