#!/usr/bin/python3
"""Record raw C1 data from an explicitly selected serial port, preserving faults."""

import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
from c1_protocol import PROTOCOL,decode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",required=True)
    parser.add_argument("--specimen",required=True)
    parser.add_argument("--condition",required=True)
    parser.add_argument("--seconds",type=float,default=30)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--geometry",type=Path,default=ROOT/"engineering/prototypes/c1/c1_manifest.json")
    parser.add_argument("--source-kind",choices=("physical","electrical_dummy"),default="physical")
    args = parser.parse_args()
    receipt = args.output.with_suffix(args.output.suffix+".receipt.json")
    if args.output.exists() or receipt.exists() or not math.isfinite(args.seconds) or not 1<=args.seconds<=3600:
        parser.error("Choose a new output and a 1..3600 second recording")
    if not args.specimen.strip() or "REPLACE" in args.specimen.upper():
        parser.error("Provide an actual specimen ID")
    if not args.geometry.is_file():
        parser.error("Select the exact C1 assembly manifest with --geometry")
    geometry_hash = hashlib.sha256(args.geometry.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    import serial
    with execution(args.output.parent/"execution","Record C1 bridge signals and electrical health without actuator commands or assumed force calibration") as record:
        record["port"] = args.port
        with args.output.open("x") as stream,serial.Serial(args.port,115200,timeout=.25) as port:
            stream.write(json.dumps({"type":"session","schema":"yam-c1-recording/1","protocol":PROTOCOL,
                "specimen":args.specimen,"condition":args.condition,
                "evidence_kind":"physical_recording_unreviewed" if args.source_kind=="physical" else "electrical_dummy_recording",
                "geometry_sha256":geometry_hash,
                "created_utc":datetime.now(timezone.utc).isoformat(),"force_calibrated":False})+"\n")
            port.reset_input_buffer()
            discarded = port.readline(16385)
            stream.write(json.dumps({"type":"startup_sync","raw_hex":discarded.hex(),
                "note":"One line discarded after buffer reset to establish a fresh frame boundary; excluded from stationary-hold means."})+"\n")
            start = time.monotonic();last = None;last_print = start;frames = faults = 0
            while time.monotonic()-start<args.seconds:
                raw = port.readline(16385)
                received = {"received_utc":datetime.now(timezone.utc).isoformat(),"host_monotonic_ns":time.monotonic_ns()}
                if not raw:
                    stream.write(json.dumps({**received,"error":"serial_timeout"})+"\n")
                    faults += 1;continue
                try:
                    frame = json.loads(raw)
                    if not isinstance(frame,dict) or frame.get("protocol")!=PROTOCOL:
                        raise ValueError("C1 protocol mismatch")
                    if frame.get("type")!="sample":
                        stream.write(json.dumps({**received,"message":frame})+"\n")
                        if frame.get("type")=="fatal":
                            raise RuntimeError(frame.get("reason","C1 firmware fault"))
                        continue
                    observation = decode(frame)
                    if last and (observation["seq"]!=last["seq"]+1 or observation["device_us"]<=last["device_us"]):
                        observation["valid"] = False
                        observation["flags"].append("sequence_or_time_discontinuity")
                    last = observation
                    stream.write(json.dumps({**received,"frame":frame,"decoded":observation},allow_nan=False)+"\n")
                    frames += 1;faults += not observation["valid"]
                except (ValueError,TypeError,KeyError) as error:
                    stream.write(json.dumps({**received,"parse_error":str(error),"raw_hex":raw.hex()})+"\n")
                    faults += 1
                if time.monotonic()-last_print>=1:
                    print(f"C1: {frames} frames, {faults} fault events; force uncalibrated",flush=True)
                    stream.flush();last_print = time.monotonic()
            record.update({"frames":frames,"faults":faults})
        data = {"schema":"yam-c1-recording-receipt/1","file":args.output.name,
                "sha256":hashlib.sha256(args.output.read_bytes()).hexdigest(),
                "specimen":args.specimen,"geometry_sha256":geometry_hash,"condition":args.condition,
                "frames":frames,"faults":faults}
        with receipt.open("x") as stream:
            json.dump(data,stream,indent=2);stream.write("\n")
        print(json.dumps(data,indent=2))


if __name__=="__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Operator stopped C1 capture; raw data retained.",file=sys.stderr)
        raise SystemExit(130)
