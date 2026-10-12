"""Extract stationary F1 signals from complete, independently revalidated frames."""

import json
from pathlib import Path
import statistics

from capacitive_force import digest, finite, identity, no_constant
from f1_protocol import FrameAssembler, PROTOCOL

RF_OHM = (499., 4990., 24900., 39200.)
# Column membership follows the actual R3/R4 routed taxel map, including
# the reversed CH4/CH5 allocation. The order within a site is immaterial
# only for this sum; preserve all 64 row-major signals separately.
COLUMNS = ((0, 1), (2, 3), (4, 5, 6), (7, 8, 9), (13, 14, 15), (10, 11, 12))


def config_hash(config):
    import hashlib
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def frame_signals(pixels, config):
    result = [None]*64
    reference = finite(config["nominal_reference_v"], "nominal reference voltage")
    if not 0 < reference <= 5:
        raise ValueError("Invalid reference voltage")
    for pixel in pixels:
        index = pixel["row"]*16+pixel["column"]
        delta = statistics.mean(pixel["baseline"]["codes"])-statistics.mean(pixel["active"]["codes"])
        result[index] = delta*reference/65536/RF_OHM[pixel["gain"]]*1e9
    if any(value is None for value in result):
        raise ValueError("Incomplete matrix signal")
    sums = [sum(result[row*16+column] for row in range(4) for column in columns) for columns in COLUMNS]
    return result, sums


def extract(path, manifest, trial):
    """A bad hold stays unavailable; recorded validator claims are not trusted."""
    receipt_path = path.with_suffix(path.suffix+".receipt.json")
    receipt = json.loads(receipt_path.read_text(), parse_constant=no_constant) if receipt_path.is_file() else None
    low, high = [finite(v, "stationary window") for v in trial["window_host_s"]]
    if low < 2 or high-low < 10:
        raise ValueError("Allow startup and at least ten seconds of stationary data")
    decoder, header, previous = FrameAssembler(), None, None
    pixels, frames, faults, configurations = [], [], [], set()
    frame_start = None
    with path.open() as stream:
        for line in stream:
            item = json.loads(line, parse_constant=no_constant)
            if item.get("type") == "session":
                if header is not None:
                    raise ValueError("Multiple recording sessions")
                header = item
                continue
            when = finite(item.get("host_elapsed_s"), "host elapsed time")
            active = low <= when <= high
            if previous is not None and when < previous:
                faults.append("host_time_reversal")
            previous = when
            message = item.get("message")
            if not isinstance(message, dict):
                decoder.invalidate("malformed_or_missing_serial_record")
                if active:
                    faults.append("recording_error")
                continue
            try:
                verdict = decoder.accept(message)
                kind = message["kind"]
                if active and (not verdict["accepted"] or verdict.get("flags")):
                    faults.extend(verdict.get("flags") or ["rejected_packet"])
                if kind == "hello":
                    pixels, frame_start = [], None
                elif kind == "frame_begin":
                    pixels, frame_start = [], when
                elif kind == "pixel":
                    pixels.append(message)
                elif kind == "frame_end" and active:
                    if verdict["complete"] and not verdict["flags"] and frame_start is not None and frame_start >= low:
                        config = decoder.config
                        configurations.add(config_hash(config))
                        pixel_values, sums = frame_signals(pixels, config)
                        frames.append({"start_s": frame_start, "end_s": when,
                                       "pixel_na": pixel_values, "site_na": sums})
                    elif frame_start is None or frame_start >= low:
                        faults.append("incomplete_or_faulty_frame")
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                decoder.invalidate("invalid_raw_packet")
                if active:
                    faults.append("invalid_raw_packet:"+type(error).__name__)
    if (header is None or header.get("schema") != "yam-f1-recording/2" or header.get("protocol") != PROTOCOL
            or header.get("evidence_kind") != "physical_recording_unreviewed"):
        raise ValueError("Use identified physical F1 version-2 recordings, not electrical dummy data")
    for key in ("specimen", "session_id", "geometry_sha256"):
        identity(manifest.get(key), key)
        if header.get(key) != manifest[key]:
            raise ValueError("Mixed "+key)
    if header.get("condition") != trial["condition_id"]:
        raise ValueError("Recording condition differs from trial")
    if (receipt is None or receipt.get("schema") != "yam-f1-recording-receipt/2"
            or receipt.get("sha256") != digest(path) or receipt.get("capture_complete") is not True
            or finite(receipt.get("requested_duration_s", 0), "duration") < high):
        faults.append("missing_or_incomplete_recording_receipt")
    elif any(receipt.get(key) != header.get(key) for key in ("specimen", "session_id", "geometry_sha256", "condition")):
        faults.append("receipt_identity_mismatch")
    if len(configurations) != 1:
        faults.append("missing_or_changed_scan_configuration")
    if len(frames) < 10:
        faults.append("fewer_than_ten_complete_frames")
    durations = [row["end_s"]-row["start_s"] for row in frames]
    intervals = [b["start_s"]-a["start_s"] for a, b in zip(frames, frames[1:])]
    median_interval = statistics.median(intervals) if intervals else None
    gap_limit = min(2., max(.2, 2*median_interval)) if median_interval is not None else .2
    if (not frames or frames[0]["start_s"] > low+gap_limit or frames[-1]["end_s"] < high-gap_limit
            or any(value > gap_limit for value in intervals)
            or any(value > 2. for value in durations)):
        faults.append("window_not_continuously_observed")
    return {
        "frames": len(frames), "available": not faults, "faults": sorted(set(faults)),
        "configuration_sha256": next(iter(configurations)) if len(configurations) == 1 else None,
        "mean_signal_na": [statistics.mean(row["site_na"][i] for row in frames) for i in range(6)] if frames else None,
        "stdev_signal_na": [statistics.stdev(row["site_na"][i] for row in frames) for i in range(6)] if len(frames) > 1 else None,
        "mean_pixel_na": [statistics.mean(row["pixel_na"][i] for row in frames) for i in range(64)] if frames else None,
        "median_frame_interval_s": median_interval,
        "maximum_frame_acquisition_s": max(durations) if durations else None,
        "signal_definition": "Sum of sequential baseline-minus-active ADC phases divided by nominal feedback resistance, expressed as apparent nA; not independent measured pixel currents or force.",
    }
