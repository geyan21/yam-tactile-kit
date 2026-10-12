"""Read O1 physical stationary holds by rechecking their lossless source images."""

import json
from pathlib import Path
import statistics

from capacitive_force import identity, load_axis, no_constant, coverage
from optical_core import finite, digest, config_hash
from optical_process import load_reference, recording_rows

SITES = ("nail0", "nail1", "gel_distal", "gel_middle_distal", "gel_middle_proximal", "gel_proximal")
REGIONS = ("left_nail", "right_nail", "nail_edges_notch", "distal_gel", "middle_gel", "proximal_gel")


def extract(source, reference, manifest, trial):
    low, high = [finite(v, "stationary window") for v in trial["window_host_s"]]
    if low < 2 or high-low < 10:
        raise ValueError("Use at least ten stationary seconds after initial synchronization")
    faults, frames, times, header = [], [], [], None
    for header, row in recording_rows(source, reference):
        for key in ("specimen", "session_id", "geometry_sha256"):
            if header[key] != manifest[key]:
                raise ValueError("Capture/manifest mismatch: "+key)
        if header["condition"] != trial["condition_id"]:
            raise ValueError("Capture condition changed")
        if low <= row["host_elapsed_s"] <= high:
            times.append(row["host_elapsed_s"])
            faults += row["faults"]
            if row["available"]:
                frames.append(row["features"])
    if header is None:
        faults.append("no_recorded_frames")
    period = reference["camera_config"]["frame_duration_us"]/1e6
    if (len(frames) < 80 or not times or times[0] > low+1.5*period or times[-1] < high-1.5*period
            or any(b-a > 1.5*period for a, b in zip(times, times[1:]))):
        faults.append("stationary_window_not_continuously_observed")
    dimensions = 2+3*len(reference["markers"])
    if any(len(row) != dimensions for row in frames):
        raise ValueError("Incomplete marker/nail feature vector")
    return {"available": not faults, "faults": sorted(set(faults)), "frames": len(frames),
            "mean_signal": [statistics.mean(row[i] for row in frames) for i in range(dimensions)] if frames else None,
            "stdev_signal": [statistics.stdev(row[i] for row in frames) for i in range(dimensions)] if len(frames) > 1 else None,
            "sample_features": frames}


def load_trials(path, phase):
    manifest = json.loads(path.read_text(), parse_constant=no_constant)
    if manifest.get("schema") != "yam-o1-force-trials/1" or manifest.get("evidence_kind") != "physical" or manifest.get("phase") != phase:
        raise ValueError("Use an identified physical O1 trial manifest for this phase")
    for key in ("specimen", "session_id", "geometry_sha256", "reference_id"):
        identity(manifest.get(key), key)
    geometry = manifest["geometry_sha256"]
    if len(geometry) != 64 or any(c not in "0123456789abcdef" for c in geometry):
        raise ValueError("Give the actual geometry SHA256")
    manifest["force_axis"] = load_axis(manifest["force_axis"])
    uncertainty = finite(manifest["reference_uncertainty_n"], "force-reference uncertainty")
    if not 0 < uncertainty <= .05:
        raise ValueError("Reference uncertainty must be documented and <=0.05 N")
    if type(manifest["minimum_holds_per_level"]) is not int or manifest["minimum_holds_per_level"] < 3:
        raise ValueError("At least three independent holds per force level")
    context = manifest["calibration_context"]
    for key in ("finger_pose_id", "camera_led_nail_electronics_id", "gel_paint_mirror_process_id"):
        identity(context.get(key), key)
    temperatures = context["temperature_band_c"]
    if len(temperatures) != 2 or not -10 <= finite(temperatures[0], "temperature") < finite(temperatures[1], "temperature") <= 60:
        raise ValueError("Declare a measured temperature band")
    base = path.parent.resolve()
    reference_path = (base/manifest["marker_reference"]).resolve()
    if not reference_path.is_relative_to(base) or digest(reference_path) != manifest["marker_reference_sha256"]:
        raise ValueError("Changed or misplaced marker reference")
    reference = load_reference(reference_path)
    for key in ("specimen", "geometry_sha256"):
        if reference[key] != manifest[key]:
            raise ValueError("Marker reference mismatch: "+key)
    trials = manifest.get("trials")
    if not isinstance(trials, list) or not trials:
        raise ValueError("No measured trials")
    ids, captures, receipts, rows = set(), set(), set(), []
    for trial in trials:
        identity(trial.get("id"), "trial ID"); identity(trial.get("condition_id"), "condition")
        if trial["id"] in ids:
            raise ValueError("Duplicate hold identity")
        ids.add(trial["id"])
        sites = trial["sites"]
        if not sites or len(set(sites)) != len(sites) or set(sites)-set(SITES):
            raise ValueError("Declare the actual nail/gel contact sites")
        if phase == "train" and len(sites) != 1:
            raise ValueError("Reserve contact mixtures for held-out evaluation")
        if trial["region"] not in (*REGIONS, "mixture") or type(trial["contact_expected"]) is not bool:
            raise ValueError("Declare physical region and contact truth")
        temperature = finite(trial["temperature_c"], "measured temperature")
        if not temperatures[0] <= temperature <= temperatures[1]:
            raise ValueError("Temperature outside the declared context")
        capture = (base/trial["capture"]).resolve()
        if not capture.is_relative_to(base) or capture in captures:
            raise ValueError("Each hold needs a separate capture beneath this manifest")
        captures.add(capture)
        receipt = digest(capture/"receipt.json")
        if receipt != trial["capture_receipt_sha256"] or receipt in receipts:
            raise ValueError("Changed or reused capture receipt")
        receipts.add(receipt)
        before, after = [finite(trial[key], key) for key in ("reference_before_n", "reference_after_n")]
        if min(before, after) < 0 or max(before, after) > 20.5:
            raise ValueError("This protocol covers positive force through 20 N")
        reference_force = (before+after)/2
        if ((trial["contact_expected"] and reference_force < .19)
                or (not trial["contact_expected"] and reference_force > .05)):
            raise ValueError("Contact truth and declared test force are inconsistent")
        observed = extract(capture, reference, manifest, trial)
        if abs(before-after) > max(.05, .02*max(reference_force, .2)):
            observed["available"] = False; observed["faults"].append("reference_force_not_stationary")
        rows.append({"id": trial["id"], "sites": sites, "region": trial["region"], "contact_expected": trial["contact_expected"],
                     "capture_receipt_sha256": receipt, "reference_n": reference_force,
                     "reference_bound_n": uncertainty+abs(before-after)/2, "temperature_c": temperature, **observed})
    manifest["device_id"] = reference["device_id"]
    manifest["camera_config_sha256"] = reference["camera_config_sha256"]
    return manifest, rows
