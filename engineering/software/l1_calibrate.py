#!/usr/bin/python3
"""Fit one root-force scale factor and test it on held-out force/moment positions."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
from l1_protocol import decode


def affine_force(points):
    """Fit raw count against force. A negative sensitivity is valid wiring polarity."""
    if len(points)<4:raise ValueError("Not enough calibration points")
    mean_f=statistics.mean(point[0] for point in points)
    mean_r=statistics.mean(point[1] for point in points)
    denominator=sum((f-mean_f)**2 for f,_ in points)
    if denominator<=0:raise ValueError("Calibration has no force span")
    sensitivity=sum((f-mean_f)*(r-mean_r) for f,r in points)/denominator
    if abs(sensitivity)<1:raise ValueError("No useful force sensitivity")
    return {"zero_counts":mean_r-sensitivity*mean_f,"counts_per_n":sensitivity}


def force_from_counts(model,raw):
    if not isinstance(raw,(int,float)) or isinstance(raw,bool) or not math.isfinite(raw):
        return None
    return (raw-model["zero_counts"])/model["counts_per_n"]


def analyze(metadata,rows):
    if metadata.get("schema")!="yam-l1-session/1" or metadata.get("evidence_kind")!="physical":
        raise ValueError("A physical L1 session is required; plans and software fixtures are not measurements")
    plan=metadata["plan"];planned={row["trial_id"]:row for row in plan["trials"]}
    if plan.get("fixture")!="combined_load_plate":
        raise ValueError("Use l1_validate_finger.py for the integrated finger; its force sensitivity must remain fixed")
    if len(planned)!=len(plan["trials"]):raise ValueError("Duplicate plan IDs")
    ids=[row["trial_id"] for row in rows]
    if len(ids)!=len(set(ids)):raise ValueError("Duplicate recorded trial IDs")
    if set(ids)!=set(planned):raise ValueError("The planned experiment is incomplete or has unplanned trials")
    for row in rows:
        if row.get("evidence_kind")!="physical" or row.get("valid") is not True:
            raise ValueError("Rejected or nonphysical trials remain; preserve them and repeat the experiment")
        expected=planned[row["trial_id"]]
        if any(row[key]!=expected[key] for key in ("split","group","target_n","u_mm","v_mm","contact_id","phase")):
            raise ValueError("Trial conditions differ from the recorded plan")
        if row["specimen"]!=metadata["specimen"] or row["pose_id"]!=metadata["pose_id"]:
            raise ValueError("Mixed specimen or pose")
        if row["gain"]!=128 or row["rate_sps"]!=80:
            raise ValueError("Readout configuration changed")
        for key in ("reference_n","raw_counts_mean","reference_uncertainty_n"):
            if not isinstance(row[key],(int,float)) or isinstance(row[key],bool) or not math.isfinite(row[key]):
                raise ValueError("Invalid numerical record")
        if not 0<=row["reference_n"]<=20.5 or not 0<row["reference_uncertainty_n"]<=.05:
            raise ValueError("Force reference is outside the pilot protocol")
        if abs(row["reference_n"]-row["target_n"])>max(.05,.025*row["target_n"]):
            raise ValueError("A required force level was missed; preserve the run and repeat it")
    train=[row for row in rows if row["split"]=="train"]
    test=[row for row in rows if row["split"]=="test"]
    if {row["group"] for row in train}&{row["group"] for row in test}:
        raise ValueError("Train/test group leakage")
    if len({row["group"] for row in train})<2:
        raise ValueError("Need two independent training cycles")
    if any(abs(row["u_mm"])>.01 or abs(row["v_mm"])>.01 for row in train):
        raise ValueError("Cell calibration must use the center only; off-center positions stay held out")
    if not test or max(row["reference_n"] for row in train)<20 or max(row["reference_n"] for row in test)<20:
        raise ValueError("20 N was not reached in both training and held-out measurements")
    model=affine_force([(row["reference_n"],row["raw_counts_mean"]) for row in train])
    predictions=[]
    for row in test:
        predicted=force_from_counts(model,row["raw_counts_mean"])
        predictions.append({
            "trial_id":row["trial_id"],"contact_id":row["contact_id"],
            "u_mm":row["u_mm"],"v_mm":row["v_mm"],
            "reference_n":row["reference_n"],"predicted_n":predicted,
            "error_n":predicted-row["reference_n"],
            "moment_u_nm":row["reference_n"]*row["v_mm"]/1000,
            "moment_v_nm":-row["reference_n"]*row["u_mm"]/1000,
        })
    port_summary=[]
    for u,v in [(0,0),*plan["required_moment_ports_uv_mm"]]:
        selected=[p for p in predictions if p["u_mm"]==u and p["v_mm"]==v]
        if not selected or max(p["reference_n"] for p in selected)<20:
            raise ValueError(f"Full-range held-out measurements missing at U={u}, V={v}")
        port_summary.append({
            "u_mm":u,"v_mm":v,"count":len(selected),
            "mean_error_n":statistics.mean(p["error_n"] for p in selected),
            "max_abs_error_n":max(abs(p["error_n"]) for p in selected),
        })
    errors=[p["error_n"] for p in predictions]
    rmse=math.sqrt(statistics.mean(error*error for error in errors))
    maximum=max(abs(error) for error in errors)
    return {
        "schema":"yam-l1-calibration/1","evidence_kind":"physical",
        "specimen":metadata["specimen"],"pose_id":metadata["pose_id"],"fixture":metadata["fixture"],
        "model":model,"train_trials":len(train),"test_trials":len(test),
        "gain":128,"rate_sps":80,"ldo_nominal_v":4.2,"calibrated_force_range_n":[0,20],
        "held_out_rmse_n":rmse,"held_out_max_abs_error_n":maximum,
        "proposed_criteria":{"rmse_n":.25,"max_abs_error_n":.5},
        "bench_force_criterion_met":rmse<=.25 and maximum<=.5,
        "port_summary":port_summary,"predictions":predictions,
        "moment_position_correction_applied":False,
        "robot_gripper_qualified":False,"closed_loop_validated":False,
        "limitations":[
            "Calibration contains one central force sensitivity; test-position information is never used to correct a prediction.",
            "This tests the cell and fixture at the recorded pose, not all robot configurations.",
            "Repeat with the integrated finger, gravity changes, dynamics, faults, wear and representative manipulation tasks.",
            "A successful single-specimen run does not establish manufacturing repeatability or a safe moment rating.",
        ],
    }


def verify_raw(session,rows):
    for row in rows:
        name=row["raw_file"]
        if Path(name).name!=name or name!=row["trial_id"]+".jsonl":
            raise ValueError("Unexpected raw data filename")
        data=(session/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=row["raw_sha256"]:
            raise ValueError(f"Raw data hash changed: {name}")
        begin,end=row["analysis_device_us"]
        counts=[];previous=None
        for line in data.splitlines():
            item=json.loads(line)
            if "frame" not in item:continue
            reading=decode(item["frame"])
            if not begin<=reading["device_us"]<=end:continue
            if not reading["valid"]:
                raise ValueError(f"Invalid sample inside the analysis window: {name}")
            if previous is not None and (
                reading["seq"]!=previous["seq"]+1 or reading["device_us"]<=previous["device_us"]
            ):
                raise ValueError(f"Discontinuous raw stream: {name}")
            previous=reading
            counts.append(reading["raw_counts"])
        if len(counts)!=row["samples"] or len(counts)<80:
            raise ValueError(f"Sample count mismatch: {name}")
        if abs(statistics.mean(counts)-row["raw_counts_mean"])>1e-6:
            raise ValueError(f"Raw and summarized counts differ: {name}")


def load_session(session):
    metadata=json.loads((session/"session.json").read_text())
    plan_bytes=(session/"plan.json").read_bytes()
    if hashlib.sha256(plan_bytes).hexdigest()!=metadata["plan_sha256"]:
        raise ValueError("Recorded trial plan changed")
    if json.loads(plan_bytes)!=metadata["plan"]:
        raise ValueError("Embedded plan differs from the saved experiment")
    rows=[json.loads(line) for line in (session/"trials.jsonl").read_text().splitlines() if line.strip()]
    return metadata,rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    metadata,rows=load_session(args.session)
    with execution(args.session/"execution","Verify raw records and test a single root-force calibration on held-out force/moment positions") as record:
        report=analyze(metadata,rows)
        verify_raw(args.session,rows)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(report,stream,indent=2,allow_nan=False);stream.write("\n")
        record["report"]=str(args.output)
        record["bench_force_criterion_met"]=report["bench_force_criterion_met"]
        print(json.dumps({key:report[key] for key in (
            "held_out_rmse_n","held_out_max_abs_error_n","bench_force_criterion_met","robot_gripper_qualified"
        )},indent=2))


if __name__=="__main__":
    main()
