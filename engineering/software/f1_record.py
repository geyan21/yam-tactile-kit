#!/usr/bin/python3
"""Record one explicitly selected F1 serial port; preserve incomplete and faulty data."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_protocol import FrameAssembler, PROTOCOL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--specimen", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--source-kind", choices=("physical", "electrical_dummy"), default="physical")
    args = parser.parse_args()
    receipt = args.output.with_suffix(args.output.suffix+".receipt.json")
    if args.output.exists() or receipt.exists():
        parser.error("Choose a new file; previous recordings are preserved")
    if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 3600:
        parser.error("Use a bounded 1-3600 second capture")
    if not args.geometry.is_file():
        parser.error("Select the actual build's geometry/assembly manifest")
    if any(not value.strip() or "REPLACE" in value.upper() for value in (args.specimen, args.condition)):
        parser.error("Supply actual specimen and condition identifiers")
    geometry_hash = hashlib.sha256(args.geometry.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    import serial
    decoder = FrameAssembler()
    count = faults = 0
    completed = False
    stop_reason = None
    with execution(args.output.parent / "execution", "Capture F1 raw phases from the selected sensor port, without writing commands or inferring calibrated force") as record:
        record["port"] = args.port
        try:
            with serial.Serial(args.port, 115200, timeout=.25) as port, args.output.open("x") as stream:
                stream.write(json.dumps({
                    "type": "session", "schema": "yam-f1-recording/1", "protocol": PROTOCOL,
                    "specimen": args.specimen, "condition": args.condition, "geometry_sha256": geometry_hash,
                    "evidence_kind": "physical_recording_unreviewed" if args.source_kind == "physical" else "electrical_dummy_recording",
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "force_calibrated": False,
                })+"\n")
                start = last_report = time.monotonic()
                while time.monotonic()-start < args.seconds:
                    raw = port.readline(8193)
                    stamp = {"received_utc": datetime.now(timezone.utc).isoformat(), "host_monotonic_ns": time.monotonic_ns()}
                    if not raw:
                        stream.write(json.dumps({**stamp, "error": "serial_timeout"})+"\n")
                        faults += 1
                        continue
                    try:
                        if len(raw) > 8192 or not raw.endswith(b"\n"):
                            raise ValueError("Incomplete or oversized serial line")
                        message = json.loads(raw)
                        verdict = decoder.accept(message)
                        stream.write(json.dumps({**stamp, "message": message, "validation": verdict}, allow_nan=False)+"\n")
                        count += 1
                        faults += not verdict["accepted"] or bool(verdict.get("flags"))
                        if message.get("kind") == "error":
                            raise RuntimeError("Firmware stopped capture: "+str(message.get("message")))
                    except (ValueError, TypeError, KeyError) as error:
                        decoder.invalidate("malformed_serial_record")
                        faults += 1
                        stream.write(json.dumps({**stamp, "parse_error": str(error), "raw_hex": raw.hex()})+"\n")
                    if time.monotonic()-last_report >= 1:
                        stream.flush()
                        print(f"F1: {decoder.complete_frames} complete frames; {faults} review events; force uncalibrated", flush=True)
                        last_report = time.monotonic()
                completed = True
        except BaseException as error:
            stop_reason = type(error).__name__+": "+str(error)
            raise
        finally:
            result = {"schema": "yam-f1-recording-receipt/1", **decoder.finish(),
                      "specimen": args.specimen, "condition": args.condition, "geometry_sha256": geometry_hash,
                      "messages": count, "review_events": faults, "capture_complete": completed, "stop_reason": stop_reason}
            if args.output.exists():
                result["sha256"] = hashlib.sha256(args.output.read_bytes()).hexdigest()
                with receipt.open("x") as stream:
                    json.dump(result, stream, indent=2); stream.write("\n")
            record["result"] = result
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
