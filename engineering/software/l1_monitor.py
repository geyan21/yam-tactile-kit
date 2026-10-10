#!/usr/bin/python3
"""Display and record L1 data from one selected port; never command an actuator."""

import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

from l1_calibrate import force_from_counts
from l1_protocol import decode
from tactile_kit.records import execution


def checked_model(report,specimen,pose,fixture):
    accepted={
        "yam-l1-calibration/1":"bench_force_criterion_met",
        "yam-l1-finger-validation/1":"static_force_criterion_met",
    }
    key=accepted.get(report.get("schema"))
    if not key or report.get("evidence_kind")!="physical" or report.get(key) is not True:
        raise ValueError("Use a physical report that met its stated bench criterion")
    if any(report.get(key)!=value for key,value in (("specimen",specimen),("pose_id",pose),("fixture",fixture))):
        raise ValueError("Calibration does not match the selected specimen, pose and fixture")
    model=report["model"]
    if any(isinstance(model.get(key),bool) or not isinstance(model.get(key),(int,float)) or not math.isfinite(model[key])
           for key in ("zero_counts","counts_per_n")) or abs(model["counts_per_n"])<1:
        raise ValueError("Invalid calibration model")
    return model


def estimate(reading,model):
    value=force_from_counts(model,reading["raw_counts"]) if model and reading["valid"] else None
    flags=list(reading["flags"])
    if value is not None and not -.5<=value<=20.5:
        flags.append("outside_screened_force_range");value=None
    return {**reading,"force_n":value,"flags":flags,
            "valid":reading["valid"] and not flags,
            "robot_gripper_qualified":False,"closed_loop_validated":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--seconds",type=float,default=60)
    parser.add_argument("--specimen",required=True)
    parser.add_argument("--pose-id",required=True)
    parser.add_argument("--fixture",required=True)
    parser.add_argument("--calibration",type=Path)
    args=parser.parse_args()
    if not math.isfinite(args.seconds) or not 0<args.seconds<=3600:parser.error("Duration must be 0..3600 seconds")
    model=None;digest=None
    if args.calibration:
        content=args.calibration.read_bytes()
        model=checked_model(json.loads(content),args.specimen,args.pose_id,args.fixture)
        digest=hashlib.sha256(content).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    import serial
    with execution(args.output.with_suffix(".execution"),"Read and preserve L1 force/health data; no automatic tare or actuator commands") as record:
        record["port"]=args.port;record["calibration_sha256"]=digest
        with args.output.open("x") as stream,serial.Serial(args.port,115200,timeout=.2) as port:
            stream.write(json.dumps({
                "type":"session","evidence_kind":"physical","specimen":args.specimen,
                "pose_id":args.pose_id,"fixture":args.fixture,"calibration_sha256":digest,
                "created_utc":datetime.now(timezone.utc).isoformat(),
            })+"\n")
            start=time.monotonic();last=None;last_print=start;count=0;faults=0
            while time.monotonic()-start<args.seconds:
                raw=port.readline(4097)
                capture={"received_utc":datetime.now(timezone.utc).isoformat(),"host_monotonic_ns":time.monotonic_ns()}
                if not raw:
                    faults+=1;print("No fresh frame — force unavailable",flush=True)
                    stream.write(json.dumps({**capture,"error":"serial_timeout","force_n":None})+"\n")
                    continue
                try:
                    frame=json.loads(raw)
                    if not isinstance(frame,dict):raise ValueError("Expected a JSON object")
                    if frame.get("type")!="sample":
                        stream.write(json.dumps({**capture,"message":frame})+"\n")
                        if frame.get("type")=="fatal":raise RuntimeError(frame.get("reason","Device fault"))
                        continue
                    reading=decode(frame)
                    if last is not None and (reading["seq"]!=last["seq"]+1 or reading["device_us"]<=last["device_us"]):
                        reading["valid"]=False;reading["flags"].append("sequence_or_time_discontinuity")
                    last=reading;result=estimate(reading,model)
                    stream.write(json.dumps({**capture,"frame":frame,"decoded":result},allow_nan=False)+"\n")
                    count+=1;faults+=int(not result["valid"])
                    if time.monotonic()-last_print>=.25:
                        force="uncalibrated" if model is None else "unavailable" if result["force_n"] is None else f"{result['force_n']:.3f} N"
                        print(f"raw={result['raw_counts']}  force={force}  V={result['bridge_v']}  mA={result['bridge_current_ma']}  flags={result['flags']}",flush=True)
                        last_print=time.monotonic();stream.flush()
                except (ValueError,KeyError,TypeError) as error:
                    faults+=1
                    stream.write(json.dumps({**capture,"parse_error":str(error),"raw_hex":raw.hex(),"force_n":None})+"\n")
            record["frames"]=count;record["faults"]=faults;record["elapsed_s"]=time.monotonic()-start
            print(f"Saved {count} frames, {faults} fault events. No mechanical tare or actuator command was issued.")


if __name__=="__main__":
    try:main()
    except KeyboardInterrupt:
        print("Stopped by operator; records retained.",file=sys.stderr)
        raise SystemExit(130)
