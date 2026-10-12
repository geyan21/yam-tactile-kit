#!/usr/bin/python3
"""Recheck O1 raw images/metadata and produce unavailable-aware marker observations."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from optical_core import SCHEMA, digest, config_hash, read_pgm, observe, metadata_faults, nail_signals, validate_config


def load_reference(path):
    ref = json.loads(path.read_text())
    if ref.get("schema") != "yam-o1-marker-reference/1" or ref.get("evidence_kind") != "physical_setup_unreviewed":
        raise ValueError("Use an identified O1 setup reference")
    if digest(path.parent/"baseline.pgm") != ref["baseline_sha256"]:
        raise ValueError("Baseline image changed")
    if config_hash(validate_config(ref["camera_config"])) != ref["camera_config_sha256"]:
        raise ValueError("Reference camera settings changed")
    if not observe(read_pgm(path.parent/"baseline.pgm"), ref)["available"]:
        raise ValueError("Baseline marker reference is no longer valid")
    return ref


def recording_rows(source, reference):
    source = source.resolve()
    header = json.loads((source/"session.json").read_text())
    receipt = json.loads((source/"receipt.json").read_text())
    if header.get("schema") != SCHEMA or header.get("evidence_kind") != "physical_recording_unreviewed":
        raise ValueError("Force/contact processing requires a physical O1 capture, not setup or synthetic data")
    if not receipt.get("capture_complete"):
        raise ValueError("Capture incomplete; retain its evidence and failure")
    for name in ("session.json", "frames.jsonl"):
        if receipt.get("files_sha256", {}).get(name) != digest(source/name):
            raise ValueError("Capture index or header changed")
    for key in ("specimen", "device_id", "geometry_sha256", "camera_config_sha256"):
        if header.get(key) != reference.get(key):
            raise ValueError("Capture/reference mismatch: "+key)
    if config_hash(validate_config(header["camera_config"])) != reference["camera_config_sha256"]:
        raise ValueError("Camera configuration hash is inconsistent")
    previous_sensor, previous_host, expected_index = None, None, 0
    with (source/"frames.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            faults = []
            if row["index"] != expected_index:
                faults.append("frame_index_gap")
            expected_index = row["index"]+1
            if previous_host is not None and row["host_elapsed_s"] <= previous_host:
                faults.append("host_time_not_increasing")
            previous_host = row["host_elapsed_s"]
            faults += metadata_faults(row.get("metadata", {}), header["camera_config"], row["host_monotonic_ns"], previous_sensor)
            previous_sensor = row.get("metadata", {}).get("SensorTimestamp", previous_sensor)
            observed = {"features": None}
            try:
                for kind in ("blue", "colour"):
                    path = (source/row[kind+"_path"]).resolve()
                    if not path.is_relative_to(source) or digest(path) != row[kind+"_sha256"]:
                        raise ValueError("Image missing or changed")
                image = read_pgm(source/row["blue_path"])
                if list(image[:2]) != reference["camera_config"]["save_roi"][2:]:
                    raise ValueError("Image size changed")
                observed = observe(image, reference)
                faults += observed["faults"]
            except (OSError, ValueError, KeyError) as error:
                faults.append("image_error:"+str(error))
            adc = row.get("adc")
            nails = nail_signals(adc.get("raw") if isinstance(adc, dict) else None)
            faults += nails["faults"]
            if isinstance(adc, dict):
                if not (row["host_monotonic_ns"] <= adc["start_monotonic_ns"] <= adc["end_monotonic_ns"]
                        <= row["host_monotonic_ns"]+50000000):
                    faults.append("nail_capture_skew_over_50ms")
            available = not faults
            yield header, {"index": row["index"], "host_elapsed_s": row["host_elapsed_s"],
                           "available": available, "faults": sorted(set(faults)),
                           "features": nails["signals"]+observed["features"] if available else None,
                           "marker_observation": observed, "nail_observation": nails,
                           "blue_path": row["blue_path"]}
    if expected_index != receipt["frames"]:
        raise ValueError("Frame count differs from completed capture receipt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output")
    reference = load_reference(args.reference)
    with execution(ROOT/"build/records", "Recompute optical marker and nail observations from the lossless images and raw ADC; preserve missed markers, clipping, timing and configuration faults"):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        count, unavailable = 0, 0
        with args.output.open("x") as stream:
            stream.write(json.dumps({"schema": "yam-o1-observations/1", "evidence_kind": "physical_features_unreviewed",
                                     "reference_sha256": digest(args.reference), "capture_receipt_sha256": digest(args.capture/"receipt.json"),
                                     "scope": "Pixel motion, log marker area and apparent nail conductance; no force or contact calibration"})+"\n")
            for _, row in recording_rows(args.capture, reference):
                stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False)+"\n")
                count += 1; unavailable += not row["available"]
        print(json.dumps({"frames": count, "unavailable": unavailable, "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
