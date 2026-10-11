#!/usr/bin/python3
"""Draw the K1 source-finger cells and native board, retaining development scope."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PlotPolygon, Circle
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from mpl_toolkits.mplot3d import proj3d
import numpy as np
import trimesh

from tactile_kit.records import execution
from capacitive_geometry import load
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cell_cad", type=Path)
    parser.add_argument("saddles", type=Path)
    parser.add_argument("board", type=Path)
    args = parser.parse_args()
    cells, saddles, board_dir = [p.resolve() for p in (args.cell_cad, args.saddles, args.board)]
    if not all(p.is_relative_to(ROOT / "build") for p in (cells, saddles, board_dir)):
        parser.error("Use saved K1 development runs")
    cfg, _ = load()
    saddle_report = json.loads((saddles / "manifest.json").read_text())
    if not saddle_report["passed_nominal_checks"]:
        raise ValueError("Resolve the conforming support checks")
    board = json.loads((board_dir / "k1_readout.json").read_text())
    check = json.loads((board_dir / "latest_check.json").read_text())
    if check["violations"] or check["unconnected"] or check["source_sha256"] != board["pcb_sha256"]:
        raise ValueError("Use the checked routed PCB")
    output = ROOT / "build/engineering/prototypes/capacitive/visuals" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Render K1 source-matched cell development and the checked readout layout; do not depict unfinished cable, foil, retention or enclosure interfaces as completed") as record:
        output.mkdir(parents=True, exist_ok=False)
        models = [m for m in json.loads((cells / "models.json").read_text()) if m["group"] != "k1_rigid_saddle"]
        models += json.loads((saddles / "models.json").read_text())
        # The overview leaves the microscopic post meshes to their dedicated
        # dimensioned drawing, so they do not obscure the cell locations.
        overview = [m for m in models if m["group"] != "k1_posts"]
        fig = plt.figure(figsize=(14, 5))
        for number, azimuth in ((121, -60), (122, 120)):
            ax = fig.add_subplot(number, projection="3d")
            labels = []
            for key in ("hard_frame", "soft_insert"):
                mesh = trimesh.load_mesh(ROOT / cfg["basis"][key], process=True)
                ax.add_collection3d(Poly3DCollection(mesh.vertices[mesh.faces][:, :, [1, 2, 0]],
                                                     facecolor="#ccd5ce", edgecolor="none", alpha=.10))
            for item in overview:
                vertices, faces = np.asarray(item["vertices"]), np.asarray(item["faces"])
                alpha = .15 if item["group"] == "k1_cover_reference" else .9
                color = "#347e9f" if item["group"] == "k1_ground_spreader" else item["color"]
                ax.add_collection3d(Poly3DCollection(vertices[faces][:, :, [1, 2, 0]],
                                                     facecolor=color, edgecolor="none", alpha=alpha))
                if item["group"] == "k1_ground_spreader":
                    center = (vertices.min(axis=0)+vertices.max(axis=0))/2
                    label = item["name"].split("_")[1].upper()
                    labels.append((label, center[[1, 2, 0]]))
            ax.set(xlim=(-122, 2), ylim=(-9, 30), zlim=(-25, 8),
                   xlabel="Native Y (mm)", ylabel="Native Z (mm)", zlabel="Native X (mm)")
            ax.set_box_aspect((124, 39, 33))
            ax.view_init(elev=24, azim=azimuth)
            for i, (label, center) in enumerate(labels):
                x, y, _ = proj3d.proj_transform(*center, ax.get_proj())
                ax.annotate(label, (x, y), xytext=(0, 15+10*(i%2)), textcoords="offset points",
                            ha="center", fontsize=9, zorder=100,
                            bbox={"facecolor": "white", "alpha": .95, "edgecolor": "#6f8f9c", "pad": 2},
                            arrowprops={"arrowstyle": "-", "color": "#426879", "lw": .8})
        fig.suptitle("K1 capacitive cell development on the source finger\n"
                     "Conforming supports, electrode envelopes and grounded spreaders · interfaces and physical tests remain", fontsize=12)
        fig.tight_layout()
        for suffix in ("png", "pdf"):
            fig.savefig(output / ("k1_cell_placement."+suffix), dpi=160)
        plt.close(fig)
        fig, axes = plt.subplots(1, 2, figsize=(13, 7))
        fig.subplots_adjust(left=.06, right=.98, bottom=.14, top=.84, wspace=.20)
        outline = np.asarray(board["outline_xy_mm"])
        colors = {"GND": "#768b80", "SHLD1": "#77aa91", "SHLD2": "#a997bb",
                   "CIN1": "#af6545", "CIN2": "#ba784c", "CIN3": "#c49b55", "CIN4": "#88578b"}
        for ax in axes:
            ax.fill(*outline.T, color="#f0f3e9", ec="#4e665e")
        for zone in board["zones"]:
            if zone["layer"] == "In1.Cu":
                axes[1].fill(*np.asarray(zone["outline_xy_mm"]).T, color=colors[zone["net"]], alpha=.75)
        for trace in board["tracks"]:
            if trace["layer"] == "F.Cu":
                axes[0].plot(*np.asarray([trace["start"], trace["end"]]).T,
                             color=colors.get(trace["net"], "#8099b2"), linewidth=max(.45, trace["width"]*2.0))
        for pad in board["pads"]:
            x, y = pad["center"]
            for ax in axes:
                ax.add_patch(Circle((x, y), .16, color=colors.get(pad["net"], "#9e9d89")))
        for hole in board["holes"]:
            for ax in axes:
                ax.add_patch(Circle(hole["center_mm"], hole["diameter_mm"]/2, fc="white", ec="#65716e"))
        for part in board["parts"]:
            axes[0].text(*part["center_mm"], part["reference"], fontsize=6, ha="center", va="center")
        for ax, title in zip(axes, ("Front routes and component references", "Declared driven-shield regions on In1.Cu")):
            ax.set(xlim=(-1, 43), ylim=(39, -1), aspect="equal", xlabel="PCB X (mm)", ylabel="PCB Y (mm)", title=title)
        fig.suptitle("K1 readout · one board serves three pressure cells and one unloaded reference\n"
                     "23 components · independent KiCad check: 0 violations, 0 missing connections · no physical board tested", fontsize=12)
        fig.text(.5, .035, "Plane graphic shows intended regions; native filled copper and drill files are authoritative. "
                          "Use two boards on separate Pico I²C buses.", ha="center", fontsize=9)
        for suffix in ("png", "pdf"):
            fig.savefig(output / ("k1_readout."+suffix), dpi=160)
        plt.close(fig)
        stack = """<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="560" viewBox="0 0 1100 560">
<rect width="1100" height="560" fill="#f7f8f2"/>
<g font-family="sans-serif" fill="#203d43">
<text x="40" y="40" font-size="25">K1: the tactile sensor is the compression capacitor</text>
<text x="40" y="69" font-size="16">Proposed nail stack · schematic, not to scale · no force calibration or physical result</text>
<path d="M210 95v42m-8-10 8 10 8-10" fill="none" stroke="#324e53" stroke-width="3"/>
<text x="240" y="119" font-size="17">Object load</text>
<rect x="75" y="145" width="390" height="25" fill="#8db69f"/>
<text x="490" y="164" font-size="17">0.10 mm protective silicone target</text>
<rect x="75" y="175" width="390" height="38" fill="#9caab0"/>
<text x="490" y="200" font-size="17">0.30 mm grounded stainless spreader</text>
<g fill="#bf9862">
<rect x="90" y="222" width="35" height="40"/><rect x="152" y="222" width="35" height="40"/>
<rect x="214" y="222" width="35" height="40"/><rect x="276" y="222" width="35" height="40"/>
<rect x="338" y="222" width="35" height="40"/><rect x="400" y="222" width="35" height="40"/>
<rect x="75" y="262" width="390" height="15"/></g>
<text x="490" y="239" font-size="17">Silicone posts: 0.15 mm high, 0.60 mm diameter</text>
<text x="490" y="269" font-size="17">0.05 mm base · vented spaces between posts</text>
<rect x="75" y="286" width="390" height="16" fill="#b67448"/>
<rect x="75" y="302" width="390" height="22" fill="#dcc477"/>
<rect x="75" y="324" width="390" height="16" fill="#659d89"/>
<text x="490" y="298" font-size="17">CIN sensing electrode, covered by polyimide coverlay</text>
<text x="490" y="324" font-size="17">Two copper layers + core + coverlays: 0.136 mm target</text>
<text x="490" y="349" font-size="17">Driven SHLD1 plane behind the sensing electrode</text>
<rect x="75" y="356" width="390" height="16" fill="#c6bd9e"/>
<rect x="75" y="372" width="390" height="45" fill="#c3cecf"/>
<text x="490" y="387" font-size="17">0.05 mm nail mounting layer, then the existing hard nail</text>
<text x="490" y="414" font-size="17">TPU cells use the separate conforming rigid saddle</text>
<text x="40" y="465" font-size="17">Four cell wires: CIN · driven shield · upper-plate ground drive · separate upper-plate ground return</text>
<text x="40" y="496" font-size="16">Two boards: A = CH0/CH2/CH3, B = CH1/CH4/CH5. Each has a protected, unloaded CIN4 reference.</text>
<text x="40" y="531" font-size="16">Electrode fabrication, plate contacts, stops/retention, vents, cable routing and physical validation remain.</text>
</g></svg>
"""
        (output / "k1_stack.svg").write_text(stack)
        report = {"input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in
                                   (cells / "models.json", saddles / "models.json", saddles / "manifest.json",
                                    board_dir / "k1_readout.json", board_dir / "latest_check.json", Path(__file__))},
                  "physical_specimens_tested": 0,
                  "files_sha256": {p.name: digest(p) for p in output.iterdir() if p.is_file()}}
        (output / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(output.relative_to(ROOT)), "files": list(report["files_sha256"])}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
