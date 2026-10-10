#!/usr/bin/python3
"""Record a planned L1 force/moment experiment from one explicitly selected serial port."""

import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
from l1_protocol import decode


def observed_force(prompt):
    while True:
        value=input(prompt).strip()
        if value.lower()=="q":raise KeyboardInterrupt
        try:
            force=float(value)
            if math.isfinite(force) and 0<=force<=20.5:return force
        except ValueError:pass
        print("Enter measured force in N (0..20.5), or q to stop.")


def collect(port,stream,seconds):
    end=time.monotonic()+seconds;samples=[];faults=0;last=None
    while time.monotonic()<end:
        raw=port.readline(4097)
        if not raw:continue
        capture={"received_utc":datetime.now(timezone.utc).isoformat(),"host_monotonic_ns":time.monotonic_ns()}
        try:
            frame=json.loads(raw)
            if not isinstance(frame,dict):raise ValueError("Expected JSON object")
            if frame.get("type")!="sample":
                stream.write(json.dumps({**capture,"message":frame})+"\n")
                if frame.get("type")=="fatal":faults+=1
                continue
            result=decode(frame)
            if last is not None and (result["seq"]!=last["seq"]+1 or result["device_us"]<=last["device_us"]):
                result["valid"]=False;result["flags"].append("sequence_or_time_discontinuity")
            last=result
            stream.write(json.dumps({**capture,"frame":frame,"decoded":result})+"\n")
            if result["valid"]:samples.append(result)
            else:faults+=1
        except (ValueError,TypeError,KeyError) as error:
            faults+=1;stream.write(json.dumps({**capture,"parse_error":str(error),"raw_hex":raw.hex()})+"\n")
    stream.flush()
    return samples,faults


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--port",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--specimen",required=True)
    parser.add_argument("--operator",required=True)
    parser.add_argument("--reference-id",required=True)
    parser.add_argument("--reference-uncertainty-n",type=float,required=True)
    parser.add_argument("--pose-id",required=True)
    parser.add_argument("--mounting-notes",required=True,help="Fastener lengths/engagement, torque, fixture and cable routing")
    args=parser.parse_args()
    if not math.isfinite(args.reference_uncertainty_n) or not 0<args.reference_uncertainty_n<=.05:
        parser.error("Reference uncertainty must be >0 and <=0.05 N")
    plan_bytes=args.plan.read_bytes();plan=json.loads(plan_bytes)
    if plan.get("schema")!="yam-l1-plan/1":parser.error("Unsupported plan")
    identifiers=[row["trial_id"] for row in plan["trials"]]
    if len(set(identifiers))!=len(identifiers) or any(not re.fullmatch(r"[A-Za-z0-9_-]+",value) for value in identifiers):
        parser.error("Trial IDs must be unique and safe filenames")
    for row in plan["trials"]:
        if row["split"] not in {"train","test"} or not all(isinstance(row[k],(int,float)) and math.isfinite(row[k]) for k in ("target_n","u_mm","v_mm")) or not 0<=row["target_n"]<=20:
            parser.error("Invalid trial plan")
    args.output.mkdir(parents=True,exist_ok=False)
    metadata={
        "schema":"yam-l1-session/1","evidence_kind":"physical","specimen":args.specimen,
        "operator":args.operator,"reference_id":args.reference_id,"reference_uncertainty_n":args.reference_uncertainty_n,
        "pose_id":args.pose_id,"mounting_notes":args.mounting_notes,"port":args.port,
        "created_utc":datetime.now(timezone.utc).isoformat(),"plan_sha256":hashlib.sha256(plan_bytes).hexdigest(),
        "fixture":plan["fixture"],"force_axis":plan["force_axis"],"plan":plan,
    }
    (args.output/"session.json").write_text(json.dumps(metadata,indent=2)+"\n")
    (args.output/"plan.json").write_bytes(plan_bytes)
    import serial
    with execution(args.output/"execution","Collect operator-applied L1 force and moment loads; no actuator commands") as record:
        record["completed_trials"]=0
        print("Positive reference force must follow the plan's W axis. Keep the fixture stationary.")
        print("Confirm bridge resistance, 5 V/3.3 V domains, 4.2 V excitation, mounting and low-load response.")
        if input("Type checks-passed to begin, or q to stop: ").strip()!="checks-passed":
            raise KeyboardInterrupt
        with serial.Serial(args.port,115200,timeout=.25) as port,(args.output/"trials.jsonl").open("x") as results:
            for trial in plan["trials"]:
                print(f"\n{trial['trial_id']}: {trial['target_n']:.2f} N at U={trial['u_mm']} mm, V={trial['v_mm']} mm.")
                before=observed_force("Actual stable reference force before capture (N): ")
                port.reset_input_buffer()
                path=args.output/f"{trial['trial_id']}.jsonl"
                with path.open("x") as stream:
                    collect(port,stream,1)
                    samples,faults=collect(port,stream,2)
                after=observed_force("Actual reference force at end of capture (N): ")
                counts=[sample["raw_counts"] for sample in samples]
                valid=len(samples)>=80 and faults==0 and abs(after-before)<=.1
                result={
                    **trial,"specimen":args.specimen,"pose_id":args.pose_id,"fixture":plan["fixture"],
                    "evidence_kind":"physical","reference_n":(before+after)/2,
                    "reference_before_n":before,"reference_after_n":after,
                    "reference_uncertainty_n":args.reference_uncertainty_n,"valid":valid,
                    "raw_counts_mean":statistics.mean(counts) if counts else None,
                    "raw_counts_stdev":statistics.stdev(counts) if len(counts)>1 else None,
                    "samples":len(samples),"faults":faults,"raw_file":path.name,
                    "raw_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                    "analysis_device_us":[samples[0]["device_us"],samples[-1]["device_us"]] if samples else None,
                    "gain":128,"rate_sps":80,"ldo_nominal_v":4.2,
                }
                results.write(json.dumps(result,allow_nan=False)+"\n");results.flush()
                record["completed_trials"]+=1
                print(f"Saved {len(samples)} valid samples; {'accepted' if valid else 'rejected'}.")
                if len(samples)<40 or faults:
                    raise RuntimeError("Readout fault; preserve the record and repair before further loading.")


if __name__=="__main__":
    try:main()
    except KeyboardInterrupt:
        print("\nStopped by operator; completed records retained.",file=sys.stderr)
        raise SystemExit(130)
