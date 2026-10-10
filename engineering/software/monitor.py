#!/usr/bin/python3
"""Show real R1 electrical readings and preserve a bounded raw stream; no force inference."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
from signals import decode


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",required=True)
    parser.add_argument("--seconds",type=float,default=60)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.seconds<=3600:parser.error("--seconds must be in 1..3600")
    if args.output.exists():parser.error("Output already exists; choose a new file")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    import serial
    with execution(args.output.parent/"execution","Read the explicitly selected R1 device for electrical checks; no actuator or firmware commands") as record:
        start=time.monotonic();last_display=start;count=0;previous=None
        with serial.Serial(args.port,115200,timeout=.25) as port,args.output.open("x") as stream:
            while time.monotonic()-start<args.seconds:
                raw=port.readline(4097)
                if not raw:continue
                captured={"received_utc":datetime.now(timezone.utc).isoformat(),"host_monotonic_ns":time.monotonic_ns()}
                try:
                    message=json.loads(raw)
                    if not isinstance(message,dict):
                        raise ValueError("Expected a JSON object")
                    if message.get("type")!="sample":
                        stream.write(json.dumps({**captured,"message":message})+"\n")
                        if message.get("type")=="fatal":
                            raise RuntimeError(f"Device stopped: {message.get('reason','unspecified fault')}")
                        continue
                    reading=decode(message)
                    if previous is not None and (
                        reading["seq"]!=previous["seq"]+1 or reading["device_us"]<=previous["device_us"]
                    ):
                        reading["valid"]=False
                        reading["flags"].append("sequence_or_time_discontinuity")
                    previous=reading;count+=1
                    stream.write(json.dumps({**captured,"frame":message,"decoded":reading})+"\n")
                    now=time.monotonic()
                    if now-last_display>=.5:
                        values=" ".join(f"CH{i}: {value:.2f}" if value is not None else f"CH{i}: FAULT" for i,value in enumerate(reading["conductance_us"]))
                        state="valid" if reading["valid"] else " / ".join(reading["flags"])
                        print(f"{values} µS  |  {state}  |  received {count/(now-start):.1f} frames/s",flush=True)
                        stream.flush();last_display=now
                except (ValueError,TypeError,KeyError) as error:
                    stream.write(json.dumps({**captured,"parse_error":str(error),"raw_hex":raw.hex()})+"\n")
                    print(f"Invalid frame: {error}",file=sys.stderr)
            record["received_sample_frames"]=count
            record["raw_file"]=str(args.output)
            print(f"Saved {count} sample frames to {args.output}. Values are conductance, not force.")


if __name__=="__main__":
    try:main()
    except KeyboardInterrupt:
        print("\nStopped by operator; raw data retained.",file=sys.stderr)
        raise SystemExit(130)
