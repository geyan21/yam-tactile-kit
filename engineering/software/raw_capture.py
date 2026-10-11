"""Shared bounded raw capture for new prototypes; preserved designs keep their recorders."""

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


def run(slug,protocol,decoder,geometry_default):
    parser=argparse.ArgumentParser(description="Record "+slug.upper()+" raw sensor data and faults from one explicitly selected port.")
    parser.add_argument("--port",required=True)
    parser.add_argument("--specimen",required=True)
    parser.add_argument("--condition",required=True)
    parser.add_argument("--seconds",type=float,default=30)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--geometry",type=Path,default=geometry_default)
    parser.add_argument("--source-kind",choices=("physical","electrical_dummy"),default="physical")
    args=parser.parse_args()
    receipt=args.output.with_suffix(args.output.suffix+".receipt.json")
    if args.output.exists() or receipt.exists():
        parser.error("Preserve earlier recordings and choose a new output")
    if not math.isfinite(args.seconds) or not 1<=args.seconds<=3600:
        parser.error("Use a bounded 1..3600 second duration")
    if not args.specimen.strip() or not args.condition.strip() or "REPLACE" in args.specimen.upper():
        parser.error("Provide actual specimen and condition identifiers")
    if not args.geometry.is_file():
        parser.error("Select this build's exact assembly manifest with --geometry")
    geometry_hash=hashlib.sha256(args.geometry.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    import serial
    with execution(args.output.parent/"execution","Record "+slug.upper()+" raw signals without actuator commands; retain malformed, stale and unavailable readings") as record:
        record["port"]=args.port
        frames=faults=0;complete=False;stop_reason=None
        try:
            with serial.Serial(args.port,115200,timeout=.25) as port,args.output.open("x") as stream:
                stream.write(json.dumps({"type":"session","schema":"yam-"+slug+"-recording/1",
                    "protocol":protocol,"specimen":args.specimen,"condition":args.condition,
                    "evidence_kind":"physical_recording_unreviewed" if args.source_kind=="physical" else "electrical_dummy_recording",
                    "geometry_sha256":geometry_hash,"created_utc":datetime.now(timezone.utc).isoformat(),
                    "force_calibrated":False})+"\n")
                port.reset_input_buffer()
                discarded=port.readline(16385)
                stream.write(json.dumps({"type":"startup_sync","raw_hex":discarded.hex(),
                    "note":"One line discarded after buffer reset to establish a fresh frame boundary; excluded from hold means."})+"\n")
                start=time.monotonic();last_print=start;previous=None
                while time.monotonic()-start<args.seconds:
                    raw=port.readline(16385)
                    stamp={"received_utc":datetime.now(timezone.utc).isoformat(),"host_monotonic_ns":time.monotonic_ns()}
                    if not raw:
                        stream.write(json.dumps({**stamp,"error":"serial_timeout"})+"\n")
                        faults+=1
                        continue
                    try:
                        if len(raw)>16384:
                            raise ValueError("Sensor frame exceeds the bounded line length")
                        frame=json.loads(raw)
                        if not isinstance(frame,dict) or frame.get("protocol")!=protocol:
                            raise ValueError("Device protocol does not match "+slug.upper())
                        if frame.get("type")!="sample":
                            stream.write(json.dumps({**stamp,"message":frame})+"\n")
                            if frame.get("type")=="fatal":
                                raise RuntimeError(frame.get("reason","Firmware fault"))
                            continue
                        observation=decoder(frame)
                        if previous and (observation["seq"]!=previous["seq"]+1 or observation["device_us"]<=previous["device_us"]):
                            observation["valid"]=False
                            observation["flags"].append("sequence_or_time_discontinuity")
                        previous=observation
                        stream.write(json.dumps({**stamp,"frame":frame,"decoded":observation},allow_nan=False)+"\n")
                        frames+=1;faults+=not observation["valid"]
                    except (ValueError,TypeError,KeyError) as error:
                        stream.write(json.dumps({**stamp,"parse_error":str(error),"raw_hex":raw.hex()})+"\n")
                        faults+=1
                    if time.monotonic()-last_print>=1:
                        stream.flush()
                        print(f"{slug.upper()}: {frames} frames, {faults} fault events; force uncalibrated",flush=True)
                        last_print=time.monotonic()
                complete=True
        except BaseException as error:
            stop_reason=type(error).__name__+": "+str(error)
            raise
        finally:
            record.update({"frames":frames,"faults":faults,"capture_complete":complete,"stop_reason":stop_reason})
            if args.output.is_file():
                result={"schema":"yam-"+slug+"-recording-receipt/1","file":args.output.name,
                        "sha256":hashlib.sha256(args.output.read_bytes()).hexdigest(),
                        "specimen":args.specimen,"geometry_sha256":geometry_hash,"condition":args.condition,
                        "frames":frames,"faults":faults,"capture_complete":complete,"stop_reason":stop_reason}
                with receipt.open("x") as stream:
                    json.dump(result,stream,indent=2);stream.write("\n")
                print(json.dumps(result,indent=2))
