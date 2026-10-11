#!/usr/bin/python3
"""Check the proposed fanout test resistor against selected-column open wires."""

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


def ideal_test_drop(cfg, load, test_ohm):
    """DC relation with an ideal amplifier, including the weak feedback path."""
    gain = cfg["gain_selection"]["branches"][1]
    riso = cfg["output_isolation_ohm"]
    ri = (gain["resistance_ohm"] + cfg["gain_selection"]["on_resistance_ohm_for_screen"] +
          cfg["column_multiplexers"]["on_resistance_ohm_for_screen"] +
          cfg["interconnect"]["current_path_ohm_assumed"] + riso)
    rs = (cfg["column_multiplexers"]["on_resistance_ohm_for_screen"] +
          cfg["interconnect"]["sense_path_ohm_assumed"])
    rp = cfg["local_park_feedback"]["resistance_ohm"]
    denominator = rs/(rp*load) + (1+rs/rp)/ri + 1/rp + rs/(rp*test_ohm)
    amplifier_drop = ((cfg["supply_v"]-cfg["bias_v"])/test_ohm)/denominator
    return amplifier_drop*(1-riso*(1+rs/rp)/ri)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    args = parser.parse_args()
    model = args.model.resolve()
    base = json.loads(CONFIG.read_text())
    fanout_path = ROOT / "engineering/designs/f1_fanout_development.json"
    fanout = json.loads(fanout_path.read_text())
    test = fanout["test_mux"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    folder = ROOT / "build/engineering/prototypes/f1/column_link_checks" / stamp
    with execution(ROOT / "build/records", "Simulate the actual proposed 10 kohm fanout test path with healthy, open-current, open-sense and double-open column links") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        for path in (CONFIG, fanout_path, Path(__file__), ROOT / "engineering/scripts/screen_f1_feedback.py",
                     ROOT / "engineering/scripts/run_f1_spice_case.py", ROOT / "engineering/scripts/f1_spice.py"):
            shutil.copyfile(path, inputs / path.name)
        cases = {}
        fault_names = ("healthy", "current_open", "sense_open", "both_open")
        for load in (25, 2500, 250000):
            for fault in fault_names:
                cfg = copy.deepcopy(base)
                if fault in ("current_open", "both_open"):
                    cfg["interconnect"]["current_path_ohm_assumed"] = 1e12
                if fault in ("sense_open", "both_open"):
                    cfg["interconnect"]["sense_path_ohm_assumed"] = 1e12
                target = folder / (f"load_{load}_"+fault)
                target.mkdir()
                deck, _ = circuit(cfg, 1, load, 3, 2, False)
                deck = ["VPARK park_ctl low 3.3" if line.startswith("VPARK ") else line for line in deck]
                deck.pop()  # .end; retain saved external signal vectors.
                deck += [
                    f"RLINKTEST vcc test_d {test['source_test_resistor_ohm']}",
                    "VLINKTEST test_ctl low 0",
                    "SLINKTEST test_d remote test_ctl low TESTSW",
                    f".model TESTSW VSWITCH(RON={test['on_resistance_limit_ohm_at_3v_pm10percent_full_temperature']} ROFF=1e12 VON=2.2 VOFF=1.1)",
                    "CTESTD test_d low 360p",
                    "CTESTS remote low 40p",
                    ".save output amp_out remote feedback test_ctl park_ctl",
                    ".end"
                ]
                (target / "circuit.cir").write_text("\n".join(deck)+"\n")
                case = {
                    "netlist": "circuit.cir", "pspice_compatibility": True, "matrix_solver": cfg["matrix_solver"],
                    "bias_seed_mode": "none",
                    "vendor_model": {"path": str(model.relative_to(ROOT)), "sha256": digest(model)},
                    "parameters": {"load_ohm": load, "fault": fault, "gain_id": 1},
                    "analyses": [
                        {"name": "baseline_dc", "command": "dc vpark 3.3 0 -0.1",
                         "vectors": ["output", "amp_out", "remote", "feedback", "park_ctl", "test_ctl"]},
                        {"action": "set_dc", "source": "vlinktest", "value": 3.3},
                        {"name": "signal_dc", "command": "dc vpark 3.3 0 -0.1",
                         "vectors": ["output", "amp_out", "remote", "feedback", "park_ctl", "test_ctl"]}
                    ],
                    "endpoint_results": {"test": ["baseline_dc", "signal_dc"]},
                    "result_aliases": {"park_release_dc": "baseline_dc"}}
                (target / "case.json").write_text(json.dumps(case, indent=2)+"\n")
                cases[target] = (case, cfg)
        rows = []; failures = []
        record["workers"] = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {pool.submit(run_case, path): path for path in cases}
            for future in as_completed(pending):
                path = pending[future]
                receipt, error = future.result(); record["workers"].append(receipt)
                if error:
                    failures.append({"case": path.name, "error": error})
                    print("Failed", path.name, error[-300:], flush=True)
                    continue
                case, cfg = cases[path]
                raw = json.loads((path / "output/results.json").read_text())["results"]
                datum = cfg.get("spice_voltage_datum_v", 0)
                observed = vector(raw["test"], "output")+datum
                amplifier = vector(raw["test"], "amp_out")+datum
                remote = vector(raw["test"], "remote")+datum
                control = vector(raw["test"], "test_ctl")+datum
                park = vector(raw["park_release_dc"], "park_ctl")+datum
                plausible = bool(np.all((observed > -.05) & (observed < cfg["supply_v"]+.05)) and
                                 np.all((amplifier > -.05) & (amplifier < cfg["supply_v"]+.05)))
                delta = float(observed[0]-observed[-1])
                healthy_band = .70 <= delta <= .95
                expected_healthy = case["parameters"]["fault"] == "healthy"
                controls_ok = bool(abs(park[-1]) < 1e-6 and abs(control[0]) < 1e-6 and abs(control[-1]-3.3) < 1e-6)
                expected = ideal_test_drop(
                    base, case["parameters"]["load_ohm"],
                    test["source_test_resistor_ohm"]+test["on_resistance_limit_ohm_at_3v_pm10percent_full_temperature"])
                relative = abs(delta/expected-1) if expected_healthy else None
                row = {**case["parameters"], "baseline_output_v": float(observed[0]),
                       "test_output_v": float(observed[-1]), "test_drop_v": delta,
                       "remote_test_voltage_v": float(remote[-1]),
                       "control_endpoints_verified": controls_ok, "physically_plausible_model_outputs": plausible,
                       "healthy_window_v": [.70, .95], "classified_healthy": healthy_band,
                       "ideal_healthy_drop_v": expected, "healthy_relative_difference_from_ideal": relative,
                       "passed": plausible and controls_ok and healthy_band == expected_healthy and
                                 (relative is None or relative < .005)}
                rows.append(row)
                print(json.dumps({"case": path.name, "drop_v": delta, "passed": row["passed"]}), flush=True)
        report = {
            "schema": "yam-f1-column-link-open-check/1", "physical_specimens_tested": 0,
            "configuration_sha256": digest(inputs / CONFIG.name),
            "fanout_configuration_sha256": digest(inputs / fanout_path.name),
            "vendor_model_sha256": digest(model),
            "results": sorted(rows, key=lambda r: (r["load_ohm"], r["fault"])), "failures": failures,
            "all_declared_cases_completed": not failures and len(rows) == len(cases),
            "all_declared_checks_passed": not failures and len(rows) == len(cases) and all(r["passed"] for r in rows),
            "limits": [
                "Static model check for the selected-column current/sense link, using gain 1 with all rows held at bias.",
                "The 0.70-0.95 V acceptance window is a development proposal; verify actual components, reference voltage and ADC readings.",
                "This does not check the sensor foil beyond the fanout pickup, row-wire continuity, shorts, swapped channels, dynamic faults or simultaneous arbitrary failures.",
                "Row-driver output limits and the coupled matrix are not included in this single-column model.",
                "Electrical test phases must never be counted as contact or force observations.",
                "No physical fault-injection or 20 N experiment has been performed."
            ]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["summary"] = {k: report[k] for k in ("all_declared_cases_completed", "all_declared_checks_passed")}
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), **record["summary"]}, indent=2))


if __name__ == "__main__":
    main()
