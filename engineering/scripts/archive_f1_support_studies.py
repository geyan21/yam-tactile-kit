#!/usr/bin/python3
"""Preserve the ADC and row-driver studies, including unsuccessful earlier runs."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from archive_f1_readout_study import digest, pack_run
from check_f1_opa_model import vector
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_screen(path):
    report = json.loads((path / "screen.json").read_text())
    config = next((path / "inputs").glob("f1_*stage.json"))
    if digest(config) != report["configuration_sha256"]:
        raise ValueError("Changed circuit configuration")
    return report, config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adc", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--adc-numerics", type=Path, required=True)
    parser.add_argument("--history", type=Path, nargs="+", required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / "engineering/development/f1/support-studies")
    args = parser.parse_args()
    adc, rows, numerics, destination = (p.resolve() for p in (args.adc, args.rows, args.adc_numerics, args.destination))
    history = [p.resolve() for p in args.history]
    if not all(p.is_relative_to(ROOT) for p in (adc, rows, numerics, destination, *history)):
        parser.error("Use repository-owned inputs and destination")
    if destination.exists():
        parser.error("Preserve prior checkpoints; choose a new destination")
    ar, acfg_path = load_screen(adc)
    rr, rcfg_path = load_screen(rows)
    nr = json.loads((numerics / "report.json").read_text())
    if not ar["all_passed"] or not rr["all_passed"] or not nr["passed"]:
        raise ValueError("Use completed current studies and numerical checks")
    if nr["reference_sha256"] != digest(adc / "screen.json"):
        raise ValueError("ADC numerical comparison used another reference")
    with execution(ROOT / "build/records", "Archive F1 ADC/row circuit studies with current results, stated numerical limits and every selected adverse predecessor") as record:
        destination.mkdir(parents=True, exist_ok=False)
        figures, evidence, runs = (destination / name for name in ("visuals", "evidence", "runs"))
        for folder in (figures, evidence, runs):
            folder.mkdir()
        for path, name in ((adc / "screen.json", "adc_screen.json"),
                           (rows / "screen.json", "row_screen.json"),
                           (numerics / "report.json", "adc_numerics.json"),
                           (acfg_path, "adc_configuration.json"), (rcfg_path, "row_configuration.json")):
            shutil.copyfile(path, evidence / name)
        acases = [r for r in ar["results"] if r["kind"] == "ac"]
        rcases = [r for r in rr["results"] if r["kind"] == "ac"]
        rt = [r for r in rr["results"] if r["kind"] != "ac"]
        at = [r for r in ar["results"] if r["kind"] == "transient"]
        previous = []
        for path in history:
            study, _ = load_screen(path)
            previous.append({"source": str(path.relative_to(ROOT)), "sha256": digest(path / "screen.json"),
                             "declared": study["declared_cases"], "completed": len(study["results"]),
                             "passed": sum(r["passed"] for r in study["results"]), "worker_failures": len(study["failures"])})
        summary = {
            "schema": "yam-f1-support-studies/1", "physical_specimens_tested": 0,
            "integrated_f1_complete": False,
            "adc": {"declared": ar["declared_cases"], "all_passed": ar["all_passed"],
                    "minimum_voltage_return_margin_deg": min(r["minimum_margin_deg"] for r in acases),
                    "maximum_sample_window_error_uv": max(r["maximum_sample_error_v"] for r in at)*1e6,
                    "peak_buffer_current_a": max(r["peak_buffer_current_a"] for r in at),
                    "smaller_time_step_cases": len(nr["refined_cases"]),
                    "completed_trapezoidal_comparisons": len(nr["completed_trapezoidal_comparisons"]),
                    "unresolved_trapezoidal_workers": nr["unresolved_trapezoidal_workers"]},
            "rows": {"declared": rr["declared_cases"], "all_passed": rr["all_passed"],
                    "minimum_voltage_return_margin_deg": min(r["minimum_margin_deg"] for r in rcases),
                    "maximum_settling_us": max(max(r["rising_settling_s"], r["return_settling_s"]) for r in rt)*1e6,
                    "maximum_incremental_output_resistance_ohm": max(r["incremental_output_resistance_ohm"] for r in rt if r["kind"] == "load_step")},
            "earlier_runs": previous,
            "limits": [
                "Typical amplifier models and explicit lumped circuit assumptions. Neither study is a measured board qualification.",
                "The ADC sampling network is an assumed charge-step model. Input noise, INL, quantizer behavior, reference dynamics and actual waveforms remain.",
                "Gear integration adds numerical damping. The saved AC responses, smaller-step cases and completed trapezoidal cases constrain only the stated model checks.",
                "Row sources are ideal. The four-row/sixteen-column coupled network and layout parasitics are not included.",
                "The row study uses centered DC/AC coordinates and released external-node initial guesses; actual-ground transients are separate saved netlists.",
                "No force, contact probability, bending lifetime or 20 N rating is established."
            ],
        }
        (evidence / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
        fig, axes = plt.subplots(2, 2, figsize=(13, 9), layout="constrained")
        for index, row in enumerate(acases):
            result = json.loads((adc / row["directory"] / "output/results.json").read_text())["results"]["ac"]
            frequency = vector(result, "frequency").real
            gain = -vector(result, "output")/vector(result, "inv")
            axes[0, 0].semilogx(frequency, 20*np.log10(abs(gain)), alpha=.6, lw=1)
        axes[0, 0].axhline(0, color="#777", ls="--")
        axes[0, 0].set(title="ADC buffer · 8 AC cases", xlabel="Frequency (Hz)", ylabel="Voltage return ratio (dB)", xlim=(1e3, 1e8))
        for row in at:
            x = row["capacitance_scale"]
            axes[0, 1].scatter(x, row["maximum_sample_error_v"]*1e6, s=25, color="#2b7783")
        axes[0, 1].set(xlabel="ADC sampling capacitance scale", ylabel="Error from the model's DC buffer endpoint (µV)",
                      title="ADC · 24 charge-step cases", xticks=[1, 2])
        for row in rt:
            result = json.loads((rows / row["directory"] / "output/results.json").read_text())["results"]
            time = vector(result["tran"], "time")
            remote = vector(result["tran"], "remote")
            if row["kind"] == "command_step":
                axes[1, 0].plot(time*1e6, (remote-row["initial_remote_v"])*1000, lw=1, alpha=.7, label=row["directory"])
            else:
                axes[1, 1].plot(time*1e6, (remote-row["initial_remote_v"])*1e6, lw=1, alpha=.7, label=row["directory"])
        axes[1, 0].set(title="Row command · four load/capacitance cases", xlabel="Time (µs)", ylabel="Row change (mV)")
        axes[1, 1].set(title="Row load disturbance · ±8 mA, four cases", xlabel="Time (µs)", ylabel="Row departure from baseline (µV)")
        for ax in axes.flat:
            ax.grid(alpha=.2)
        axes[1, 0].legend(fontsize=8)
        axes[1, 1].legend(fontsize=8)
        fig.suptitle("F1 ADC and row support studies · circuit simulation only\n"
                     "32 ADC cases + 26 row cases · no physical force measurements", fontsize=13)
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(figures / ("support_results."+suffix), dpi=170)
        plt.close(fig)
        sources = {"adc_current": adc, "row_current": rows, "adc_numerics": numerics}
        sources.update({f"earlier_{i+1}": path for i, path in enumerate(history)})
        contents = {label: pack_run(path, runs / f"{label}.tar.gz", label) for label, path in sources.items()}
        (runs / "contents.json").write_text(json.dumps(contents, indent=2)+"\n")
        (destination / "README.md").write_text(
            "# F1 ADC and row-driver development studies\n\n"
            "These are circuit studies for the wrist board, not a finished F1 finger or a hardware qualification.\n\n"
            "![Circuit-study results](visuals/support_results.png)\n\n"
            "`evidence/summary.json` records 32 ADC and 26 row cases, their declared limits, the numerical comparison, "
            "and the unsuccessful predecessor runs. `runs/` preserves complete case files, input snapshots, raw vectors "
            "and logs, including failures. Vendor model libraries are not redistributed.\n\n"
            "The ADC driver uses OPA320AQDBVRQ1, two 22-ohm resistors, a 2.2 nF differential capacitor and "
            "2.2 nF from each ADC input to ground. The row driver uses OPA392DBVR, 47-ohm output isolation, "
            "4.7-kohm sense input, 100 pF local feedback and 100 Mohm weak DC feedback.\n\n"
            "Read `engineering/docs/F1_WRIST_CAPTURE.md` for the complete candidate part identities and the "
            "separate raw-capture contract. The reference, complete coupled array, layout, fitted sensor foils, "
            "carrier and physical contact/force experiments remain.\n\n"
            "From the repository root, the existing archive verifier can verify and extract this checkpoint:\n\n"
            "```sh\n/usr/bin/python3 engineering/scripts/verify_f1_readout_study.py "
            "--checkpoint engineering/development/f1/support-studies --extract\n```\n\n"
            "Use `fetch_f1_models.py opa392_pspice opa320_pspice` to obtain the reviewed manufacturer models "
            "directly, then replay selected extracted cases with `run_f1_spice_case.py --model ...`. "
            "A different model hash requires a new review; do not overwrite these results.\n")
        checkpoint = {
            "schema": "yam-f1-support-study-checkpoint/1", "created_utc": datetime.now(timezone.utc).isoformat(),
            "physical_specimens_tested": 0, "integrated_f1_complete": False,
            "summary": summary, "source_locations": {label: str(path.relative_to(ROOT)) for label, path in sources.items()},
            "files_sha256": {str(path.relative_to(destination)): digest(path)
                             for path in sorted(destination.rglob("*")) if path.is_file()},
            "archiver_sha256": digest(Path(__file__)),
        }
        (destination / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2)+"\n")
        record["checkpoint"] = {"directory": str(destination.relative_to(ROOT)), "summary": summary,
                                "files": len(checkpoint["files_sha256"]),
                                "archive_bytes": {name: info["bytes"] for name, info in contents.items()}}
        print(json.dumps(record["checkpoint"], indent=2))


if __name__ == "__main__":
    main()
