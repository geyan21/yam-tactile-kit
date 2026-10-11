#!/usr/bin/python3
"""Compare preserved N1 structural runs without claiming measured force accuracy."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from structural_tools import digest
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/prototypes/nail"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coarse",type=Path,required=True)
    parser.add_argument("--fine",type=Path,required=True)
    args=parser.parse_args()
    current=json.loads((ROOT/"engineering/designs/nail.json").read_text())
    plans=[json.loads((folder/"inputs/configuration.json").read_text()) for folder in (args.coarse,args.fine)]
    physical=lambda cfg:{key:value for key,value in cfg.items() if key not in ("revision","status")}
    if any(physical(plan)!=physical(current) for plan in plans):
        raise ValueError("Compare runs of the same current N1 design")
    plan=json.loads((OUTPUT/"nail_manifest.json").read_text())
    current_step=OUTPUT/plan["analysis_step"]
    if any(digest(folder/"inputs/analysis.step")!=digest(current_step) for folder in (args.coarse,args.fine)):
        raise ValueError("Structural inputs do not match the current bonded assembly")
    coarse=json.loads((args.coarse/"screen.json").read_text())
    fine=json.loads((args.fine/"screen.json").read_text())
    if [row["id"] for row in coarse["cases"]]!=[row["id"] for row in fine["cases"]]:
        raise ValueError("Structural case sets differ")
    for name,patch in fine["patches"].items():
        other=coarse["patches"][name]
        if patch["radius_mm"]!=other["radius_mm"] or np.linalg.norm(np.asarray(patch["centroid_native_mm"])-other["centroid_native_mm"])>1e-6:
            raise ValueError("Convergence comparison changed the physical contact patches")
    with execution(ROOT/"build/records","Compare N1 mesh convergence and plot the actual metal/prong calculations, keeping physical qualification separate") as record:
        maximum_change=0;maximum_patch=0;rows=[]
        for a,b in zip(coarse["cases"],fine["cases"]):
            if b["kind"]!="normal_20n":
                continue
            delta=abs(a["max_leading_tip_normal_motion_mm"]-b["max_leading_tip_normal_motion_mm"])
            relative=delta/max(b["max_leading_tip_normal_motion_mm"],1e-12)
            patch_delta=max(np.linalg.norm(np.asarray(a["patch_mean_displacement_native_mm"][name])-value)
                          for name,value in b["patch_mean_displacement_native_mm"].items())
            patch_relative=float(patch_delta/max(b["max_leading_tip_motion_magnitude_mm"],1e-12))
            maximum_change=max(maximum_change,relative);maximum_patch=max(maximum_patch,patch_relative)
            rows.append({"id":b["id"],"normal_motion_change_mm":delta,"relative_normal_motion_change":relative,
                         "patch_motion_change_mm":float(patch_delta),"relative_patch_motion_change":patch_relative})
        limit=current["structural_screen"]["motion_convergence_relative_limit"]
        convergence={"normal_cases":rows,"maximum_relative_change":maximum_change,
                     "maximum_patch_relative_change":maximum_patch,"relative_limit":limit,
                     "passed":bool(maximum_change<=limit and maximum_patch<=limit)}
        report={"schema":"yam-nail-structural-review/1","evidence_kind":"linear_FEA_screen_only",
                "physical_specimens_tested":0,"force_accuracy_qualified":False,
                "convergence":convergence,
                "max_leading_tip_motion_mm_at_20n":fine["max_leading_tip_normal_motion_mm_at_20n"],
                "provisional_target_mm":fine["provisional_motion_target_mm"],"motion_screen_met":fine["motion_screen_met"],
                "scope":fine["scope"],"limits":fine["limits"],
                "fine_mesh":fine["mesh"],"cases":fine["cases"],
                "inputs":[{"directory":str(folder.resolve().relative_to(ROOT)),"screen_sha256":digest(folder/"screen.json")}
                          for folder in (args.coarse,args.fine)]}
        (OUTPUT/"nail_structural_review.json").write_text(json.dumps(report,indent=2)+"\n")
        normal=[row for row in fine["cases"] if row["kind"]=="normal_20n"]
        labels=[row["id"].replace("_20n","").replace("_"," ") for row in normal]
        fig,axes=plt.subplots(1,2,figsize=(12,5),layout="constrained")
        x=np.arange(len(normal))
        axes[0].bar(x,[row["max_leading_tip_normal_motion_mm"] for row in normal],color="#438f81")
        axes[0].axhline(fine["provisional_motion_target_mm"],ls="--",color="#aa763e",label="0.1 mm provisional screen")
        axes[0].set_ylabel("Calculated leading-tip normal motion (mm)")
        axes[0].set_title("20 N normal loads · metal assembly only")
        axes[0].legend(fontsize=8)
        axes[1].bar(x,[row["max_integration_point_von_mises_mpa"] for row in normal],color="#8d85a7")
        axes[1].set_ylabel("Calculated integration-point von Mises stress (MPa)")
        axes[1].set_title("Model stress · no strength or fatigue rating")
        for ax in axes:
            ax.set_xticks(x,labels,rotation=25,ha="right");ax.grid(axis="y",alpha=.2)
        fig.suptitle("N1 structural screen · fixed supports and ideal bonded metal joints")
        fig.savefig(OUTPUT/"nail_structural_screen.svg")
        fig.savefig(OUTPUT/"nail_structural_screen.png",dpi=145)
        plt.close(fig)
        record["review"]={"convergence":convergence,"motion_screen_met":fine["motion_screen_met"],
                          "max_tip_motion_mm":fine["max_leading_tip_normal_motion_mm_at_20n"]}
        print(json.dumps(record["review"],indent=2))
        if not convergence["passed"]:
            raise ValueError("N1 displacement convergence has not yet been established")


if __name__=="__main__":
    main()
