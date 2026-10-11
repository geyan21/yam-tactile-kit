#!/usr/bin/python3
"""Record a declared K1 port, preserving raw packets and every decoder failure."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from capacitive_protocol import Decoder, PROTOCOL


def reject_constant(value):
    raise ValueError("Nonfinite JSON constant: "+value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--specimen", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()
    if args.output.exists() or not math.isfinite(args.seconds) or not 1 <= args.seconds <= 3600:
        parser.error("Use a new output file and a 1..3600 second duration")
    if any(not v.strip() or "REPLACE" in v.upper() for v in (args.specimen, args.condition)):
        parser.error("Give actual specimen and condition identifiers")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    import serial
    decoder = Decoder()
    with execution(args.output.parent / "execution", "Record a user-selected K1 USB port with no actuator commands or automatic force/contact claims") as record:
        record["port"] = args.port
        with args.output.open("x") as stream, serial.Serial(args.port, 115200, timeout=.25) as port:
            stream.write(json.dumps({"type": "session", "protocol": PROTOCOL,
                                     "specimen": args.specimen, "condition": args.condition,
                                     "started_utc": datetime.now(timezone.utc).isoformat(),
                                     "force_calibrated": False, "contact_calibrated": False})+"\n")
            start = time.monotonic()
            counts = {"received": 0, "decoded_samples": 0, "unavailable_frames": 0, "rejected": 0}
            complete = False
            try:
                while time.monotonic()-start < args.seconds:
                    raw = port.read_until(b"\n", size=65537)
                    if not raw:
                        continue
                    counts["received"] += 1
                    entry = {"host_elapsed_s": time.monotonic()-start, "raw_line": raw.decode("utf-8", errors="replace")}
                    try:
                        if len(raw) > 65536 or not raw.endswith(b"\n"):
                            raise ValueError("Incomplete or oversized packet")
                        packet = json.loads(raw, parse_constant=reject_constant)
                        entry["decoded"] = decoder.accept(packet)
                        if entry["decoded"]["type"] == "sample":
                            counts["decoded_samples"] += 1
                            if not entry["decoded"]["complete_finger_available"]:
                                counts["unavailable_frames"] += 1
                    except (ValueError, TypeError, KeyError, AttributeError) as error:
                        counts["rejected"] += 1
                        entry["decode_error"] = str(error)
                    stream.write(json.dumps(entry, allow_nan=False)+"\n")
                    stream.flush()
                complete = True
            except KeyboardInterrupt:
                record["intentional_stop_requests"].append("Operator interrupted this K1 recording")
            finally:
                stream.write(json.dumps({"type": "record_end", "complete_duration": complete, **counts})+"\n")
                record["result"] = {"complete_duration": complete, **counts, "output": str(args.output)}
                print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
