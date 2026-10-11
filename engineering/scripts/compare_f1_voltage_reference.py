#!/usr/bin/python3
"""Compare the same F1 circuit using two numerical voltage-reference choices."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(folder):
    report_path = folder / "screen.json"
    cfg_path = folder / "inputs/f1_feedback_screen.json"
    report = json.loads(report_path.read_text())
    cfg = json.loads(cfg_path.read_text())
    if digest(cfg_path) != report["configuration_sha256"] or not report["all_declared_screens_passed"]:
        raise ValueError("Use complete passed runs with unchanged configurations")
    return report, cfg


def key(row):
    return tuple(row[k] for k in ("gain_id", "load_ohm", "capacitance_nf", "capacitance_scale", "transient"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    first, second = args.first.resolve(), args.second.resolve()
    if not all(p.is_relative_to(ROOT) for p in (first, second)):
        parser.error("Use repository-owned feedback runs")
    a, ca = load(first); b, cb = load(second)
    differences = {k for k in set(ca) | set(cb) if ca.get(k) != cb.get(k)}
    if differences - {"spice_voltage_datum_v", "voltage_datum_note"}:
        raise ValueError(f"Physical circuit changed: {differences}")
    if ca["spice_voltage_datum_v"] == cb["spice_voltage_datum_v"]:
        raise ValueError("Select two distinct numerical voltage references")
    if a["vendor_model_sha256"] != b["vendor_model_sha256"]:
        raise ValueError("Vendor model changed")
    for name in ("screen_f1_feedback.py", "f1_spice.py", "run_f1_spice_case.py", "check_f1_opa_model.py"):
        if digest(first / "inputs" / name) != digest(second / "inputs" / name):
            raise ValueError(f"Numerical workflow changed between reference cases: {name}")
    aa = {key(r): r for r in a["results"]}; bb = {key(r): r for r in b["results"]}
    if set(aa) != set(bb) or len(aa) != 104:
        raise ValueError("Case grids differ")
    with execution(ROOT / "build/records", "Check whether the complete selected-column circuit gives consistent model results under two numerical voltage references") as record:
        pairs = []
        for k in sorted(aa):
            ra, rb = aa[k], bb[k]
            if ra["transient"]:
                span_a = ra["dc_final_v"]-ra["dc_initial_v"]
                span_b = rb["dc_final_v"]-rb["dc_initial_v"]
                pairs.append({"parameters": k, "kind": "transient",
                              "delta_span_v": abs(span_a-span_b),
                              "delta_baseline_v": abs(ra["dc_initial_v"]-rb["dc_initial_v"]),
                              "delta_settling_us": abs(ra["settling_s"]-rb["settling_s"])*1e6})
            else:
                pairs.append({"parameters": k, "kind": "AC",
                              "delta_margin_deg": abs(ra["minimum_margin_deg"]-rb["minimum_margin_deg"]),
                              "delta_bias_v": abs(ra["dc_output_v"]-rb["dc_output_v"])})
        max_margin = max(r.get("delta_margin_deg", 0) for r in pairs)
        max_span = max(r.get("delta_span_v", 0) for r in pairs)
        max_settling = max(r.get("delta_settling_us", 0) for r in pairs)
        result = {
            "schema": "yam-f1-reference-comparison/1", "physical_evidence": False,
            "first_run": str(first.relative_to(ROOT)), "second_run": str(second.relative_to(ROOT)),
            "first_screen_sha256": digest(first / "screen.json"), "second_screen_sha256": digest(second / "screen.json"),
            "case_pairs": len(pairs), "maximum_margin_delta_deg": max_margin,
            "maximum_step_span_delta_v": max_span, "maximum_settling_delta_us": max_settling,
            "maximum_bias_delta_v": max(max(r.get("delta_baseline_v", 0), r.get("delta_bias_v", 0)) for r in pairs),
            "criteria": {"margin_delta_deg_max": 1, "step_span_delta_v_max": 25e-6, "settling_delta_us_max": 5},
            "passed": max_margin < 1 and max_span < 25e-6 and max_settling < 5,
            "pairs": pairs,
            "limits": "Numerical reference consistency only; no full-array, ADC or hardware performance conclusion."
        }
        folder = ROOT / "build/engineering/prototypes/f1/reference_comparisons"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+".json")
        path.write_text(json.dumps(result, indent=2)+"\n")
        record["comparison"] = result
        print(json.dumps({"path": str(path.relative_to(ROOT)), **{k: v for k, v in result.items() if k != "pairs"}}, indent=2))
        if not result["passed"]:
            raise ValueError("Voltage-reference comparison did not meet the declared numerical criteria")


if __name__ == "__main__":
    main()
