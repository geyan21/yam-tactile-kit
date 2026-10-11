#!/usr/bin/python3
"""Fit and test FB1 stationary-hold force calibration from preserved raw recordings."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from force_button_protocol import Decoder, SETTINGS

LEVELS = (0, .2, .5, 1, 2, 5, 10, 15, 20)
REGIONS = ("left_nail", "right_nail", "nail_edges_notch", "distal_tpu", "middle_tpu", "proximal_tpu")


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Finite number required: "+name)
    return float(value)


def identity(value, name):
    if not isinstance(value, str) or not value.strip() or "REPLACE" in value.upper():
        raise ValueError("Actual identity required: "+name)
    return value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_constant(value):
    raise ValueError("Nonfinite JSON constant: "+value)


def fit_numeric(counts, forces):
    if len(counts) != len(forces) or len(counts) < 6:
        raise ValueError("At least six independent paired holds are required")
    x = [finite(v, "counts") for v in counts]
    y = [finite(v, "force") for v in forces]
    mx, my = sum(x)/len(x), sum(y)/len(y)
    variance = sum((v-mx)**2 for v in x)
    if max(x)-min(x) < 32 or variance <= 0:
        raise ValueError("Insufficient force-dependent count variation")
    slope = sum((a-mx)*(b-my) for a, b in zip(x, y))/variance
    if slope <= 0:
        raise ValueError("Expected increasing counts under positive normal force")
    return {"offset_n": my-slope*mx, "slope_n_per_count": slope}


def predict(model, counts):
    return finite(model["offset_n"], "offset")+finite(model["slope_n_per_count"], "slope")*finite(counts, "counts")


def coverage(rows, repetitions):
    result = []
    for level in sorted(LEVELS):
        selected = [r for r in rows if r["available"] and abs(r["reference_n"]-level) <= max(.05, .03*level)
                    and (level != 20 or r["reference_n"] >= 20)]
        result.append({"target_n": level, "independent_holds": len(selected), "required": repetitions})
    return result, all(r["independent_holds"] >= repetitions for r in result)


def load_trials(path, phase):
    manifest = json.loads(path.read_text(), parse_constant=no_constant)
    if (manifest.get("schema") != "yam-fb1-force-trials/1" or manifest.get("evidence_kind") != "physical"
            or manifest.get("phase") != phase):
        raise ValueError("Use a physical FB1 trial manifest for the requested phase")
    for key in ("specimen", "session_id", "reference_id"):
        identity(manifest.get(key), key)
    if not re.fullmatch(r"[0-9a-f]{64}", manifest.get("geometry_sha256") or ""):
        raise ValueError("Record the exact geometry/checkpoint SHA-256")
    uncertainty = finite(manifest.get("reference_uncertainty_n"), "reference uncertainty")
    if not 0 < uncertainty <= .05:
        raise ValueError("Use a documented reference uncertainty of 0.05 N or better")
    repetitions = manifest.get("minimum_holds_per_level")
    if type(repetitions) is not int or repetitions < 3:
        raise ValueError("At least three independent holds per force level are required")
    trials = manifest.get("trials")
    if not isinstance(trials, list) or not trials:
        raise ValueError("A nonempty planned trial list is required")
    if len({r.get("id") for r in trials}) != len(trials) or len({r.get("recording_sha256") for r in trials}) != len(trials):
        raise ValueError("Use unique trial identities and separate recordings")
    rows, base = [], path.parent.resolve()
    for trial in trials:
        identity(trial.get("id"), "trial")
        identity(trial.get("condition_id"), "condition")
        if trial.get("region") not in REGIONS:
            raise ValueError("Name the nail or TPU region for every hold")
        source = (base/trial["recording"]).resolve()
        if not source.is_relative_to(base) or not source.is_file() or source.stat().st_size > 32*1024*1024:
            raise ValueError("Use a recording below the manifest directory, at most 32 MiB")
        if digest(source) != trial.get("recording_sha256"):
            raise ValueError("Recording SHA-256 mismatch")
        window = trial.get("window_host_s")
        if not isinstance(window, list) or len(window) != 2:
            raise ValueError("Declare the stationary sample window")
        low, high = [finite(v, "window time") for v in window]
        if low < 1.5 or high-low < 2:
            raise ValueError("Allow startup synchronization and at least two seconds of stationary data")
        before = finite(trial.get("reference_before_n"), "reference before")
        after = finite(trial.get("reference_after_n"), "reference after")
        if min(before, after) < 0 or max(before, after) > 20.5:
            raise ValueError("The pilot covers positive normal force through 20 N")
        decoder, header, footer = Decoder(), None, None
        values, faults, times, previous_host = [], [], [], None
        with source.open() as stream:
            for line in stream:
                item = json.loads(line, parse_constant=no_constant)
                if item.get("type") == "session":
                    if header is not None:
                        raise ValueError("Multiple recording sessions in a hold")
                    header = item
                    continue
                if item.get("type") == "record_end":
                    footer = item
                    continue
                when = finite(item.get("host_elapsed_s"), "host timestamp")
                active = low <= when <= high
                if previous_host is not None and when < previous_host:
                    faults.append("host_time_reversal")
                previous_host = when
                if "raw_line" not in item:
                    if active:
                        faults.append("recording_error")
                    continue
                try:
                    decoded = decoder.accept(json.loads(item["raw_line"], parse_constant=no_constant))
                    if not active:
                        continue
                    if decoded["type"] == "hello":
                        if decoded["restarted"]:
                            faults.append("device_restarted")
                    elif decoded["available"]:
                        values.append(decoded["raw_force_counts"])
                        times.append(when)
                    else:
                        faults.extend(decoded["faults"])
                except (ValueError, KeyError, TypeError, AttributeError):
                    if active:
                        faults.append("invalid_raw_packet")
        if (header is None or header.get("schema") != "yam-fb1-recording/1"
                or header.get("evidence_kind") != "physical_recording_unreviewed"):
            raise ValueError("Missing physical FB1 recording identity")
        for key in ("specimen", "session_id", "geometry_sha256"):
            if header.get(key) != manifest[key]:
                raise ValueError("Mixed "+key+" in the trial plan")
        if header.get("condition") != trial["condition_id"]:
            raise ValueError("Condition differs between recording and plan")
        if footer is None or footer.get("complete_duration") is not True or finite(footer.get("duration_s"), "duration") < high:
            faults.append("incomplete_recording")
        if len(values) < 200:
            faults.append("short_hold")
        if not times or times[0] > low+.1 or times[-1] < high-.1 or any(b-a > .1 for a, b in zip(times, times[1:])):
            faults.append("window_not_continuously_observed")
        reference = (before+after)/2
        if abs(after-before) > max(.05, .02*max(reference, .2)):
            faults.append("reference_not_stationary")
        mean = sum(values)/len(values) if values else None
        rows.append({"id": trial["id"], "region": trial["region"], "condition_id": trial["condition_id"],
                     "recording_sha256": trial["recording_sha256"], "reference_n": reference,
                     "reference_bound_n": uncertainty+abs(after-before)/2,
                     "mean_counts": mean, "samples": len(values), "window_host_s": window,
                     "available": not faults, "faults": sorted(set(faults))})
    return manifest, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fit", "evaluate"))
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve previous results and use a new output path")
    manifest, rows = load_trials(args.trials, "train" if args.action == "fit" else "test")
    common = {"evidence_kind": "physical", "specimen": manifest["specimen"], "session_id": manifest["session_id"],
              "geometry_sha256": manifest["geometry_sha256"], "reference_id": manifest["reference_id"],
              "reference_uncertainty_n": manifest["reference_uncertainty_n"], "settings": SETTINGS,
              "created_utc": datetime.now(timezone.utc).isoformat(), "trial_manifest_sha256": digest(args.trials),
              "robot_gripper_qualified": False, "contact_reliability_qualified": False,
              "scope": "Means of declared stationary holds; excludes dynamic force, moving-arm compensation, contact confidence and lifetime."}
    if args.action == "fit":
        levels, complete = coverage(rows, manifest["minimum_holds_per_level"])
        if not complete or any(not r["available"] for r in rows):
            raise ValueError("Complete the planned force levels; retain and resolve unavailable holds before calibration")
        model = fit_numeric([r["mean_counts"] for r in rows], [r["reference_n"] for r in rows])
        rmse = math.sqrt(sum((predict(model, r["mean_counts"])-r["reference_n"])**2 for r in rows)/len(rows))
        report = {"schema": "yam-fb1-force-model/1", **common, **model, "training_rmse_n": rmse,
                  "training_recordings": [r["recording_sha256"] for r in rows],
                  "training_session_ids": [manifest["session_id"]], "force_level_coverage": levels,
                  "training_rmse_target_met": rmse <= .5, "training_holds": len(rows)}
    else:
        if args.model is None:
            parser.error("--model is required for evaluation")
        model = json.loads(args.model.read_text(), parse_constant=no_constant)
        if model.get("schema") != "yam-fb1-force-model/1" or model.get("evidence_kind") != "physical" or model.get("settings") != SETTINGS:
            raise ValueError("Use the frozen physical FB1 calibration")
        if model.get("geometry_sha256") != manifest["geometry_sha256"]:
            raise ValueError("Geometry changed; calibrate this build separately")
        if model.get("specimen") != manifest["specimen"] and manifest.get("transfer_experiment") is not True:
            raise ValueError("Declare cross-specimen transfer explicitly")
        if manifest["session_id"] in model["training_session_ids"] or any(r["recording_sha256"] in model["training_recordings"] for r in rows):
            raise ValueError("Evaluation must use new recordings from a held-out session")
        required = manifest.get("required_conditions")
        if not isinstance(required, list) or {r.get("region") for r in required} != set(REGIONS):
            raise ValueError("Plan held-out conditions covering all six nail/TPU regions")
        if len({r.get("condition_id") for r in required}) != len(required):
            raise ValueError("Use unique required condition identities")
        observed = []
        complete = True
        for condition in required:
            identity(condition.get("condition_id"), "required condition")
            selected = [r for r in rows if r["condition_id"] == condition["condition_id"] and r["region"] == condition["region"]]
            levels, passed = coverage(selected, manifest["minimum_holds_per_level"])
            complete &= passed
            observed.append({**condition, "force_levels": levels, "complete": passed})
        errors = []
        for row in rows:
            if row["available"]:
                row["predicted_n"] = predict(model, row["mean_counts"])
                row["error_n"] = row["predicted_n"]-row["reference_n"]
                row["individual_error_rule_met"] = abs(row["error_n"])+row["reference_bound_n"] <= max(.5, .1*row["reference_n"])
                errors.append(row["error_n"])
        rmse = math.sqrt(sum(e*e for e in errors)/len(errors)) if errors else None
        report = {"schema": "yam-fb1-static-validation/1", **common, "model_sha256": digest(args.model),
                  "transfer_experiment": manifest.get("transfer_experiment", False), "training_specimen": model["specimen"],
                  "held_out_holds": len(rows), "unavailable_holds": sum(not r["available"] for r in rows),
                  "rmse_n": rmse, "max_abs_error_n": max(map(abs, errors)) if errors else None,
                  "condition_coverage": observed, "trials": rows,
                  "passed_static_screen": bool(complete and len(errors) == len(rows) and rmse <= .5
                                               and model.get("training_rmse_target_met", False)
                                               and all(r.get("individual_error_rule_met") for r in rows))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({key: report[key] for key in ("schema", "training_holds", "training_rmse_n", "held_out_holds", "unavailable_holds", "rmse_n", "passed_static_screen") if key in report}, indent=2))


if __name__ == "__main__":
    with execution(ROOT / "build/records", "Fit or evaluate FB1 static force using physical raw recordings; keep training sessions separate and count unavailable holds"):
        main()
