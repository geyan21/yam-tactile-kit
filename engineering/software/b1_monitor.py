#!/usr/bin/python3
"""Capture an explicitly selected B1 port with raw frames, faults and specimen identity."""

import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
from b1_protocol import decode,native_vectors


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--specimen",required=True)
    parser.add_argument("--condition",required=True,help="e.g. unloaded-motor-off or M0-5N-loading")
    parser.add_argument("--seconds",type=float,default=30)
    args=parser.parse_args()
    if not math.isfinite(args.seconds) or not 1<=args.seconds<=3600:
        parser.error("Duration must be 1..3600 seconds")
    if args.output.exists():parser.error("Output already exists")
    manifest=ROOT/"engineering/release/b1/b1_manifest.json"
    poses=json.loads(manifest.read_text())["sensor_poses"]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    import serial
    with execution(args.output.parent/"execution","Preserve B1 raw observations and faults for one declared specimen and condition") as record:
        record["port"]=args.port
        with args.output.open("x") as stream,serial.Serial(args.port,115200,timeout=.25) as port:
            stream.write(json.dumps({"type":"session","evidence_kind":"physical","specimen":args.specimen,
                "condition":args.condition,"created_utc":datetime.now(timezone.utc).isoformat(),
                "geometry_sha256":hashlib.sha256(manifest.read_bytes()).hexdigest(),"force_calibrated":False})+"\n")
            start=time.monotonic();last=None;last_print=start;count=0;faults=0
            while time.monotonic()-start<args.seconds:
                raw=port.readline(8193)
                capture={"received_utc":datetime.now(timezone.utc).isoformat(),"host_monotonic_ns":time.monotonic_ns()}
                if not raw:
                    faults+=1;stream.write(json.dumps({**capture,"error":"serial_timeout","force_n":None})+"\n");continue
                try:
                    frame=json.loads(raw)
                    if not isinstance(frame,dict):raise ValueError("Expected JSON object")
                    if frame.get("type")!="sample":
                        stream.write(json.dumps({**capture,"message":frame})+"\n")
                        if frame.get("type")=="fatal":raise RuntimeError(frame.get("reason","Device fault"))
                        continue
                    reading=decode(frame)
                    if last and (reading["seq"]!=last["seq"]+1 or reading["device_us"]<=last["device_us"]):
                        reading["valid"]=False;reading["flags"].append("sequence_or_time_discontinuity")
                    last=reading
                    reading["magnetic_native_ut"]=native_vectors(reading["magnetic_local_ut"],poses)
                    stream.write(json.dumps({**capture,"frame":frame,"decoded":reading},allow_nan=False)+"\n")
                    count+=1;faults+=not reading["valid"]
                    if time.monotonic()-last_print>=.5:
                        print(f"{count} frames · valid={reading['valid']} · flags={reading['flags']} · force uncalibrated",flush=True)
                        last_print=time.monotonic();stream.flush()
                except (ValueError,KeyError,TypeError) as error:
                    faults+=1;stream.write(json.dumps({**capture,"parse_error":str(error),"raw_hex":raw.hex()})+"\n")
            record["frames"]=count;record["faults"]=faults
        print(f"Saved {count} frames and {faults} fault events to {args.output}")


if __name__=="__main__":
    try:main()
    except KeyboardInterrupt:
        print("Stopped by operator; raw data retained.",file=sys.stderr)
        raise SystemExit(130)
