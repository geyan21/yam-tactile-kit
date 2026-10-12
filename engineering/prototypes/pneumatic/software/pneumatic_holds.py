"""Read identified P1 stationary holds, independently checking every raw packet."""

import json
from pathlib import Path
import statistics

from capacitive_force import SITES, REGIONS, digest, finite, identity, no_constant, load_axis
from pneumatic_protocol import Decoder, PROTOCOL, config_hash


def extract(recording, manifest, trial):
    low, high = [finite(value, "stationary window") for value in trial["window_host_s"]]
    if low < 2 or high-low < 10:
        raise ValueError("Allow synchronization and at least ten stationary seconds")
    decoder, header, previous = Decoder(), None, None
    frames, faults, boots, devices = [], [], set(), set()
    with recording.open() as stream:
        for line in stream:
            item = json.loads(line, parse_constant=no_constant)
            if item.get("type") == "session":
                if header is not None:
                    raise ValueError("Multiple sessions in one recording")
                header = item
                continue
            when = finite(item.get("host_elapsed_s"), "host elapsed time")
            active = low <= when <= high
            if previous is not None and when < previous:
                faults.append("host_time_reversal")
            previous = when
            try:
                raw = bytes.fromhex(item["raw_hex"])
                if len(raw) > 8192 or not raw.endswith(b"\n"):
                    raise ValueError("Incomplete raw packet")
                packet = json.loads(raw, parse_constant=no_constant)
                observed = decoder.accept(packet)
                if not active:
                    continue
                if observed["type"] == "hello":
                    if observed["restarted"]:
                        faults.append("device_restarted")
                elif observed["complete_finger_available"]:
                    frames.append({"when": when, "signals": observed["signals"], "scan_us": observed["scan_us"]})
                    boots.add(observed["boot_id"])
                    devices.add(decoder.hello["device_id"])
                else:
                    faults.extend(reason for cell in observed["cells"] for reason in cell["faults"])
            except (ValueError, TypeError, KeyError, AttributeError):
                decoder.invalidate("invalid_or_missing_raw_packet")
                if active:
                    faults.append("invalid_or_missing_raw_packet")
    if (header is None or header.get("schema") != "yam-p1-recording/1"
            or header.get("protocol") != PROTOCOL or header.get("evidence_kind") != "physical_recording_unreviewed"):
        raise ValueError("P1 calibration requires identified physical recordings; electronic or synthetic data are excluded")
    for key in ("specimen", "session_id", "geometry_sha256"):
        if header.get(key) != manifest[key]:
            raise ValueError("Mixed recording "+key)
    if header.get("condition") != trial["condition_id"]:
        raise ValueError("Recording condition differs from the trial")
    receipt_path = recording.with_suffix(recording.suffix+".receipt.json")
    receipt = json.loads(receipt_path.read_text(), parse_constant=no_constant) if receipt_path.is_file() else None
    if (receipt is None or receipt.get("schema") != "yam-p1-recording-receipt/1"
            or receipt.get("sha256") != digest(recording) or receipt.get("capture_complete") is not True
            or finite(receipt.get("requested_duration_s", 0), "duration") < high):
        faults.append("missing_or_incomplete_capture_receipt")
    elif any(receipt.get(key) != header.get(key) for key in ("specimen", "session_id", "condition", "geometry_sha256")):
        faults.append("capture_receipt_identity")
    if len(boots) != 1 or len(devices) != 1:
        faults.append("missing_or_changed_device_identity")
    if receipt is not None and devices and receipt.get("device_id") not in devices:
        faults.append("capture_receipt_device")
    if len(frames) < 100:
        faults.append("fewer_than_100_valid_frames")
    times = [row["when"] for row in frames]
    if (not times or times[0] > low+.1 or times[-1] < high-.1
            or any(b-a > .1 for a, b in zip(times, times[1:]))):
        faults.append("window_not_continuously_observed")
    return {"available": not faults, "faults": sorted(set(faults)), "frames": len(frames),
            "device_id": next(iter(devices)) if len(devices) == 1 else None,
            "configuration_sha256": config_hash(decoder.hello["config"]) if decoder.hello else None,
            "mean_signal": [statistics.mean(row["signals"][i] for row in frames) for i in range(6)] if frames else None,
            "stdev_signal": [statistics.stdev(row["signals"][i] for row in frames) for i in range(6)] if len(frames) > 1 else None,
            "maximum_scan_us": max(row["scan_us"] for row in frames) if frames else None}


def load_trials(path, phase):
    manifest = json.loads(path.read_text(), parse_constant=no_constant)
    if (manifest.get("schema") != "yam-p1-force-trials/1" or manifest.get("phase") != phase
            or manifest.get("evidence_kind") != "physical"):
        raise ValueError("Use a physical P1 manifest for the requested phase")
    for key in ("specimen", "session_id", "reference_id", "geometry_sha256"):
        identity(manifest.get(key), key)
    if len(manifest["geometry_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in manifest["geometry_sha256"]):
        raise ValueError("Give the actual geometry SHA256")
    manifest["force_axis"] = load_axis(manifest.get("force_axis"))
    uncertainty = finite(manifest.get("reference_uncertainty_n"), "reference uncertainty")
    if not 0 < uncertainty <= .05:
        raise ValueError("Use a documented reference uncertainty no greater than 0.05 N")
    repetitions = manifest.get("minimum_holds_per_level")
    if type(repetitions) is not int or repetitions < 3:
        raise ValueError("At least three separate holds per force level")
    context = manifest.get("calibration_context")
    if not isinstance(context, dict):
        raise ValueError("Identify the actual hose set, pose, electronics and temperature band")
    for key in ("hose_set_id", "finger_pose_id", "electronics_id", "material_process_id"):
        identity(context.get(key), key)
    lengths, temperatures = context.get("tube_lengths_mm"), context.get("temperature_band_c")
    if not isinstance(lengths, list) or len(lengths) != 8 or any(not 10 <= finite(v, "tube length") <= 1000 for v in lengths):
        raise ValueError("Record eight measured tube lengths")
    if not isinstance(temperatures, list) or len(temperatures) != 2 or not (
            -10 <= finite(temperatures[0], "minimum temperature") < finite(temperatures[1], "maximum temperature") <= 60):
        raise ValueError("Declare the studied temperature band")
    trials = manifest.get("trials")
    if not isinstance(trials, list) or not trials:
        raise ValueError("No measured trials supplied")
    if len({t.get("id") for t in trials}) != len(trials) or len({t.get("recording_sha256") for t in trials}) != len(trials):
        raise ValueError("Each hold needs its own identity and separate recording")
    rows, base = [], path.parent.resolve()
    for trial in trials:
        identity(trial.get("id"), "trial")
        identity(trial.get("condition_id"), "condition")
        sites = trial.get("sites")
        if not isinstance(sites, list) or not sites or len(set(sites)) != len(sites) or set(sites)-set(SITES):
            raise ValueError("Declare contact sites CH0..CH5")
        if phase == "train" and len(sites) != 1:
            raise ValueError("Use separate-site training and reserve mixtures for independent testing")
        if trial.get("region") not in (*REGIONS, "mixture"):
            raise ValueError("Declare the physical contact region")
        temperature = finite(trial.get("temperature_c"), "measured temperature")
        if not temperatures[0] <= temperature <= temperatures[1]:
            raise ValueError("Hold temperature is outside the declared context")
        recording = (base/trial["recording"]).resolve()
        if not recording.is_relative_to(base) or not recording.is_file() or recording.stat().st_size > 64*1024*1024:
            raise ValueError("Use a bounded recording beneath the trial manifest directory")
        if digest(recording) != trial.get("recording_sha256"):
            raise ValueError("Recording changed")
        window = trial.get("window_host_s")
        if not isinstance(window, list) or len(window) != 2:
            raise ValueError("Declare a stationary time window")
        before, after = [finite(trial.get(key), key) for key in ("reference_before_n", "reference_after_n")]
        if min(before, after) < 0 or max(before, after) > 20.5:
            raise ValueError("This pilot covers positive force through 20 N")
        observed = extract(recording, manifest, trial)
        reference = (before+after)/2
        if abs(after-before) > max(.05, .02*max(reference, .2)):
            observed["faults"].append("reference_not_stationary")
            observed["available"] = False
        rows.append({"id": trial["id"], "condition_id": trial["condition_id"], "sites": sites,
                     "region": trial["region"], "recording_sha256": trial["recording_sha256"],
                     "reference_n": reference, "reference_bound_n": uncertainty+abs(after-before)/2,
                     "temperature_c": temperature, **observed})
    return manifest, rows
