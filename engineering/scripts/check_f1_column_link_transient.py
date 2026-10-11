#!/usr/bin/python3
"""Exercise selected-column wire breaks after the intended parked startup."""

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
from screen_f1_feedback import CONFIG, circuit, run_case, digest
from check_f1_opa_model import vector
from check_f1_column_link import ideal_test_drop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    model = args.model.resolve()
    base = json.loads(CONFIG.read_text())
    fanout_path = ROOT / "engineering/designs/f1_fanout_development.json"
    fanout = json.loads(fanout_path.read_text())
    test = fanout["test_mux"]
    folder = ROOT / "build/engineering/prototypes/f1/column_link_transients" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check the selected-column test path when wires open after a verified parked startup; no hardware or force inference") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        for path in (CONFIG, fanout_path, Path(__file__), ROOT / "engineering/scripts/screen_f1_feedback.py",
                     ROOT / "engineering/scripts/run_f1_spice_case.py", ROOT / "engineering/scripts/f1_spice.py",
                     ROOT / "engineering/scripts/check_f1_column_link.py"):
            shutil.copyfile(path, inputs / path.name)
        cases = {}
        for load in (25, 2500, 250000):
            for fault in ("healthy", "current_open", "sense_open", "both_open"):
                cfg = copy.deepcopy(base)
                cfg["spice_voltage_datum_v"] = 0
                cfg["transient"]["stop_s"] = .003
                deck, _ = circuit(cfg, 1, load, 3, 2, True)
                lines = []
                for line in deck:
                    if line.startswith("RCABLEI "):
                        lines.append("SCABLEI current_s remote gate_i low WIREI")
                    elif line.startswith("RCABLES "):
                        lines.append("SCABLES remote sense_s gate_s low WIRES")
                    elif line.startswith("IIN "):
                        lines.append("IIN bias remote 0")
                    elif line != ".end":
                        lines.append(line)
                for label, opens in (("i", fault in ("current_open", "both_open")),
                                    ("s", fault in ("sense_open", "both_open"))):
                    waveform = "3.3" if not opens else "3.3 PWL(0 3.3 0.001 3.3 0.0010002 0 0.003 0)"
                    lines.append(f"VGATE{label.upper()} gate_{label} low {waveform}")
                lines += [
                    f".model WIREI VSWITCH(RON={cfg['interconnect']['current_path_ohm_assumed']} ROFF=1e12 VON=2.2 VOFF=1.1)",
                    f".model WIRES VSWITCH(RON={cfg['interconnect']['sense_path_ohm_assumed']} ROFF=1e12 VON=2.2 VOFF=1.1)",
                    f"RLINKTEST vcc test_d {test['source_test_resistor_ohm']}",
                    "VLINKTEST test_ctl low 0 PWL(0 0 0.002 0 0.0020002 3.3 0.003 3.3)",
                    "SLINKTEST test_d remote test_ctl low TESTSW",
                    f".model TESTSW VSWITCH(RON={test['on_resistance_limit_ohm_at_3v_pm10percent_full_temperature']} ROFF=1e12 VON=2.2 VOFF=1.1)",
                    "CTESTD test_d low 360p",
                    "CTESTS remote low 40p",
                    ".save time output amp_out remote park_ctl gate_i gate_s test_ctl",
                    ".end"
                ]
                case_dir = folder / (f"load_{load}_"+fault)
                case_dir.mkdir()
                (case_dir / "circuit.cir").write_text("\n".join(lines)+"\n")
                case = {
                    "netlist": "circuit.cir", "pspice_compatibility": True,
                    "matrix_solver": cfg["matrix_solver"], "bias_seed_mode": "none",
                    "vendor_model": {"path": str(model.relative_to(ROOT)), "sha256": digest(model)},
                    "parameters": {"load_ohm": load, "fault": fault, "gain_id": 1,
                                   "fault_time_s": .001, "test_enable_time_s": .002},
                    "analyses": [
                        {"name": "startup_op", "command": "op",
                         "vectors": ["output", "amp_out", "park_ctl", "gate_i", "gate_s", "test_ctl"]},
                        {"name": "tran", "command": "tran 1e-7 0.003 0 1e-7",
                         "vectors": ["time", "output", "amp_out", "remote", "park_ctl", "gate_i", "gate_s", "test_ctl"]}
                    ]}
                (case_dir / "case.json").write_text(json.dumps(case, indent=2)+"\n")
                cases[case_dir] = case
        record["workers"] = []
        rows = []; failures = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {pool.submit(run_case, path): path for path in cases}
            for future in as_completed(pending):
                path = pending[future]
                receipt, error = future.result(); record["workers"].append(receipt)
                if error:
                    failures.append({"case": path.name, "error": error})
                    print("Failed", path.name, error[-200:], flush=True)
                    continue
                case = cases[path]; fault = case["parameters"]["fault"]
                result = json.loads((path / "output/results.json").read_text())["results"]
                raw = result["tran"]
                times = vector(raw, "time")
                output = vector(raw, "output")
                amplifier = vector(raw, "amp_out")
                remote = vector(raw, "remote")
                before = (times > .0018) & (times < .0019)
                after = times > .00285
                if times[-1] < .003*(1-1e-9) or not np.any(before) or not np.any(after):
                    failures.append({"case": path.name, "error": "Saved transient is incomplete", "last_time_s": float(times[-1])})
                    continue
                startup_ok = bool(vector(result["startup_op"], "park_ctl")[0] > 2.2)
                released = times > .00005
                startup_ok &= bool(np.all(vector(raw, "park_ctl")[released] < .8))
                controls_ok = bool(np.all(vector(raw, "test_ctl")[before] < .8) and
                                   np.all(vector(raw, "test_ctl")[after] > 2.2))
                for label, expected_open in (("gate_i", fault in ("current_open", "both_open")),
                                            ("gate_s", fault in ("sense_open", "both_open"))):
                    gate = vector(raw, label)
                    controls_ok &= bool(np.all(gate[times < .001] > 2.2) and
                                        (np.all(gate[times > .001001] < .8) if expected_open else
                                         np.all(gate[times > .001001] > 2.2)))
                baseline = float(np.mean(output[before]))
                final = float(np.mean(output[after]))
                delta = baseline-final
                steady = bool(np.ptp(output[before]) < .006 and np.ptp(output[after]) < .006)
                physically_plausible = bool(np.all((output > -.05) & (output < base["supply_v"]+.05)) and
                                             np.all((amplifier > -.05) & (amplifier < base["supply_v"]+.05)))
                expected = ideal_test_drop(base, case["parameters"]["load_ohm"],
                                           test["source_test_resistor_ohm"] +
                                           test["on_resistance_limit_ohm_at_3v_pm10percent_full_temperature"])
                healthy = fault == "healthy"
                classified_healthy = .70 <= delta <= .95
                row = {
                    **case["parameters"], "baseline_output_v": baseline, "test_output_v": final,
                    "drop_v": delta, "healthy_window_v": [.70, .95],
                    "startup_verified": startup_ok, "control_timing_verified": controls_ok,
                    "settled_measurement_windows": steady, "physically_plausible_outputs": physically_plausible,
                    "minimum_output_v": float(output.min()), "maximum_output_v": float(output.max()),
                    "remote_test_voltage_v": float(np.mean(remote[after])),
                    "classified_healthy": classified_healthy,
                    "expected_healthy_drop_v": expected,
                    "passed": bool(startup_ok and controls_ok and steady and physically_plausible and
                                   classified_healthy == healthy and (not healthy or abs(delta/expected-1) < .005))
                }
                rows.append(row)
                print(json.dumps({"case": path.name, "drop_v": delta, "passed": row["passed"]}), flush=True)
        report = {
            "schema": "yam-f1-column-link-transient-check/1",
            "physical_specimens_tested": 0, "configuration_sha256": digest(inputs / CONFIG.name),
            "vendor_model_sha256": digest(model), "results": rows, "failures": failures,
            "all_completed": not failures and len(rows) == len(cases),
            "all_passed": not failures and len(rows) == len(cases) and all(r["passed"] for r in rows),
            "limits": [
                "Twelve circuit simulations: three healthy controls and nine open-wire scenarios; no physical wire was tested.",
                "Only the selected column's current and sense conductors are exercised. Foil continuity, row wiring, shorts, swaps and arbitrary faults remain unqualified.",
                "Switch charge injection, full row-driver dynamics, the ADC and physical component variation are not modeled.",
                "Test phases are electrical observations and must not enter contact or force datasets."
            ]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["summary"] = {k: report[k] for k in ("all_completed", "all_passed")}
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), **record["summary"]}, indent=2))


if __name__ == "__main__":
    main()
