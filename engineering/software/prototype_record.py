#!/usr/bin/python3
"""Record an explicitly selected prototype port, retaining identity and failures."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
import b2_protocol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design",required=True,choices=("B2",))
    parser.add_argument("--port",required=True)
    parser.add_argument("--specimen",required=True)
    parser.add_argument("--condition",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--seconds",type=float,default=30)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 3600:
        parser.error("Recording duration must be 1..3600 seconds")
    if args.output.exists():
        parser.error("Output exists; retain it and select a new recording name")
    if not args.specimen.strip() or "REPLACE" in args.specimen.upper():
        parser.error("Provide the actual specimen ID")
    basis = ROOT/"engineering/release/b1/b1_manifest.json"
    poses = json.loads(basis.read_text())["sensor_poses"]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    import serial
    with execution(args.output.parent/"execution","Record a declared prototype without actuator commands, preserving malformed/missing samples") as record:
        record["port"] = args.port
        with args.output.open("x") as stream, serial.Serial(args.port,115200,timeout=.25) as port:
            stream.write(json.dumps({
                "type":"session","schema":"yam-prototype-recording/1","design_id":args.design,
                "protocol":b2_protocol.PROTOCOL,"specimen":args.specimen,"condition":args.condition,
                "evidence_kind":"physical_recording_unreviewed",
                "created_utc":datetime.now(timezone.utc).isoformat(),
                "pose_basis_sha256":hashlib.sha256(basis.read_bytes()).hexdigest(),
                "force_calibrated":False,
            })+"\n")
            start = time.monotonic();last = None;frames = faults = 0;last_print = start
            while time.monotonic()-start < args.seconds:
                raw = port.readline(8193)
                capture = {"received_utc":datetime.now(timezone.utc).isoformat(),
                           "host_monotonic_ns":time.monotonic_ns()}
                if not raw:
                    stream.write(json.dumps({**capture,"error":"serial_timeout","force_n":None})+"\n")
                    faults += 1
                    continue
                try:
                    frame = json.loads(raw)
                    if not isinstance(frame,dict):
                        raise ValueError("Expected a JSON object")
                    if frame.get("protocol") != b2_protocol.PROTOCOL:
                        raise ValueError("Device protocol does not match the requested design")
                    if frame.get("type") != "sample":
                        stream.write(json.dumps({**capture,"message":frame})+"\n")
                        if frame.get("type") == "fatal":
                            raise RuntimeError(frame.get("reason","Device fault"))
                        continue
                    observation = b2_protocol.decode(frame)
                    if last and (observation["seq"] != last["seq"]+1 or observation["device_us"] <= last["device_us"]):
                        observation["valid"] = False
                        observation["flags"].append("sequence_or_time_discontinuity")
                    last = observation
                    observation["magnetic_native_ut"] = b2_protocol.native_vectors(observation["magnetic_local_ut"],poses)
                    stream.write(json.dumps({**capture,"frame":frame,"decoded":observation},allow_nan=False)+"\n")
                    frames += 1
                    faults += not observation["valid"]
                except (ValueError,TypeError,KeyError) as error:
                    stream.write(json.dumps({**capture,"parse_error":str(error),"raw_hex":raw.hex()})+"\n")
                    faults += 1
                if time.monotonic()-last_print >= 1:
                    print(f"{args.design}: {frames} frames, {faults} fault events; force uncalibrated",flush=True)
                    stream.flush();last_print = time.monotonic()
            record["frames"] = frames
            record["faults"] = faults
        print(f"Saved {args.output}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Operator stopped recording; raw evidence retained.",file=sys.stderr)
        raise SystemExit(130)
