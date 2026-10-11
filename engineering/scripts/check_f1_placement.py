#!/usr/bin/python3
"""Check F1's connector-board candidate against the actual contact profile."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"] = str(ROOT / "build/engineering/tools/cache")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.patches import Polygon as PlotPolygon, Rectangle
import numpy as np
from shapely.geometry import Polygon, box
import trimesh
from analyze_baseline_meshes import PARTS
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/prototypes/f1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    paths = [ROOT / "engineering/designs/f1_integration_development.json",
             ROOT / "engineering/designs/f1_placement_screen.json",
             ROOT / "engineering/release/r1/r1_manifest.json",
             ROOT / "engineering/release/contact_regions/tpu_contact_unroll.csv",
             ROOT / "engineering/release/contact_regions/contact_report.json", Path(__file__)]
    cfg = json.loads(paths[0].read_text()); limits = json.loads(paths[1].read_text())
    r1 = json.loads(paths[2].read_text())
    data = np.loadtxt(paths[3], delimiter=",", skiprows=1)
    contact = json.loads(paths[4].read_text())
    pose = cfg["connector_board_pose_candidate"]
    with execution(ROOT / "build/records", "Screen the F1 board/connector placement against source contact access and a declared travel allowance; derive a contoured candidate without qualifying hardware") as record:
        folder = OUTPUT / "placement_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        folder.mkdir(parents=True, exist_ok=False)
        for path in paths:
            shutil.copyfile(path, folder / path.name)
        frame = trimesh.load_mesh(PARTS["hard_frame"], process=False)
        soft = trimesh.load_mesh(PARTS["soft_insert"], process=False)
        y0, y1 = pose["native_y_bounds_mm"]; z0, z1 = pose["native_z_bounds_mm"]
        ys = np.linspace(y0, y1, int(np.ceil((y1-y0)/limits["sampling_step_mm"]))+1)
        front = np.interp(ys, data[:, 1], data[:, 2])
        for pad in r1["pads"]:
            curve = np.asarray(pad["front_curve_native_yz_mm"])
            mask = (ys >= curve[0, 0]) & (ys <= curve[-1, 0])
            front[mask] = np.interp(ys[mask], curve[:, 0], curve[:, 1])
        required = front + limits["normal_travel_native_z_mm_assumed"] + limits["additional_contact_access_clearance_mm"]
        band = Polygon([(y0, -30), (y1, -30), *zip(ys[::-1], required[::-1])])
        rectangle = box(y0, z0, y1, z1)
        board_front = np.maximum(required, z0)
        if np.max(board_front) >= z1:
            raise ValueError("No usable board remains behind the assumed travel band")
        contoured = Polygon([(y0, z1), (y1, z1), *zip(ys[::-1], board_front[::-1])]).simplify(.01, preserve_topology=True)
        # Roundoff/simplification must not move the boundary into the required band.
        contoured = contoured.difference(band)
        if contoured.geom_type != "Polygon" or not contoured.is_valid:
            raise ValueError("The contoured candidate is not one valid board outline")
        proposed = []; adjusted = []; envelopes = []
        half = limits["connector_body_y_half_span_mm"]
        low, high = limits["connector_body_z_from_library_datum_mm"]
        for index, (y, z) in enumerate(pose["paired_connector_library_datums_native_yz_mm"]):
            before = box(y-half, z+low, y+half, z+high)
            land_half = limits["connector_land_y_half_span_mm"]
            mask = (ys >= y-land_half) & (ys <= y+land_half)
            needed = float(board_front[mask].max()) - low + limits["component_to_contoured_board_front_mm"]
            changed_z = max(float(z), needed)
            after = box(y-half, changed_z+low, y+half, changed_z+high)
            proposed.append({"pair": index, "datum_yz_mm": [y, z],
                             "contact_access_intrusion_mm2": before.intersection(band).area})
            adjusted.append({"pair": index, "datum_yz_mm": [y, changed_z], "shift_z_mm": changed_z-z,
                             "contact_access_intrusion_mm2": after.intersection(band).area,
                             "body_outside_board_mm2": after.difference(contoured).area})
            envelopes.append(after)
        overlaps = [{"a": i, "b": j, "area_mm2": a.intersection(envelopes[j]).area}
                    for i, a in enumerate(envelopes) for j in range(i+1, len(envelopes))]
        frame_max_x = float(frame.bounds[1, 0])
        pcb_inner = pose["native_x_center_mm"] - pose["pcb_thickness_mm"]/2
        pcb_outer = pose["native_x_center_mm"] + pose["pcb_thickness_mm"]/2
        closed_gap = pcb_inner-limits["connector_closed_height_mm"]-frame_max_x
        report = {
            "schema": "yam-f1-placement-development/1", "evidence_kind": "geometry_and_prescribed_travel",
            "physical_specimens_tested": 0, "installed_drive_verified": False,
            "assumptions": limits, "original_board_access_intrusion_mm2": rectangle.intersection(band).area,
            "original_connector_pairs": proposed, "adjusted_connector_pairs": adjusted,
            "contoured_board_native_yz_mm": list(contoured.exterior.coords),
            "contoured_board_access_intrusion_mm2": contoured.intersection(band).area,
            "same_face_component_overlap_mm2": overlaps,
            "closed_inner_component_frame_x_separation_lower_bound_mm": closed_gap,
            "open_inner_latch_frame_x_separation_bound_mm": pcb_inner-limits["connector_open_height_mm_reference"]-frame_max_x,
            "pcb_and_closed_connector_added_global_width_mm": max(0, pcb_outer+limits["connector_closed_height_mm"]-frame_max_x),
            "board_back_height_increase_mm": z1-float(frame.bounds[1, 2]),
            "board_front_end_distance_behind_nail_tip_mm": y0-contact["hard_tip_native_y_mm"],
            "source_hashes": {str(path.relative_to(ROOT)): digest(path) for path in paths},
            "source_mesh_hashes": {name: digest(PARTS[name]) for name in ("hard_frame", "soft_insert")},
            "limits": [
                "The contour and shifted connector datums are a candidate to check in actual PCB/carrier CAD.",
                "Axis separation proves only nominal closed-connector/source-frame nonintersection.",
                "A negative open-latch box bound is not a collision proof; the removable-board assembly sequence remains required.",
                "The modeled travel allowance is not a 20 N deformation or mechanical rating.",
                "FFC contact-plane and insertion dimensions, formed flex paths and actual drive clearances are not yet verified."
            ],
        }
        report["contoured_candidate_screen_passed"] = (
            report["contoured_board_access_intrusion_mm2"] < 1e-7
            and all(row["contact_access_intrusion_mm2"] < 1e-7 and row["body_outside_board_mm2"] < 1e-7 for row in adjusted)
            and max(row["area_mm2"] for row in overlaps) < 1e-7 and closed_gap > .3)
        (folder / "placement.json").write_text(json.dumps(report, indent=2)+"\n")
        (OUTPUT / "f1_placement_development.json").write_text(json.dumps(report, indent=2)+"\n")
        fig, axes = plt.subplots(1, 2, figsize=(13, 6), layout="constrained")
        for ax, revised in zip(axes, (False, True)):
            for mesh, color in ((frame, "#708391"), (soft, "#a4b57d")):
                ax.add_collection(PolyCollection(mesh.triangles[:, :, [1, 2]], facecolors=color, edgecolors="none", alpha=.10))
            outline = contoured if revised else rectangle
            ax.add_patch(PlotPolygon(list(outline.exterior.coords), facecolor="#468d7a", edgecolor="#286952", alpha=.3))
            ax.plot(ys, front, color="#5a7842", label="Contact reference")
            ax.plot(ys, required, "--", color="#a46f36", label="Assumed travel + access margin")
            for item in (adjusted if revised else proposed):
                y, z = item["datum_yz_mm"]
                ax.add_patch(Rectangle((y-half, z+low), 2*half, high-low,
                                       facecolor="#8679a5", edgecolor="#54476d", alpha=.6))
                ax.text(y, z, str(item["pair"]), ha="center", fontsize=9)
            ax.set_xlim(-122, 2); ax.set_ylim(-12, 49); ax.set_aspect("equal")
            ax.grid(alpha=.15); ax.set_xlabel("Native Y (mm)"); ax.set_ylabel("Native Z (mm)")
            ax.set_title("Contoured candidate" if revised else "Original rectangular candidate")
            ax.legend(fontsize=8)
        fig.suptitle("F1 connector-board access screen · prescribed travel, no physical qualification")
        fig.savefig(folder / "placement.svg")
        fig.savefig(folder / "placement.png", dpi=150)
        plt.close(fig)
        result = {"directory": str(folder.relative_to(ROOT)),
                  "original_board_intrusion_mm2": report["original_board_access_intrusion_mm2"],
                  "adjusted_pair_shifts_z_mm": [row["shift_z_mm"] for row in adjusted],
                  "closed_frame_gap_bound_mm": closed_gap,
                  "candidate_passed": report["contoured_candidate_screen_passed"]}
        record["result"] = result
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
