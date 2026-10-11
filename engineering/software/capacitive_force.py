#!/usr/bin/python3
"""Fit K1 capacitance/force curves and evaluate new physical stationary holds."""

import argparse
from bisect import bisect_right
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from capacitive_protocol import Decoder, PROTOCOL, TIMING

SITES = tuple("CH"+str(i) for i in range(6))
LEVELS = (0, .2, .5, 1, 2, 5, 10, 15, 20)
REGIONS = ("left_nail", "right_nail", "nail_edges_notch", "distal_tpu", "middle_tpu", "proximal_tpu")


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("Finite numerical value required: "+name)
    return float(value)


def identity(value, name):
    if not isinstance(value, str) or not value.strip() or "REPLACE" in value.upper():
        raise ValueError("Actual identity required: "+name)
    return value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_constant(value):
    raise ValueError("Nonfinite JSON constant: "+value)


def knots(points):
    """Weighted monotone least squares over distinct capacitance observations."""
    grouped = {}
    for capacitance, force in points:
        x, y = finite(capacitance, "capacitance"), finite(force, "reference force")
        if x <= 0 or y < 0:
            raise ValueError("Expected positive capacitance and nonnegative normal force")
        grouped.setdefault(x, []).append(y)
    xs = sorted(grouped)
    if len(xs) < 3:
        raise ValueError("Insufficient distinct capacitance values")
    blocks = []
    for i, x in enumerate(xs):
        blocks.append([i, i, sum(grouped[x]), len(grouped[x])])
        while len(blocks) > 1 and blocks[-2][2]/blocks[-2][3] > blocks[-1][2]/blocks[-1][3]:
            last, previous = blocks.pop(), blocks.pop()
            blocks.append([previous[0], last[1], previous[2]+last[2], previous[3]+last[3]])
    ys = [None]*len(xs)
    for first, last, total, count in blocks:
        for i in range(first, last+1):
            ys[i] = total/count
    if max(ys)-min(ys) < 1:
        raise ValueError("Capacitance does not resolve the required force range")
    return [[x, y] for x, y in zip(xs, ys)]


def cell_predict(model, value):
    value = finite(value, "capacitance")
    curve, guard = model["knots_pf_n"], model["signal_guard_pf"]
    if not curve[0][0]-guard <= value <= curve[-1][0]+guard:
        return None
    index = bisect_right([p[0] for p in curve], value)-1
    index = min(max(index, 0), len(curve)-2)
    x0, y0 = curve[index]; x1, y1 = curve[index+1]
    # The explicit small signal guard is extrapolated, never clipped to 0
    # or 20 N. It exposes offset/noise instead of concealing it.
    return y0+(value-x0)*(y1-y0)/(x1-x0)


def predict(model, capacitances):
    if len(capacitances) != 6:
        raise ValueError("All six K1 capacitances are required")
    values = [cell_predict(model["cells"][site], capacitances[i]) for i, site in enumerate(SITES)]
    return {"cell_force_n": dict(zip(SITES, values)),
            "total_force_n": sum(values) if all(v is not None for v in values) else None}


def coverage(rows, repetitions):
    result = []
    for target in LEVELS:
        count = sum(row["available"] and abs(row["reference_n"]-target) <= max(.05, .03*target)
                    and (target != 20 or row["reference_n"] >= 20) for row in rows)
        result.append({"target_n": target, "independent_holds": count, "required": repetitions})
    return result, all(r["independent_holds"] >= repetitions for r in result)


def load_axis(value):
    if not isinstance(value, dict) or value.get("frame") != "source_finger_native":
        raise ValueError("Declare one force axis in the source finger's native frame")
    vector = value.get("unit_vector")
    if not isinstance(vector, list) or len(vector) != 3:
        raise ValueError("Declare the three-component force unit vector")
    vector = [finite(v, "force axis") for v in vector]
    if abs(sum(v*v for v in vector)-1) > 1e-6:
        raise ValueError("The declared force axis must be a unit vector")
    return {"frame": "source_finger_native", "unit_vector": vector}


def same_force_axis(model, manifest):
    if load_axis(model.get("force_axis")) != load_axis(manifest.get("force_axis")):
        raise ValueError("Force axis changed; local normal magnitudes cannot be summed as gripper-axis force")


def load_trials(path, phase):
    manifest = json.loads(path.read_text(), parse_constant=no_constant)
    if (manifest.get("schema") != "yam-k1-force-trials/1" or manifest.get("evidence_kind") != "physical"
            or manifest.get("phase") != phase):
        raise ValueError("Use a physical K1 trial manifest for the requested phase")
    for key in ("specimen", "session_id", "reference_id"):
        identity(manifest.get(key), key)
    manifest["force_axis"] = load_axis(manifest.get("force_axis"))
    if not re.fullmatch(r"[0-9a-f]{64}", manifest.get("geometry_sha256") or ""):
        raise ValueError("Give the actual assembly geometry hash")
    uncertainty = finite(manifest.get("reference_uncertainty_n"), "reference uncertainty")
    if not 0 < uncertainty <= .05:
        raise ValueError("Use a documented reference uncertainty of 0.05 N or better")
    repetitions = manifest.get("minimum_holds_per_level")
    if type(repetitions) is not int or repetitions < 3:
        raise ValueError("At least three independent holds per level are required")
    trials = manifest.get("trials")
    if (not isinstance(trials, list) or not trials or len({t.get("id") for t in trials}) != len(trials)
            or len({t.get("recording_sha256") for t in trials}) != len(trials)):
        raise ValueError("Use unique trial IDs and separate recording files")
    rows, base = [], path.parent.resolve()
    for trial in trials:
        identity(trial.get("id"), "trial")
        identity(trial.get("condition_id"), "condition")
        sites = trial.get("sites")
        if not isinstance(sites, list) or not sites or len(set(sites)) != len(sites) or set(sites)-set(SITES):
            raise ValueError("Identify distinct physical contact sites CH0..CH5")
        if phase == "train" and len(sites) != 1:
            raise ValueError("Train each cell separately; reserve mixed contacts for evaluation")
        if trial.get("region") not in (*REGIONS, "mixture"):
            raise ValueError("Give the physical nail/TPU region")
        recording = (base/trial["recording"]).resolve()
        if not recording.is_relative_to(base) or not recording.is_file() or recording.stat().st_size > 64*1024*1024:
            raise ValueError("Use a recording beneath the manifest directory, at most 64 MiB")
        if digest(recording) != trial.get("recording_sha256"):
            raise ValueError("Recording hash changed")
        window = trial.get("window_host_s")
        if not isinstance(window, list) or len(window) != 2:
            raise ValueError("Declare the stationary time window")
        low, high = [finite(v, "window") for v in window]
        if low < 1.5 or high-low < 4:
            raise ValueError("Allow synchronization and at least four seconds of stationary data")
        before, after = [finite(trial.get(k), k) for k in ("reference_before_n", "reference_after_n")]
        if min(before, after) < 0 or max(before, after) > 20.5:
            raise ValueError("This pilot covers positive normal force through 20 N")
        decoder, header, footer, previous_host = Decoder(), None, None, None
        samples, times, faults = [], [], []
        with recording.open() as stream:
            for line in stream:
                item = json.loads(line, parse_constant=no_constant)
                if item.get("type") == "session":
                    if header is not None:
                        raise ValueError("Multiple sessions in one hold")
                    header = item; continue
                if item.get("type") == "record_end":
                    footer = item; continue
                when = finite(item.get("host_elapsed_s"), "host time")
                active = low <= when <= high
                if previous_host is not None and when < previous_host:
                    faults.append("host_time_reversal")
                previous_host = when
                if "raw_line" not in item:
                    if active:
                        faults.append("recording_error")
                    continue
                try:
                    observation = decoder.accept(json.loads(item["raw_line"], parse_constant=no_constant))
                    if not active:
                        continue
                    if observation["type"] == "hello":
                        if observation["restarted"]:
                            faults.append("device_restarted")
                    elif observation["complete_finger_available"]:
                        values = [finite(c["sequential_reconstructed_pf"], "cell capacitance") for c in observation["cells"]]
                        samples.append(values); times.append(when)
                    else:
                        faults.extend(f for c in observation["cells"] for f in c["faults"])
                except (ValueError, TypeError, KeyError, AttributeError):
                    if active:
                        faults.append("invalid_raw_packet")
        if (header is None or header.get("schema") != "yam-k1-recording/2"
                or header.get("protocol") != PROTOCOL or header.get("evidence_kind") != "physical_recording_unreviewed"):
            raise ValueError("Electronic test data or unidentified recordings cannot enter tactile calibration")
        for key in ("specimen", "session_id", "geometry_sha256"):
            if header.get(key) != manifest[key]:
                raise ValueError("Mixed "+key)
        if header.get("condition") != trial["condition_id"]:
            raise ValueError("Recording condition does not match")
        if footer is None or footer.get("complete_duration") is not True or finite(footer.get("duration_s"), "duration") < high:
            faults.append("incomplete_recording")
        if len(samples) < 200:
            faults.append("short_hold")
        if not times or times[0] > low+.1 or times[-1] < high-.1 or any(b-a > .1 for a, b in zip(times, times[1:])):
            faults.append("window_not_continuously_observed")
        reference = (before+after)/2
        if abs(after-before) > max(.05, .02*max(reference, .2)):
            faults.append("reference_not_stationary")
        rows.append({"id": trial["id"], "condition_id": trial["condition_id"], "region": trial["region"], "sites": sites,
                     "recording_sha256": trial["recording_sha256"], "reference_n": reference,
                     "reference_bound_n": uncertainty+abs(after-before)/2, "samples": len(samples),
                     "mean_pf": [statistics.mean(row[i] for row in samples) for i in range(6)] if samples else None,
                     "stdev_pf": [statistics.stdev(row[i] for row in samples) for i in range(6)] if len(samples) > 1 else None,
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
        parser.error("Preserve earlier output and use a new filename")
    manifest, rows = load_trials(args.trials, "train" if args.action == "fit" else "test")
    common = {"evidence_kind": "physical", "protocol": PROTOCOL, "timing": TIMING,
              "specimen": manifest["specimen"], "session_id": manifest["session_id"],
              "geometry_sha256": manifest["geometry_sha256"], "reference_id": manifest["reference_id"],
              "force_axis": manifest["force_axis"],
              "force_component": "Force on the finger along the one declared native-frame axis",
              "reference_uncertainty_n": manifest["reference_uncertainty_n"],
              "created_utc": datetime.now(timezone.utc).isoformat(), "trial_manifest_sha256": digest(args.trials),
              "robot_gripper_qualified": False, "contact_reliability_qualified": False,
              "scope": "Stationary hold means; no moving-robot, dynamic, wear or contact-confidence qualification"}
    if args.action == "fit":
        if any(not r["available"] for r in rows):
            raise ValueError("Calibration has unavailable holds; retain failed attempts and collect a complete plan")
        models, level_reports = {}, {}
        for i, site in enumerate(SITES):
            selected = [r for r in rows if r["sites"] == [site]]
            levels, complete = coverage(selected, manifest["minimum_holds_per_level"])
            if not complete:
                raise ValueError("Incomplete actual 0..20 N force levels for "+site)
            points = []
            for level in LEVELS:
                same = [r for r in selected if abs(r["reference_n"]-level) <= max(.05, .03*level)
                        and (level != 20 or r["reference_n"] >= 20)]
                points.append([statistics.median(r["mean_pf"][i] for r in same),
                               statistics.median(r["reference_n"] for r in same)])
            curve = knots(points)
            span = curve[-1][0]-curve[0][0]
            guard = min(.05*span, max(4*max(r["stdev_pf"][i] for r in selected), 16/524288))
            model = {"knots_pf_n": curve, "signal_guard_pf": guard,
                     "range_n": [min(r["reference_n"] for r in selected), max(r["reference_n"] for r in selected)]}
            errors = [cell_predict(model, r["mean_pf"][i]) for r in selected]
            rmse = (math.sqrt(statistics.mean((value-r["reference_n"])**2 for value, r in zip(errors, selected)))
                    if all(v is not None for v in errors) else None)
            model.update({"training_rmse_n": rmse, "training_target_met": rmse is not None and rmse <= .5})
            models[site], level_reports[site] = model, levels
        report = {"schema": "yam-k1-force-model/1", **common, "cells": models,
                  "training_holds": len(rows), "training_session_ids": [manifest["session_id"]],
                  "training_recordings": [r["recording_sha256"] for r in rows],
                  "force_level_coverage": level_reports, "training_target_met": all(m["training_target_met"] for m in models.values())}
    else:
        if args.model is None:
            parser.error("--model is required")
        model = json.loads(args.model.read_text(), parse_constant=no_constant)
        if (model.get("schema") != "yam-k1-force-model/1" or model.get("evidence_kind") != "physical"
                or model.get("protocol") != PROTOCOL or model.get("timing") != TIMING):
            raise ValueError("Use a physical K1 calibration from this acquisition version")
        if model.get("geometry_sha256") != manifest["geometry_sha256"]:
            raise ValueError("Assembly geometry changed")
        same_force_axis(model, manifest)
        if model["specimen"] != manifest["specimen"] and manifest.get("transfer_experiment") is not True:
            raise ValueError("Declare cross-specimen transfer explicitly")
        if manifest["session_id"] in model["training_session_ids"] or any(r["recording_sha256"] in model["training_recordings"] for r in rows):
            raise ValueError("Use new recordings from a held-out session")
        conditions = manifest.get("required_conditions")
        if (not isinstance(conditions, list) or not conditions
                or not set(REGIONS) <= {c.get("region") for c in conditions}
                or len({c.get("condition_id") for c in conditions}) != len(conditions)):
            raise ValueError("Require distinct conditions covering nails, edges/notch and all TPU regions")
        condition_reports, covered, single_sites, mixtures = [], True, set(), []
        for condition in conditions:
            sites = condition.get("sites")
            if not isinstance(sites, list) or not sites or set(sites)-set(SITES) or len(set(sites)) != len(sites):
                raise ValueError("Invalid required contact-site pattern")
            selected = [r for r in rows if r["condition_id"] == condition["condition_id"]
                        and r["region"] == condition["region"] and set(r["sites"]) == set(sites)]
            levels, complete = coverage(selected, manifest["minimum_holds_per_level"])
            covered &= complete
            if len(sites) == 1:
                single_sites.update(sites)
            else:
                mixtures.append(set(sites))
            condition_reports.append({**condition, "coverage": levels, "complete": complete})
        mixture_coverage = (any(s == {"CH0", "CH1"} for s in mixtures)
                            and any(s <= {"CH2", "CH3", "CH4", "CH5"} and len(s) >= 2 for s in mixtures)
                            and any(s & {"CH0", "CH1"} and s & {"CH2", "CH3", "CH4", "CH5"} for s in mixtures))
        covered &= single_sites == set(SITES) and mixture_coverage
        errors = []
        for row in rows:
            if row["available"]:
                prediction = predict(model, row["mean_pf"])
                row.update(prediction)
                value = prediction["total_force_n"]
                if value is None:
                    row["available"] = False; row["faults"].append("outside_calibrated_signal_guard")
                    continue
                row["error_n"] = value-row["reference_n"]
                row["individual_error_rule_met"] = abs(row["error_n"])+row["reference_bound_n"] <= max(.5, .1*row["reference_n"])
                row["inactive_cell_force_max_abs_n"] = max([abs(v) for s, v in prediction["cell_force_n"].items() if s not in row["sites"]] or [0.])
                row["no_large_negative_cell_force"] = min(prediction["cell_force_n"].values()) >= -.2
                row["background_cell_screen_met"] = row["inactive_cell_force_max_abs_n"] <= .2
                errors.append(row["error_n"])
        rmse = math.sqrt(statistics.mean(e*e for e in errors)) if errors else None
        report = {"schema": "yam-k1-static-validation/1", **common, "model_sha256": digest(args.model),
                  "transfer_experiment": manifest.get("transfer_experiment", False),
                  "held_out_holds": len(rows), "unavailable_holds": sum(not r["available"] for r in rows),
                  "condition_coverage": condition_reports, "mixed_contact_patterns_present": mixture_coverage,
                  "rmse_n": rmse, "trials": rows,
                  "passed_static_screen": bool(covered and len(errors) == len(rows) and rmse <= .5 and model["training_target_met"]
                                               and all(r.get("individual_error_rule_met") and r.get("background_cell_screen_met")
                                                       and r.get("no_large_negative_cell_force") for r in rows))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({k: report[k] for k in ("schema", "training_holds", "training_target_met", "held_out_holds", "rmse_n",
                                           "unavailable_holds", "passed_static_screen") if k in report}, indent=2))


if __name__ == "__main__":
    with execution(ROOT / "build/records", "Fit/evaluate K1 from physical raw stationary holds, preserving unavailable readings and mixed-contact requirements"):
        main()
