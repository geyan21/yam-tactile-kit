#!/usr/bin/python3
"""Guided, off-robot static-force collection from an explicitly selected R1 serial port."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from signals import decode

LEVELS = [0, .2, .5, 1, 2, 5, 2, 1, .5, .2, 0]
LEVELS_20 = [0, .2, .5, 1, 2, 5, 10, 15, 20, 15, 10, 5, 2, 1, .5, .2, 0]


def plan(channels, maximum_n=20):
    rows = []
    for cycle in range(3):
        for channel in channels:
            levels = LEVELS if maximum_n==5 else LEVELS_20
            for level_index, force in enumerate(levels):
                rows.append({
                    "trial_id": f"c{cycle+1}_ch{channel}_p{level_index:02d}",
                    "cycle": cycle+1, "channel": channel, "target_n": force,
                    "phase": "loading" if level_index <= levels.index(maximum_n) else "unloading",
                    "split": "train" if cycle < 2 else "test",
                    "group": f"cycle-{cycle+1}",
                    "range_n": maximum_n,
                })
    return rows


def reference_reading(prompt, maximum_n):
    while True:
        text = input(prompt).strip()
        if text.lower() == "q":
            raise KeyboardInterrupt
        try:
            value = float(text)
            if math.isfinite(value) and 0 <= value <= maximum_n+.5:
                return value
        except ValueError:
            pass
        print(f"Enter the observed normal force in N, from 0 to {maximum_n+.5}, or q to stop.")


def sample_window(port, raw_stream, duration):
    end = time.monotonic()+duration
    samples, rejected = [], 0
    previous = None
    while time.monotonic() < end:
        raw = port.readline(4097)
        if not raw:
            continue
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            message = json.loads(raw)
            if not isinstance(message,dict):
                raise ValueError("Expected a JSON object")
            if message.get("type") != "sample":
                raw_stream.write(json.dumps({"received_utc":timestamp,"message":message})+"\n")
                if message.get("type")=="fatal":
                    rejected+=1
                continue
            decoded = decode(message)
            if previous is not None and (
                decoded["seq"] != previous["seq"]+1 or decoded["device_us"] <= previous["device_us"]
            ):
                decoded["valid"] = False
                decoded["flags"].append("sequence_or_time_discontinuity")
            previous = decoded
            raw_stream.write(json.dumps({
                "received_utc": timestamp, "host_monotonic_ns": time.monotonic_ns(),
                "frame": message, "decoded": decoded,
            })+"\n")
            if decoded["valid"]:
                samples.append(decoded)
            else:
                rejected += 1
        except (ValueError, TypeError, KeyError):
            rejected += 1
            raw_stream.write(json.dumps({"received_utc": timestamp, "parse_error_hex": raw[:4097].hex()})+"\n")
    raw_stream.flush()
    return samples, rejected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Explicit serial device; never auto-selected or scanned")
    parser.add_argument("--output", type=Path, required=True, help="New session directory; existing directories are refused")
    parser.add_argument("--specimen", required=True)
    parser.add_argument("--material", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reference-id", required=True, help="Reference sensor/scale and calibration record identifier")
    parser.add_argument("--reference-uncertainty-n", type=float, required=True)
    parser.add_argument("--channels", default="0,1,2,3,4,5")
    parser.add_argument("--max-force-n", type=int, choices=(5,20), default=20)
    parser.add_argument("--probe", required=True, help="Actual contact fixture, shape, size, and orientation")
    parser.add_argument("--plan-only", action="store_true", help="Write the plan without opening any serial port")
    args = parser.parse_args()
    channels = [int(item) for item in args.channels.split(",")]
    if len(set(channels)) != len(channels) or not channels or any(item not in range(6) for item in channels):
        parser.error("Channels must be unique integers in 0..5")
    if not math.isfinite(args.reference_uncertainty_n) or not 0 < args.reference_uncertainty_n <= .05:
        parser.error("For this pilot, use a reference with stated uncertainty >0 and <=0.05 N")
    if not args.plan_only and not args.port:
        parser.error("--port is required for acquisition")
    args.output.mkdir(parents=True, exist_ok=False)
    schedule = plan(channels,args.max_force_n)
    metadata = {
        "schema": "yam-bench/1", "evidence_kind": "physical" if not args.plan_only else "plan_only",
        "created_utc": datetime.now(timezone.utc).isoformat(), "specimen": args.specimen,
        "material": args.material, "operator": args.operator, "reference_id": args.reference_id,
        "reference_uncertainty_n": args.reference_uncertainty_n, "port": args.port,
        "channels": channels, "duration_s": 2.0, "settle_s": 1.0,
        "range_n":args.max_force_n, "requested_per_finger_range_n":20, "probe":args.probe,
        "protocol": "Off-robot, one active zone loaded with the recorded fixture. Static reference readings before and after each window.",
        "schedule": schedule,
    }
    (args.output/"session.json").write_text(json.dumps(metadata,indent=2)+"\n")
    if args.plan_only:
        print(f"Wrote {len(schedule)} planned trials to {args.output}")
        return
    import serial
    with execution(args.output/"execution", "Record operator-applied static loads from the explicitly selected R1 device; no actuator commands") as record:
        print("Off-robot static collection. Keep the probe on the named zone and normal to its local surface.")
        print("Enter actual reference readings, not target values. q stops and preserves completed trials.")
        print("A fixed 10 kΩ resistor must first read approximately 100 µS on every cell input.")
        confirmation = input(f"Type touch-check-passed after verifying selected channels {channels} respond and recover: ").strip()
        if confirmation != "touch-check-passed":
            raise ValueError("Six-cell touch check was not confirmed")
        metadata["touch_check_confirmed_utc"] = datetime.now(timezone.utc).isoformat()
        metadata["touch_check_channels"] = channels
        (args.output/"session.json").write_text(json.dumps(metadata,indent=2)+"\n")
        completed = 0
        with serial.Serial(args.port, 115200, timeout=.25) as port, (args.output/"trials.jsonl").open("x") as trials:
            for item in schedule:
                print(f"\n{item['trial_id']}: CH{item['channel']}, target {item['target_n']:.2f} N, {item['phase']}")
                before = reference_reading("Hold steady. Observed force now (N): ",args.max_force_n)
                port.reset_input_buffer()
                with (args.output/f"{item['trial_id']}.jsonl").open("x") as raw_stream:
                    # Settling frames are preserved separately from the analysis window.
                    settle, settle_rejected = sample_window(port, raw_stream, 1.0)
                    samples, rejected = sample_window(port, raw_stream, 2.0)
                after = reference_reading("Observed force at the end of that hold (N): ",args.max_force_n)
                stable = abs(after-before) <= .1
                same_configuration = bool(samples) and all(sample["pull_down_ohm"]==samples[0]["pull_down_ohm"] for sample in samples)
                valid = stable and len(samples) >= 50 and rejected == 0 and same_configuration
                g = [sample["conductance_us"][item["channel"]] for sample in samples]
                row = {
                    **item, "specimen": args.specimen, "material": args.material,
                    "evidence_kind": "physical", "reference_n": (before+after)/2,
                    "reference_before_n":before, "reference_after_n":after,
                    "reference_uncertainty_n":args.reference_uncertainty_n,
                    "valid":valid, "samples":len(samples), "rejected_frames":rejected,
                    "settle_samples":len(settle), "settle_rejected":settle_rejected,
                    "analysis_device_us": [samples[0]["device_us"],samples[-1]["device_us"]] if samples else None,
                    "conductance_us":statistics.median(g) if g else None,
                    "conductance_stdev_us":statistics.stdev(g) if len(g)>1 else None,
                    "raw_file":f"{item['trial_id']}.jsonl",
                    "pull_down_ohm":samples[0]["pull_down_ohm"] if samples else None,
                    "continuity_ohm":100000,
                    "probe":args.probe,
                }
                trials.write(json.dumps(row,allow_nan=False)+"\n");trials.flush()
                completed += 1
                print(f"Saved {len(samples)} valid samples; trial {'accepted for analysis' if valid else 'REJECTED — preserve and repeat in a new session'}.")
                record["completed_trials"] = completed
                if len(samples)<25 or rejected:
                    raise RuntimeError("Acquisition fault: saved the trial and stopped. Repair the readout before another load session.")


if __name__=="__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by operator; saved data retained.",file=sys.stderr)
        raise SystemExit(130)
