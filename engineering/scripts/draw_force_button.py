#!/usr/bin/python3
"""Draw FB1's actual assembly, root section and sensor PCB for reproduction."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/force-button-matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/force-button-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle
from matplotlib.transforms import Affine2D
from matplotlib.backends.backend_pdf import PdfPages
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from mpl_toolkits.mplot3d import proj3d
import numpy as np
import trimesh
from tactile_kit.records import execution
from force_button_mechanics import CONFIG
from prototype_cad import packed
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cad_run", type=Path)
    parser.add_argument("board", type=Path)
    parser.add_argument("--fit-check", type=Path, required=True)
    args = parser.parse_args()
    source, board_dir = args.cad_run.resolve(), args.board.resolve()
    cfg = json.loads(CONFIG.read_text())
    plan = json.loads((source / "manifest.json").read_text())
    fit = json.loads(args.fit_check.read_text())
    board = json.loads((board_dir / "fb1_sensor.json").read_text())
    check = json.loads((board_dir / "latest_check.json").read_text())
    if (not fit["passed_declared_checks"] or fit["source_manifest_sha256"] != digest(source / "manifest.json")
            or check["violations"] or check["unconnected"] or check["source_sha256"] != board["pcb_sha256"]):
        raise ValueError("Use the matched, checked geometry and PCB")
    folder = ROOT / "build/engineering/prototypes/force_button/visuals" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Render actual FB1 meshes, a geometric center section, the native board and explicit sensor/wiring diagrams without depicting physical hardware") as record:
        folder.mkdir(parents=True, exist_ok=False)
        models = json.loads((source / "models.json").read_text())
        models = [item for item in models if item["group"] != "bench_fixture"]
        original = []
        for key, group, color in (("hard_frame", "frame", "#819394"), ("soft_insert", "tpu", "#b8c49e")):
            mesh = trimesh.load_mesh(ROOT / cfg["basis"][key], process=True)
            mesh.apply_translation(cfg["mechanism"]["finger_translation_native_mm"])
            item = packed(mesh, "original_"+key, group, color)
            original.append(item)
        complete = original+models
        for item in complete:
            offsets = {"sensor": [0, 0, -10], "pcb": [0, 0, 10], "support": [0, 0, 20],
                       "insulation": [0, 0, 15], "pcb_components": [0, 0, -5],
                       "frame": [0, -15, 0], "tpu": [0, -15, 12], "plunger": [0, 0, -15]}
            item["explosion"] = offsets.get(item["group"], [0, 0, 0])
        (folder / "models.json").write_text(json.dumps([{
            "id": "fb1_assembly_reference", "title": "FB1 · force button at the root",
            "coordinates": "native_mm", "assembly": True, "components": complete,
            "note": "Actual CAD with the original finger. Reference hardware, an open stop gap and a zero-preload assembly pose are shown. Cable routing, real joints and physical performance remain unqualified."
        }], separators=(",", ":"))+"\n")
        cx, cy, cz = plan["sensor_contact_native_mm"]
        figures = []
        fig = plt.figure(figsize=(14, 6))
        ax = fig.add_subplot(111, projection="3d")
        ax.set_position([.02, .02, .96, .88])
        ax.set_proj_type("ortho")
        for item in complete:
            vertices = np.asarray(item["vertices"]); faces = np.asarray(item["faces"])
            alpha = .28 if item["group"] == "fixed" else .9
            ax.add_collection3d(Poly3DCollection(vertices[faces][:, :, [1, 2, 0]], facecolor=item["color"],
                                                 edgecolor="none", alpha=alpha, rasterized=True))
        all_xyz = np.vstack([item["vertices"] for item in complete])
        low, high = all_xyz.min(axis=0), all_xyz.max(axis=0)
        ax.set(xlim=(low[1]-5, high[1]+5), ylim=(low[2]-5, high[2]+5), zlim=(low[0]-5, high[0]+5),
               xlabel="Native Y (mm)", ylabel="Native Z (mm)", zlabel="Native X (mm)")
        ax.set_box_aspect((high-low)[[1, 2, 0]]+[10, 10, 10], zoom=1.28)
        ax.view_init(elev=24, azim=70)
        for label, point, offset in (
                ("FMA 25 N at root", [cy, cz, cx], (10, 55)),
                ("Original thin nail + TPU", [(low[1]+cy)/2, 12, -7.5], (-60, -55))):
            x, y, _ = proj3d.proj_transform(*point, ax.get_proj())
            ax.annotate(label, (x, y), xytext=offset, textcoords="offset points", fontsize=11, zorder=1000,
                        bbox={"facecolor": "white", "edgecolor": "#77978e", "pad": 4},
                        arrowprops={"arrowstyle": "->", "color": "#315b63"})
        fig.suptitle("FB1: the complete finger loads a packaged sensor at the root\n"
                     "50 mm added reach · no sensor film on the leading tip · CAD rendering, not a physical specimen", fontsize=13)
        figures.append((fig, "fb1_assembly"))
        fig, axes = plt.subplots(1, 2, figsize=(14, 7), gridspec_kw={"width_ratios": [1.8, 1]}, layout="constrained")
        colors = {}
        for item in models:
            if item["group"] in ("clamps", "leaves", "hardware", "root_hardware", "stops"):
                continue
            mesh = trimesh.Trimesh(vertices=item["vertices"], faces=item["faces"], process=False)
            section = mesh.section(plane_origin=[cx, 0, 0], plane_normal=[1, 0, 0])
            if section is None:
                continue
            for loop in section.discrete:
                axes[0].plot(loop[:, 1], loop[:, 2], color=item["color"], linewidth=1.7)
            colors[item["group"]] = item["color"]
        axes[0].set(xlim=(-60, -6), ylim=(-7, 36), xlabel="Native Y (mm)", ylabel="Native Z (mm)",
                    aspect="equal", title="Actual center section at native X = −7.5 mm")
        axes[0].grid(alpha=.15)
        for label, point, text in (
                ("FMA sphere / flat plunger", [cy, cz], [-56, 19]),
                ("PCB + 50 µm insulation", [cy, plan["pcb_back_face_z_mm"]], [-56, 32]),
                ("Compliant metal backing", [cy+11, 25.9], [-24, 33]),
                ("M4 adjustable plunger", [cy, 3], [-55, -4])):
            axes[0].annotate(label, point, xytext=text, fontsize=8.5,
                             arrowprops={"arrowstyle": "->", "color": "#526b73"},
                             bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85})
        axes[1].set(aspect="equal", xlim=(-12, 12), ylim=(-12, 12), xlabel="Offset X (mm)", ylabel="Offset Y (mm)",
                    title="Three stops around the plunger\nPlan view; separate from the section")
        axes[1].add_patch(Circle((0, 0), cfg["mechanism"]["fixed_stop_center_bore_mm"]/2, fill=False, ec="#537d86"))
        axes[1].add_patch(Circle((0, 0), cfg["mechanism"]["plunger_contact_diameter_mm"]/2, fc="#ccc", ec="#555"))
        for index, (x, y) in enumerate(plan["stop_points_xy_mm"]):
            axes[1].add_patch(Circle((x-cx, y-cy), cfg["mechanism"]["stop_tip_diameter_mm"]/2, fc="#c2885b"))
            axes[1].annotate("Stop "+str(index+1), (x-cx, y-cy), xytext=(4, 7), textcoords="offset points", fontsize=9)
        axes[1].text(0, -10, "Target gap after preload: 0.08 ± 0.01 mm\nSet by measurement; CAD is not the setting tool.",
                     ha="center", fontsize=9)
        fig.suptitle("FB1 load coupling: support the package, press only the sphere, keep the vent open", fontsize=13)
        figures.append((fig, "fb1_section"))
        fig, axes = plt.subplots(1, 2, figsize=(11, 8), layout="constrained")
        colors = {"VDD_REMOTE": "#b85d45", "GND_REMOTE": "#4b8172", "SDA": "#7954a1", "SCL": "#4778b4", "": "#999"}
        for axis, layer in zip(axes, ("F.Cu", "B.Cu")):
            axis.fill(*np.asarray(board["outline_xy_mm"]).T, color="#f0f4ea", ec="#35565b")
            for trace in board["tracks"]:
                if trace["layer"] == layer:
                    axis.plot(*np.asarray([trace["start"], trace["end"]]).T, color=colors[trace["net"]], lw=1.8)
            for pad in board["pads"]:
                if layer not in pad["layers"]:
                    continue
                width, height = pad["size"]
                patch = Rectangle((-width/2, -height/2), width, height, fc="#d4b365", ec="#806e40", lw=.4)
                patch.set_transform(Affine2D().rotate_deg(-pad["rotation"]).translate(*pad["center"])+axis.transData)
                axis.add_patch(patch)
                if pad["reference"] == "U1" or pad["reference"] == "JW":
                    axis.text(*pad["center"], pad["pad"], ha="center", va="center", fontsize=8)
            for hole in board["holes"]:
                axis.add_patch(Circle(hole["center_mm"], hole["diameter_mm"]/2, fc="white", ec="#4f6673"))
            for via in board["vias"]:
                axis.add_patch(Circle(via["center"], via["diameter"]/2, fc="#baa777", ec="#586777", lw=.4))
            axis.set(xlim=(-.5, 14.5), ylim=(20.5, -.5), aspect="equal", xlabel="PCB X (mm)", ylabel="PCB Y (mm)",
                     title=layer+" · same coordinate projection")
        axes[0].add_patch(Rectangle((5.39, 4.5), 5, 5, fill=False, ls="--", ec="#b96543"))
        axes[0].annotate("Open Ø0.45 mm vent\n(force axis)", (7, 7), xytext=(.6, 11.5), fontsize=9,
                         arrowprops={"arrowstyle": "->", "color": "#526b73"})
        axes[0].text(6.5, 13.5, "JW: 1 V+  ·  2 GND  ·  3 SDA\n4 SCL  ·  5 V-sense  ·  6 G-sense", ha="center", fontsize=8)
        fig.suptitle("FB1 sensor board · 14 × 20 × 1 mm · two copper layers\n"
                     "Actual routed primitives; native KiCad/Gerbers are authoritative · solder leads from the back", fontsize=12)
        figures.append((fig, "fb1_pcb"))
        with PdfPages(folder / "fb1_review_drawings.pdf") as pdf:
            for figure, name in figures:
                figure.savefig(folder / (name+".png"), dpi=160)
                pdf.savefig(figure)
                plt.close(figure)
        for name in ("fb1_stack.svg", "fb1_wiring.svg"):
            (folder / name).write_text((ROOT / "engineering/web" / name).read_text())
        report = {"schema": "yam-fb1-visuals/1", "physical_specimens_tested": 0,
                  "assembly_bounds_native_mm": [low.tolist(), high.tolist()],
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in (
                      CONFIG, source / "manifest.json", source / "models.json", args.fit_check.resolve(),
                      board_dir / "fb1_sensor.json", ROOT / "engineering/web/fb1_stack.svg", ROOT / "engineering/web/fb1_wiring.svg")},
                  "files_sha256": {p.name: digest(p) for p in folder.iterdir() if p.is_file()}}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "figures": len(figures), "physical_specimens_tested": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
