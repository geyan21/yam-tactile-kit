#!/usr/bin/python3
"""Fit/evaluate O1 stationary force and contact baselines from physical captures."""

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
from capacitive_force import no_constant, same_force_axis
from optical_core import finite, digest, config_hash
from optical_holds import SITES, REGIONS, coverage, load_trials
from contact_core import failure_upper_bound


def solve(matrix, values):
    size = len(values)
    rows = [list(matrix[i])+[values[i]] for i in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda i: abs(rows[i][column]))
        if abs(rows[pivot][column]) < 1e-12:
            raise ValueError("Degenerate calibration system")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]; rows[column] = [v/divisor for v in rows[column]]
        for i in range(size):
            if i != column:
                factor = rows[i][column]
                rows[i] = [a-factor*b for a, b in zip(rows[i], rows[column])]
    return [row[-1] for row in rows]


def linear_fit(rows):
    vectors = [row["mean_signal"] for row in rows]
    dimensions = len(vectors[0])
    if not 3 <= dimensions <= 128 or any(len(v) != dimensions for v in vectors):
        raise ValueError("Inconsistent O1 feature vectors")
    center = [statistics.mean(v[i] for v in vectors) for i in range(dimensions)]
    scale = [statistics.pstdev(v[i] for v in vectors) for i in range(dimensions)]
    active = [i for i, value in enumerate(scale) if value > 1e-12]
    if not active:
        raise ValueError("No observed response; no force model can be inferred")
    target = statistics.mean(row["reference_n"] for row in rows)
    normalized = [[(v[i]-center[i])/scale[i] for i in active] for v in vectors]
    penalty = .1*len(rows)
    gram = [[sum(v[i]*v[j] for v in normalized)+(penalty if i == j else 0)
             for j in range(len(active))] for i in range(len(active))]
    rhs = [sum(v[i]*(row["reference_n"]-target) for v, row in zip(normalized, rows)) for i in range(len(active))]
    bounds = []
    for i in range(dimensions):
        low, high = min(v[i] for v in vectors), max(v[i] for v in vectors)
        guard = min(.05*(high-low), 4*max(row["stdev_signal"][i] for row in rows))
        bounds.append([low-guard, high+guard])
    return {"kind": "standardized_linear_ridge", "active_features": active, "center": center, "scale": scale,
            "coefficients": solve(gram, rhs), "intercept_n": target, "signal_bounds": bounds,
            "ridge_penalty": penalty, "ridge_rule": "0.1 times the independent training hold count",
            "feature_order": "nail0 apparent uS, nail1 apparent uS, then marker 0..41 (dx px,dy px,log area ratio)",
            "limits": "Fixed linear baseline, not a learned 3D pressure map. It may fail coupled/nonlinear behavior."}


def predict(model, features, check_bounds=True):
    if not isinstance(features, list) or len(features) != len(model["center"]):
        raise ValueError("Complete feature vector required")
    values = [finite(v, "feature") for v in features]
    if check_bounds and any(not low <= value <= high for value, (low, high) in zip(values, model["signal_bounds"])):
        return None
    return model["intercept_n"]+sum(c*(values[i]-model["center"][i])/model["scale"][i]
                                   for c, i in zip(model["coefficients"], model["active_features"]))


def contact_score(model, features):
    if len(features) != len(model["center"]):
        raise ValueError("Contact feature count changed")
    return max(abs(finite(value, "contact feature")-center)/scale
               for value, center, scale in zip(features, model["center"], model["scale"]))


def fit_contact(rows):
    absent = [r for r in rows if not r["contact_expected"]]
    present = [r for r in rows if r["contact_expected"]]
    if not absent or not present:
        raise ValueError("Both physical free-space and contact presentations are required")
    dimensions = len(rows[0]["mean_signal"])
    # Floors keep a zero-variance training coordinate from dividing by zero.
    # They are fixed numerical regularizers, not claims of sensor resolution.
    floor = [.05, .05]+[.05, .05, .01]*42
    center = [statistics.mean(r["mean_signal"][i] for r in absent) for i in range(dimensions)]
    scale = [max(floor[i], max(r["stdev_signal"][i] for r in absent),
                 statistics.pstdev(r["mean_signal"][i] for r in absent)) for i in range(dimensions)]
    model = {"center": center, "scale": scale, "kind": "maximum_standardized_deviation"}
    maximum_absent = max(contact_score(model, v) for row in absent for v in row["sample_features"])
    minimum_present = min(contact_score(model, v) for row in present for v in row["sample_features"])
    separable = minimum_present > maximum_absent
    return {**model, "available": separable, "threshold": (maximum_absent+minimum_present)/2 if separable else None,
            "maximum_absent_training_score": maximum_absent, "minimum_present_training_score": minimum_present,
            "limits": "A fixed threshold trained on these presentations; inseparable training data yields no detector."}


def fit(manifest, rows):
    if any(not row["available"] for row in rows):
        raise ValueError("Retain failed trials and complete the physical calibration")
    coverage_reports = {}
    for site in SITES:
        report, complete = coverage([r for r in rows if r["sites"] == [site]], manifest["minimum_holds_per_level"])
        coverage_reports[site] = report
        if not complete:
            raise ValueError("Incomplete independent 0..20 N training at "+site)
    model = linear_fit(rows)
    residual = [predict(model, row["mean_signal"], False)-row["reference_n"] for row in rows]
    rmse = math.sqrt(statistics.mean(v*v for v in residual))
    return {"schema": "yam-o1-stationary-model/1", "model": model, "contact_model": fit_contact(rows),
            "training_holds": len(rows), "training_rmse_n": rmse,
            "training_target_met": rmse <= .5 and all(abs(error)+row["reference_bound_n"] <= max(.5, .1*row["reference_n"])
                                                     for error, row in zip(residual, rows)),
            "training_session_id": manifest["session_id"],
            "training_capture_receipts": [r["capture_receipt_sha256"] for r in rows], "coverage": coverage_reports}


def evaluate(saved, manifest, rows):
    if saved.get("schema") != "yam-o1-stationary-model/1" or saved.get("evidence_kind") != "physical":
        raise ValueError("Use a saved physical O1 model")
    for key in ("specimen", "geometry_sha256", "device_id", "camera_config_sha256", "marker_reference_sha256"):
        if saved.get(key) != manifest.get(key):
            raise ValueError("Model/test context changed: "+key)
    same_force_axis(saved, manifest)
    if config_hash(saved["calibration_context"]) != config_hash(manifest["calibration_context"]):
        raise ValueError("Pose, electronics, surface/mirror process or temperature context changed")
    if saved["training_session_id"] == manifest["session_id"]:
        raise ValueError("Evaluation requires a separate physical session")
    if set(saved["training_capture_receipts"]) & {r["capture_receipt_sha256"] for r in rows}:
        raise ValueError("Training captures cannot be reused for validation")
    coverage_reports, covered = {}, True
    for region in REGIONS:
        report, complete = coverage([r for r in rows if r["region"] == region], manifest["minimum_holds_per_level"])
        coverage_reports[region] = report; covered &= complete
    mixture_sites = [set(r["sites"]) for r in rows if r["region"] == "mixture" and r["available"]]
    nails, gel = set(SITES[:2]), set(SITES[2:])
    mixtures = (any(s == nails for s in mixture_sites) and any(len(s) >= 2 and s <= gel for s in mixture_sites)
                and any(s & nails and s & gel for s in mixture_sites))
    covered &= mixtures and {r["sites"][0] for r in rows if len(r["sites"]) == 1} == set(SITES)
    errors, output = [], []
    for row in rows:
        contact_ok = False
        faults = list(row["faults"])
        estimate = predict(saved["model"], row["mean_signal"]) if row["available"] else None
        if row["available"] and saved["contact_model"]["available"]:
            decisions = [contact_score(saved["contact_model"], v) > saved["contact_model"]["threshold"] for v in row["sample_features"]]
            contact_ok = bool(decisions) and all(v == row["contact_expected"] for v in decisions)
        if estimate is None:
            faults.append("force_unavailable_or_outside_training_envelope")
        result = {k: v for k, v in row.items() if k != "sample_features"}
        result.update({"force_available": estimate is not None, "total_force_n": estimate,
                       "contact_correct_all_frames": contact_ok, "faults": sorted(set(faults))})
        if estimate is not None:
            error = estimate-row["reference_n"]; errors.append(error)
            result.update({"error_n": error, "individual_error_rule_met": abs(error)+row["reference_bound_n"] <= max(.5, .1*row["reference_n"])})
        output.append(result)
    contact = {}
    for region in (*REGIONS, "mixture"):
        contact[region] = {}
        for expected in (False, True):
            selected = [r for r in output if r["region"] == region and r["contact_expected"] == expected]
            failures = sum(not r["contact_correct_all_frames"] for r in selected)
            contact[region]["present" if expected else "absent"] = {
                "independent_presentations": len(selected), "conservative_failures": failures,
                "one_sided_95pct_upper_bound": failure_upper_bound(failures, len(selected))}
    rmse = math.sqrt(statistics.mean(v*v for v in errors)) if errors else None
    return {"schema": "yam-o1-stationary-validation/1", "held_out_holds": len(rows), "trials": output,
            "rmse_n": rmse, "force_unavailable_holds": len(rows)-len(errors), "coverage": coverage_reports,
            "mixed_contact_patterns_present": mixtures, "contact_by_condition": contact,
            "passed_static_force_screen": bool(covered and len(errors) == len(rows) and rmse <= .5 and saved["training_target_met"]
                                                and all(r.get("individual_error_rule_met") for r in output)),
            "contact_bound_scope": "Separately declared stationary conditions; every unavailable presentation is a failure. Bounds are per condition, not simultaneous across the family."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fit", "evaluate"))
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output")
    manifest, rows = load_trials(args.trials, "train" if args.action == "fit" else "test")
    if args.action == "fit":
        result = fit(manifest, rows)
    else:
        if args.model is None:
            parser.error("--model required for evaluation")
        result = evaluate(json.loads(args.model.read_text(), parse_constant=no_constant), manifest, rows)
        result["model_sha256"] = digest(args.model)
    result.update({key: manifest[key] for key in ("specimen", "session_id", "geometry_sha256", "reference_id", "reference_uncertainty_n",
                                                 "force_axis", "device_id", "camera_config_sha256", "marker_reference_sha256", "calibration_context")})
    result.update({"evidence_kind": "physical", "created_utc": datetime.now(timezone.utc).isoformat(),
                   "trial_manifest_sha256": digest(args.trials), "robot_gripper_qualified": False,
                   "scope": "Stationary force means and contact presentations in one frozen optical/material/pose context. No dynamic control, 3D pressure map, wear or general robot qualification."})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({key: result[key] for key in ("schema", "training_holds", "training_rmse_n", "training_target_met",
                                                  "held_out_holds", "rmse_n", "force_unavailable_holds", "passed_static_force_screen") if key in result}, indent=2))


if __name__ == "__main__":
    with execution(ROOT/"build/records", "Fit or evaluate identified O1 physical captures with fixed baselines and separate sessions; retain unavailable force/contact outcomes"):
        main()
