#!/usr/bin/python3
"""Apply a frozen contact model to one selected sensor stream; no auto-zero or robot commands."""

import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

from contact_core import ContactWindow, classify
from contact_io import bind_model
from tactile_kit.records import execution


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",required=True)
    parser.add_argument("--model",type=Path,required=True)
    parser.add_argument("--specimen",required=True)
    parser.add_argument("--variant",required=True)
    parser.add_argument("--pose-id",required=True)
    parser.add_argument("--transfer-experiment",action="store_true")
    parser.add_argument("--seconds",type=float,default=60)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if not math.isfinite(args.seconds) or not 0<args.seconds<=3600:
        parser.error("Duration must be 0..3600 seconds")
    model_bytes=args.model.read_bytes();model=json.loads(model_bytes)
    bind_model(model,model["sensor"],args.specimen,args.pose_id,args.variant,
               [entry["channel"] for entry in model["thresholds"]],args.transfer_experiment)
    window=ContactWindow(model["sensor"],model["configuration"])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    import serial
    with execution(args.output.with_suffix(".execution"),"Display and record the frozen contact classifier on the explicitly selected device; no actuator commands") as record:
        record["model_sha256"]=hashlib.sha256(model_bytes).hexdigest()
        with args.output.open("x") as output,serial.Serial(args.port,115200,timeout=.08) as port:
            output.write(json.dumps({
                "type":"session","schema":"yam-contact-live/1","model_sha256":record["model_sha256"],
                "specimen":args.specimen,"variant":args.variant,"pose_id":args.pose_id,
                "transfer_experiment":args.transfer_experiment,
                "started_utc":datetime.now(timezone.utc).isoformat(),
                "robot_gripper_qualified":False,
            })+"\n")
            start=time.monotonic();last_display=start;frames=0;faults=0
            while time.monotonic()-start<args.seconds:
                raw=port.readline(4097)
                captured={"received_utc":datetime.now(timezone.utc).isoformat(),"host_monotonic_ns":time.monotonic_ns()}
                frame=None
                try:
                    if not raw:raise ValueError("serial_timeout")
                    if len(raw)>4096:raise ValueError("frame_too_long")
                    frame=json.loads(raw)
                    if not isinstance(frame,dict):raise ValueError("non_object_frame")
                    if frame.get("type")!="sample":
                        output.write(json.dumps({**captured,"message":frame,"contact":None})+"\n")
                        window.fault("device_event")
                        if frame.get("type")=="fatal":raise RuntimeError(frame.get("reason","Device fault"))
                        continue
                    result=window.feed(frame);frames+=1
                except (ValueError,TypeError,KeyError) as error:
                    result=window.fault(str(error))
                decision=classify(result["features"],model) if result["status"]=="ready" else {"contact":None,"active_channels":[]}
                faults+=int(result["status"]=="fault")
                output.write(json.dumps({
                    **captured,"frame":frame,"raw_hex":raw.hex() if frame is None else None,
                    "result":result,**decision,"robot_gripper_qualified":False,"force_n":None,
                },allow_nan=False)+"\n")
                if time.monotonic()-last_display>=.25:
                    print(f"contact={decision['contact']}  channels={decision['active_channels']}  status={result['status']}  flags={result['flags']}",flush=True)
                    output.flush();last_display=time.monotonic()
            record["frames"]=frames;record["fault_events"]=faults
            print(f"Saved {frames} frames and {faults} fault events. Contact decisions do not establish robot qualification.")


if __name__=="__main__":
    try:main()
    except KeyboardInterrupt:
        print("Stopped by operator; records retained.",file=sys.stderr)
        raise SystemExit(130)
