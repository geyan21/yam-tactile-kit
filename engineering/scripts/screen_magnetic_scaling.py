#!/usr/bin/python3
"""Study magnetic tolerance, zeroing and reference limits at the released B1 geometry."""

import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(ROOT/"engineering/software"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from model_b1_field import cylinder_field
from b1_protocol import LSB_UT
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/architecture"


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    spec=json.loads((ROOT/"engineering/designs/architecture_study.json").read_text())["magnetic_screen"]
    path=ROOT/"engineering/release/b1/b1_manifest.json"
    plan=json.loads(path.read_text())
    magnet_spec=json.loads((ROOT/"engineering/designs/b1.json").read_text())["magnet"]
    centers=np.array([m["native_xyz_mm"] for m in plan["magnet_locations"]])
    sensors=np.array([s["die_center_native_mm"] for s in plan["sensor_poses"]])
    direction=[]
    for magnet in plan["magnet_locations"]:
        angle=np.deg2rad(magnet["front_tangent_angle_deg"])
        direction.append([0,-np.sin(angle),np.cos(angle)])
    direction=np.array(direction)
    axes=np.tile([1.,0,0],(4,1))

    def fields(c,p,a,br):
        return np.array([cylinder_field(p,center,axis,magnet_spec["diameter_mm"]/2,magnet_spec["thickness_mm"],remanence,
                                       radial_order=8,angular_order=24)*1e6
                         for center,axis,remanence in zip(c,a,br)])

    def motion(c,p,a,br,i):
        moved=c.copy();moved[i]+=spec["assumed_inward_motion_mm"]*direction[i]
        return fields(moved,p,a,br).sum(axis=0)-fields(c,p,a,br).sum(axis=0)

    with execution(ROOT/"build/records","Calculate hypothetical magnetic assembly/interference sensitivity; no force conversion or fabricated measurements") as record:
        br=np.full(4,magnet_spec["remanence_nominal_t"])
        baseline=fields(centers,sensors,axes,br).sum(axis=0)
        nominal=np.array([motion(centers,sensors,axes,br,i) for i in range(4)])
        rng=np.random.default_rng(spec["seed"])
        cases=[]
        for bound in spec["position_error_bounds_mm"]:
            offsets=[];ratios=[]
            for _ in range(spec["realizations_per_case"]):
                c=centers+rng.uniform(-bound,bound,centers.shape)
                p=sensors+rng.uniform(-bound,bound,sensors.shape)
                a=axes.copy()
                a[:,1:]=np.tan(np.deg2rad(rng.uniform(-spec["axis_tilt_bound_deg"],spec["axis_tilt_bound_deg"],(4,2))))
                a/=np.linalg.norm(a,axis=1)[:,None]
                strengths=br*(1+rng.uniform(-spec["magnet_remanence_relative_bound"],
                                           spec["magnet_remanence_relative_bound"],4))
                offsets.append(float(np.linalg.norm(fields(c,p,a,strengths).sum(axis=0)-baseline)))
                # Per-unit unloaded zero is removed here; the remaining gain
                # variation therefore cannot be fixed by zeroing alone.
                ratios.append([float(np.linalg.norm(motion(c,p,a,strengths,i)[i])/np.linalg.norm(nominal[i,i]))
                               for i in range(4)])
            ratios=np.array(ratios)
            cases.append({"position_error_bound_mm":bound,
                          "baseline_vector_offset_ut_percentiles":np.percentile(offsets,[5,50,95]).tolist(),
                          "zeroed_own_response_ratio_percentiles":np.percentile(ratios,[5,50,95],axis=0).tolist(),
                          "ratios_for_plot":ratios.tolist()})
        uniform=np.tile(spec["uniform_field_change_ut"],(5,1))
        uniform_corrected=uniform[:4]-uniform[4]
        # Symmetric, traceless gradient: Bx=g*(y-yref), By=g*(x-xref).
        # This is locally divergence- and curl-free in the sampled air volume.
        g=spec["source_free_field_gradient_ut_per_mm"]
        gradient=np.column_stack((g*(sensors[:,1]-sensors[4,1]),
                                  g*(sensors[:,0]-sensors[4,0]),np.zeros(5)))
        residual=gradient[:4]-gradient[4]
        poses=np.array([s["rotation_sensor_to_native"] for s in plan["sensor_poses"]])
        original_plane=plan["sensor_pcb_top_x_mm"]
        gap_cases=[]
        for plane in [original_plane,*spec["alternative_pcb_plane_native_x_mm"]]:
            points=sensors.copy();points[:,0]+=plane-original_plane
            local=np.einsum("sji,sj->si",poses,fields(centers,points,axes,br).sum(axis=0))
            normal_response=[float(np.linalg.norm(motion(centers,points,axes,br,i)[i])) for i in range(4)]
            limits=np.array(LSB_UT)*32767
            gap_cases.append({
                "pcb_plane_native_x_mm":plane,
                "minimum_paired_center_distance_mm":float(min(np.linalg.norm(points[i]-centers[i]) for i in range(4))),
                "nominal_peak_fraction_of_configured_signed_range":float(np.max(np.abs(local)/limits)),
                "own_response_to_assumed_motion_ut":normal_response,
                "conservative_min_head_frame_clearance_mm":float(min(
                    plane-1.05-s["hard_frame_max_x_in_footprint_mm"] for s in plan["sensor_poses"])),
                "unloaded_component_to_tpu_side_gap_mm":plane-1.05,
                "scope":"Translation-only field/clearance screen, not a modified frame or permitted motion."})
        result={
            "evidence_kind":"hypothetical_calculation","b1_manifest_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "assumptions":spec,"nominal_own_response_to_0_1mm_ut":[float(np.linalg.norm(nominal[i,i])) for i in range(4)],
            "uniform_reference_residual_ut":np.linalg.norm(uniform_corrected,axis=1).tolist(),
            "gradient_reference_residual_ut":np.linalg.norm(residual,axis=1).tolist(),
            "reference_contact_coupling_ut":[float(np.linalg.norm(nominal[i,4])) for i in range(4)],
            "tolerance_cases":cases,
            "recessed_board_scenarios":gap_cases,
            "limits":["No measured placement error, noise, field gradient or installed motor field.",
                      "No mechanical force-to-motion model; cannot infer contact sensitivity in newtons.",
                      "Reference subtraction assumes perfect axis/gain matching and uniform field in its successful case.",
                      "Monte Carlo percentiles describe the chosen mathematical scenarios, not production yield.",
                      "No steel, hysteresis, creep, temperature or electronics model."]}
        (OUTPUT/"magnetic_scaling.json").write_text(json.dumps(result,indent=2)+"\n")
        fig,axes_plot=plt.subplots(1,2,figsize=(12,4.8),layout="constrained")
        for case in cases:
            values=np.array(case["ratios_for_plot"]).flatten()
            axes_plot[0].hist(values,bins=26,alpha=.5,label=f"position ±{case['position_error_bound_mm']:.2f} mm")
        axes_plot[0].axvline(1,color="#333",linestyle=":")
        axes_plot[0].set_xlabel("Response after per-unit zero / nominal response")
        axes_plot[0].set_ylabel("Hypothetical samples")
        axes_plot[0].set_title("Zeroing does not fix sensitivity variation")
        axes_plot[0].legend(fontsize=9)
        x=np.arange(4)
        axes_plot[1].bar(x-.18,result["nominal_own_response_to_0_1mm_ut"],.36,label="0.1 mm magnet motion")
        axes_plot[1].bar(x+.18,result["gradient_reference_residual_ut"],.36,label="5 µT/mm gradient after reference")
        axes_plot[1].set_xticks(x,labels=[f"S{i}" for i in range(4)])
        axes_plot[1].set_ylabel("Vector magnitude (µT)")
        axes_plot[1].set_title("One reference removes uniform fields only")
        axes_plot[1].legend(fontsize=8)
        fig.suptitle("Calculation at B1 geometry · imposed scenarios · no physical or force validation")
        fig.savefig(OUTPUT/"magnetic_scaling.svg")
        plt.close(fig)
        fig,axs=plt.subplots(1,2,figsize=(11,4.5),layout="constrained")
        planes=[case["pcb_plane_native_x_mm"] for case in gap_cases]
        for i in range(4):
            axs[0].plot(planes,[case["own_response_to_assumed_motion_ut"][i] for case in gap_cases],marker="o",label=f"S{i}")
        axs[0].set_xlabel("PCB plane, native X (mm) · lower brings heads inward")
        axs[0].set_ylabel("Response to assumed 0.1 mm motion (µT)")
        axs[0].legend(fontsize=9);axs[0].grid(alpha=.2)
        axs[1].plot(planes,[100*c["nominal_peak_fraction_of_configured_signed_range"] for c in gap_cases],marker="o")
        axs[1].axhline(100,ls=":",color="#ad5b35",label="Configured signed output range")
        axs[1].set_xlabel("PCB plane, native X (mm)")
        axs[1].set_ylabel("Largest resting-axis field / configured range (%)")
        axs[1].legend(fontsize=8);axs[1].grid(alpha=.2)
        fig.suptitle("Recessing the board: more signal, less clearance and range margin\nCalculation only; no new hard-frame design or 20 N travel proof")
        fig.savefig(OUTPUT/"magnetic_gap.svg");plt.close(fig)
        record["result"]={key:result[key] for key in ("nominal_own_response_to_0_1mm_ut","gradient_reference_residual_ut")}
        print(json.dumps(record["result"],indent=2))
        for case in cases:
            print("Position bound",case["position_error_bound_mm"],"mm; own-response 5/50/95% ratios:",case["zeroed_own_response_ratio_percentiles"])
        print("Recessed-board screening:",json.dumps(gap_cases,indent=2))


if __name__=="__main__":main()
