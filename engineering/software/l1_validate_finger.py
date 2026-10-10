#!/usr/bin/python3
"""Validate the assembled finger using a fixed cell sensitivity and an explicit pose zero."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from l1_calibrate import ROOT, force_from_counts, load_session, verify_raw
from tactile_kit.records import execution


def analyze_finger(base,metadata,rows):
    if base.get("schema")!="yam-l1-calibration/1" or base.get("evidence_kind")!="physical":
        raise ValueError("A physical center/plate calibration is required")
    if base.get("bench_force_criterion_met") is not True:
        raise ValueError("The cell/plate calibration did not meet the proposed force criterion")
    if metadata.get("schema")!="yam-l1-session/1" or metadata.get("evidence_kind")!="physical":
        raise ValueError("A physical integrated-finger session is required")
    if base["specimen"]!=metadata["specimen"]:
        raise ValueError("The force-cell specimen changed")
    plan=metadata["plan"]
    if plan.get("fixture")!="integrated_enpire_l1" or plan.get("sensitivity_refit_permitted") is not False:
        raise ValueError("Expected the fixed-sensitivity integrated-finger plan")
    expected={item["trial_id"]:item for item in plan["trials"]}
    if len(expected)!=len(plan["trials"]) or len({row["trial_id"] for row in rows})!=len(rows):
        raise ValueError("Duplicate trial IDs")
    if set(expected)!={row["trial_id"] for row in rows}:
        raise ValueError("The integrated experiment is incomplete")
    for row in rows:
        if row.get("evidence_kind")!="physical" or row.get("valid") is not True:
            raise ValueError("A rejected trial remains; preserve and repeat the run")
        if row["pose_id"]!=metadata["pose_id"] or row["specimen"]!=metadata["specimen"]:
            raise ValueError("Mixed pose or specimen")
        if row["gain"]!=128 or row["rate_sps"]!=80:
            raise ValueError("Readout configuration changed")
        if any(row[key]!=expected[row["trial_id"]][key] for key in (
            "split","group","contact_id","target_n","u_mm","v_mm","phase"
        )):
            raise ValueError("Recorded trial conditions changed")
        for key in ("reference_n","reference_uncertainty_n","raw_counts_mean"):
            value=row[key]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError("Invalid measurement")
        if not 0<=row["reference_n"]<=20.5 or not 0<row["reference_uncertainty_n"]<=.05:
            raise ValueError("Reference outside the test protocol")
        if abs(row["reference_n"]-row["target_n"])>max(.05,.025*row["target_n"]):
            raise ValueError("A required force level was missed")
    zero=[row for row in rows if row["split"]=="train"]
    held_out=[row for row in rows if row["split"]=="test"]
    if len(zero)!=3 or any(row["phase"]!="explicit_unloaded_zero" or row["reference_n"]>.05 for row in zero):
        raise ValueError("Exactly three explicit unloaded readings are required")
    sensitivity=base["model"]["counts_per_n"]
    if not math.isfinite(sensitivity) or abs(sensitivity)<1:
        raise ValueError("Invalid saved sensitivity")
    # Offset is measured once with the assembled finger unloaded. No loaded
    # trial, contact identity or later zero-return reading changes this model.
    model={"counts_per_n":sensitivity,"zero_counts":statistics.mean(row["raw_counts_mean"] for row in zero)}
    zero_spread=(max(row["raw_counts_mean"] for row in zero)-min(row["raw_counts_mean"] for row in zero))/abs(sensitivity)
    predictions=[{
        "trial_id":row["trial_id"],"contact_id":row["contact_id"],"phase":row["phase"],
        "u_mm":row["u_mm"],"v_mm":row["v_mm"],"reference_n":row["reference_n"],
        "predicted_n":force_from_counts(model,row["raw_counts_mean"]),
    } for row in held_out]
    for point in predictions:point["error_n"]=point["predicted_n"]-point["reference_n"]
    contacts=[]
    for site in plan["required_contacts"]:
        points=[point for point in predictions if point["contact_id"]==site["id"]]
        if not points or max(point["reference_n"] for point in points)<20:
            raise ValueError(f"20 N measurements missing at {site['id']}")
        contacts.append({
            "contact_id":site["id"],"native_xyz_mm":site["native_xyz_mm"],"count":len(points),
            "max_abs_error_n":max(abs(point["error_n"]) for point in points),
        })
    errors=[point["error_n"] for point in predictions]
    rmse=math.sqrt(statistics.mean(error*error for error in errors))
    maximum=max(abs(error) for error in errors)
    zero_return=max(abs(point["error_n"]) for point in predictions if point["phase"]=="unloading")
    return {
        "schema":"yam-l1-finger-validation/1","evidence_kind":"physical",
        "specimen":metadata["specimen"],"pose_id":metadata["pose_id"],"fixture":metadata["fixture"],
        "model":model,"gain":128,"rate_sps":80,"ldo_nominal_v":4.2,"calibrated_force_range_n":[0,20],
        "sensitivity_refitted":False,"zero_method":"Three explicit unloaded readings at the recorded pose",
        "initial_zero_spread_n":zero_spread,"max_zero_return_error_n":zero_return,
        "held_out_rmse_n":rmse,"held_out_max_abs_error_n":maximum,
        "static_force_criterion_met":rmse<=.25 and maximum<=.5 and zero_return<=.2 and zero_spread<=.1,
        "proposed_criteria":{"rmse_n":.25,"max_abs_error_n":.5,"zero_return_n":.2,"initial_zero_spread_n":.1},
        "contact_summary":contacts,"predictions":predictions,
        "robot_gripper_qualified":False,"closed_loop_validated":False,"fault_coverage_qualified":False,
        "limitations":[
            "Valid only for the tested cell, assembly, force direction and stationary pose.",
            "Gravity and acceleration compensation are not implemented.",
            "This does not establish wear life, manufacturing repeatability or a safe off-axis moment rating.",
            "Low-force contact statistics, dynamics, faults and manipulation tasks require separate measurements.",
        ],
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session",type=Path)
    parser.add_argument("--cell-calibration",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    metadata,rows=load_session(args.session)
    base_bytes=args.cell_calibration.read_bytes()
    with execution(args.session/"execution","Verify integrated-finger records with fixed sensitivity and an explicit unloaded pose zero") as record:
        report=analyze_finger(json.loads(base_bytes),metadata,rows)
        verify_raw(args.session,rows)
        report["cell_calibration_sha256"]=hashlib.sha256(base_bytes).hexdigest()
        report["session_plan_sha256"]=metadata["plan_sha256"]
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(report,stream,indent=2,allow_nan=False);stream.write("\n")
        record["report"]=str(args.output)
        record["static_force_criterion_met"]=report["static_force_criterion_met"]
        print(json.dumps({key:report[key] for key in (
            "held_out_rmse_n","held_out_max_abs_error_n","max_zero_return_error_n",
            "static_force_criterion_met","robot_gripper_qualified"
        )},indent=2))


if __name__=="__main__":
    main()
