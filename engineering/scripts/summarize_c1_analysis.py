#!/usr/bin/python3
"""Compare two C1 structural discretizations without treating simulation as hardware evidence."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT/"build/engineering/tools/mpl-cache")
sys.path.insert(0,str(ROOT/"src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/c1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mechanical(config):
    return {key:config[key] for key in ("beam","gauges","mount")}


def load(path):
    return json.loads((path/"screen.json").read_text()),json.loads((path/"inputs/configuration.json").read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coarse",type=Path,required=True)
    parser.add_argument("--fine",type=Path,required=True)
    args = parser.parse_args()
    coarse,coarse_cfg = load(args.coarse)
    fine,fine_cfg = load(args.fine)
    current = json.loads((ROOT/"engineering/designs/c1.json").read_text())
    if mechanical(coarse_cfg)!=mechanical(fine_cfg) or mechanical(fine_cfg)!=mechanical(current):
        raise ValueError("Convergence comparison must use the same current mechanical design")
    if coarse.get("gauge_area_quadrature_order")!=fine.get("gauge_area_quadrature_order"):
        raise ValueError("Use matching gauge quadrature rules for the convergence comparison")
    with execution(ROOT/"build/records","Compare C1 displacement and gauge-derived force convergence, preserving simulation-only interpretation") as record:
        loads = [case["wrench_about_root_n_nmm"] for case in fine["contact_cases_20n"]]
        loads += [list(np.eye(6)[i]*(20 if i<3 else 2200)) for i in range(6)]
        loads = np.asarray(loads).T
        ca = np.asarray([r["gauge_strain_per_unit"] for r in coarse["forces_and_moments"]]).T
        fa = np.asarray([r["gauge_strain_per_unit"] for r in fine["forces_and_moments"]]).T
        gauge_delta = float(np.max(np.abs((fa-ca)@loads)))
        fc = np.asarray(coarse["force_equivalent_response_per_unit"])
        ff = np.asarray(fine["force_equivalent_response_per_unit"])
        force_delta = float(np.max(np.abs((ff-fc)@loads)))
        displacement_delta = max(abs(a["added_normal_displacement_mm"]-b["added_normal_displacement_mm"])
                                 for a,b in zip(coarse["contact_cases_20n"],fine["contact_cases_20n"]))
        displacement_relative = displacement_delta/max(fine["max_added_normal_displacement_mm"],1e-12)
        limits = current["structural_screen"]
        convergence = {
            "maximum_gauge_strain_change":gauge_delta,
            "maximum_equivalent_force_change_n":force_delta,
            "maximum_normal_motion_change_mm":displacement_delta,
            "relative_motion_change":displacement_relative,
            "gauge_limit":limits["gauge_strain_convergence_limit"],
            "force_limit_n":limits["force_equivalent_convergence_limit_n"],
            "motion_relative_limit":.01,
        }
        convergence["passed"] = gauge_delta<=convergence["gauge_limit"] and force_delta<=convergence["force_limit_n"] and displacement_relative<=.01
        report = {
            "schema":"yam-c1-structural-review/1","evidence_kind":"linear_FEA_screen_only",
            "physical_specimens_tested":0,"revision":current["revision"],"convergence":convergence,
            "max_added_normal_displacement_mm_at_20n":fine["max_added_normal_displacement_mm"],
            "provisional_motion_target_mm":limits["provisional_added_tip_motion_limit_mm"],
            "motion_screen_met":fine["max_added_normal_displacement_mm"]<=limits["provisional_added_tip_motion_limit_mm"],
            "max_force_error_using_ideal_beam_weights_n":fine["max_ideal_force_error_n"],
            "max_force_error_after_simulated_fz_my_identification_n":fine["max_simulation_force_error_n"],
            "max_integration_point_von_mises_mpa":fine.get("max_integration_point_von_mises_mpa"),
            "cases_20n":fine["contact_cases_20n"],
            "inputs":[{"directory":str(path.resolve().relative_to(ROOT)),"screen_sha256":digest(path/"screen.json")}
                      for path in (args.coarse,args.fine)],
            "limits":fine["limits"]+[
                "Convergence compares these discretizations and declared load cases; it is not a bound for every possible numerical error.",
                "Simulated identification weights are not supplied as physical calibration coefficients.",
                "The real clamp/fastener/gauge/cable system must be assembled and measured through the intended load range.",
            ],
        }
        (OUTPUT/"c1_structural_review.json").write_text(json.dumps(report,indent=2)+"\n")
        fig,axes = plt.subplots(1,2,figsize=(13,4.8),layout="constrained")
        names = [c["id"].replace("_"," ") for c in fine["contact_cases_20n"]]
        x = np.arange(len(names))
        axes[0].bar(x,[c["added_normal_displacement_mm"] for c in fine["contact_cases_20n"]],color="#39867d")
        axes[0].axhline(limits["provisional_added_tip_motion_limit_mm"],ls="--",color="#a76d37",label="0.1 mm provisional screen")
        axes[0].set_xticks(x,names,rotation=35,ha="right")
        axes[0].set_ylabel("Calculated added normal motion (mm)")
        axes[0].set_title("20 N normal load · rigid finger + bonded adapter")
        axes[0].legend(fontsize=8);axes[0].grid(axis="y",alpha=.2)
        axes[1].bar(x,[c["force_from_simulation_fz_my_weights_n"]-20 for c in fine["contact_cases_20n"]],color="#947eae")
        axes[1].axhline(0,color="#657b7e",lw=1)
        axes[1].set_xticks(x,names,rotation=35,ha="right")
        axes[1].set_ylabel("Calculated force-recovery error (N)")
        axes[1].set_title("Simulation-only identification\nNot measured sensor accuracy")
        axes[1].grid(axis="y",alpha=.2)
        fig.suptitle("C1 structural screen · no physical specimens tested")
        fig.savefig(OUTPUT/"c1_structural_screen.svg")
        fig.savefig(OUTPUT/"c1_structural_screen.png",dpi=145)
        plt.close(fig)
        record["review"] = {"convergence":convergence,"motion_screen_met":report["motion_screen_met"],
                            "max_added_motion_mm":report["max_added_normal_displacement_mm_at_20n"]}
        print(json.dumps(record["review"],indent=2))
        if not convergence["passed"]:
            raise ValueError("C1 numerical convergence is not yet established")


if __name__=="__main__":
    main()
