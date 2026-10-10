#!/usr/bin/python3
"""Record independent low-force presentations on R1 or L1; never command an actuator."""

import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

from contact_core import FEATURE_SPEC, extract_trial, finite, reference_flags
from contact_io import ROOT, bind_model, selected_cases
from tactile_kit.records import execution


def make_plan(cases,phase,repeats,seed):
    if phase not in {"train","test"} or not isinstance(repeats,int) or not 20<=repeats<=10000:
        raise ValueError("Choose train/test and 20..10000 repetitions per label and region before collection")
    entries=[]
    for case in cases:
        for repeat in range(repeats):
            for label in (False,True):
                entries.append({
                    "region_id":case["id"],"contact_expected":label,
                    "train_channel":case["train_channel"],"repeat":repeat,
                    "instruction":case["instruction"],
                })
    random.Random(seed).shuffle(entries)
    for index,trial in enumerate(entries):
        trial["trial_id"]=f"{phase}_{index:06d}_{trial['region_id']}"
    return {
        "schema":"yam-contact-plan/1","phase":phase,"kind":"plan_only",
        "repeats_per_label_and_region":repeats,"seed":seed,"trials":entries,
        "counting_unit":"One independently reset physical presentation, not an ADC frame or decision window",
    }


def reference(prompt):
    while True:
        value=input(prompt).strip()
        if value.lower()=="q":raise KeyboardInterrupt
        try:
            force=float(value)
            if math.isfinite(force) and -.1<=force<=20.5:return force
        except ValueError:pass
        print("Enter the actual reference force in N, or q to stop.")


def capture(port,stream,stage,duration):
    records=[];end=time.monotonic()+duration
    while time.monotonic()<end:
        raw=port.readline(4097)
        item={"stage":stage,"received_utc":datetime.now(timezone.utc).isoformat(),"host_monotonic_ns":time.monotonic_ns()}
        if not raw:
            item["error"]="serial_timeout"
        else:
            try:
                if len(raw)>4096:raise ValueError("Frame exceeds 4096 bytes")
                frame=json.loads(raw)
                if not isinstance(frame,dict):raise ValueError("Expected JSON object")
                item["frame" if frame.get("type")=="sample" else "message"]=frame
            except (ValueError,TypeError) as error:
                item.update({"error":str(error),"raw_hex":raw.hex()})
        stream.write(json.dumps(item,allow_nan=False)+"\n");records.append(item)
    stream.flush()
    return records


def main():
    pre=argparse.ArgumentParser(add_help=False)
    pre.add_argument("--setup",type=Path)
    known,_=pre.parse_known_args()
    setup={}
    if known.setup:
        setup=json.loads(known.setup.read_text())
        if setup.pop("schema",None)!="yam-contact-setup/1":
            pre.error("Unknown contact setup format")
        allowed={"sensor","specimen","variant","pose_id","operator","reference_id",
                 "reference_uncertainty_n","fixture","port","channels"}
        if set(setup)-allowed:pre.error("Setup contains unsupported fields")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup",type=Path,help="Saved specimen/reference settings; explicit arguments override these values")
    parser.add_argument("--phase",choices=("train","test"),required=True)
    parser.add_argument("--sensor",choices=("R1","L1"))
    parser.add_argument("--specimen")
    parser.add_argument("--variant",help="Material, thickness, assembly/replacement state")
    parser.add_argument("--pose-id")
    parser.add_argument("--operator")
    parser.add_argument("--reference-id")
    parser.add_argument("--reference-uncertainty-n",type=float)
    parser.add_argument("--fixture",help="Actual probe shape, region positions and photo/fixture-record identifier")
    parser.add_argument("--cases",type=Path,default=ROOT/"engineering/templates/contact_cases.json")
    parser.add_argument("--channels",help="R1 channels, e.g. 0,1 for a two-nail pilot; L1 always uses 0")
    parser.add_argument("--regions",help="Optional comma-separated pilot subset; omitted means all declared regions")
    parser.add_argument("--repeats",type=int,default=20)
    parser.add_argument("--seed",type=int,default=20261010)
    parser.add_argument("--model",type=Path)
    parser.add_argument("--transfer-experiment",action="store_true",help="Deliberately test another pose/variant using the unchanged model")
    parser.add_argument("--port")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--plan-only",action="store_true")
    parser.set_defaults(**setup)
    args=parser.parse_args()
    if args.sensor not in {"R1","L1"}:parser.error("Set sensor to R1 or L1")
    missing=[name for name in ("specimen","variant","pose_id","operator","reference_id","fixture")
             if not isinstance(getattr(args,name),str) or not getattr(args,name).strip()]
    if missing:parser.error("Fill these setup fields: "+", ".join(missing))
    uncertainty=args.reference_uncertainty_n
    if not finite(uncertainty) or not 0<uncertainty<=.05:
        parser.error("Reference uncertainty must be >0 and <=0.05 N")
    if args.channels is not None and not isinstance(args.channels,str):
        parser.error("Channels must be a comma-separated string or null")
    if not args.plan_only and not args.port:parser.error("Select the actual dedicated sensor port explicitly")
    channels=[int(value) for value in (args.channels or ("0,1,2,3,4,5" if args.sensor=="R1" else "0")).split(",")]
    if len(channels)!=len(set(channels)) or not channels or any(value not in range(6 if args.sensor=="R1" else 1) for value in channels):
        parser.error("Invalid enabled channels")
    payload,cases=selected_cases(args.cases,args.sensor,channels,args.phase,args.regions.split(",") if args.regions else None)
    plan=make_plan(cases,args.phase,args.repeats,args.seed)
    model=None;model_bytes=None
    if args.phase=="test":
        if not args.model and not args.plan_only:parser.error("Freeze a training model before evaluation")
        if args.model:
            model_bytes=args.model.read_bytes()
            model=bind_model(json.loads(model_bytes),args.sensor,args.specimen,args.pose_id,args.variant,channels,args.transfer_experiment)
    elif args.model or args.transfer_experiment:
        parser.error("Training does not use a previous model or transfer flag")
    args.output.mkdir(parents=True,exist_ok=False)
    plan_bytes=(json.dumps(plan,indent=2)+"\n").encode()
    metadata={
        "schema":"yam-contact-session/1","evidence_kind":"plan_only" if args.plan_only else "physical",
        "phase":args.phase,"sensor":args.sensor,"specimen":args.specimen,"variant":args.variant,
        "pose_id":args.pose_id,"operator":args.operator,"fixture":args.fixture,"port":args.port,
        "reference_id":args.reference_id,"reference_uncertainty_n":uncertainty,
        "created_utc":datetime.now(timezone.utc).isoformat(),"channels":channels,
        "cases":payload,"cases_sha256":hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "plan":plan,"plan_sha256":hashlib.sha256(plan_bytes).hexdigest(),"feature_spec":FEATURE_SPEC,
        "transfer_experiment":args.transfer_experiment,
        "model_sha256":hashlib.sha256(model_bytes).hexdigest() if model_bytes else None,
        "model_frozen_before_collection":bool(model_bytes) and not args.plan_only,
        "physical_scope":"Stationary closing-face contact bounded above by 0.2 N, at the recorded specimen/pose/variant",
    }
    (args.output/"plan.json").write_bytes(plan_bytes)
    (args.output/"cases.json").write_bytes(args.cases.read_bytes())
    if args.setup:
        (args.output/"input_setup.json").write_bytes(args.setup.read_bytes())
    (args.output/"session.json").write_text(json.dumps(metadata,indent=2)+"\n")
    if model_bytes:(args.output/"frozen_model.json").write_bytes(model_bytes)
    with execution(args.output/"execution","Plan or record independent R1/L1 contact presentations; preserve faults and issue no actuator commands") as record:
        record["planned_trials"]=len(plan["trials"]);record["completed_trials"]=0
        if args.plan_only:
            print(f"Saved {len(plan['trials'])} planned trials. No serial port opened or physical result created.")
            return
        import serial
        print("Lift the probe clear and reset to the documented starting position before EVERY trial.")
        print("Keep the fixture at the recorded pose. Raw contact predictions are withheld until evaluation ends.")
        print(f"For loaded trials, aim near {0.2-uncertainty-.01:.3f} N: observed force + reference uncertainty must not exceed 0.2 N.")
        if input("Type setup-checked after verifying wiring, reference, fixture and region positions: ").strip()!="setup-checked":
            raise KeyboardInterrupt
        with serial.Serial(args.port,115200,timeout=.05) as port,(args.output/"trials.jsonl").open("x") as stream:
            previous_end=None;expected_config=model["configuration"] if model else None
            for trial in plan["trials"]:
                print(f"\n{trial['trial_id']} — {'LIGHT CONTACT' if trial['contact_expected'] else 'CLEAR / NO CONTACT'}")
                print(trial["instruction"])
                before=reference("Reset, apply the requested condition and hold steady. Actual force (N): ")
                port.reset_input_buffer()
                raw_path=args.output/(trial["trial_id"]+".jsonl")
                with raw_path.open("x") as raw_stream:
                    capture(port,raw_stream,"settle",.5)
                    raw_records=capture(port,raw_stream,"capture",.6)
                after=reference("Actual force at end of hold (N): ")
                extracted=extract_trial(raw_records,args.sensor,expected_config)
                if expected_config is None:expected_config=extracted["configuration"]
                row={**trial,"reference_before_n":before,"reference_after_n":after,
                     "raw_file":raw_path.name,"raw_sha256":hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                     "recorded_frames":extracted["frames"],"readout_flags":extracted["flags"]}
                if previous_end is not None and extracted["first_device_us"] is not None and extracted["first_device_us"]<=previous_end:
                    row["readout_flags"].append("device_restart_or_replayed_trial")
                previous_end=extracted["last_device_us"]
                row["reference_flags"]=reference_flags(row,uncertainty)
                stream.write(json.dumps(row,allow_nan=False)+"\n");stream.flush()
                record["completed_trials"]+=1
                print("Saved presentation and raw records.")
                if row["readout_flags"] or row["reference_flags"]:
                    raise RuntimeError("Readout/reference problem saved. Preserve this incomplete experiment; inspect it before a new run.")


if __name__=="__main__":
    try:main()
    except KeyboardInterrupt:
        print("Stopped by operator; completed records retained.",file=sys.stderr)
        raise SystemExit(130)
