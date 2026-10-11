#!/usr/bin/python3
"""Draw the F1 sensor locations and material stack without implying finished copper."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.patches import Polygon as PlotPolygon, Rectangle
import numpy as np
from shapely.geometry import box
import trimesh
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_surfaces import load_surfaces, layer_offsets
from layout_f1_cells import fan_cell
from screen_f1_feedback import digest


def boundary_points(shape):
    pieces = []
    for a, b in zip(shape.exterior.coords, list(shape.exterior.coords)[1:]):
        pieces.extend(np.linspace(a, b, 8, endpoint=False).tolist())
    return np.asarray(pieces)


def main():
    cfg, r1, nail, surfaces = load_surfaces()
    source_path = ROOT / cfg["basis"]["hard_frame"]
    frame = trimesh.load_mesh(source_path, process=True)
    folder = ROOT / "build/engineering/prototypes/f1/placement_visuals" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Draw the exact intended F1 sensing surfaces and explicit pressure-film stack, separating contact laminate from fixed readout electronics") as record:
        folder.mkdir(parents=True, exist_ok=False)
        fig, axes = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [1.05, 1]}, layout="constrained")
        ax, bx = axes
        ax.add_collection(PolyCollection(frame.triangles[:, :, [1, 0]], facecolors="#b5c1c5", edgecolors="none", alpha=.07))
        cells = []
        for surface in surfaces:
            site = surface.site
            count = 2 if site < 2 else 3
            low, high = surface.active.bounds[1], surface.active.bounds[3]
            centers = []
            for row in range(4):
                lo = low+row*(high-low)/4+.125
                hi = low+(row+1)*(high-low)/4-.125
                for col in range(count):
                    polygon = fan_cell(surface.active, lo, hi, col, count, .1)
                    points = boundary_points(polygon)
                    xyz = surface.points(points[:, 0], points[:, 1], layer_offsets(site, cfg)["film_center"])
                    ax.add_patch(PlotPolygon(xyz[:, [1, 0]], facecolor="#3c8d94", edgecolor="white", linewidth=.5))
                    centers.append(xyz.mean(axis=0))
                    cells.append({"site": f"CH{site}", "row": row, "local_column": col,
                                  "boundary_native_mm": xyz.tolist(), "kind": "proposed_allocation_not_routed_copper"})
            center = np.mean(centers, axis=0)
            label_x = center[1]
            label_y = -24 if site == 0 else 10.5
            if site == 1:
                label_x -= 3.0
            ax.annotate(f"CH{site}\n4 × {count} = {4*count}", xy=(center[1], center[0]),
                        xytext=(label_x, label_y), ha="center", va="center", fontsize=10,
                        arrowprops={"arrowstyle": "-", "color": "#365c65", "lw": .8},
                        bbox={"boxstyle": "round,pad=.3", "facecolor": "white", "edgecolor": "#b8cbcb"})
        ax.set(xlim=(-122, -5), ylim=(-29, 17), aspect="equal",
               xlabel="Native Y (mm): thin nail at left, fixed root at right",
               ylabel="Native X (mm)")
        ax.set_title("Contact surface: two nail matrices + four TPU matrices = 64 intended locations", fontsize=14)
        ax.grid(alpha=.12)
        bx.set(xlim=(0, 100), ylim=(0, 100))
        bx.axis("off")
        layers = [
            ("Object", "#ecedf0", "contact"),
            ("Protective cover", "#b9d79d", "0.10 / 0.40 mm"),
            ("Row electrode foil", "#74a3c6", "0.145 / 0.060 mm in active area"),
            ("Conductive pressure film", "#535967", "0.10 mm — this is the sensing material"),
            ("Column electrode foil", "#d4b467", "0.060 mm in active area"),
            ("Mounting layer", "#e6cbb5", "0.05 / 0.10 mm"),
            ("Original nail / TPU", "#a5b5ba", "retained contact support"),
        ]
        for index, (name, color, detail) in enumerate(layers):
            y = 88-index*10
            bx.add_patch(Rectangle((3, y-7), 38, 8, facecolor=color, edgecolor="white"))
            bx.text(22, y-3, name, ha="center", va="center", fontsize=10,
                    color="white" if name == "Conductive pressure film" else "#193740")
            bx.text(43, y-3, detail, va="center", fontsize=10)
        bx.text(3, 7, "Numbers are nail / TPU targets. Layer drawing is enlarged, not to thickness scale.\n"
                "Adhesive stays out of the film–copper sensing interfaces. Keep six film islands separate.",
                fontsize=10, color="#36515b")
        bx.text(3, 99, "Sensor = the film/electrode laminate", fontsize=14, weight="bold")
        bx.text(64, 98, "Fixed electronics", fontsize=14, weight="bold")
        bx.text(64, 88, "Finger side: 12 FH12 foil connectors\n"
                "Wrist/base: OPA392 readout + ADS8866\n"
                "Pico records raw electrical values\n\n"
                "No ADC or rigid PCB goes in these pads.\n"
                "Force calibration and physical tests remain.",
                fontsize=10, va="top", linespacing=1.6,
                bbox={"boxstyle": "round,pad=.8", "facecolor": "#eef3f0", "edgecolor": "#bccdc6"})
        fig.suptitle("F1 — what the tactile sensor is, and where it goes\n"
                     "Source-geometry allocation and nominal stack; fitted copper and physical qualification pending",
                     fontsize=16)
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(folder / ("sensor_placement."+suffix), dpi=180)
        plt.close(fig)
        report = {"schema": "yam-f1-placement-visual/1", "physical_specimens_tested": 0,
                  "allocation": cells, "total_locations": len(cells),
                  "source_frame_sha256": digest(source_path),
                  "configuration_sha256": digest(ROOT / "engineering/designs/f1_formed_stack.json"),
                  "generator_sha256": digest(Path(__file__)),
                  "limits": "Proposed film/contact allocation and nominal stack, not fitted electrode Gerbers, a camera image or measured force."}
        (folder / "sensor_placement.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "proposed_locations": len(cells)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
