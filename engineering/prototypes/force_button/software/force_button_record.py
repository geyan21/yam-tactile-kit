#!/usr/bin/python3
"""Record FB1 raw USB data from the selected port, preserving faults and gaps."""

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
from force_button_protocol import Decoder, PROTOCOL


def no_constant(value):
    raise ValueError("Nonfinite JSON constant: "+value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--specimen", required=True)
    parser.add_argument("--session", required=True, help="Independent bench-session identity")
    parser.add_argument("--condition", required=True)
    parser.add_argument("--geometry", type=Path, required=True, help="Actual build checkpoint or geometry manifest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=15)
    args = parser.parse_args()
    if args.output.exists() or not math.isfinite(args.seconds) or not 3 <= args.seconds <= 3600:
        parser.error("Use a new file and 3..3600 seconds")
    if any(not v.strip() or "REPLACE" in v.upper() for v in (args.specimen, args.condition, args.session)):
        parser.error("Enter actual specimen and condition identities")
    if not args.geometry.is_file():
        parser.error("--geometry must identify the actual build file")
    geometry_hash = hashlib.sha256(args.geometry.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    import serial
    decoder = Decoder()
    with execution(args.output.parent / "execution", "Record one explicitly selected FB1 USB port without actuator commands; retain raw data and reject unavailable force estimates") as record:
        record["port"] = args.port
        with args.output.open("x") as stream, serial.Serial(args.port, 115200, timeout=.25) as port:
            stream.write(json.dumps({"type": "session", "schema": "yam-fb1-recording/1", "protocol": PROTOCOL,
                                     "evidence_kind": "physical_recording_unreviewed", "specimen": args.specimen,
                                     "condition": args.condition, "session_id": args.session, "geometry_sha256": geometry_hash,
                                     "started_utc": datetime.now(timezone.utc).isoformat()})+"\n")
            start, complete = time.monotonic(), False
            counts = {"received": 0, "samples": 0, "unavailable": 0, "rejected": 0, "serial_timeouts": 0}
            try:
                while time.monotonic()-start < args.seconds:
                    raw = port.read_until(b"\n", size=16385)
                    entry = {"host_elapsed_s": time.monotonic()-start}
                    if not raw:
                        counts["serial_timeouts"] += 1
                        entry["recording_error"] = "serial_timeout"
                    else:
                        counts["received"] += 1
                        entry["raw_line"] = raw.decode("utf-8", errors="replace")
                        try:
                            if len(raw) > 16384 or not raw.endswith(b"\n"):
                                raise ValueError("Incomplete or oversized packet")
                            packet = json.loads(raw, parse_constant=no_constant)
                            entry["decoded"] = decoder.accept(packet)
                            if entry["decoded"]["type"] == "sample":
                                counts["samples"] += 1
                                counts["unavailable"] += not entry["decoded"]["available"]
                        except (ValueError, TypeError, KeyError, AttributeError) as error:
                            counts["rejected"] += 1
                            entry["decode_error"] = str(error)
                    stream.write(json.dumps(entry, allow_nan=False)+"\n")
                    stream.flush()
                complete = True
            except KeyboardInterrupt:
                record["intentional_stop_requests"].append("Operator interrupted this FB1 recording")
            finally:
                stream.write(json.dumps({"type": "record_end", "complete_duration": complete,
                                         "duration_s": time.monotonic()-start, **counts})+"\n")
                record["result"] = {"complete_duration": complete, **counts, "output": str(args.output)}
                print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
