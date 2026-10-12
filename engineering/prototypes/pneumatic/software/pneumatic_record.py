#!/usr/bin/python3
"""Record one explicitly selected P1 USB port, preserving raw errors and receipts."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from pneumatic_protocol import Decoder, PROTOCOL


def no_constant(value):
    raise ValueError("Nonfinite JSON value: "+value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("port", "specimen", "session", "condition"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--kind", choices=("physical", "electronics"), required=True)
    args = parser.parse_args()
    receipt = args.output.with_suffix(args.output.suffix+".receipt.json")
    if args.output.exists() or receipt.exists() or not args.geometry.is_file():
        parser.error("Choose a new output and the actual assembly/geometry manifest")
    if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 3600:
        parser.error("Use a 1..3600 second bounded recording")
    if any(not value.strip() or "REPLACE" in value.upper() for value in (args.specimen, args.session, args.condition)):
        parser.error("Use actual specimen/session/condition identities")
    identity = {"specimen": args.specimen, "session_id": args.session, "condition": args.condition,
                "geometry_sha256": hashlib.sha256(args.geometry.read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    import serial
    decoder, completed, reason = Decoder(), False, None
    with execution(args.output.parent/"execution", "Read the explicitly selected P1 sensor port; preserve raw packets and interruptions, without sending actuator commands") as record:
        record["port"] = args.port
        try:
            with serial.Serial(args.port, 115200, timeout=.25) as port, args.output.open("x") as stream:
                header = {"type": "session", "schema": "yam-p1-recording/1", "protocol": PROTOCOL, **identity,
                          "evidence_kind": "physical_recording_unreviewed" if args.kind == "physical" else "electronics_test",
                          "created_utc": datetime.now(timezone.utc).isoformat(), "force_calibrated": False}
                stream.write(json.dumps(header)+"\n")
                start, last_report = time.monotonic(), time.monotonic()
                while time.monotonic()-start < args.seconds:
                    raw = port.read_until(b"\n", size=8193)
                    row = {"host_elapsed_s": time.monotonic()-start}
                    if not raw:
                        row["recording_error"] = "serial_timeout"
                        decoder.invalidate("serial_timeout")
                    else:
                        row["raw_hex"] = raw.hex()
                        try:
                            if len(raw) > 8192 or not raw.endswith(b"\n"):
                                raise ValueError("Incomplete or oversized serial packet")
                            message = json.loads(raw, parse_constant=no_constant)
                            row["message"] = message
                            row["validation"] = decoder.accept(message)
                        except (ValueError, TypeError, KeyError, AttributeError) as error:
                            row["recording_error"] = str(error)
                            decoder.invalidate("malformed_serial_record")
                    stream.write(json.dumps(row, allow_nan=False)+"\n")
                    if time.monotonic()-last_report >= 1:
                        stream.flush()
                        print(f"P1: {decoder.sample_count} frames, {decoder.unavailable_count} unavailable; force uncalibrated", flush=True)
                        last_report = time.monotonic()
                completed = True
        except BaseException as error:
            reason = type(error).__name__+": "+str(error)
            if isinstance(error, KeyboardInterrupt):
                record["intentional_stop_requests"].append("Operator interrupted this P1 recording")
            raise
        finally:
            result = {"schema": "yam-p1-recording-receipt/1", **identity, **decoder.finish(),
                      "requested_duration_s": args.seconds, "capture_complete": completed, "stop_reason": reason}
            if args.output.exists():
                result["sha256"] = hashlib.sha256(args.output.read_bytes()).hexdigest()
                with receipt.open("x") as stream:
                    json.dump(result, stream, indent=2); stream.write("\n")
            record["result"] = result
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
