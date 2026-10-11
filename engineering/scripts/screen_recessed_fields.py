#!/usr/bin/python3
"""Compare B2/B3 magnetic range over explicit sampled motion and tolerance states."""

from datetime import datetime,timezone
import itertools
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"]=str(ROOT/"build/engineering/tools/cache")
os.environ["OPENBLAS_NUM_THREADS"]="1"
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from model_b1_field import cylinder_field
from prototype_cad import digest
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/prototypes/recessed"
# Melexis 3901090393 rev012, Table 17: HALLCONF=0xC, RES=1,
# TCMP off, nominal values at 25 C. Higher GAIN_SEL is more sensitive.
LSB_RES1_UT={
    7:(.300,.300,.484),6:(.401,.401,.645),5:(.501,.501,.807),4:(.601,.601,.968),
    3:(.751,.751,1.210),2:(.901,.901,1.452),1:(1.202,1.202,1.936),0:(1.502,1.502,2.420),
}


def axis_for(tilt_y,tilt_z):
    y,z=np.deg2rad([tilt_y,tilt_z])
    return np.array([np.cos(y)*np.cos(z),np.cos(y)*np.sin(z),-np.sin(y)])


def analyze_plane(plane,cfg,spec,b1,magnet):
    nominal=np.asarray([row["die_center_native_mm"] for row in b1["sensor_poses"]],dtype=float)
    nominal[:,0]+=plane-b1["sensor_pcb_top_x_mm"]
    rotations=np.asarray([row["rotation_sensor_to_native"] for row in b1["sensor_poses"]],dtype=float)
    error=spec["magnet_position_error_mm"]+spec["sensor_position_error_mm"]
    offsets=np.array(list(itertools.product(spec["relative_position_grid"],repeat=3)),dtype=float)*error
    observers=(nominal[:,None,:]+offsets[None,:,:]).reshape(-1,3)
    all_min=[];all_max=[];worst=[];nominal_fields=[];normal_responses=[]
    diameters=[magnet["diameter_mm"]-spec["magnet_diameter_tolerance_mm"],
               magnet["diameter_mm"],magnet["diameter_mm"]+spec["magnet_diameter_tolerance_mm"]]
    thickness=[magnet["thickness_mm"]-spec["magnet_thickness_tolerance_mm"],
               magnet["thickness_mm"],magnet["thickness_mm"]+spec["magnet_thickness_tolerance_mm"]]
    sizes=[(diameters[1],thickness[1]),*itertools.product((diameters[0],diameters[2]),(thickness[0],thickness[2]))]
    tilt=cfg["motion_screen"]["magnet_axis_tilt_deg"]
    tilt_pairs=list(itertools.product((-tilt,0.,tilt),repeat=2))
    for source_index,entry in enumerate(b1["magnet_locations"]):
        center=np.asarray(entry["native_xyz_mm"],dtype=float)
        angle=np.deg2rad(entry["front_tangent_angle_deg"])
        inward=np.array([0,-np.sin(angle),np.cos(angle)])
        low=np.full((5,3),np.inf);high=np.full((5,3),-np.inf)
        low_case={};high_case={}
        for side,amount,angles,size in itertools.product(cfg["motion_screen"]["side_bulge_native_x_mm"],
                cfg["motion_screen"]["magnet_inward_motion_mm"],tilt_pairs,sizes):
            shifted=center+np.array([side,0,0])+amount*inward
            axis=axis_for(*angles)
            native=cylinder_field(observers,shifted,axis.copy(),size[0]/2,size[1],magnet["remanence_nominal_t"],
                                  radial_order=spec["coarse_quadrature"][0],angular_order=spec["coarse_quadrature"][1])*1e6
            local=np.einsum("hji,hpj->hpi",rotations,native.reshape(5,len(offsets),3))
            for sensor in range(5):
                for coordinate in range(3):
                    values=local[sensor,:,coordinate]
                    imin=int(values.argmin());imax=int(values.argmax())
                    for extreme,index,target,records,condition in (
                        (float(values[imin]),imin,low,low_case,float(values[imin])<low[sensor,coordinate]),
                        (float(values[imax]),imax,high,high_case,float(values[imax])>high[sensor,coordinate])):
                        if condition:
                            target[sensor,coordinate]=extreme
                            records[(sensor,coordinate)]={"sensor":sensor,"component":coordinate,
                                "observer_native_mm":(nominal[sensor]+offsets[index]).tolist(),
                                "magnet_center_native_mm":shifted.tolist(),"magnet_axis_native":axis.tolist(),
                                "diameter_mm":size[0],"thickness_mm":size[1],"coarse_component_ut":extreme}
        # Positive remanence uncertainty expands each signed interval.
        bound=spec["remanence_relative_bound"]
        low=np.where(low<0,low*(1+bound),low*(1-bound))
        high=np.where(high>0,high*(1+bound),high*(1-bound))
        all_min.append(low);all_max.append(high)
        worst.extend([{**case,"magnet":source_index} for case in (*low_case.values(),*high_case.values())])
        field=cylinder_field(nominal,center,[1.,0,0],magnet["diameter_mm"]/2,magnet["thickness_mm"],
                             magnet["remanence_nominal_t"])*1e6
        nominal_fields.append(field)
        moved=cylinder_field(nominal,center+.1*inward,[1.,0,0],magnet["diameter_mm"]/2,
                             magnet["thickness_mm"],magnet["remanence_nominal_t"])*1e6
        normal_responses.append(float(np.linalg.norm(moved[source_index]-field[source_index])))
        print(f"PCB X={plane:.3f}: sampled M{source_index}",flush=True)
    quadrature_error=0.
    for case in worst:
        field=cylinder_field([case["observer_native_mm"]],case["magnet_center_native_mm"],
            case["magnet_axis_native"],case["diameter_mm"]/2,case["thickness_mm"],
            magnet["remanence_nominal_t"],radial_order=spec["fine_quadrature"][0],
            angular_order=spec["fine_quadrature"][1])[0]*1e6
        local=rotations[case["sensor"]].T@field
        difference=abs(float(local[case["component"]])-case["coarse_component_ut"])
        case["fine_component_ut"]=float(local[case["component"]])
        case["quadrature_difference_ut"]=difference
        quadrature_error=max(quadrature_error,difference)
    low=np.sum(all_min,axis=0);high=np.sum(all_max,axis=0)
    peak=np.maximum(np.abs(low),np.abs(high))
    external=spec["external_field_native_axis_bound_ut_assumed"]*np.sum(np.abs(rotations),axis=1)
    physical_bound=peak+external
    norm_bound=np.linalg.norm(physical_bound,axis=1)
    axis_error=2*np.sin(np.deg2rad(spec["sensor_axis_error_deg_assumed"])/2)*norm_bound
    required=(physical_bound+axis_error[:,None])*(1+spec["electrical_scale_margin_assumed"])+spec["electrical_offset_allowance_ut_assumed"]
    gains=[]
    for gain,lsb in LSB_RES1_UT.items():
        fraction=required/(np.asarray(lsb)*32767)
        gains.append({"gain_sel":gain,"lsb_ut":list(lsb),
                      "peak_fraction_by_sensor":fraction.max(axis=1).tolist(),
                      "maximum_fraction":float(fraction.max()),
                      "sampled_range_screen_met":bool(fraction.max()<=spec["digital_range_fraction_limit"])})
    qualified=[row for row in gains if row["sampled_range_screen_met"]]
    return {"pcb_plane_native_x_mm":plane,
            "nominal_field_native_ut":np.sum(nominal_fields,axis=0).tolist(),
            "nominal_own_response_to_0p1mm_inward_ut":normal_responses,
            "summed_sampled_component_intervals_ut":{"low":low.tolist(),"high":high.tolist()},
            "physical_field_component_bound_with_external_ut":physical_bound.tolist(),
            "required_nominal_output_component_bound_ut":required.tolist(),
            "maximum_physical_vector_bound_ut":float(norm_bound.max()),
            "imc_screen_met":bool(norm_bound.max()<=spec["imc_saturation_onset_ut"]*spec["imc_range_fraction_limit"]),
            "gain_options":gains,"highest_gain_passing_sampled_screen":qualified[0]["gain_sel"] if qualified else None,
            "quadrature_max_difference_ut":quadrature_error,"limiting_source_samples":worst}


def main():
    cfg_path=ROOT/"engineering/designs/recessed.json"
    assumptions=ROOT/"engineering/designs/recessed_field_screen.json"
    cfg=json.loads(cfg_path.read_text());spec=json.loads(assumptions.read_text())
    if cfg["readout"]["hallconf"]!=12 or cfg["readout"]["resolution"]!=1 or cfg["readout"]["temperature_compensation"]:
        raise ValueError("This screen supports only the documented HALLCONF/RES/TCMP combination")
    b1_path=ROOT/"engineering/release/b1/b1_manifest.json"
    b1=json.loads(b1_path.read_text())
    magnet=json.loads((ROOT/"engineering/designs/b1.json").read_text())["magnet"]
    folder=OUTPUT/"magnetic_runs"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records","Evaluate B3 field range using prescribed motions, dimension/position cases and independent-source intervals; do not infer newtons or permitted travel") as record:
        folder.mkdir(parents=True,exist_ok=False)
        for path in (cfg_path,assumptions,b1_path,Path(__file__)):
            shutil.copyfile(path,folder/path.name)
        planes=[b1["sensor_pcb_top_x_mm"],cfg["mechanical"]["pcb_component_plane_native_x_mm"]]
        results=[analyze_plane(plane,cfg,spec,b1,magnet) for plane in planes]
        maximum_error=max(row["quadrature_max_difference_ut"] for row in results)
        report={"schema":"yam-b3-magnetic-range/1","evidence_kind":"sampled_magnetic_model",
                "physical_specimens_tested":0,"force_accuracy_qualified":False,
                "assumptions":spec,"planes":results,
                "quadrature_check":{"maximum_difference_ut":maximum_error,
                                    "limit_ut":spec["quadrature_difference_limit_ut"],
                                    "passed":bool(maximum_error<=spec["quadrature_difference_limit_ut"])},
                "source_hashes":{str(path.relative_to(ROOT)):digest(path) for path in
                    (cfg_path,assumptions,b1_path,ROOT/"engineering/designs/b1.json",
                     Path(__file__),ROOT/"engineering/scripts/model_b1_field.py")},
                "limits":spec["notes"]+[
                    "This interval contains combinations of sampled source states; no continuous-domain or hardware guarantee is claimed.",
                    "The geometric motion cases are not a prediction of TPU movement under 20 N.",
                    "Actual field bias, repeatability, force calibration and contact confidence require physical data."]}
        (folder/"screen.json").write_text(json.dumps(report,indent=2)+"\n")
        (OUTPUT/"recessed_magnetic_review.json").write_text(json.dumps(report,indent=2)+"\n")
        fig,axes=plt.subplots(1,2,figsize=(12,5),layout="constrained")
        for result,label,color in zip(results,("B2 original plane","B3 recessed plane"),("#8d9f91","#307e78")):
            axes[0].plot(range(4),result["nominal_own_response_to_0p1mm_inward_ut"],marker="o",label=label,color=color)
            axes[1].plot([row["gain_sel"] for row in result["gain_options"]],
                         [row["maximum_fraction"] for row in result["gain_options"]],marker="o",label=label,color=color)
        axes[0].set_xticks(range(4),[f"S{i}" for i in range(4)])
        axes[0].set_ylabel("Calculated field response (µT)")
        axes[0].set_title("Assumed 0.1 mm local inward motion")
        axes[1].axhline(spec["digital_range_fraction_limit"],ls="--",color="#a46c36",label="80% sampled-range screen")
        axes[1].set_xlabel("GAIN_SEL · higher is more sensitive")
        axes[1].set_ylabel("Required output / configured signed range")
        axes[1].set_title("Sampled motion/tolerance envelope + allowances")
        for ax in axes:
            ax.grid(alpha=.2);ax.legend(fontsize=8)
        fig.suptitle("B3 magnetic calculation · no force calibration or travel rating")
        fig.savefig(OUTPUT/"recessed_magnetic_screen.svg")
        fig.savefig(OUTPUT/"recessed_magnetic_screen.png",dpi=150)
        plt.close(fig)
        record["summary"]=[{"plane_mm":row["pcb_plane_native_x_mm"],
                            "gain_candidate":row["highest_gain_passing_sampled_screen"],
                            "imc_screen_met":row["imc_screen_met"],
                            "quadrature_error_ut":row["quadrature_max_difference_ut"]} for row in results]
        print(json.dumps(record["summary"],indent=2))
        if not report["quadrature_check"]["passed"]:
            raise ValueError("Recessed magnetic numerical quadrature has not converged")


if __name__=="__main__":
    main()
