#!/usr/bin/python3
"""Render saved, independently checked F1 copper and component envelopes."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PlotPolygon, Circle
from shapely import affinity
from shapely.geometry import LineString, box


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checked_directory", type=Path)
    args = parser.parse_args()
    source = args.checked_directory.resolve()
    if not source.is_relative_to(ROOT):
        parser.error("Use one repository-owned independent check")
    summary = json.loads((source / "summary.json").read_text())
    manifest = source / "f1_fanout.json"
    if not summary["passed"] or digest(manifest) != summary["source_manifest_sha256"]:
        raise ValueError("Select unchanged geometry from a clean independent check")
    board = json.loads(manifest.read_text())
    output = source / "visual_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Render checked F1 board faces and assembly envelopes for visual review") as record:
        output.mkdir(parents=True, exist_ok=False)
        fig, axes = plt.subplots(1, 2, figsize=(16, 7), layout="constrained")
        for ax, side in zip(axes, ("F", "B")):
            ax.add_patch(PlotPolygon(board["outline_xy_mm"], facecolor="#f2f6f0", edgecolor="#34413a", lw=1))
            for t in board["tracks"]:
                if t["layer"] != side+".Cu":
                    continue
                shape = LineString([t["start"], t["end"]]).buffer(t["width"]/2)
                ax.add_patch(PlotPolygon(list(shape.exterior.coords), edgecolor="none",
                                        facecolor="#b85e3c" if side == "F" else "#3c78b8", alpha=.8))
            for p in board["pads"]:
                if p["layers"] != [side+".Cu"]:
                    continue
                w, h = p["size"]
                shape = affinity.rotate(box(-w/2, -h/2, w/2, h/2), -p["rotation"], origin=(0, 0))
                shape = affinity.translate(shape, *p["center"])
                ax.add_patch(PlotPolygon(list(shape.exterior.coords), edgecolor="#8c6321",
                                        facecolor="#d9ad55", lw=.2))
            for v in board["vias"]:
                ax.add_patch(Circle(v["center"], v["diameter"]/2, facecolor="#52695e", lw=0))
                ax.add_patch(Circle(v["center"], v["drill"]/2, facecolor="white", lw=0))
            for h in board["holes"]:
                ax.add_patch(Circle(h["center_mm"], h["diameter_mm"]/2, facecolor="white", edgecolor="#667"))
            for part in board["parts"]:
                if part["side"] != side:
                    continue
                shape = box(*part["body_envelope_mm"])
                if side == "B":
                    shape = affinity.scale(shape, xfact=-1, yfact=1, origin=(0, 0))
                shape = affinity.rotate(shape, -part["rotation_deg"], origin=(0, 0))
                shape = affinity.translate(shape, *part["center_mm"])
                ax.add_patch(PlotPolygon(list(shape.exterior.coords), facecolor="#dbe6f1",
                                        edgecolor="#344a61", lw=.6, alpha=.65))
                if part["reference"].startswith("J") or part["reference"] == "UT":
                    ax.text(*part["center_mm"], part["reference"], ha="center", va="center",
                            fontsize=8, color="#132c43",
                            bbox={"facecolor": "white", "edgecolor": "none", "alpha": .75, "pad": 1})
            ax.set(xlim=(13, 76) if side == "F" else (76, 13), ylim=(38, -2),
                   aspect="equal", xlabel="PCB x = −native Y (mm)", ylabel="PCB y = 44 −native Z (mm)")
            ax.grid(alpha=.15)
            ax.set_title("Outer row face • F.Cu" if side == "F" else "Inner column face • B.Cu, viewed from the back")
        fig.suptitle("F1 connector-board development • four copper layers • 42 components\n"
                     "Independent DRC: 0 violations, 0 unconnected • no physical prototype tested", fontsize=13)
        fig.text(.5, .02, "Actual routed outer-layer copper; rectangular part envelopes. "
                 "KiCad assembly SVGs provide pad numbers and silkscreen. The inner ground pour is not pictured.",
                 ha="center", fontsize=9)
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(output / ("fanout_faces."+suffix), dpi=190, bbox_inches="tight")
        plt.close(fig)
        receipt = {"manifest_sha256": digest(manifest), "independent_check_sha256": digest(source / "summary.json"),
                   "renderer_sha256": digest(Path(__file__)), "physical_evidence": False,
                   "files": {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()}}
        (output / "visual_review.json").write_text(json.dumps(receipt, indent=2)+"\n")
        record["visual_review"] = receipt
        print(json.dumps({"directory": str(output.relative_to(ROOT)), **receipt}, indent=2))


if __name__ == "__main__":
    main()
