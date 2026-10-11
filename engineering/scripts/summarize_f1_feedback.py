#!/usr/bin/python3
"""Draw and summarize a completed F1 selected-column circuit study."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from check_f1_opa_model import vector
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    source = args.run.resolve()
    if not source.is_relative_to(ROOT):
        parser.error("Use a repository-owned circuit run")
    report_path = source / "screen.json"
    report = json.loads(report_path.read_text())
    cfg_path = source / "inputs/f1_feedback_screen.json"
    cfg = json.loads(cfg_path.read_text())
    if digest(cfg_path) != report["configuration_sha256"] or not report["all_declared_cases_completed"]:
        raise ValueError("Use a complete run with unchanged configuration")
    folder = source / "reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Summarize the explicit F1 feedback simulation grid and render its limiting responses without inferring physical force performance") as record:
        folder.mkdir(parents=True, exist_ok=False)
        ac = [r for r in report["results"] if not r["transient"]]
        transient = [r for r in report["results"] if r["transient"]]
        if len(ac) != 96 or len(transient) != 8:
            raise ValueError("This summary requires the complete 96 AC / 8 transient grid")
        for row in report["results"]:
            case_dir = source / row["directory"]
            results = json.loads((case_dir / "output/results.json").read_text())
            if results["input_hashes"]["case"] != digest(case_dir / "case.json"):
                raise ValueError("Case description changed after simulation")
            if results["input_hashes"]["netlist"] != digest(case_dir / "circuit.cir"):
                raise ValueError("Case circuit changed after simulation")
            for name, expected in results["input_hashes"].get("additional_netlists", {}).items():
                if digest(case_dir / name) != expected:
                    raise ValueError("Additional case circuit changed after simulation")
        by_gain = []
        for gain in range(4):
            a = min((r for r in ac if r["gain_id"] == gain), key=lambda r: r["minimum_margin_deg"])
            t = max((r for r in transient if r["gain_id"] == gain),
                    key=lambda r: r["settling_s"] if r["settling_s"] is not None else float("inf"))
            by_gain.append({"gain_id": gain,
                            "resistance_ohm": cfg["gain_selection"]["branches"][gain]["resistance_ohm"],
                            "limiting_margin_case": a["directory"],
                            "minimum_voltage_return_margin_deg": a["minimum_margin_deg"],
                            "limiting_settling_case": t["directory"],
                            "maximum_settling_us": t["settling_s"]*1e6 if t["settling_s"] is not None else None})
        adc = cfg["main_adc_candidate"]
        max_rf = max(b["resistance_ohm"] for b in cfg["gain_selection"]["branches"])
        summary = {
            "schema": "yam-f1-feedback-summary/1", "physical_specimens_tested": 0,
            "ac_cases": len(ac), "transient_cases": len(transient),
            "all_declared_screens_passed": report["all_declared_screens_passed"],
            "minimum_voltage_return_margin_deg": min(r["minimum_margin_deg"] for r in ac),
            "maximum_settling_us": max(r["settling_s"] for r in transient)*1e6,
            "settling_error_uv": cfg["transient"]["settling_error_v"]*1e6,
            "maximum_baseline_error_uv": max(r["baseline_error_v_before_step"] for r in transient)*1e6,
            "all_parking_controls_verified": all(r["park_dc_open"] for r in ac) and
                                             all(r["park_dc_open"] and r["park_timing_verified"] for r in transient),
            "all_linear_headroom_checks_passed": all(r["regular_bias"] for r in ac) and
                                                all(r["linear_headroom"] for r in transient),
            "nominal_current_na_per_adc_code_at_highest_gain": 1e9*adc["reference_v_for_scale_calculation"]/(2**adc["resolution_bits"]*max_rf),
            "by_gain": by_gain,
            "input_hashes": {"screen": digest(report_path), "configuration": digest(cfg_path),
                             "summarizer": digest(Path(__file__)), "vendor_model": report["vendor_model_sha256"]},
            "limits": [
                "One selected column with stiff ideal row/bias sources; the four row-driver loops and full array are not included.",
                "Muxes and gain switches use explicit lumped resistance/capacitance approximations, not complete transistor models.",
                "The voltage return-ratio measurement is a development stability screen, not a formal multi-loop guarantee.",
                "The model is typical and older than the current amplifier datasheet. Component tolerances, temperature, leakage, charge injection, clipping and cable faults remain.",
                "The ADC is a selected candidate and a nominal code-spacing calculation; acquisition, reference drive, ADC noise and INL are not simulated here.",
                "No hardware, contact probability, force accuracy, bending life or 20 N rating follows from these plots."
            ]}
        (folder / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
        with (folder / "cases.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["case", "gain", "load_ohm", "sensor_capacitance_nf", "mux_capacitance_scale",
                             "analysis", "margin_deg", "settling_us", "passed"])
            for r in report["results"]:
                writer.writerow([r["directory"], r["gain_id"], r["load_ohm"], r["capacitance_nf"],
                                 r["capacitance_scale"], "transient" if r["transient"] else "AC",
                                 r.get("minimum_margin_deg", ""),
                                 r["settling_s"]*1e6 if r.get("settling_s") is not None else "", r["passed"]])
        fig, axes = plt.subplots(2, 2, figsize=(13, 9), layout="constrained")
        colors = ("#256f80", "#a87125", "#7e4f96", "#b6484d")
        for entry, color in zip(by_gain, colors):
            label = f"G{entry['gain_id']} · {entry['resistance_ohm']/1000:g} kΩ"
            results = json.loads((source / entry["limiting_margin_case"] / "output/results.json").read_text())["results"]
            frequency = vector(results["ac"], "frequency").real
            gain = -vector(results["ac"], "feedback")/vector(results["ac"], "inv")
            axes[0, 0].semilogx(frequency, 20*np.log10(abs(gain)), color=color, label=label)
            axes[0, 1].semilogx(frequency, np.unwrap(np.angle(gain))*180/np.pi, color=color, label=label)
            transient_dir = source / entry["limiting_settling_case"]
            result = json.loads((transient_dir / "output/results.json").read_text())["results"]
            parameters = json.loads((transient_dir / "case.json").read_text())["parameters"]
            datum = parameters.get("voltage_datum_v", cfg.get("spice_voltage_datum_v", 0))
            dc_datum = parameters.get("dc_voltage_datum_v", datum)
            times = vector(result["tran"], "time")-cfg["transient"]["step_start_s"]-cfg["transient"]["rise_s"]
            voltage = vector(result["tran"], "output")+datum
            initial, final = vector(result["dc"], "output")[[0, -1]]+dc_datum
            visible = (times >= 0) & (times <= .0004)
            axes[1, 0].plot(times[visible]*1e6, (voltage[visible]-initial)/(final-initial), color=color, label=label)
            axes[1, 1].semilogy(times[visible]*1e6, np.maximum(abs(voltage[visible]-final)*1e6, .01), color=color, label=label)
        axes[0, 0].axhline(0, color="#64748b", ls="--", lw=1)
        axes[0, 1].axhline(-135, color="#64748b", ls="--", lw=1, label="45° screen at unity")
        axes[1, 1].axhline(cfg["transient"]["settling_error_v"]*1e6, color="#64748b", ls="--", lw=1)
        axes[1, 1].axvline(cfg["transient"]["settling_time_limit_s"]*1e6, color="#64748b", ls=":", lw=1)
        axes[0, 0].set(xlabel="Frequency (Hz)", ylabel="Voltage return ratio (dB)", title="Limiting AC case for each gain", xlim=(10, 1e8))
        axes[0, 1].set(xlabel="Frequency (Hz)", ylabel="Unwrapped phase (degrees)", title="Phase of the same cases", xlim=(10, 1e8), ylim=(-230, 20))
        axes[1, 0].set(xlabel="Time after current-step rise (µs)", ylabel="Fraction of simulated DC output change", title="Limiting settling case for each gain")
        axes[1, 1].set(xlabel="Time after current-step rise (µs)", ylabel="Error from simulated DC endpoint (µV)", title="25 µV / 300 µs work criterion", ylim=(.01, 1e6))
        for ax in axes.flat:
            ax.grid(alpha=.2); ax.legend(fontsize=8)
        fig.suptitle("F1 selected-column feedback · manufacturer-model simulation\n"
                     "96 AC cases + 8 current-step cases · no physical force measurements", fontsize=13)
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(folder / ("feedback_results."+suffix), dpi=170, bbox_inches="tight")
        plt.close(fig)
        record["summary"] = summary
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), **summary}, indent=2))


if __name__ == "__main__":
    main()
