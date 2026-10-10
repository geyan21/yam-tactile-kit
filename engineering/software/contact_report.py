#!/usr/bin/python3
"""Freeze contact thresholds from training, or evaluate a separately recorded fixed plan."""

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

from contact_core import FEATURE_SPEC, classify, fit_thresholds, summarize_outcome
from contact_io import load_session
from tactile_kit.records import execution


def fit(metadata,rows):
    if metadata.get("schema")!="yam-contact-session/1" or metadata.get("evidence_kind")!="physical":
        raise ValueError("Physical training records are required")
    if metadata["phase"]!="train" or len(rows)!=len(metadata["plan"]["trials"]):
        raise ValueError("Complete the entire training plan; preserve incomplete attempts")
    if not rows or any(not row["available"] for row in rows):
        raise ValueError("Training contains a readout/reference failure")
    if any(row["train_channel"] is None for row in rows):
        raise ValueError("Leading edges and gaps must remain held out")
    thresholds=fit_thresholds(rows,metadata["sensor"],metadata["channels"])
    return {
        "schema":"yam-contact-model/1","evidence_kind":"physical",
        "sensor":metadata["sensor"],"specimen":metadata["specimen"],"variant":metadata["variant"],
        "pose_id":metadata["pose_id"],"configuration":rows[0]["extracted"]["configuration"],
        "feature_spec":FEATURE_SPEC,"thresholds":thresholds,
        "created_utc":datetime.now(timezone.utc).isoformat(),"training_trials":len(rows),
        "cases_sha256":metadata["cases_sha256"],
        "training_plan_sha256":metadata["plan_sha256"],
        "decision_rule":"Any enabled channel crossing its fixed signed threshold; region/label/reference never enters prediction",
        "robot_gripper_qualified":False,"force_range_qualified_n":None,
    }


def evaluate(metadata,rows,model):
    if metadata.get("schema")!="yam-contact-session/1" or metadata.get("evidence_kind")!="physical":
        raise ValueError("Physical evaluation records are required")
    if metadata["phase"]!="test":raise ValueError("Only a separately recorded evaluation can be scored")
    evaluations=[]
    for row in rows:
        decisions=[classify(window,model) for window in row["extracted"]["windows"]] if row["available"] else []
        evaluations.append({
            "trial_id":row["trial_id"],"region_id":row["region_id"],"contact_expected":row["contact_expected"],
            "available":row["available"],"decisions":[decision["contact"] for decision in decisions],
            "active_channels":[decision["active_channels"] for decision in decisions],
            "reference_upper_n":max(row["reference_before_n"],row["reference_after_n"])+metadata["reference_uncertainty_n"],
            "flags":row["extracted"]["flags"]+row["reference_flags"],
        })
    selected_ids={trial["region_id"] for trial in metadata["plan"]["trials"]}
    planned_regions=[case["id"] for case in metadata["cases"]["regions"] if case["id"] in selected_ids]
    summaries=[]
    for region in planned_regions:
        selected=[row for row in evaluations if row["region_id"]==region]
        summaries.append({"region_id":region,"loaded":summarize_outcome(selected,True),"clear":summarize_outcome(selected,False)})
    complete=len(rows)==len(metadata["plan"]["trials"])
    metrics=[summary[outcome] for summary in summaries for outcome in ("loaded","clear")]
    point_screen=complete and bool(metrics) and all(
        metric["trials"]>=20 and metric["unavailable_trials"]==0 and metric["conservative_error_rate"]<=.01
        for metric in metrics
    )
    per_metric_bound=point_screen and all(metric["upper_error_bound_95"]<=.01 for metric in metrics)
    declared={case["id"] for case in metadata["cases"]["regions"]}
    full_map=set(planned_regions)==declared
    return {
        "schema":"yam-contact-validation/1","evidence_kind":"physical",
        "sensor":metadata["sensor"],"specimen":metadata["specimen"],"variant":metadata["variant"],
        "pose_id":metadata["pose_id"],"training_variant":model["variant"],"training_pose_id":model["pose_id"],
        "transfer_experiment":metadata["transfer_experiment"],"model_sha256":metadata["model_sha256"],
        "plan_sha256":metadata["plan_sha256"],"feature_spec":FEATURE_SPEC,
        "cases_sha256":metadata["cases_sha256"],
        "declared_regions":[case["id"] for case in metadata["cases"]["regions"]],
        "planned_trials":len(metadata["plan"]["trials"]),"recorded_trials":len(rows),"plan_complete":complete,
        "declared_closing_face_map_complete":full_map and complete,
        "observed_rate_screen_met":point_screen,"per_metric_95_bound_below_1pct":per_metric_bound,
        "regions":summaries,"trials":evaluations,
        "confidence_scope":"One-sided exact 95% bound separately for each region/outcome; not a simultaneous guarantee across all metrics",
        "reference_uncertainty_n":metadata["reference_uncertainty_n"],
        "robot_gripper_qualified":False,"force_range_qualified_n":None,"dynamic_latency_ms":None,
        "limitations":[
            "Counts are independent physical presentations, not overlapping rolling windows or ADC frames.",
            "Any wrong decision during the evaluated stationary hold counts as an episode error.",
            "Unavailable trials are preserved separately and counted as errors in the conservative bound.",
            "A pilot rate screen does not establish a 1% error limit with confidence.",
            "Bounds assume independent representative trials under the declared specimen, pose, probe and material conditions.",
            "Side/back contacts, localization, motion, latency, 20 N force accuracy, wear and manufacturing yield require separate evidence.",
        ],
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("fit","evaluate"))
    parser.add_argument("session",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error("Output already exists; preserve it and choose another name")
    events_path=args.output.with_name(args.output.stem+"-events.jsonl")
    if args.action=="evaluate" and events_path.exists():parser.error("Event-details output already exists")
    with execution(args.session/"execution","Recompute contact features from preserved raw data and fit or evaluate the frozen decision rule") as record:
        metadata,rows,model=load_session(args.session,"train" if args.action=="fit" else "test")
        report=fit(metadata,rows) if args.action=="fit" else evaluate(metadata,rows,model)
        report["source_session_sha256"]=hashlib.sha256((args.session/"session.json").read_bytes()).hexdigest()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        if args.action=="evaluate":
            # Keep the browser report small even for thousands of presentations.
            # Preserve every per-window decision in a separate, hashed artifact.
            with events_path.open("x") as stream:
                for trial in report.pop("trials"):
                    stream.write(json.dumps(trial,allow_nan=False,separators=(",",":"))+"\n")
            report["event_details"]={"file":events_path.name,"sha256":hashlib.sha256(events_path.read_bytes()).hexdigest()}
        with args.output.open("x") as stream:
            json.dump(report,stream,indent=2,allow_nan=False);stream.write("\n")
        record["output"]=str(args.output)
        print(json.dumps({key:report[key] for key in (
            ("schema","training_trials","robot_gripper_qualified") if args.action=="fit" else
            ("schema","recorded_trials","plan_complete","observed_rate_screen_met","per_metric_95_bound_below_1pct","robot_gripper_qualified")
        )},indent=2))


if __name__=="__main__":
    main()
