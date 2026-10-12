#!/usr/bin/python3
"""Render the actual retained F1 R4 layers, complete foils and terminal pieces."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from mpl_toolkits.mplot3d import proj3d
import numpy as np
from tactile_kit.records import execution
from screen_f1_feedback import digest

BASE = ROOT / "engineering/development/f1/r3"


def draw(axis, item, alpha):
    vertices, faces = np.asarray(item["vertices"]), np.asarray(item["faces"])
    group = item["group"]
    layer = {"frame": 1, "tpu": 1, "f1_covers": 7, "f1_foils": 5,
             "f1_film": 6, "f1_stiffeners": 4}.get(group, 3)
    axis.add_collection3d(Poly3DCollection(vertices[faces][:, :, [1, 2, 0]],
                                         facecolor=item["color"], edgecolor="none",
                                         alpha=alpha, zorder=layer, rasterized=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("skin", "foils", "terminals"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ("skin", "foils", "terminals")}
    source = json.loads((BASE / "models.json").read_text())[0]["components"]
    retained = [item for item in source if item["group"] not in ("f1_stacks", "f1_tails")]
    complete = []
    skin_report = json.loads((paths["skin"] / "report.json").read_text())
    skin_parts = {part["id"]: part for part in skin_report["parts"]}
    for item in json.loads((paths["skin"] / "models.json").read_text()):
        if item["name"].endswith(("_columns_body", "_rows_body", "_column_finish_envelope", "_row_finish_envelope")):
            continue
        if skin_parts[item["name"]]["kind"] == "fabricate_tool":
            continue
        if item["name"].endswith("_pressure_film"):
            item["group"] = "f1_film"
            item["color"] = "#51465f"
        complete.append(item)
    complete.extend(json.loads((paths["foils"] / "models.json").read_text()))
    complete.extend(item for item in json.loads((paths["terminals"] / "models.json").read_text())
                    if item["group"] == "f1_stiffeners")
    for item in complete:
        item["explosion"] = [0, 0, -5 if item["group"] == "f1_covers" else 0]
    models = [{"id": "f1_r4_assembly_reference", "title": "F1 R4 · retained film sensors and complete flex envelopes",
               "coordinates": "native_mm", "assembly": True, "components": retained+complete,
               "note": "Actual source/CAD geometry. The closed connector cavities, physical seals/strain relief, installed drive and moving tails remain unqualified. No physical force/contact performance is shown."}]
    folder = ROOT / "build/engineering/prototypes/f1/r4_visuals" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Render F1 R4 actual source, retained skin, finished terminal pieces and joined foil geometry; keep unqualified interfaces and zero physical specimens explicit") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        fig = plt.figure(figsize=(15, 7), layout="constrained")
        films = [item for item in complete if item["group"] == "f1_film"]
        for number, closeup in ((121, False), (122, True)):
            axis = fig.add_subplot(number, projection="3d", computed_zorder=False)
            chosen_films = [item for item in films if not closeup or item["name"].startswith(("f1_ch0_", "f1_ch1_"))]
            points = np.vstack([item["vertices"] for item in chosen_films])
            if closeup:
                low, high = points.min(axis=0)-2, points.max(axis=0)+2
            else:
                points = np.vstack([item["vertices"] for item in retained+complete])
                low, high = points.min(axis=0)-3, points.max(axis=0)+3
            for original in retained+complete:
                item = dict(original)
                if closeup:
                    vertices, faces = np.asarray(item["vertices"]), np.asarray(item["faces"])
                    centers = vertices[faces].mean(axis=1)
                    item["faces"] = faces[np.all((centers >= low-2) & (centers <= high+2), axis=1)].tolist()
                    if not item["faces"]:
                        continue
                alpha = {"frame": .10, "tpu": .12, "f1_foils": .20,
                         "f1_covers": .06, "f1_film": 1., "f1_stack_bonds": .15}.get(item["group"], .6)
                draw(axis, item, alpha)
            axis.set_proj_type("ortho")
            axis.set(xlim=(low[1], high[1]), ylim=(low[2], high[2]), zlim=(low[0], high[0]),
                     xlabel="Native Y (mm)", ylabel="Native Z (mm)", zlabel="Native X (mm)")
            axis.set_box_aspect((high-low)[[1, 2, 0]])
            axis.view_init(elev=25, azim=120 if closeup else -60)
            for item in chosen_films:
                center = np.asarray(item["vertices"]).mean(axis=0)[[1, 2, 0]]
                x, y, _ = proj3d.proj_transform(*center, axis.get_proj())
                axis.annotate(item["name"].split("_")[1].upper(), (x, y), xytext=(5, 15), textcoords="offset points",
                              fontsize=11, zorder=1000, bbox={"fc": "white", "ec": "#819b94", "alpha": .98},
                              arrowprops={"arrowstyle": "-", "color": "#526f72"})
            axis.set_title("Two separate nail islands; notch retained" if closeup else "Six film sensors → twelve flexes → fixed interface", fontsize=11)
        fig.suptitle("F1 R4 · purple surfaces are the six pressure-film islands\n"
                     "Source, covers and electrode envelopes are transparent · CAD rendering, 0 physical specimens", fontsize=13)
        fig.savefig(folder / "f1_r4_assembly.png", dpi=160)
        with PdfPages(folder / "f1_r4_review_drawings.pdf") as pdf:
            pdf.savefig(fig)
        plt.close(fig)
        for name in ("f1_stack.svg", "f1_wiring.svg"):
            shutil.copyfile(ROOT / "engineering/web" / name, folder / name)
        inputs = [Path(__file__), BASE / "models.json", *[path / "models.json" for path in paths.values()],
                  paths["skin"] / "report.json", ROOT / "engineering/web/f1_stack.svg", ROOT / "engineering/web/f1_wiring.svg"]
        report = {"schema": "yam-f1-r4-visuals/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "files_sha256": {path.name: digest(path) for path in folder.iterdir() if path.is_file()}}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "models": len(models), "drawings": 1}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
