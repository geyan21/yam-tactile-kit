#!/usr/bin/python3
"""Render the K1.2 cells, formed terminals and protected readout case from saved CAD."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/capacitive-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from mpl_toolkits.mplot3d import proj3d
import numpy as np
import trimesh
from tactile_kit.records import execution
from capacitive_geometry import CONFIG
from prototype_cad import packed
from screen_f1_feedback import digest


def draw_mesh(axis, item, alpha=1., shift=(0, 0, 0), order=(1, 2, 0)):
    vertices = np.asarray(item["vertices"])+shift
    layer = {"frame": 1, "tpu": 1, "k1_saddles": 2, "k1_flex": 3, "k1_terminals": 4,
             "k1_stops": 4, "k1_plates": 5, "k1_plate_bonds": 6, "k1_covers": 7}.get(item["group"], 3)
    if order == (0, 1, 2):
        name = item["name"]
        layer = (1 if name in ("k1_bank_case", "k1_bank_lid") else 2 if name == "k1_pcb_envelope"
                 else 5 if "retained_plate" in name else 6 if "vented_cover" in name else 4)
    axis.add_collection3d(Poly3DCollection(vertices[np.asarray(item["faces"])][:, :, list(order)],
                                         facecolor=item["color"], edgecolor="none", alpha=alpha,
                                         zorder=layer, rasterized=True))


def setup_axes(axis, vertices, elevation=24, azimuth=-60, order=(1, 2, 0)):
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    axis.set_proj_type("ortho")
    a, b, c = order
    labels = ["Native X (mm)", "Native Y (mm)", "Native Z (mm)"]
    axis.set(xlim=(low[a]-4, high[a]+4), ylim=(low[b]-4, high[b]+4), zlim=(low[c]-4, high[c]+4),
             xlabel=labels[a], ylabel=labels[b], zlabel=labels[c])
    axis.set_box_aspect((high-low)[list(order)]+8)
    axis.view_init(elev=elevation, azim=azimuth)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("mechanics", "foil_fit", "saddles", "enclosure", "screen"):
        parser.add_argument("--"+name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ("mechanics", "foil_fit", "saddles", "enclosure", "screen")}
    cfg = json.loads(CONFIG.read_text())
    if not json.loads((paths["enclosure"] / "report.json").read_text())["passed"]:
        raise ValueError("Use a passing enclosure check")
    folder = ROOT / "build/engineering/prototypes/capacitive/prototype_visuals" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Render only the actual K1.2 source, mechanical and terminal CAD; separate the finger from the remote protected-reference electronics case") as record:
        folder.mkdir(parents=True)
        originals = []
        for key, color in (("hard_frame", "#9aa7a4"), ("soft_insert", "#bfccb5")):
            originals.append(packed(trimesh.load_mesh(ROOT / cfg["basis"][key], process=True),
                                    "original_"+key, "frame" if key == "hard_frame" else "tpu", color))
        complete = []
        for item in json.loads((paths["mechanics"] / "models.json").read_text()):
            role = item["group"]
            if role.startswith("cover_bond") or role.endswith("_bond") and not role.startswith("ground_bond"):
                continue
            item["group"] = ("k1_plates" if role == "retained_plate" else "k1_covers" if role == "vented_cover"
                             else "k1_plate_bonds" if role.startswith("ground_bond") else "k1_stops")
            item["color"] = {"k1_plates": "#638ca1", "k1_covers": "#c1d5ae",
                             "k1_plate_bonds": "#b88c64", "k1_stops": "#c9ad67"}[item["group"]]
            item["explosion"] = [0, 0, {"k1_covers": 12, "k1_plates": 8, "k1_stops": 3}.get(item["group"], 8)]
            complete.append(item)
        for item in json.loads((paths["foil_fit"] / "models.json").read_text()):
            if item["group"] == "stiffener_bond":
                continue
            item["group"] = "k1_flex" if item["group"] == "foil" else "k1_terminals"
            complete.append(item)
        for item in json.loads((paths["saddles"] / "models.json").read_text()):
            item["group"] = "k1_saddles"; complete.append(item)
        bank = json.loads((paths["enclosure"] / "models.json").read_text())
        for item in bank:
            item["explosion"] = [0, 0, 12 if item["name"] == "k1_bank_lid" else 0]
            name = item["name"]
            item["group"] = ("k1_case" if name == "k1_bank_case" else "k1_case_lid" if name == "k1_bank_lid"
                             else "k1_readout" if name == "k1_pcb_envelope" else "k1_electronics" if "component_" in name
                             else "k1_reference_support" if name in ("k1_reference_support", "k1_reference_mount_bond")
                             else "k1_reference")
            item["color"] = ("#81a49a" if name == "k1_pcb_envelope" else "#48626a" if "component_" in name
                             else "#437e9d" if "retained_plate" in name else "#bb9665" if "joint" in name or "ground_bond" in name
                             else "#c8d5cf" if name in ("k1_bank_case", "k1_bank_lid") else "#92b9a1")
        models = [
            {"id": "k1_assembly_reference", "title": "K1.2 · six capacitive cells and formed terminals",
             "coordinates": "native_mm", "assembly": True, "components": originals+complete,
             "note": "Actual source/CAD geometry. Remote bank cases and flexible wires are shown separately. Nominal geometry does not establish loaded fit, cable motion, contact reliability or force accuracy."},
            {"id": "k1_bank_reference", "title": "K1.2 · one bank case, used twice",
             "coordinates": "native_mm", "assembly": True, "components": bank,
             "note": "One checked PCB envelope and the protected reference. Build two cases; keep the Pico outside them. The lid must not preload REF."}]
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        figures = []
        fig = plt.figure(figsize=(14, 7), layout="constrained")
        for number, nail_only in ((121, False), (122, True)):
            axis = fig.add_subplot(number, projection="3d", computed_zorder=False)
            selected = [p for p in complete if not nail_only or p["name"].startswith(("k1_ch0_", "k1_ch1_"))]
            vertices = np.vstack([p["vertices"] for p in selected])
            low, high = vertices.min(axis=0), vertices.max(axis=0)
            for original in originals:
                if not nail_only:
                    draw_mesh(axis, original, .12)
                else:
                    item = dict(original)
                    faces = np.asarray(original["faces"]); points = np.asarray(original["vertices"])
                    centers = points[faces].mean(axis=1)
                    item["faces"] = faces[np.all((centers >= low-6) & (centers <= high+6), axis=1)]
                    draw_mesh(axis, item, .12)
            for item in selected:
                alpha = {"k1_covers": .08, "k1_flex": .22, "k1_plates": 1.}.get(item["group"], .8)
                draw_mesh(axis, item, alpha)
            setup_axes(axis, vertices, azimuth=120 if nail_only else -60)
            for item in selected:
                if item["group"] != "k1_plates":
                    continue
                center = np.asarray(item["vertices"]).mean(axis=0)[[1, 2, 0]]
                x, y, _ = proj3d.proj_transform(*center, axis.get_proj())
                label = item["name"].split("_")[1].upper()
                axis.annotate(label, (x, y), xytext=(4, 16), textcoords="offset points", fontsize=10,
                              zorder=1000, bbox={"fc": "white", "ec": "#819b94", "alpha": .96},
                              arrowprops={"arrowstyle": "-", "color": "#526f72"})
            axis.set_title("Two separate nail cells and lifted terminals" if nail_only else "Four TPU cells + two nail cells", fontsize=11)
        fig.suptitle("K1.2: blue grounded plates over guarded green flex electrodes\n"
                     "Transparent cover/source · gold stop pieces · CAD rendering, 0 physical specimens", fontsize=13)
        figures.append((fig, "k1_assembly"))
        fig = plt.figure(figsize=(12, 7), layout="constrained")
        axis = fig.add_subplot(111, projection="3d", computed_zorder=False)
        points = []
        for item in bank:
            shift = item["explosion"]
            points.append(np.asarray(item["vertices"])+shift)
            alpha = .10 if item["name"] in ("k1_bank_case", "k1_bank_lid") else .35 if "vented_cover" in item["name"] else 1.
            draw_mesh(axis, item, alpha, shift, order=(0, 1, 2))
        setup_axes(axis, np.vstack(points), elevation=35, azimuth=-65, order=(0, 1, 2))
        for name, label, offset in (
                ("k1_reference_retained_plate", "Protected REF capacitor", (40, -50)),
                ("k1_component_U1", "FDC1004DGSR", (-100, 25)),
                ("k1_component_U2", "ADS1115 health monitor", (30, 45))):
            item = next(p for p in bank if p["name"] == name)
            point = np.asarray(item["vertices"]).mean(axis=0)
            x, y, _ = proj3d.proj_transform(*point, axis.get_proj())
            axis.annotate(label, (x, y), xytext=offset, textcoords="offset points", fontsize=10,
                          zorder=1000, bbox={"fc": "white", "ec": "#819b94", "alpha": .96},
                          arrowprops={"arrowstyle": "->", "color": "#526f72"})
        fig.suptitle("K1 bank enclosure · make two identical copies\n"
                     "Lid lifted for viewing · reference capacitor on its separate 0.5 mm support · Pico is outside the case", fontsize=13)
        figures.append((fig, "k1_enclosure"))
        with PdfPages(folder / "k1_review_drawings.pdf") as pdf:
            for figure, name in figures:
                figure.savefig(folder / (name+".png"), dpi=160); pdf.savefig(figure); plt.close(figure)
        for name in ("k1_stack.svg", "k1_wiring.svg"):
            shutil.copyfile(ROOT / "engineering/web" / name, folder / name)
        for suffix in ("png", "pdf"):
            shutil.copyfile(paths["screen"] / ("assembly_sensitivity."+suffix), folder / ("assembly_sensitivity."+suffix))
        inputs = [CONFIG, Path(__file__), ROOT / "engineering/web/k1_stack.svg", ROOT / "engineering/web/k1_wiring.svg"]
        inputs += [p / "models.json" for key, p in paths.items() if key != "screen"]
        inputs += [paths["screen"] / "report.json"]
        report = {"schema": "yam-k1-prototype-visuals/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "files_sha256": {p.name: digest(p) for p in folder.iterdir() if p.is_file()}}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "models": len(models), "drawings": len(figures)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
