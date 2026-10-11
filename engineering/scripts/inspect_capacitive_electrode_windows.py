#!/usr/bin/python3
"""Check whether the K1 electrode envelopes leave room for the specified driven guard."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from tactile_kit.records import execution
from capacitive_geometry import CONFIG, load, offsets, unrolled, reference_footprints
from screen_f1_feedback import digest


def main():
    cfg, surfaces = load()
    f = cfg["flex"]
    required = f["edge_clearance_mm"]+f["clearance_mm"]+f["trace_mm"]
    target_inset = required+.1
    folder = ROOT / "build/engineering/prototypes/capacitive/electrode_windows" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check the retained K1 sensing envelopes against their stated copper-edge, isolation and guard-width requirements before drawing fabrication artwork; preserve the existing module") as record:
        folder.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(CONFIG, folder / CONFIG.name)
        rows = []
        fig, axes = plt.subplots(2, 4, figsize=(14, 8), layout="constrained")
        for index, surface in enumerate([*surfaces, None]):
            label = "REF" if surface is None else "CH"+str(surface.site)
            if surface is None:
                body, active = reference_footprints(cfg)
            else:
                neutral = offsets(surface.site, cfg)["flex_bottom"]+f["coverlay_each_mm"]+f["copper_each_mm"]+f["polyimide_core_mm"]/2
                body = unrolled(surface.body, surface, neutral)
                active = unrolled(surface.active, surface, neutral)
            guarded = active.buffer(f["clearance_mm"]+f["trace_mm"], join_style="mitre")
            available = body.buffer(-f["edge_clearance_mm"], join_style="mitre")
            overrun = guarded.difference(available)
            proposed = active.intersection(body.buffer(-target_inset, join_style="mitre"))
            if proposed.is_empty or proposed.geom_type != "Polygon" or not proposed.is_valid:
                raise ValueError("A new footprint is required at "+label)
            minimum_gap = body.boundary.distance(active.boundary)
            row = {"site": label, "body_area_mm2": body.area, "original_active_area_mm2": active.area,
                   "minimum_active_to_outline_mm": minimum_gap,
                   "required_active_inset_mm": required,
                   "original_guard_fits": overrun.area <= 1e-7,
                   "guard_overrun_area_mm2": overrun.area,
                   "proposed_minimum_inset_mm": target_inset,
                   "proposed_active_area_mm2": proposed.area,
                   "retained_active_area_fraction": proposed.area/active.area,
                   "body_flat_xy_mm": list(body.exterior.coords),
                   "original_active_flat_xy_mm": list(active.exterior.coords),
                   "proposed_active_flat_xy_mm": list(proposed.exterior.coords)}
            rows.append(row)
            ax = axes.flat[index]
            ax.fill(*np.asarray(body.exterior.coords).T, color="#eff3e9", ec="#325661")
            ax.fill(*np.asarray(active.exterior.coords).T, color="#d8ac83", alpha=.55, label="Existing envelope")
            ax.plot(*np.asarray(proposed.exterior.coords).T, color="#367d65", lw=1.5, label="Proposed inset")
            ax.set(aspect="equal", title=label+(" · fits" if row["original_guard_fits"] else " · insufficient guard space"),
                   xlabel="Developed X (mm)", ylabel="Developed arc (mm)")
            ax.grid(alpha=.15)
        axes.flat[-1].axis("off")
        axes.flat[-1].text(0, .92, "Guard requirement\n\n0.30 mm board edge\n+ 0.20 mm driven guard\n+ 0.20 mm isolation\n= 0.70 mm minimum inset\n\nProposal: 0.80 mm inset\nwhere the original area is closer.\n\nNo CAD, post sheet or electrode\nhas been changed by this check.",
                           va="top", fontsize=11)
        fig.suptitle("K1 electrode integration check · existing envelopes are not fabrication artwork\n"
                     "Geometric guard fit only; capacitance, post layout and physical behavior need separate review", fontsize=12)
        for suffix in ("png", "pdf", "svg"):
            fig.savefig(folder / ("electrode_windows."+suffix), dpi=160)
        plt.close(fig)
        report = {"schema": "yam-k1-electrode-window-review/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in (
                      CONFIG, Path(__file__), ROOT / "engineering/scripts/capacitive_geometry.py",
                      ROOT / "engineering/scripts/f1_surfaces.py")},
                  "edge_clearance_mm": f["edge_clearance_mm"], "guard_width_mm": f["trace_mm"],
                  "active_guard_clearance_mm": f["clearance_mm"], "cells": rows,
                  "limits": ["Geometric planning only. A reduced electrode needs matched post tooling and renewed capacitance/shield-load checks.",
                             "This does not complete copper routing, tail connections, stops, retention, vents, plate bonds or physical tests."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)),
                            "existing_footprints_with_insufficient_guard_space": [r["site"] for r in rows if not r["original_guard_fits"]],
                            "minimum_retained_active_area_fraction": min(r["retained_active_area_fraction"] for r in rows)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
