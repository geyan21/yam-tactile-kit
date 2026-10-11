#!/usr/bin/python3
"""Fit/evaluate a specimen-specific C1 static force model from preserved physical holds."""

import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution

from c1_protocol import decode,SETTINGS

PILOT_FORCE_LEVELS_N = (0,.2,.5,1,2,5,10,15,20)


def finite(value,name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError("Finite numerical value required: "+name)
    return float(value)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fit_numeric(features,forces):
    """Two-feature least squares with explicit scaling and a conditioning gate."""
    if len(features)!=len(forces) or len(features)<6:
        raise ValueError("At least six independent calibration holds required")
    if any(not isinstance(row,(tuple,list)) or len(row)!=2 for row in features):
        raise ValueError("Every calibration hold needs both bridge features")
    n = len(forces)
    a = [finite(v[0],"bridge A") for v in features]
    b = [finite(v[1],"bridge B") for v in features]
    f = [finite(v,"reference force") for v in forces]
    ma,mb,mf = sum(a)/n,sum(b)/n,sum(f)/n
    ca = [v-ma for v in a];cb = [v-mb for v in b];cf = [v-mf for v in f]
    sa = math.sqrt(sum(v*v for v in ca)/n);sb = math.sqrt(sum(v*v for v in cb)/n)
    if min(sa,sb)<=0:
        raise ValueError("Both strain stations must vary during calibration")
    correlation = sum(x*y for x,y in zip(ca,cb))/(n*sa*sb)
    if abs(correlation)>=1:
        raise ValueError("Calibration is rank-deficient; vary the contact lever as well as force")
    condition = (1+abs(correlation))/(1-abs(correlation))
    if condition>1000:
        raise ValueError("Calibration is ill-conditioned; include independent left/right lever loads")
    va = sum(x*y for x,y in zip(ca,cf))/(n*sa)
    vb = sum(x*y for x,y in zip(cb,cf))/(n*sb)
    w0 = (va-correlation*vb)/(1-correlation*correlation)/sa
    w1 = (vb-correlation*va)/(1-correlation*correlation)/sb
    offset = mf-w0*ma-w1*mb
    return {"offset_n":offset,"weights_n_per_count":[w0,w1],"scaled_condition_number":condition}


def predict(model,counts):
    if not isinstance(counts,(tuple,list)) or len(counts)!=2 or len(model.get("weights_n_per_count",[]))!=2:
        raise ValueError("A two-bridge model and feature pair are required")
    return finite(model["offset_n"],"model offset")+sum(
        finite(w,"model weight")*finite(x,"bridge feature") for w,x in zip(model["weights_n_per_count"],counts))


def level_coverage(rows,manifest):
    levels = manifest.get("required_force_levels_n",list(PILOT_FORCE_LEVELS_N))
    repetitions = manifest.get("minimum_holds_per_level",3)
    if not isinstance(levels,list) or not levels or type(repetitions) is not int or repetitions<3:
        raise ValueError("Declare force levels and at least three independent holds per level")
    levels = [finite(value,"required force level") for value in levels]
    if len(set(levels))!=len(levels) or any(value<0 or value>20 for value in levels):
        raise ValueError("Declare distinct force levels within 0..20 N")
    if not all(any(abs(value-target)<1e-9 for value in levels) for target in PILOT_FORCE_LEVELS_N):
        raise ValueError("The static pilot must include every required 0..20 N force level")
    counts = []
    for level in levels:
        tolerance = max(.05,.03*level)
        count = sum(row["available"] and abs(row["reference_n"]-level)<=tolerance for row in rows)
        counts.append({"target_n":level,"holds":count,"required":repetitions})
    return counts,all(row["holds"]>=row["required"] for row in counts)


def load_trials(path,phase):
    manifest = json.loads(path.read_text())
    if manifest.get("schema")!="yam-c1-force-trials/1" or manifest.get("evidence_kind")!="physical" or manifest.get("phase")!=phase:
        raise ValueError("A physical, phase-specific trial manifest is required")
    if not manifest.get("reference_id") or not manifest.get("specimen") or not manifest.get("geometry_sha256"):
        raise ValueError("Reference, specimen and geometry identity are required")
    uncertainty = finite(manifest.get("reference_uncertainty_n"),"reference uncertainty")
    if not 0<uncertainty<=.05:
        raise ValueError("Use a documented reference uncertainty of 0.05 N or better")
    trials = manifest.get("trials")
    if not isinstance(trials,list) or not trials or len({t["id"] for t in trials})!=len(trials):
        raise ValueError("Nonempty, uniquely identified planned trials are required")
    if len({t.get("recording_sha256") for t in trials})!=len(trials):
        raise ValueError("Each independent hold needs its own recording; duplicates cannot increase sample counts")
    base = path.parent.resolve();rows = []
    for trial in trials:
        recording = (base/trial["recording"]).resolve()
        if not recording.is_relative_to(base) or not recording.is_file() or recording.stat().st_size>32*1024*1024:
            raise ValueError("Recordings must be existing local files below the trial manifest, at most 32 MiB")
        if digest(recording)!=trial.get("recording_sha256"):
            raise ValueError("Recording hash mismatch: "+trial["id"])
        before = finite(trial["reference_before_n"],"reference before")
        after = finite(trial["reference_after_n"],"reference after")
        reference = (before+after)/2
        if min(before,after)<0 or max(before,after)>20.5:
            raise ValueError("This screen covers positive normal forces through 20 N")
        header = None;values = [];flags = [];previous = None
        with recording.open() as stream:
            for line in stream:
                item = json.loads(line)
                if item.get("type")=="session":
                    if header is not None:
                        raise ValueError("Multiple recording sessions in one trial")
                    header = item
                elif item.get("type")=="startup_sync":
                    if values:
                        flags.append("mid_trial_sync")
                elif "frame" in item:
                    try:
                        frame = item["frame"]
                        observation = decode(frame)
                        if previous and (observation["seq"]!=previous["seq"]+1 or observation["device_us"]<=previous["device_us"]):
                            flags.append("sequence_or_time")
                        previous = observation
                        if not observation["valid"]:
                            flags.extend(observation["flags"])
                        else:
                            values.append(frame["adc_raw"])
                    except (ValueError,KeyError,TypeError):
                        flags.append("invalid_frame")
                elif item.get("message",{}).get("type")=="diagnostic":
                    flags.append("diagnostic_during_hold")
                elif "error" in item or "parse_error" in item or item.get("message",{}).get("type")=="fatal":
                    flags.append("recording_error")
        if header is None or header.get("schema")!="yam-c1-recording/1" or header.get("evidence_kind")!="physical_recording_unreviewed":
            raise ValueError("Missing C1 raw recording identity")
        if header.get("specimen")!=manifest["specimen"] or header.get("geometry_sha256")!=manifest["geometry_sha256"]:
            raise ValueError("Mixed specimen or geometry")
        if header.get("condition")!=trial["condition_id"]:
            raise ValueError("Recording condition does not match the declared trial")
        if len(values)<200:
            flags.append("short_hold")
        if abs(after-before)>max(.05,.02*max(reference,.2)):
            flags.append("reference_not_stationary")
        mean = [sum(v[i] for v in values)/len(values) for i in range(2)] if values else None
        rows.append({"id":trial["id"],"condition_id":trial["condition_id"],"recording_sha256":trial["recording_sha256"],
                     "reference_n":reference,"reference_bound_n":uncertainty+abs(after-before)/2,
                     "mean_counts":mean,"samples":len(values),"available":not flags,"flags":sorted(set(flags))})
    return manifest,rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("fit","evaluate"))
    parser.add_argument("--trials",type=Path,required=True)
    parser.add_argument("--model",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve earlier output and choose a new filename")
    phase = "train" if args.action=="fit" else "test"
    manifest,rows = load_trials(args.trials,phase)
    common = {"evidence_kind":"physical","specimen":manifest["specimen"],"geometry_sha256":manifest["geometry_sha256"],
              "settings":SETTINGS,"created_utc":datetime.now(timezone.utc).isoformat(),
              "trial_manifest_sha256":digest(args.trials),"reference_id":manifest["reference_id"],
              "reference_uncertainty_n":manifest["reference_uncertainty_n"],
              "robot_gripper_qualified":False,"dynamic_force_accuracy_qualified":False,
              "scope":"Means of declared stationary holds. No dynamic, moving-robot, contact-confidence or lifetime qualification."}
    if args.action=="fit":
        if any(not r["available"] for r in rows):
            raise ValueError("Calibration contains unavailable holds; keep failed attempts and collect a complete new plan")
        if min(r["reference_n"] for r in rows)>.2 or max(r["reference_n"] for r in rows)<20:
            raise ValueError("Calibration must span low contact force through the 20 N target")
        coefficients = fit_numeric([r["mean_counts"] for r in rows],[r["reference_n"] for r in rows])
        levels,levels_met = level_coverage(rows,manifest)
        if not levels_met:
            raise ValueError("Complete the declared force levels and independent repetitions before fitting")
        training_rmse = math.sqrt(sum((predict(coefficients,r["mean_counts"])-r["reference_n"])**2 for r in rows)/len(rows))
        report = {"schema":"yam-c1-force-model/1",**common,**coefficients,
                  "training_recordings":[r["recording_sha256"] for r in rows],"training_holds":len(rows),
                  "training_force_level_coverage":levels,
                  "training_reference_range_n":[min(r["reference_n"] for r in rows),max(r["reference_n"] for r in rows)],
                  "training_rmse_n":training_rmse,"training_rmse_target_met":training_rmse<=.5}
    else:
        if args.model is None:
            parser.error("--model is required for evaluation")
        model = json.loads(args.model.read_text())
        if model.get("schema")!="yam-c1-force-model/1" or model.get("evidence_kind")!="physical" or model.get("settings")!=SETTINGS:
            raise ValueError("Select a physical C1 calibration model")
        if model["geometry_sha256"]!=manifest["geometry_sha256"]:
            raise ValueError("Geometry changed; calibrate this geometry separately")
        if model["specimen"]!=manifest["specimen"] and manifest.get("transfer_experiment") is not True:
            raise ValueError("A different specimen requires an explicitly declared transfer experiment")
        if any(r["recording_sha256"] in model["training_recordings"] for r in rows):
            raise ValueError("Training recordings cannot be reused for held-out evaluation")
        errors = []
        for row in rows:
            if row["available"]:
                row["predicted_n"] = predict(model,row["mean_counts"])
                row["error_n"] = row["predicted_n"]-row["reference_n"]
                row["error_with_reference_bound_n"] = abs(row["error_n"])+row["reference_bound_n"]
                row["individual_error_rule_met"] = row["error_with_reference_bound_n"]<=max(.5,.1*row["reference_n"])
                errors.append(row["error_n"])
        conditions = set(manifest.get("required_condition_ids",[]))
        observed = {r["condition_id"] for r in rows}
        coverage = bool(conditions) and conditions<=observed and all(
            min(r["reference_n"] for r in rows if r["condition_id"]==c)<=.2 and
            max(r["reference_n"] for r in rows if r["condition_id"]==c)>=20 for c in conditions)
        rmse = math.sqrt(sum(e*e for e in errors)/len(errors)) if errors else None
        by_condition = {}
        for condition in conditions:
            selected = [row for row in rows if row["condition_id"]==condition]
            levels,complete = level_coverage(selected,manifest)
            by_condition[condition] = levels
            coverage = coverage and complete
        report = {"schema":"yam-c1-static-validation/1",**common,"model_sha256":digest(args.model),
                  "transfer_experiment":manifest.get("transfer_experiment",False),"training_specimen":model["specimen"],
                  "held_out_holds":len(rows),"unavailable_holds":sum(not r["available"] for r in rows),
                  "declared_condition_range_coverage":coverage,"rmse_n":rmse,
                  "force_level_coverage_by_condition":by_condition,
                  "max_abs_error_n":max(map(abs,errors)) if errors else None,"trials":rows,
                  "passed_static_screen":coverage and len(errors)==len(rows) and rmse<=.5 and model.get("training_rmse_target_met",False) and all(r.get("individual_error_rule_met") for r in rows)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report,stream,indent=2,allow_nan=False);stream.write("\n")
    print(json.dumps({k:report[k] for k in report if k in ("schema","training_holds","training_rmse_n","rmse_n","unavailable_holds","passed_static_screen")},indent=2))


if __name__=="__main__":
    with execution(ROOT/"build/records","Fit or evaluate a C1 force model from preserved physical trial recordings; no actuator control"):
        main()
