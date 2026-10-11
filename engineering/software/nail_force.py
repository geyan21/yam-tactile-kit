#!/usr/bin/python3
"""Fit and evaluate an N1 static force baseline from preserved physical holds."""

import argparse
from bisect import bisect_right
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
from c1_force import finite,digest,fit_numeric,predict as predict_bridge,level_coverage
from calibrate import isotonic_knots
from nail_protocol import decode,SETTINGS,LSB_V

REGIONS=("nail","CH2","CH3","CH4","CH5")


def soft_predict(curve,value):
    """A bounded monotonic interpolation; expose negative zero errors."""
    value=finite(value,"soft conductance")
    knots=curve["knots"];guard=finite(curve["signal_guard_us"],"signal guard")
    if guard<0 or value<knots[0][0]-guard or value>knots[-1][0]+guard:
        return None
    index=bisect_right([point[0] for point in knots],value)-1
    if index<0:
        index=0
        end=1
        while end<len(knots)-1 and knots[end][1]==knots[0][1]:
            end+=1
    elif index>=len(knots)-1:
        end=len(knots)-1
        index=end-1
        while index>0 and knots[index][1]==knots[end][1]:
            index-=1
    else:
        end=index+1
    x0,y0=knots[index];x1,y1=knots[end]
    return y0+(value-x0)*(y1-y0)/(x1-x0)


def predict_model(model,row):
    components=[predict_bridge(model["nail_bridge_model"],row["mean_counts"])]
    components += [soft_predict(model["soft_models"][region],value)
                   for region,value in zip(REGIONS[1:],row["mean_conductance_us"])]
    return (sum(components) if all(value is not None for value in components) else None),components


def load_trials(path,phase):
    manifest=json.loads(path.read_text())
    if manifest.get("schema")!="yam-nail-force-trials/1" or manifest.get("evidence_kind")!="physical" or manifest.get("phase")!=phase:
        raise ValueError("Select a physical N1 manifest with the correct train/test phase")
    if not manifest.get("specimen") or not manifest.get("geometry_sha256") or not manifest.get("reference_id"):
        raise ValueError("Specimen, geometry and reference identity are required")
    uncertainty=finite(manifest.get("reference_uncertainty_n"),"reference uncertainty")
    if not 0<uncertainty<=.05:
        raise ValueError("Use a documented reference uncertainty of 0.05 N or better")
    trials=manifest.get("trials")
    if not isinstance(trials,list) or not trials or len({trial["id"] for trial in trials})!=len(trials):
        raise ValueError("Use unique identifiers for every planned physical hold")
    if len({trial.get("recording_sha256") for trial in trials})!=len(trials):
        raise ValueError("Each independent hold needs a different recording")
    base=path.parent.resolve();rows=[];resistors=None
    for trial in trials:
        active=trial.get("active_regions")
        if not isinstance(active,list) or not active or len(set(active))!=len(active) or set(active)-set(REGIONS) or (phase=="train" and len(active)!=1):
            raise ValueError("Training loads one named region at a time; test rows name their actual active regions")
        recording=(base/trial["recording"]).resolve()
        if not recording.is_relative_to(base) or not recording.is_file() or recording.stat().st_size>32*1024*1024:
            raise ValueError("Select a local hold recording below the manifest directory, at most 32 MiB")
        if digest(recording)!=trial.get("recording_sha256"):
            raise ValueError("Recording hash mismatch: "+trial["id"])
        receipt_path=recording.with_suffix(recording.suffix+".receipt.json")
        receipt=json.loads(receipt_path.read_text())
        if receipt.get("schema")!="yam-nail-recording-receipt/1" or receipt.get("sha256")!=trial["recording_sha256"]:
            raise ValueError("Missing or mismatched N1 recording receipt")
        before=finite(trial["reference_before_n"],"reference before")
        after=finite(trial["reference_after_n"],"reference after")
        if min(before,after)<0 or max(before,after)>20.5:
            raise ValueError("The N1 static pilot covers positive normal forces through 20 N")
        reference=(before+after)/2
        flags=[];header=None;previous=None;first_us=None
        nail=[];soft=[{} for _ in range(4)];raw_soft=[{} for _ in range(4)];excitation=[]
        if receipt.get("capture_complete") is not True:
            flags.append("incomplete_capture")
        with recording.open() as stream:
            for line in stream:
                item=json.loads(line)
                if item.get("type")=="session":
                    if header is not None:
                        raise ValueError("Multiple sessions in one hold")
                    header=item
                elif item.get("type")=="startup_sync":
                    if nail:
                        flags.append("mid_hold_sync")
                elif "frame" in item:
                    try:
                        frame=item["frame"];observation=decode(frame)
                        if previous and (observation["seq"]!=previous["seq"]+1 or observation["device_us"]<=previous["device_us"]):
                            flags.append("sequence_or_time")
                        previous=observation
                        if first_us is None:
                            first_us=observation["device_us"]
                        values=frame["pull_down_ohm"]
                        if resistors is None:
                            resistors=list(values)
                        if values!=resistors:
                            raise ValueError("Pull-down resistors changed within the trial set")
                        if not observation["valid"]:
                            flags.extend(observation["flags"])
                            continue
                        nail.append(frame["adc_raw"])
                        excitation.append(observation["soft"]["excitation_v"])
                        for index,(start,value) in enumerate(zip(observation["soft"]["sample_start_us"],observation["soft"]["conductance_us"])):
                            if start>=first_us:
                                raw_index=index+2
                                signature=(frame["pressure"]["raw"][raw_index],
                                           frame["pressure"]["ready_observed_us"][raw_index],
                                           frame["pressure"]["configuration"][raw_index])
                                if start in raw_soft[index]:
                                    if raw_soft[index][start]!=signature:
                                        flags.append("inconsistent_cached_pressure_sample")
                                    # New references can change a derived value
                                    # while its raw pressure count is cached.
                                    continue
                                raw_soft[index][start]=signature
                                soft[index][start]=value
                    except (KeyError,TypeError) as error:
                        flags.append("invalid_frame:"+type(error).__name__)
                    except ValueError as error:
                        if "resistors changed" in str(error):
                            raise
                        flags.append("invalid_frame")
                elif "error" in item or "parse_error" in item or item.get("message",{}).get("type") in ("diagnostic","fatal"):
                    flags.append("recording_error_or_diagnostic")
        if header is None or header.get("schema")!="yam-nail-recording/1" or header.get("evidence_kind")!="physical_recording_unreviewed":
            raise ValueError("Electrical dummies and unidentified recordings cannot calibrate N1 force")
        if header.get("specimen")!=manifest["specimen"] or header.get("geometry_sha256")!=manifest["geometry_sha256"] or header.get("condition")!=trial["condition_id"]:
            raise ValueError("Mixed specimen, geometry or condition")
        if len(nail)<200 or any(len(values)<50 for values in soft):
            flags.append("short_hold")
        if abs(before-after)>max(.05,.02*max(reference,.2)):
            flags.append("reference_not_stationary")
        rows.append({"id":trial["id"],"condition_id":trial["condition_id"],"active_regions":active,
                     "recording_sha256":trial["recording_sha256"],"reference_n":reference,
                     "reference_bound_n":uncertainty+abs(before-after)/2,
                     "mean_counts":[statistics.fmean(pair[index] for pair in nail) for index in range(2)] if nail else None,
                     "mean_conductance_us":[statistics.fmean(values.values()) if values else None for values in soft],
                     "conductance_stdev_us":[statistics.pstdev(values.values()) if len(values)>1 else None for values in soft],
                     "mean_excitation_v":statistics.fmean(excitation) if excitation else None,
                     "nail_frames":len(nail),"distinct_pressure_samples":[len(values) for values in soft],
                     "available":not flags,"flags":sorted(set(flags))})
    return manifest,rows,resistors


def fit_model(manifest,rows,resistors):
    if any(not row["available"] for row in rows):
        raise ValueError("Keep failed attempts and collect a complete calibration plan before fitting")
    groups={region:[row for row in rows if row["active_regions"]==[region]] for region in REGIONS}
    coverage={}
    for region,selected in groups.items():
        levels,complete=level_coverage(selected,manifest)
        if not complete or max(row["reference_n"] for row in selected)<20:
            raise ValueError("Complete all force levels and repetitions for "+region)
        coverage[region]=levels
    selected=groups["nail"]
    model={"nail_bridge_model":fit_numeric([row["mean_counts"] for row in selected],[row["reference_n"] for row in selected]),
           "soft_models":{},"training_force_level_coverage":coverage}
    for index,region in enumerate(REGIONS[1:]):
        selected=groups[region]
        knots=isotonic_knots([(row["mean_conductance_us"][index],row["reference_n"]) for row in selected])
        noise=3*max(row["conductance_stdev_us"][index] for row in selected)
        quantization=max(LSB_V*1e6*(1+row["mean_conductance_us"][index]*resistors[index]/1e6)**2/
                            (resistors[index]*row["mean_excitation_v"]) for row in selected)
        model["soft_models"][region]={"knots":knots,"signal_guard_us":max(noise,quantization),
                                      "guard_basis":"Larger of three times observed within-hold standard deviation and one ADC-count conductance equivalent."}
    errors=[];unavailable=0
    for row in rows:
        estimate,_=predict_model(model,row)
        if estimate is None:
            unavailable+=1
        else:
            errors.append(estimate-row["reference_n"])
    rmse=math.sqrt(statistics.fmean(value*value for value in errors)) if errors else None
    model.update({"training_holds":len(rows),"training_rmse_n":rmse,"training_unavailable_predictions":unavailable,
                  "training_rmse_target_met":unavailable==0 and rmse is not None and rmse<=.5,
                  "training_recordings":[row["recording_sha256"] for row in rows]})
    return model


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("fit","evaluate"))
    parser.add_argument("--trials",type=Path,required=True)
    parser.add_argument("--model",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error("Keep earlier reports and choose a new output")
    manifest,rows,resistors=load_trials(args.trials,"train" if args.action=="fit" else "test")
    common={"evidence_kind":"physical","specimen":manifest["specimen"],"geometry_sha256":manifest["geometry_sha256"],
            "settings":SETTINGS,"pull_down_ohm":resistors,"continuity_ohm":100000,
            "reference_id":manifest["reference_id"],"reference_uncertainty_n":manifest["reference_uncertainty_n"],
            "created_utc":datetime.now(timezone.utc).isoformat(),"trial_manifest_sha256":digest(args.trials),
            "robot_gripper_qualified":False,"dynamic_force_accuracy_qualified":False,"contact_reliability_qualified":False,
            "scope":"Additive baseline for means of stationary normal-force holds: one two-bridge nail model plus four individual TPU curves. Inactive-channel bias and mixed-contact error remain in validation."}
    if args.action=="fit":
        report={"schema":"yam-nail-force-model/1",**common,**fit_model(manifest,rows,resistors)}
    else:
        if args.model is None:
            parser.error("--model is required for evaluation")
        model=json.loads(args.model.read_text())
        if model.get("schema")!="yam-nail-force-model/1" or model.get("evidence_kind")!="physical" or model.get("settings")!=SETTINGS:
            raise ValueError("Select a physical N1 calibration model")
        if model["geometry_sha256"]!=manifest["geometry_sha256"] or model["pull_down_ohm"]!=resistors:
            raise ValueError("Geometry or electronics changed; recalibrate this configuration")
        if model["specimen"]!=manifest["specimen"] and manifest.get("transfer_experiment") is not True:
            raise ValueError("A different specimen needs an explicitly declared transfer experiment")
        if any(row["recording_sha256"] in model["training_recordings"] for row in rows):
            raise ValueError("Calibration recordings cannot be reused for held-out validation")
        errors=[]
        for row in rows:
            if row["available"]:
                estimate,components=predict_model(model,row)
                row["component_forces_n"]=dict(zip(REGIONS,components))
                row["predicted_n"]=estimate
                if estimate is None:
                    row["available"]=False;row["flags"].append("outside_calibrated_signal_guard")
                    continue
                error=estimate-row["reference_n"]
                row.update({"error_n":error,"error_with_reference_bound_n":abs(error)+row["reference_bound_n"],
                            "individual_error_rule_met":abs(error)+row["reference_bound_n"]<=max(.5,.1*row["reference_n"])})
                errors.append(error)
        required=set(manifest.get("required_condition_ids",[]))
        coverage=bool(required);by_condition={};qualified_regions=set();mixed=False
        for condition in sorted(required):
            selected=[row for row in rows if row["condition_id"]==condition]
            levels,complete=level_coverage(selected,manifest)
            patterns={tuple(sorted(row["active_regions"])) for row in selected}
            complete=complete and max((row["reference_n"] for row in selected),default=0)>=20 and len(patterns)==1
            coverage=coverage and complete
            by_condition[condition]=levels
            if complete:
                pattern=next(iter(patterns))
                if len(pattern)==1:
                    qualified_regions.add(pattern[0])
                else:
                    mixed=True
        all_regions=set(REGIONS)<=qualified_regions
        rmse=math.sqrt(statistics.fmean(value*value for value in errors)) if errors else None
        report={"schema":"yam-nail-static-validation/1",**common,"model_sha256":digest(args.model),
                "training_specimen":model["specimen"],"transfer_experiment":manifest.get("transfer_experiment",False),
                "held_out_holds":len(rows),"unavailable_holds":len(rows)-len(errors),
                "declared_condition_range_coverage":coverage,"force_level_coverage_by_condition":by_condition,
                "all_sensor_regions_have_complete_single_region_tests":all_regions,
                "complete_mixed_contact_test":mixed,
                "rmse_n":rmse,"max_abs_error_n":max(map(abs,errors)) if errors else None,
                "trials":rows,"passed_static_screen":coverage and all_regions and mixed and len(errors)==len(rows)
                    and rmse is not None and rmse<=.5 and model.get("training_rmse_target_met",False)
                    and all(row.get("individual_error_rule_met",False) for row in rows)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report,stream,indent=2,allow_nan=False);stream.write("\n")
    print(json.dumps({key:report[key] for key in report if key in ("schema","training_holds","training_rmse_n","rmse_n","unavailable_holds","passed_static_screen")},indent=2))


if __name__=="__main__":
    with execution(ROOT/"build/records","Fit or validate an N1 static baseline from preserved physical recordings; no synthetic force coefficients or actuator control"):
        main()
