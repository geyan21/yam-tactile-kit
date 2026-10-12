#!/usr/bin/python3
"""Place independent front/back air channels with minimal internal support additions."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT/"build/engineering/tools/pneumatic-matplotlib"))
sys.path.insert(0, str(ROOT/"src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon as PatchPolygon
import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from tactile_kit.records import execution
from analyze_b1_interfaces import original_profile
from analyze_baseline_meshes import PARTS
from f1_surfaces import load_surfaces
from screen_f1_feedback import digest

CONFIG = ROOT/"engineering/designs/pneumatic_wall_pairs.json"


def material_bands(profile, depths, centers):
    bands, active = [], []
    for depth, center in zip(depths, centers):
        if profile.contains(Point(center[1:])):
            active.append((float(depth), center))
        elif active:
            bands.append(active)
            active = []
    if active:
        bands.append(active)
    return bands


def choose(profile, exterior, band, radius, config):
    support_radius = radius+config["minimum_wall_mm"]
    candidates = []
    for depth, center in band:
        point = Point(center[1:])
        if exterior.boundary.distance(point) < support_radius:
            continue
        disk = point.buffer(support_radius, quad_segs=64)
        added = disk.difference(profile)
        overlap = disk.intersection(profile).area/disk.area
        if overlap < config["minimum_original_material_overlap_fraction"]:
            continue
        if added.area > 1e-6 and not config["allow_local_fill_inside_existing_holes"]:
            continue
        candidates.append((added.area, depth, center, disk, overlap))
    if not candidates:
        return None
    selected = min(candidates, key=lambda row: (row[0], row[1]))
    area, depth, center, disk, overlap = selected
    return {"center_native_mm": list(map(float, center)), "search_depth_mm": depth,
            "support_disk": disk, "added_profile_area_mm2": area,
            "original_material_overlap_fraction": float(overlap),
            "source_wall_to_channel_mm": profile.boundary.distance(Point(center[1:]))-radius,
            "exterior_wall_to_channel_mm": exterior.boundary.distance(Point(center[1:]))-radius}


def main():
    config = json.loads(CONFIG.read_text())
    basis = ROOT/config["surface_basis"]
    stack, _, _, surfaces = load_surfaces(basis)
    mesh, profile, _ = original_profile()
    if abs(profile.area*config["source_width_mm"]-mesh.volume) > mesh.volume*1e-5:
        raise ValueError("Source profile does not reproduce the declared constant-width TPU")
    exterior = Polygon(profile.exterior.coords)
    radius = config["channel_diameter_mm"]/2
    folder = ROOT/"build/engineering/prototypes/pneumatic/wall_pair_layouts"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Lay out separate front/back air-channel sections inside the original external TPU profile; report the exact internal fill and preserve missing physical qualifications") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        cases, support_disks, holes = [], [], []
        for site in config["sites"]:
            surface = surfaces[site]
            station = surface.length/2
            point, _, normal = surface.frame(station)
            front_depths = np.arange(*config["front_normal_depth_mm"], config["sample_step_mm"])
            back_depths = np.arange(*config["back_vertical_depth_mm"], config["sample_step_mm"])
            front_bands = material_bands(profile, front_depths, point-front_depths[:, None]*normal)
            back_bands = material_bands(profile, back_depths, point+back_depths[:, None]*np.array([0., 0., 1.]))
            if not front_bands or not back_bands:
                raise ValueError(f"CH{site}: missing original front/back member")
            front = choose(profile, exterior, front_bands[0], radius, config)
            back = choose(profile, exterior, back_bands[-1], radius, config)
            if front is None or back is None:
                raise ValueError(f"CH{site}: no contained channel/support disk in the selected members")
            separation = np.linalg.norm(np.asarray(front["center_native_mm"])-back["center_native_mm"])
            if separation < config["minimum_center_separation_mm"]:
                raise ValueError("Front/back channels are not sufficiently separated")
            for name, value in (("front", front), ("back", back)):
                support_disks.append(value.pop("support_disk"))
                center = value["center_native_mm"]
                holes.append(Point(center[1:]).buffer(radius, quad_segs=64))
                value["id"] = f"p1_ch{site}_{name}"
            cases.append({"site": site, "surface_midpoint_native_mm": point.tolist(), "front": front, "back": back,
                          "center_separation_mm": float(separation)})
        support = unary_union([profile, *support_disks])
        voids = unary_union(holes)
        modified = support.difference(voids)
        if modified.geom_type != "Polygon" or not modified.is_valid or support.difference(exterior).area > 1e-8:
            raise ValueError("Proposed section disconnects material or leaves the original exterior")
        if abs(sum(hole.area for hole in holes)-voids.area) > 1e-6:
            raise ValueError("Channels overlap")
        added = support.difference(profile)
        fig, axes = plt.subplots(2, 2, figsize=(12, 9), layout="constrained")
        for axis, case in zip(axes.flat, cases):
            axis.add_patch(PatchPolygon(np.asarray(profile.exterior.coords), fc="#c3cec0", ec="#617169", lw=.6))
            for ring in profile.interiors:
                axis.add_patch(PatchPolygon(np.asarray(ring.coords), fc="white", ec="#617169", lw=.6))
            for value, color in ((case["front"], "#327f9a"), (case["back"], "#805b95")):
                point = np.asarray(value["center_native_mm"])[1:]
                axis.add_patch(Circle(point, radius+config["minimum_wall_mm"], fill=False, ec=color, ls="--", lw=1))
                axis.add_patch(Circle(point, radius, fc=color, ec=color, alpha=.85))
            points = np.asarray([case["front"]["center_native_mm"], case["back"]["center_native_mm"]])[:, 1:]
            low, high = points.min(axis=0), points.max(axis=0)
            axis.set(xlim=(low[0]-6, high[0]+6), ylim=(low[1]-4, high[1]+4),
                     xlabel="Native Y (mm)", ylabel="Native Z (mm)", title=f"CH{case['site']}: separate front/back channels")
            axis.set_aspect("equal")
            axis.grid(alpha=.15)
        fig.suptitle("P1: Ø1.5 mm candidate channels in separate TPU members\n"
                     "Dashed rings reserve 0.6 mm walls; small internal support additions are tabulated · geometry only", fontsize=12)
        for extension in ("png", "pdf"):
            fig.savefig(folder/("wall_pairs."+extension), dpi=160)
        plt.close(fig)
        inputs = [CONFIG, basis, Path(__file__), ROOT/"engineering/scripts/analyze_b1_interfaces.py",
                  ROOT/"engineering/scripts/analyze_baseline_meshes.py", ROOT/"engineering/scripts/f1_surfaces.py",
                  ROOT/stack["basis"]["r1_manifest"], ROOT/stack["basis"]["nail_coordinates"], PARTS["soft_insert"]]
        for path in inputs:
            if "build/engineering/sources" in str(path.relative_to(ROOT)):
                continue
            destination = folder/"inputs"/path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        report = {"schema": "yam-pneumatic-wall-pair-layout/1", "physical_specimens_tested": 0,
                  "cases": cases, "channel_diameter_mm": config["channel_diameter_mm"],
                  "source_width_mm": config["source_width_mm"],
                  "source_volume_mm3": mesh.volume,
                  "added_internal_material_mm3": added.area*config["source_width_mm"],
                  "channel_void_volume_mm3": voids.area*config["source_width_mm"],
                  "modified_profile": {"outer": list(modified.exterior.coords),
                                       "holes": [list(ring.coords) for ring in modified.interiors]},
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": config["limits"]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "channel_pairs": len(cases),
                            "added_internal_material_mm3": report["added_internal_material_mm3"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
