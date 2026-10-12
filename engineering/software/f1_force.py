#!/usr/bin/python3
"""Fit and evaluate experimental F1 site-force curves from physical stationary holds."""

import argparse
from bisect import bisect_right
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from capacitive_force import (SITES, LEVELS, REGIONS, coverage, digest, finite, identity,
                              load_axis, no_constant, same_force_axis)
from f1_holds import extract
from f1_protocol import PROTOCOL


def monotone(points):
    grouped = {}
    for signal, force in points:
        grouped.setdefault(finite(signal, "signal"), []).append(finite(force, "force"))
    xs = sorted(grouped)
    if len(xs) < 3:
        raise ValueError("Insufficient distinct F1 signals")
    blocks = []
    for index, x in enumerate(xs):
        blocks.append([index, index, sum(grouped[x]), len(grouped[x])])
        while len(blocks) > 1 and blocks[-2][2]/blocks[-2][3] > blocks[-1][2]/blocks[-1][3]:
            last, previous = blocks.pop(), blocks.pop()
            blocks.append([previous[0], last[1], previous[2]+last[2], previous[3]+last[3]])
    ys = [None]*len(xs)
    for first, last, total, count in blocks:
        ys[first:last+1] = [total/count]*(last-first+1)
    if max(ys)-min(ys) < 1:
        raise ValueError("F1 signal does not resolve the required force range")
    return [[x, y] for x, y in zip(xs, ys)]


def cell_predict(model, signal):
    signal = finite(signal, "signal")
    curve, guard = model["knots_na_n"], model["signal_guard_na"]
    if not curve[0][0]-guard <= signal <= curve[-1][0]+guard:
        return None
    index = min(max(bisect_right([p[0] for p in curve], signal)-1, 0), len(curve)-2)
    x0, y0 = curve[index]
    x1, y1 = curve[index+1]
    return y0+(signal-x0)*(y1-y0)/(x1-x0)


def load_trials(path, phase):
    manifest = json.loads(path.read_text(), parse_constant=no_constant)
    if (manifest.get("schema") != "yam-f1-force-trials/1" or manifest.get("phase") != phase
            or manifest.get("evidence_kind") != "physical"):
        raise ValueError("Use an identified physical F1 trial manifest for this phase")
    for name in ("specimen", "session_id", "reference_id"):
        identity(manifest.get(name), name)
    manifest["force_axis"] = load_axis(manifest.get("force_axis"))
    if not re.fullmatch(r"[0-9a-f]{64}", manifest.get("geometry_sha256") or ""):
        raise ValueError("Declare the actual assembly hash")
    uncertainty = finite(manifest.get("reference_uncertainty_n"), "reference uncertainty")
    if not 0 < uncertainty <= .05:
        raise ValueError("Document reference uncertainty of 0.05 N or better")
    repeats = manifest.get("minimum_holds_per_level")
    if type(repeats) is not int or repeats < 3:
        raise ValueError("At least three independent holds per level")
    trials = manifest.get("trials")
    if (not isinstance(trials, list) or not trials or len({t.get("id") for t in trials}) != len(trials)
            or len({t.get("recording_sha256") for t in trials}) != len(trials)):
        raise ValueError("Use unique trial IDs and separate recordings")
    rows, base = [], path.parent.resolve()
    for trial in trials:
        for name in ("id", "condition_id"):
            identity(trial.get(name), name)
        sites = trial.get("sites")
        if not isinstance(sites, list) or not sites or len(set(sites)) != len(sites) or set(sites)-set(SITES):
            raise ValueError("Identify distinct physical contact sites CH0..CH5")
        if phase == "train" and len(sites) != 1:
            raise ValueError("Train single sites; evaluate mixtures independently")
        if trial.get("region") not in (*REGIONS, "mixture"):
            raise ValueError("Identify the physical contact region")
        path_record = (base/trial["recording"]).resolve()
        if (not path_record.is_relative_to(base) or not path_record.is_file()
                or path_record.stat().st_size > 128*1024*1024 or digest(path_record) != trial["recording_sha256"]):
            raise ValueError("Use a matching recording beneath the manifest directory, at most 128 MiB")
        window = trial.get("window_host_s")
        if not isinstance(window, list) or len(window) != 2:
            raise ValueError("Declare the stationary window")
        before, after = [finite(trial.get(name), name) for name in ("reference_before_n", "reference_after_n")]
        if min(before, after) < 0 or max(before, after) > 20.5:
            raise ValueError("This experiment covers 0..20 N")
        observation = extract(path_record, manifest, trial)
        reference = (before+after)/2
        if abs(after-before) > max(.05, .02*max(reference, .2)):
            observation["faults"].append("reference_not_stationary")
            observation["available"] = False
        rows.append({**observation, "id": trial["id"], "condition_id": trial["condition_id"],
                     "sites": sites, "region": trial["region"], "recording_sha256": trial["recording_sha256"],
                     "reference_n": reference, "reference_bound_n": uncertainty+abs(after-before)/2})
    return manifest, rows


def fit(manifest, rows):
    if any(not row["available"] for row in rows):
        raise ValueError("Unavailable training holds; retain failures and collect the complete plan")
    configurations = {row["configuration_sha256"] for row in rows}
    if len(configurations) != 1:
        raise ValueError("Use one frozen gain map, timing and hardware configuration")
    cells, level_reports = {}, {}
    for index, site in enumerate(SITES):
        selected = [row for row in rows if row["sites"] == [site]]
        levels, complete = coverage(selected, manifest["minimum_holds_per_level"])
        if not complete:
            raise ValueError("Incomplete actual 0..20 N coverage for "+site)
        points = []
        for level in LEVELS:
            same = [row for row in selected if abs(row["reference_n"]-level) <= max(.05, .03*level)
                    and (level != 20 or row["reference_n"] >= 20)]
            points.append([statistics.median(row["mean_signal_na"][index] for row in same),
                           statistics.median(row["reference_n"] for row in same)])
        curve = monotone(points)
        guard = min(.05*(curve[-1][0]-curve[0][0]),
                    max(4*max(row["stdev_signal_na"][index] for row in selected), 1e-6))
        model = {"knots_na_n": curve, "signal_guard_na": guard}
        predictions = [cell_predict(model, row["mean_signal_na"][index]) for row in selected]
        rmse = (math.sqrt(statistics.mean((value-row["reference_n"])**2 for value, row in zip(predictions, selected)))
                if all(value is not None for value in predictions) else None)
        model.update({"training_rmse_n": rmse, "training_target_met": rmse is not None and rmse <= .5})
        cells[site], level_reports[site] = model, levels
    return {"schema": "yam-f1-force-model/1", "cells": cells, "configuration_sha256": configurations.pop(),
            "training_holds": len(rows), "training_session_ids": [manifest["session_id"]],
            "training_recordings": [row["recording_sha256"] for row in rows],
            "force_level_coverage": level_reports, "training_target_met": all(c["training_target_met"] for c in cells.values())}


def evaluate(model, manifest, rows):
    if (model.get("schema") != "yam-f1-force-model/1" or model.get("evidence_kind") != "physical"
            or model.get("protocol") != PROTOCOL or model.get("geometry_sha256") != manifest["geometry_sha256"]):
        raise ValueError("Use a physical F1 model for this geometry and protocol")
    same_force_axis(model, manifest)
    if model["specimen"] != manifest["specimen"] and manifest.get("transfer_experiment") is not True:
        raise ValueError("Declare transfer between specimens explicitly")
    if manifest["session_id"] in model["training_session_ids"] or any(
            row["recording_sha256"] in model["training_recordings"] for row in rows):
        raise ValueError("Use a held-out session and new recordings")
    conditions = manifest.get("required_conditions")
    if (not isinstance(conditions, list) or not conditions
            or not set(REGIONS) <= {c.get("region") for c in conditions}
            or len({c.get("condition_id") for c in conditions}) != len(conditions)):
        raise ValueError("Require distinct nail, edge/notch and TPU test conditions")
    condition_reports, covered, single_sites, mixtures = [], True, set(), []
    for condition in conditions:
        sites = condition.get("sites")
        if not isinstance(sites, list) or not sites or set(sites)-set(SITES) or len(set(sites)) != len(sites):
            raise ValueError("Invalid required contact pattern")
        selected = [row for row in rows if row["condition_id"] == condition["condition_id"]
                    and row["region"] == condition["region"] and set(row["sites"]) == set(sites)]
        levels, complete = coverage(selected, manifest["minimum_holds_per_level"])
        covered &= complete
        if len(sites) == 1:
            single_sites.update(sites)
        else:
            mixtures.append(set(sites))
        condition_reports.append({**condition, "coverage": levels, "complete": complete})
    mixed = (any(s == {"CH0", "CH1"} for s in mixtures)
             and any(s <= {"CH2", "CH3", "CH4", "CH5"} and len(s) >= 2 for s in mixtures)
             and any(s & {"CH0", "CH1"} and s & {"CH2", "CH3", "CH4", "CH5"} for s in mixtures))
    covered &= single_sites == set(SITES) and mixed
    errors = []
    for row in rows:
        if row["configuration_sha256"] != model["configuration_sha256"]:
            row["available"] = False
            row["faults"].append("scan_configuration_changed")
        if not row["available"]:
            continue
        values = [cell_predict(model["cells"][site], row["mean_signal_na"][i]) for i, site in enumerate(SITES)]
        row["cell_force_n"] = dict(zip(SITES, values))
        if any(value is None for value in values):
            row["available"] = False
            row["faults"].append("outside_calibrated_signal_guard")
            continue
        total = sum(values)
        row.update({"total_force_n": total, "error_n": total-row["reference_n"],
                    "inactive_cell_force_max_abs_n": max([abs(value) for site, value in zip(SITES, values)
                                                          if site not in row["sites"]] or [0.])})
        row["individual_error_rule_met"] = abs(row["error_n"])+row["reference_bound_n"] <= max(.5, .1*row["reference_n"])
        row["background_cell_screen_met"] = row["inactive_cell_force_max_abs_n"] <= .2
        row["no_large_negative_cell_force"] = min(values) >= -.2
        errors.append(row["error_n"])
    rmse = math.sqrt(statistics.mean(value*value for value in errors)) if errors else None
    return {"schema": "yam-f1-static-validation/1", "held_out_holds": len(rows),
            "unavailable_holds": sum(not row["available"] for row in rows), "rmse_n": rmse, "trials": rows,
            "condition_coverage": condition_reports, "mixed_contact_patterns_present": mixed,
            "passed_static_screen": bool(covered and len(errors) == len(rows) and rmse <= .5 and model["training_target_met"]
                                         and all(row.get("individual_error_rule_met") and row.get("background_cell_screen_met")
                                                 and row.get("no_large_negative_cell_force") for row in rows))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fit", "evaluate"))
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output; preserve earlier results")
    manifest, rows = load_trials(args.trials, "train" if args.action == "fit" else "test")
    if args.action == "fit":
        result = fit(manifest, rows)
    else:
        if args.model is None:
            parser.error("--model is required for evaluation")
        result = evaluate(json.loads(args.model.read_text(), parse_constant=no_constant), manifest, rows)
        result["model_sha256"] = digest(args.model)
    result.update({key: manifest[key] for key in ("specimen", "session_id", "geometry_sha256", "reference_id",
                                                 "force_axis", "reference_uncertainty_n")})
    result.update({"evidence_kind": "physical", "protocol": PROTOCOL,
                   "created_utc": datetime.now(timezone.utc).isoformat(), "trial_manifest_sha256": digest(args.trials),
                   "robot_gripper_qualified": False, "contact_reliability_qualified": False,
                   "force_component": "Force along the declared common source-finger axis",
                   "scope": "Experimental monotone curves of six site-current sums during stationary holds; no calibrated 64-taxel pressure map, dynamic, wear or contact qualification."})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("schema", "training_holds", "training_target_met",
                                                  "held_out_holds", "rmse_n", "unavailable_holds", "passed_static_screen")
                      if key in result}, indent=2))


if __name__ == "__main__":
    with execution(ROOT / "build/records", "Fit/evaluate F1 using identified physical stationary holds; preserve unavailable readings and independent mixed-contact evaluation"):
        main()
