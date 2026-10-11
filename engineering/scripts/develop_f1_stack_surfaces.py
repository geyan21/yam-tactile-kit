#!/usr/bin/python3
"""Develop separate F1 layer lengths and actual-coordinate stack surfaces."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_surfaces import CONFIG, load_surfaces, layer_offsets
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    config_path = args.config.resolve()
    if not config_path.is_relative_to(ROOT):
        parser.error("Use a repository-owned configuration")
    cfg, r1, nail, surfaces = load_surfaces(config_path)
    folder = ROOT / "build/engineering/prototypes/f1/stack_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Develop F1 layer-specific conductor reference lengths on the original R1/nail surfaces, preserving the unfinished tail and physical-test status") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        sources = [config_path, Path(__file__), ROOT / "engineering/scripts/f1_surfaces.py",
                   ROOT / cfg["basis"]["r1_manifest"], ROOT / cfg["basis"]["nail_coordinates"]]
        for path in sources:
            target = inputs / path.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        fig, axes = plt.subplots(2, 2, figsize=(13, 9), layout="constrained")
        rows = []
        for surface in surfaces:
            offsets = layer_offsets(surface.site, cfg)
            trim = cfg["body"]["tpu_foil_arc_trim_each_end_mm"] if surface.site >= 2 else 0
            span = [trim, surface.length-trim]
            arcs = {name: offsets_value for name, offsets_value in (
                (name, surface.offset_arc(value)) for name, value in offsets.items())}
            lengths = {name: float(np.interp(span[1], surface.s, arc)-np.interp(span[0], surface.s, arc))
                       for name, arc in arcs.items()}
            curvature = np.abs(surface.curvature())
            derivative = 1+surface.curvature()*offsets["cover_outer"]
            if np.any(derivative <= 0):
                raise ValueError("Offset surface folds through a curvature singularity")
            sigma = cfg["body"]["neutral_axis_sensitivity_offset_mm"]
            sensitivities = {}
            for name in ("column_conductor_center", "row_conductor_center"):
                difference = []
                for delta in (-sigma, sigma):
                    arc = surface.offset_arc(offsets[name]+delta)
                    length = np.interp(span[1], surface.s, arc)-np.interp(span[0], surface.s, arc)
                    difference.append(float(abs(length-lengths[name])))
                sensitivities[name] = max(difference)
            row = {
                "site": f"CH{surface.site}", "kind": surface.kind, "reference_length_mm": surface.length,
                "body_reference_s_span_mm": span, "body_reference_outline": list(surface.body.exterior.coords),
                "active_reference_outline": list(surface.active.exterior.coords),
                "normal_offsets_mm": offsets, "layer_cut_reference_lengths_mm": lengths,
                "column_minus_row_cut_length_mm": lengths["column_conductor_center"]-lengths["row_conductor_center"],
                "neutral_reference_sensitivity_mm": sensitivities,
                "minimum_curvature_radius_mm": 1/float(np.max(curvature)) if np.max(curvature) > 1e-9 else None,
                "minimum_offset_jacobian": float(np.min(derivative)),
                "proximal_center": surface.points(0, span[1], offsets["film_center"]).tolist(),
                "proximal_tangent": surface.frame(span[1])[1].tolist(),
                "proximal_normal": surface.frame(span[1])[2].tolist(),
                "physical_evidence": False,
            }
            rows.append(row)
            with (folder / f"ch{surface.site}_layer_unroll.csv").open("w", newline="") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(["base_s_mm", *["arc_"+name+"_mm" for name in offsets]])
                writer.writerows(zip(surface.s, *[arcs[name] for name in offsets]))
            if surface.site >= 2:
                ax = axes.flat[surface.site-2]
                for name, color in (("mount_outer", "#858585"), ("column_contact", "#956522"),
                                   ("row_contact", "#3c629b"), ("cover_outer", "#648c68")):
                    points = surface.points(np.zeros_like(surface.s), surface.s, offsets[name])
                    ax.plot(points[:, 0+1], points[:, 2], color=color, label=name.replace("_", " "))
                ax.set(title="CH"+str(surface.site)+" · individual layer curves",
                       xlabel="Native Y (mm)", ylabel="Native Z (mm)")
                ax.grid(alpha=.2); ax.legend(fontsize=8)
        fig.suptitle("F1 mounted layer references · geometry development\n"
                     "Separate conductor cut lengths; no fitted tails or physical performance claim", fontsize=13)
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(folder / f"stack_surfaces.{suffix}", dpi=170)
        plt.close(fig)
        report = {"schema": "yam-f1-stack-surfaces/1",
                  "input_hashes": {str(path.relative_to(ROOT)): digest(path) for path in sources},
                  "physical_specimens_tested": 0, "complete_f1_package": False,
                  "surfaces": rows,
                  "limits": [
                      "Reference curves follow the retained R1 saddle and nail geometry. Complete frame collision checks and formed-tail interfaces remain.",
                      "Conductor-center planes define nominal developed lengths. A +/-0.02 mm offset sensitivity is reported, not a material-qualified neutral-axis bound.",
                      "Copper/film pressure behavior, inter-layer slip, preload, fatigue and force accuracy require physical measurements.",
                      "The thinner nail cover and trimmed TPU foil outlines are new F1 process choices awaiting tooling and assembly checks."
                  ]}
        (folder / "surfaces.json").write_text(json.dumps(report, indent=2)+"\n")
        record["summary"] = {"directory": str(folder.relative_to(ROOT)),
                            "nail_stack_mm": rows[0]["normal_offsets_mm"]["cover_outer"],
                            "tpu_stack_mm": rows[2]["normal_offsets_mm"]["cover_outer"],
                            "maximum_cut_length_difference_mm": max(abs(row["column_minus_row_cut_length_mm"]) for row in rows)}
        print(json.dumps({**record["summary"], "surfaces": [
            {key: row[key] for key in ("site", "reference_length_mm", "column_minus_row_cut_length_mm",
                                      "proximal_center", "proximal_tangent", "proximal_normal")}
            for row in rows]}, indent=2))


if __name__ == "__main__":
    main()
