#!/usr/bin/python3
"""Cross-check AC return ratios using time-domain sine probes after parking."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import circuit, run_case, digest
from check_f1_opa_model import vector


def fit_wave(time, values, frequency):
    centered_time = time-time.mean()
    design = np.column_stack((np.ones_like(time), centered_time,
                              np.cos(2*np.pi*frequency*time), np.sin(2*np.pi*frequency*time)))
    parameters = np.linalg.lstsq(design, values, rcond=None)[0]
    complex_amplitude = complex(parameters[2], -parameters[3])
    residual = np.sqrt(np.mean((design @ parameters-values)**2))
    return complex_amplitude, float(residual / max(abs(complex_amplitude), 1e-30))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_run", type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--worst-only", action="store_true")
    args = parser.parse_args()
    source = args.reference_run.resolve(); model = args.model.resolve()
    if not source.is_relative_to(ROOT) or not model.is_relative_to(ROOT):
        parser.error("Use repository-owned reference and model files")
    reference = json.loads((source / "screen.json").read_text())
    cfg_path = source / "inputs/f1_feedback_screen.json"
    cfg = json.loads(cfg_path.read_text())
    if not reference["all_declared_screens_passed"] or digest(cfg_path) != reference["configuration_sha256"]:
        raise ValueError("Use a passed, unchanged reference grid")
    if digest(model) != reference["vendor_model_sha256"]:
        raise ValueError("Use the same vendor model")
    cfg = copy.deepcopy(cfg)
    cfg["spice_voltage_datum_v"] = 0
    candidates = [r for r in reference["results"] if not r["transient"]]
    if args.worst_only:
        candidates = [min((r for r in candidates if r["gain_id"] == g),
                          key=lambda r: r["minimum_margin_deg"]) for g in range(4)]
    folder = ROOT / "build/engineering/prototypes/f1/time_reference_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Compare the frequency-domain return ratios with physical-ground time-domain sine probes initialized in the actual parked state") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        for path in (Path(__file__), ROOT / "engineering/scripts/screen_f1_feedback.py",
                     ROOT / "engineering/scripts/run_f1_spice_case.py", ROOT / "engineering/scripts/f1_spice.py",
                     ROOT / "engineering/scripts/check_f1_opa_model.py", cfg_path):
            shutil.copyfile(path, inputs / path.name)
        cases = {}
        for index, ref in enumerate(candidates):
            if len(ref["crossings"]) != 1:
                raise ValueError("Every crossing requires its own time-domain probe")
            frequency = ref["crossings"][0]["unity_frequency_hz"]
            delay = .0004
            stop = delay+20/frequency
            save_from = delay+10/frequency
            maximum_step = min(.5e-6, 1/frequency/128)
            local_cfg = copy.deepcopy(cfg)
            local_cfg["transient"]["stop_s"] = stop
            deck, _ = circuit(local_cfg, ref["gain_id"], ref["load_ohm"],
                              ref["capacitance_nf"], ref["capacitance_scale"], True)
            transformed = []
            for line in deck:
                if line.startswith("VTEST "):
                    transformed.append(f"VTEST inv feedback DC 0 SIN(0 0.0001 {frequency:.14g} {delay:.14g} 0 0)")
                elif line.startswith("VPARK "):
                    # Transient initialization must use the actual parked
                    # state. The later waveform releases the switch.
                    transformed.append(line.replace("DC 0 PWL", "DC 3.3 PWL", 1))
                elif line.startswith("IIN "):
                    transformed.append("IIN bias remote 0")
                elif line.startswith(".options "):
                    transformed.append(".options reltol=1e-7 abstol=1p vntol=1n")
                else:
                    transformed.append(line)
            case_dir = folder / f"case_{index:03d}"
            case_dir.mkdir()
            (case_dir / "circuit.cir").write_text("\n".join(transformed)+"\n")
            case = {
                "netlist": "circuit.cir", "pspice_compatibility": True, "matrix_solver": cfg["matrix_solver"],
                "vendor_model": {"path": str(model.relative_to(ROOT)), "sha256": digest(model)},
                "reference": ref,
                "sine": {"frequency_hz": frequency, "amplitude_v": .0001, "start_s": delay,
                         "save_from_s": save_from, "stop_s": stop, "maximum_step_s": maximum_step},
                "analyses": [
                    {"name": "startup_op", "command": "op", "vectors": ["output", "amp_out", "park_ctl"]},
                    {"name": "tran", "command": f"tran {maximum_step:.14g} {stop:.14g} {save_from:.14g} {maximum_step:.14g}",
                     "vectors": ["time", "output", "amp_out", "inv", "feedback", "park_ctl"]}
                ]}
            (case_dir / "case.json").write_text(json.dumps(case, indent=2)+"\n")
            cases[case_dir] = case
        record["workers"] = []
        results = []; failures = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {pool.submit(run_case, p): p for p in cases}
            for future in as_completed(pending):
                case_dir = pending[future]
                receipt, error = future.result(); record["workers"].append(receipt)
                if error:
                    failures.append({"case": case_dir.name, "error": error})
                    print("Failed", case_dir.name, error[-300:], flush=True)
                    continue
                case = cases[case_dir]; ref = case["reference"]
                raw = json.loads((case_dir / "output/results.json").read_text())["results"]
                times = vector(raw["tran"], "time")
                frequency = case["sine"]["frequency_hz"]
                vinv, inv_residual = fit_wave(times, vector(raw["tran"], "inv"), frequency)
                vfeedback, feedback_residual = fit_wave(times, vector(raw["tran"], "feedback"), frequency)
                measured = -vfeedback/vinv
                ref_raw = json.loads((source / ref["directory"] / "output/results.json").read_text())["results"]["ac"]
                fref = vector(ref_raw, "frequency").real
                tref = -vector(ref_raw, "feedback")/vector(ref_raw, "inv")
                expected = complex(np.interp(np.log(frequency), np.log(fref), tref.real),
                                   np.interp(np.log(frequency), np.log(fref), tref.imag))
                magnitude_error = abs(abs(measured)/abs(expected)-1)
                phase_error = abs(float(np.angle(measured/expected, deg=True)))
                amp = vector(raw["tran"], "amp_out")
                initial_control = vector(raw["startup_op"], "park_ctl")[0]
                controls = vector(raw["tran"], "park_ctl")
                startup_ok = bool(initial_control > 2.2 and np.all(controls < .8))
                headroom = bool(np.all((amp > .1) & (amp < cfg["supply_v"]-.1)))
                row = {"reference_case": ref["directory"], "gain_id": ref["gain_id"],
                       "frequency_hz": frequency, "expected": [expected.real, expected.imag],
                       "measured": [measured.real, measured.imag],
                       "relative_magnitude_error": float(magnitude_error), "phase_error_deg": phase_error,
                       "fit_residual_relative_to_amplitude": max(inv_residual, feedback_residual),
                       "startup_and_release_verified": startup_ok, "linear_headroom": headroom,
                       "passed": bool(startup_ok and headroom and magnitude_error < .02 and phase_error < 1
                                      and max(inv_residual, feedback_residual) < .01)}
                results.append(row)
                print(json.dumps(row), flush=True)
        result = {"schema": "yam-f1-time-reference-crosscheck/1",
                  "physical_evidence": False, "reference_run": str(source.relative_to(ROOT)),
                  "reference_screen_sha256": digest(source / "screen.json"),
                  "scope": "Four limiting crossings" if args.worst_only else "One time-domain probe at every declared unity crossing",
                  "results": results, "failures": failures,
                  "all_completed": not failures and len(results) == len(cases),
                  "all_passed": not failures and len(results) == len(cases) and all(r["passed"] for r in results)}
        (folder / "comparison.json").write_text(json.dumps(result, indent=2)+"\n")
        record["summary"] = {k: result[k] for k in ("scope", "all_completed", "all_passed")}
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), **record["summary"]}, indent=2))


if __name__ == "__main__":
    main()
