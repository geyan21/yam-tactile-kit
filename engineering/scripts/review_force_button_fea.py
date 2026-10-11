#!/usr/bin/python3
"""Compare FB1 mesh sizes and declared sensor-compliance scenarios."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/force-button-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tactile_kit.records import execution
from force_button_mechanics import CONFIG
from screen_f1_feedback import digest


def load(path):
    report = json.loads((path / "report.json").read_text())
    if report["input_sha256"].get(str(CONFIG.relative_to(ROOT))) != digest(CONFIG):
        raise ValueError("Structural comparison must use the current design")
    if report["mesh_sha256"] != digest(path / "mesh.inp"):
        raise ValueError("Structural mesh changed")
    for name, expected in report["input_sha256"].items():
        if digest(path / "inputs" / name) != expected:
            raise ValueError("Captured structural input changed: "+name)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fine", type=Path, required=True)
    parser.add_argument("--coarse", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, action="append", default=[])
    args = parser.parse_args()
    paths = [p.resolve() for p in (args.fine, args.coarse, *args.scenario)]
    if not all(p.is_relative_to(ROOT / "build/engineering/prototypes/force_button/fea") for p in paths):
        parser.error("Use saved FB1 structural runs")
    fine, coarse, *scenarios = [load(path) for path in paths]
    if (fine["sensor_compliance_mm_per_n"] != coarse["sensor_compliance_mm_per_n"]
            or fine["mesh"]["nodes"] <= coarse["mesh"]["nodes"]):
        raise ValueError("Compare a finer mesh at the same sensor compliance")
    folder = ROOT / "build/engineering/prototypes/force_button/structural_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Compare independent FB1 mesh resolutions and explicit sensor-stiffness cases, retaining model scope and physical evidence gaps") as record:
        folder.mkdir(parents=True, exist_ok=False)
        comparisons = []
        coarse_by_id = {r["id"]: r for r in coarse["contact_cases"]}
        for row in fine["contact_cases"]:
            other = coarse_by_id[row["id"]]
            difference = abs(row["added_motion_norm_mm"]-other["added_motion_norm_mm"])
            comparisons.append({"site": row["id"], "fine_motion_mm": row["added_motion_norm_mm"],
                                "coarse_motion_mm": other["added_motion_norm_mm"], "difference_mm": difference,
                                "relative_difference": difference/row["added_motion_norm_mm"]})
        gain_difference = abs(fine["sensor_gain_per_root_wrench"][2]/coarse["sensor_gain_per_root_wrench"][2]-1)
        converged = max(r["relative_difference"] for r in comparisons) <= .01 and gain_difference <= .01
        allowance = max(r["difference_mm"] for r in comparisons)
        cases = [fine, *scenarios]
        maximum = max(r["maximum_added_contact_motion_mm"] for r in cases)
        report = {"schema": "yam-fb1-structural-review/1", "physical_specimens_tested": 0,
                  "inputs": [{"directory": str(path.relative_to(ROOT)), "report_sha256": digest(path / "report.json")}
                             for path in paths],
                  "convergence": {"passed": converged, "criterion": "At most 1% change in each contact motion and root Fz sensor gain",
                                  "contact_comparisons": comparisons, "root_fz_gain_relative_difference": gain_difference},
                  "sensor_compliance_cases_mm_per_n": sorted(set(r["sensor_compliance_mm_per_n"] for r in cases)),
                  "maximum_observed_contact_motion_mm": maximum,
                  "mesh_comparison_allowance_mm": allowance,
                  "motion_screen_with_mesh_allowance_mm": maximum+allowance,
                  "motion_screen_met": bool(converged and maximum+allowance <= .1),
                  "maximum_model_contact_location_error_n": max(r["maximum_root_gain_contact_error_n"] for r in cases),
                  "limits": ["The mesh allowance is the observed mesh difference, not a rigorous error bound.",
                             "Only the stated sensor compliance cases are evaluated; no manufacturer stroke law is guaranteed.",
                             "Perfectly bonded clamps, rigid local patches, linear materials and the source finger as a rigid lever.",
                             "No physical force accuracy, low-force contact reliability, overforce strength, fatigue or moving-robot qualification."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        fig, axes = plt.subplots(1, 2, figsize=(13, 5), layout="constrained")
        for value, label in ((coarse, "Coarser mesh"), (fine, "Finer mesh")):
            rows = value["contact_cases"]
            axes[0].plot([r["id"] for r in rows], [r["added_motion_norm_mm"] for r in rows], marker="o", label=label)
        for value in cases:
            rows = value["contact_cases"]
            axes[1].plot([r["id"] for r in rows], [r["added_motion_norm_mm"] for r in rows], marker="o",
                         label=f"Assumed sensor {value['sensor_compliance_mm_per_n']*20*1000:g} µm at 20 N")
        for ax in axes:
            ax.axhline(.1, color="#a24b43", ls="--", label="Provisional 0.1 mm target")
            ax.set(ylabel="Added contact motion at 20 N (mm)")
            ax.tick_params(axis="x", rotation=28); ax.grid(alpha=.2); ax.legend(fontsize=8)
        fig.suptitle("FB1.1 bonded-metal structural screen · original finger treated as a rigid lever\n"
                     "Numerical comparison only; physical force, contact and precision tests remain", fontsize=12)
        for suffix in ("png", "pdf", "svg"):
            fig.savefig(folder / ("fb1_structural_screen."+suffix), dpi=160)
        plt.close(fig)
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "convergence_passed": converged,
                            "motion_screen_met": report["motion_screen_met"],
                            "motion_screen_with_mesh_allowance_mm": maximum+allowance}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
