#!/usr/bin/python3
"""Recover and summarize saved F1 readout checks without rerunning a solver."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from check_f1_opa_model import vector
from check_f1_column_link import ideal_test_drop
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_case_inputs(folder, report):
    actual = {"case": digest(folder / "case.json"), "netlist": digest(folder / "circuit.cir")}
    for key, value in actual.items():
        if report["input_hashes"][key] != value:
            raise ValueError(f"Saved {key} differs from simulated input: {folder.name}")


def review_fault(folder, cfg, fanout):
    """Keep simulation validity distinct from a proposed wire-fault decision."""
    case = json.loads((folder / "case.json").read_text())
    result_path = folder / "output/results.json"
    log_path = folder / "output/ngspice.log"
    row = {**case["parameters"], "case": folder.name,
           "input_sha256": {"case": digest(folder / "case.json"),
                            "netlist": digest(folder / "circuit.cir")},
           "simulation_valid": False, "fault_decision_supported": False}
    if log_path.exists():
        row["log_sha256"] = digest(log_path)
    if not result_path.exists():
        row["status"] = "missing_completed_result"
        return row, None
    report = json.loads(result_path.read_text())
    check_case_inputs(folder, report)
    row["result_sha256"] = digest(result_path)
    result = report["results"]
    raw = result.get("tran")
    if not raw:
        row["status"] = "missing_transient"
        return row, None
    time = vector(raw, "time")
    output = vector(raw, "output")
    amp = vector(raw, "amp_out")
    trace = (time, output)
    row["last_time_s"] = float(time[-1])
    row["minimum_output_v"] = float(output.min())
    row["maximum_output_v"] = float(output.max())
    physical = bool(np.all(np.isfinite(output)) and np.all(np.isfinite(amp))
                    and np.all((output > -.05) & (output < cfg["supply_v"]+.05))
                    and np.all((amp > -.05) & (amp < cfg["supply_v"]+.05)))
    row["physically_plausible_outputs"] = physical
    before = (time > .0018) & (time < .0019)
    after = time > .00285
    if time[-1] < .003*(1-1e-9) or not np.any(before) or not np.any(after):
        row["status"] = "incomplete_transient" if physical else "incomplete_nonphysical_transient"
        return row, trace
    if log_path.exists():
        log = log_path.read_text().lower()
        if "doanalyses:" in log or "simulation(s) aborted" in log:
            row["status"] = "solver_reported_abort"
            return row, trace
    startup = bool(vector(result["startup_op"], "park_ctl")[0] > 2.2)
    startup &= bool(np.all(vector(raw, "park_ctl")[time > .00005] < .8))
    controls = bool(np.all(vector(raw, "test_ctl")[before] < .8)
                    and np.all(vector(raw, "test_ctl")[after] > 2.2))
    for name, opens in (("gate_i", case["parameters"]["fault"] in ("current_open", "both_open")),
                        ("gate_s", case["parameters"]["fault"] in ("sense_open", "both_open"))):
        values = vector(raw, name)
        controls &= bool(np.all(values[time < .001] > 2.2))
        controls &= bool(np.all(values[time > .001001] < .8) if opens
                         else np.all(values[time > .001001] > 2.2))
    baseline = float(np.mean(output[before]))
    signal = float(np.mean(output[after]))
    delta = baseline-signal
    steady = bool(np.ptp(output[before]) < .006 and np.ptp(output[after]) < .006)
    # A stable in-window response is necessary for a healthy decision.
    # Numerically invalid traces never count as demonstrations of rejection.
    classified_healthy = bool(steady and .70 <= delta <= .95)
    test = fanout["test_mux"]
    expected = ideal_test_drop(
        cfg, case["parameters"]["load_ohm"],
        test["source_test_resistor_ohm"]
        + test["on_resistance_limit_ohm_at_3v_pm10percent_full_temperature"])
    healthy = case["parameters"]["fault"] == "healthy"
    valid = bool(startup and controls and physical)
    supported = bool(valid and classified_healthy == healthy
                     and (not healthy or abs(delta/expected-1) < .005))
    row.update({
        "status": ("supported_provisional_decision" if supported else
                   "decision_not_supported" if valid else "invalid_controls_or_output"),
        "simulation_valid": valid, "fault_decision_supported": supported,
        "startup_verified": startup, "control_timing_verified": controls,
        "physically_plausible_outputs": physical,
        "settled_measurement_windows": steady,
        "baseline_peak_to_peak_v": float(np.ptp(output[before])),
        "test_peak_to_peak_v": float(np.ptp(output[after])),
        "baseline_output_v": baseline, "test_output_v": signal, "drop_v": delta,
        "classified_healthy": classified_healthy, "expected_healthy_drop_v": expected,
        "healthy_drop_window_v": [.70, .95],
    })
    return row, trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nominal", type=Path, required=True)
    parser.add_argument("--crosscheck", type=Path, required=True)
    parser.add_argument("--faults", type=Path, required=True)
    args = parser.parse_args()
    nominal, cross, faults = (p.resolve() for p in (args.nominal, args.crosscheck, args.faults))
    if not all(p.is_relative_to(ROOT / "build") for p in (nominal, cross, faults)):
        parser.error("Review saved repository build results only")
    screen_path, cross_path = nominal / "screen.json", cross / "comparison.json"
    screen, comparison = (json.loads(p.read_text()) for p in (screen_path, cross_path))
    if comparison["reference_screen_sha256"] != digest(screen_path):
        raise ValueError("Time-domain checks used a different nominal screen")
    fault_cfg_path = faults / "inputs/f1_feedback_screen.json"
    fanout_path = faults / "inputs/f1_fanout_development.json"
    cfg, fanout = (json.loads(p.read_text()) for p in (fault_cfg_path, fanout_path))
    destination = ROOT / "build/engineering/prototypes/f1/readout_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Recover saved F1 circuit evidence, including incomplete or invalid simulations; read-only with respect to original runs") as record:
        destination.mkdir(parents=True, exist_ok=False)
        rows = []
        fig, axes = plt.subplots(3, 4, figsize=(16, 9), layout="constrained")
        fault_names = ("healthy", "current_open", "sense_open", "both_open")
        for load_index, load in enumerate((25, 2500, 250000)):
            for fault_index, fault in enumerate(fault_names):
                folder = faults / f"load_{load}_{fault}"
                row, trace = review_fault(folder, cfg, fanout)
                rows.append(row)
                ax = axes[load_index, fault_index]
                if trace is not None:
                    time, output = trace
                    ax.plot(time*1000, output, lw=.8, color="#216a80")
                ax.axvline(1, ls=":", color="#7754a3", lw=.9)
                ax.axvline(2, ls=":", color="#b86a22", lw=.9)
                ax.axhline(0, color="#aaa", lw=.6)
                ax.axhline(3.3, color="#aaa", lw=.6)
                ax.set(xlim=(0, 3), xlabel="Time (ms)", ylabel="Output (V)",
                       title=f"{load:g} Ω · {fault.replace('_', ' ')}")
                ax.text(.02, .97, row["status"].replace("_", " "), transform=ax.transAxes,
                        va="top", fontsize=8, bbox={"facecolor": "white", "alpha": .8, "edgecolor": "none"})
        fig.suptitle("F1 wire-break study · saved simulation evidence\n"
                     "Wire opens at 1 ms; electrical test enabled at 2 ms. Incomplete/invalid traces are not passes.",
                     fontsize=13)
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(destination / f"column_link_evidence.{suffix}", dpi=150)
        plt.close(fig)
        cross_counts = {
            "declared": 96, "completed": len(comparison["results"]),
            "passed": sum(r["passed"] for r in comparison["results"]),
            "failed_workers": len(comparison["failures"]),
            "worker_failure_types": dict(Counter("timeout" if r["error"] == "worker_timeout"
                                                else "solver_failure" for r in comparison["failures"])),
            "failed_cases": [r["case"] for r in comparison["failures"]],
            "maximum_completed_phase_error_deg": max(r["phase_error_deg"] for r in comparison["results"]),
            "maximum_completed_relative_magnitude_error": max(r["relative_magnitude_error"] for r in comparison["results"]),
            "all_completed": comparison["all_completed"], "all_passed": comparison["all_passed"],
        }
        faults_report = {
            "declared": len(rows), "results": rows,
            "status_counts": dict(Counter(r["status"] for r in rows)),
            "numerically_valid": sum(r["simulation_valid"] for r in rows),
            "provisional_decisions_supported": sum(r["fault_decision_supported"] for r in rows),
            "healthy_controls_supported": sum(r["fault"] == "healthy" and r["fault_decision_supported"] for r in rows),
            "all_supported": all(r["fault_decision_supported"] for r in rows),
        }
        report = {
            "schema": "yam-f1-readout-evidence-review/1",
            "physical_specimens_tested": 0, "integrated_f1_complete": False,
            "nominal": {"cases": len(screen["results"]),
                        "passed": sum(r["passed"] for r in screen["results"]),
                        "all_completed": screen["all_declared_cases_completed"],
                        "all_passed": screen["all_declared_screens_passed"]},
            "time_domain_crosscheck": cross_counts, "wire_break_study": faults_report,
            "source_locations": {"nominal": str(nominal.relative_to(ROOT)),
                                 "crosscheck": str(cross.relative_to(ROOT)), "faults": str(faults.relative_to(ROOT))},
            "source_sha256": {"nominal_screen": digest(screen_path), "crosscheck": digest(cross_path),
                              "fault_configuration": digest(fault_cfg_path), "fanout_configuration": digest(fanout_path),
                              "reviewer": digest(Path(__file__))},
            "limits": [
                "The nominal grid is one selected-column model with ideal bias sources, not the coupled array or finished electronics.",
                "A failed solver does not establish a hardware failure or a pass. Retain it as unresolved evidence.",
                "The first wire-break collector stopped on an empty measurement window. This review recovers every saved case without changing the original files.",
                "A healthy decision requires a settled response in the declared window. Invalid, aborted or incomplete simulations never qualify a fault detector.",
                "No simulation result establishes physical contact reliability, force accuracy, repeatability or a 20 N rating.",
            ],
        }
        (destination / "review.json").write_text(json.dumps(report, indent=2)+"\n")
        record["review"] = {"directory": str(destination.relative_to(ROOT)), "nominal": report["nominal"],
                            "time_domain_crosscheck": cross_counts,
                            "wire_break_status_counts": faults_report["status_counts"]}
        print(json.dumps(record["review"], indent=2))


if __name__ == "__main__":
    main()
