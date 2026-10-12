#!/usr/bin/python3
"""Fit/evaluate a P1 stationary common-axis force estimator from physical holds."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from capacitive_force import SITES, REGIONS, coverage, digest, finite, no_constant, same_force_axis
from pneumatic_holds import load_trials
from pneumatic_protocol import PROTOCOL, config_hash


def solve(matrix, values):
    """Partial-pivot elimination for the small, explicitly regularized system."""
    n = len(values)
    rows = [list(matrix[i])+[values[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda i: abs(rows[i][col]))
        if abs(rows[pivot][col]) < 1e-12:
            raise ValueError("Degenerate calibration system")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [v/divisor for v in rows[col]]
        for index in range(n):
            if index != col:
                factor = rows[index][col]
                rows[index] = [a-factor*b for a, b in zip(rows[index], rows[col])]
    return [row[-1] for row in rows]


def linear_fit(rows):
    """Fixed ridge rule; no test-set tuning, rectification or force clipping."""
    vectors = [row["mean_signal"] for row in rows]
    center = [statistics.mean(v[i] for v in vectors) for i in range(6)]
    scales = [statistics.pstdev(v[i] for v in vectors) for i in range(6)]
    active = [i for i in range(6) if scales[i] > 1e-12]
    if not active:
        raise ValueError("No measured signal response")
    target = statistics.mean(row["reference_n"] for row in rows)
    normalized = [[(v[i]-center[i])/scales[i] for i in active] for v in vectors]
    penalty = .01*len(rows)
    gram = [[sum(v[i]*v[j] for v in normalized)+(penalty if i == j else 0)
             for j in range(len(active))] for i in range(len(active))]
    rhs = [sum(v[i]*(row["reference_n"]-target) for v, row in zip(normalized, rows))
           for i in range(len(active))]
    coefficients = solve(gram, rhs)
    bounds = []
    for i in range(6):
        low, high = min(v[i] for v in vectors), max(v[i] for v in vectors)
        # The envelope is an observed-signal range, not a confidence interval.
        guard = min(.05*(high-low), 4*max(row["stdev_signal"][i] for row in rows))
        bounds.append([low-guard, high+guard])
    return {"kind": "standardized_linear_ridge", "active_features": active, "center": center,
            "scale": scales, "coefficients": coefficients, "intercept_n": target,
            "ridge_penalty": penalty, "ridge_rule": "0.01 times number of independent training holds",
            "signal_bounds": bounds,
            "feature_order": ["nail0_apparent_us", "nail1_apparent_us",
                              "ch2_nominal_differential_pa", "ch3_nominal_differential_pa",
                              "ch4_nominal_differential_pa", "ch5_nominal_differential_pa"]}


def predict(model, signals, check_bounds=True):
    if not isinstance(signals, list) or len(signals) != 6:
        raise ValueError("All six signals are required")
    values = [finite(value, "signal") for value in signals]
    if check_bounds and any(not limits[0] <= value <= limits[1] for value, limits in zip(values, model["signal_bounds"])):
        return None
    return model["intercept_n"]+sum(coefficient*(values[i]-model["center"][i])/model["scale"][i]
                                     for coefficient, i in zip(model["coefficients"], model["active_features"]))


def fit(manifest, rows):
    if any(not row["available"] for row in rows):
        raise ValueError("Preserve failed holds and complete the physical calibration plan")
    coverage_reports = {}
    for site in SITES:
        report, complete = coverage([row for row in rows if row["sites"] == [site]], manifest["minimum_holds_per_level"])
        coverage_reports[site] = report
        if not complete:
            raise ValueError("Incomplete physical 0..20 N coverage at "+site)
    identities = {(row["device_id"], row["configuration_sha256"]) for row in rows}
    if len(identities) != 1:
        raise ValueError("Mixed devices or acquisition configurations")
    model = linear_fit(rows)
    residuals = [predict(model, row["mean_signal"], check_bounds=False)-row["reference_n"] for row in rows]
    target_met = (math.sqrt(statistics.mean(v*v for v in residuals)) <= .5
                  and all(abs(error)+row["reference_bound_n"] <= max(.5, .1*row["reference_n"])
                          for error, row in zip(residuals, rows)))
    device, configuration = next(iter(identities))
    return {"schema": "yam-p1-stationary-model/1", "model": model, "training_holds": len(rows),
            "training_rmse_n": math.sqrt(statistics.mean(v*v for v in residuals)),
            "training_target_met": target_met, "training_session_id": manifest["session_id"],
            "training_recording_sha256": [row["recording_sha256"] for row in rows],
            "calibration_context": manifest["calibration_context"], "device_id": device,
            "configuration_sha256": configuration, "coverage": coverage_reports,
            "training_limits": "A fixed linear baseline may fail nonlinear, coupled or cancelling pressure modes. A fitted file is not validation."}


def evaluate(saved, manifest, rows):
    if saved.get("schema") != "yam-p1-stationary-model/1" or saved.get("evidence_kind") != "physical":
        raise ValueError("Use the saved physical P1 model")
    for key in ("specimen", "geometry_sha256"):
        if saved.get(key) != manifest.get(key):
            raise ValueError("Changed "+key)
    same_force_axis(saved, manifest)
    if config_hash(saved["calibration_context"]) != config_hash(manifest["calibration_context"]):
        raise ValueError("The hose/material/pose/electronics/temperature context changed; collect a separate qualification")
    if saved["training_session_id"] == manifest["session_id"]:
        raise ValueError("Evaluation requires a separate physical session")
    if set(saved["training_recording_sha256"]) & {row["recording_sha256"] for row in rows}:
        raise ValueError("Training recordings cannot be reused for evaluation")
    condition_reports, covered = {}, True
    for region in REGIONS:
        report, complete = coverage([row for row in rows if row["region"] == region], manifest["minimum_holds_per_level"])
        condition_reports[region] = report
        covered &= complete
    mixtures = [set(row["sites"]) for row in rows if row["region"] == "mixture" and row["available"]]
    mixed = (any(s == {"CH0", "CH1"} for s in mixtures)
             and any(len(s) >= 2 and s <= {"CH2", "CH3", "CH4", "CH5"} for s in mixtures)
             and any(s & {"CH0", "CH1"} and s & {"CH2", "CH3", "CH4", "CH5"} for s in mixtures))
    covered &= mixed and {row["sites"][0] for row in rows if len(row["sites"]) == 1} == set(SITES)
    errors = []
    for row in rows:
        if (row["device_id"] != saved["device_id"] or row["configuration_sha256"] != saved["configuration_sha256"]):
            row["available"] = False
            row["faults"].append("device_or_configuration_changed")
        if not row["available"]:
            continue
        estimate = predict(saved["model"], row["mean_signal"])
        if estimate is None:
            row["available"] = False
            row["faults"].append("outside_training_signal_envelope")
            continue
        error = estimate-row["reference_n"]
        row.update({"total_force_n": estimate, "error_n": error,
                    "individual_error_rule_met": abs(error)+row["reference_bound_n"] <= max(.5, .1*row["reference_n"])})
        errors.append(error)
    rmse = math.sqrt(statistics.mean(v*v for v in errors)) if errors else None
    return {"schema": "yam-p1-static-validation/1", "held_out_holds": len(rows), "trials": rows,
            "unavailable_holds": sum(not row["available"] for row in rows), "rmse_n": rmse,
            "condition_coverage": condition_reports, "mixed_contact_patterns_present": mixed,
            "passed_static_screen": bool(covered and len(errors) == len(rows) and rmse <= .5
                                         and saved["training_target_met"] and all(row.get("individual_error_rule_met") for row in rows))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fit", "evaluate"))
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output; preserve previous results")
    manifest, rows = load_trials(args.trials, "train" if args.action == "fit" else "test")
    if args.action == "fit":
        result = fit(manifest, rows)
    else:
        if args.model is None:
            parser.error("--model is required")
        result = evaluate(json.loads(args.model.read_text(), parse_constant=no_constant), manifest, rows)
        result["model_sha256"] = digest(args.model)
    result.update({key: manifest[key] for key in ("specimen", "session_id", "geometry_sha256", "reference_id",
                                                 "force_axis", "reference_uncertainty_n")})
    result.update({"evidence_kind": "physical", "protocol": PROTOCOL,
                   "created_utc": datetime.now(timezone.utc).isoformat(), "trial_manifest_sha256": digest(args.trials),
                   "robot_gripper_qualified": False, "contact_reliability_qualified": False,
                   "force_component": "Force along the declared common source-finger axis",
                   "scope": "Stationary means in one identified pose/hose/temperature context. No contact, arbitrary object, dynamic or robot qualification."})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({key: result[key] for key in ("schema", "training_holds", "training_rmse_n",
                                                  "training_target_met", "held_out_holds", "rmse_n",
                                                  "unavailable_holds", "passed_static_screen") if key in result}, indent=2))


if __name__ == "__main__":
    with execution(ROOT/"build/records", "Fit or evaluate P1 using identified physical stationary holds; keep signed coupled signals, withheld tests and unavailable outcomes"):
        main()
