#!/usr/bin/python3
"""Screen the F1 wrist row-driver candidate before full-array integration."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
import shutil
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest, run_case
from check_f1_opa_model import vector, loop_measure

CONFIG = ROOT / "engineering/designs/f1_row_stage.json"


def circuit(cfg, p, datum=0, steady=False):
    t, f, w = cfg["screen"], cfg["feedback"], cfg["interconnect"]
    transient = p["kind"] != "ac"
    def wave(base, amplitude):
        return (f"{base} PWL(0 {base} {t['step_start_s']} {base} "
                f"{t['step_start_s']+t['transition_s']} {base+amplitude} "
                f"{t['step_end_s']} {base+amplitude} "
                f"{t['step_end_s']+t['transition_s']} {base} {t['stop_s']} {base})")
    command = wave(cfg["bias_v"]-datum, t["command_step_v"]) if p["kind"] == "command_step" and not steady else str(cfg["bias_v"]-datum)
    current = wave(0, p["current_a"]) if p["kind"] == "load_step" and not steady else "0"
    lines = [
        "F1 sensed row-driver development", ".temp 25",
        f".options reltol=1e-6 abstol=1p vntol=1n method={t['integration_method']} maxord=2",
        f"VDD vcc 0 {cfg['supply_v']-datum}", f"VLOW low 0 {-datum}", f"VBIAS bias 0 {cfg['bias_v']-datum}",
        f".nodeset v(output)={cfg['bias_v']-datum} v(remote)={cfg['bias_v']-datum} v(feedback)={cfg['bias_v']-datum}",
        f"VCMD command 0 {command}",
        f"RMUX command row_cmd {cfg['selection']['on_resistance_ohm_for_screen']}",
        f"CMUX row_cmd low {cfg['selection']['on_capacitance_pf_assumed_at_command_node']*1e-12:.12g}",
        f"RCMDBIAS row_cmd bias {cfg['selection']['command_bias_pull_ohm']}",
        "VTEST inv feedback 0"+("" if transient else " AC 1"),
        f"XAMP row_cmd inv vcc low output {cfg['amplifiers']['model_subcircuit']}",
        f"RISO output current {f['output_isolation_ohm']}",
        f"RWIREI current remote {p['wire_ohm']}",
        f"RWIRES remote sense {w['sense_resistance_ohm_assumed']}",
        f"CSENSE sense low {w['sense_capacitance_pf_assumed']*1e-12:.12g}",
        f"RSENSE sense feedback {f['sense_input_series_ohm']}",
        f"CFLOCAL output feedback {f['local_capacitance_pf']*1e-12:.12g}",
        f"RFLOCAL output feedback {f['weak_local_dc_resistance_ohm']}",
        f"RLOAD remote bias {p['load_ohm']}",
        f"CLOAD remote low {p['capacitance_nf']*1e-9:.12g}",
        f"RMON output monitor {cfg['monitor']['series_ohm']}",
        f"CMON monitor low {cfg['monitor']['shunt_capacitance_nf']*1e-9:.12g}",
        f"ILOAD remote bias {current}",
        ".save output remote inv feedback command row_cmd monitor", ".end",
    ]
    return lines


def settling(time, signal, final, start, end, tolerance):
    mask = (time >= start) & (time < end)
    selected = time[mask]
    error = abs(signal[mask]-final)
    bad = np.flatnonzero(error > tolerance)
    if not len(selected) or (len(bad) and bad[-1] == len(selected)-1):
        return None
    return float((selected[bad[-1]+1] if len(bad) else selected[0])-start)


def evaluate(case, result, cfg):
    p, t = case["parameters"], cfg["screen"]
    datum = p.get("dc_voltage_datum_v", 0)
    data = result["results"]
    row = dict(p)
    if p["kind"] == "ac":
        ac = data["ac"]
        crossings = loop_measure(vector(ac, "frequency").real, -vector(ac, "feedback")/vector(ac, "inv"))
        margin = min((r["phase_margin_deg"] for r in crossings), default=None)
        remote = float(vector(data["op"], "remote")[0])+datum
        row.update({"crossings": crossings, "minimum_margin_deg": margin, "bias_remote_v": remote,
                    "passed": bool(abs(remote-cfg["bias_v"]) < .001 and margin is not None
                                   and margin >= t["minimum_voltage_return_margin_deg"])})
        return row
    time, remote, output = (vector(data["tran"], name) for name in ("time", "remote", "output"))
    initial = float(vector(data["dc_initial"], "remote")[-1])+datum
    final = float(vector(data["dc_final"], "remote")[-1])+datum
    rise = settling(time, remote, final, t["step_start_s"]+t["transition_s"], t["step_end_s"], t["settling_error_v"])
    fall = settling(time, remote, initial, t["step_end_s"]+t["transition_s"], t["stop_s"], t["settling_error_v"])
    physical = bool(np.all((output > .1) & (output < cfg["supply_v"]-.1))
                    and np.all((remote > .1) & (remote < cfg["supply_v"]-.1)))
    row.update({"initial_remote_v": initial, "active_remote_v": final,
                "rising_settling_s": rise, "return_settling_s": fall,
                "physical_headroom": physical, "minimum_output_v": float(output.min()),
                "maximum_output_v": float(output.max())})
    if p["kind"] == "load_step":
        row["incremental_output_resistance_ohm"] = abs((final-initial)/p["current_a"])
    passed = bool(physical and rise is not None and fall is not None
                  and max(rise, fall) < t["settling_limit_s"])
    if p["kind"] == "load_step":
        passed &= row["incremental_output_resistance_ohm"] <= t["incremental_output_resistance_ohm_limit"]
    else:
        row["command_gain"] = (final-initial)/t["command_step_v"]
        passed &= abs(row["command_gain"]-1) < .005
    row["passed"] = bool(passed)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    model, config_path = args.model.resolve(), args.config.resolve()
    if not model.is_relative_to(ROOT / "build/engineering/prototypes/f1/model_sources") or not config_path.is_relative_to(ROOT):
        parser.error("Use the F1 model cache and a repository-owned configuration")
    cfg = json.loads(config_path.read_text())
    t = cfg["screen"]
    folder = ROOT / "build/engineering/prototypes/f1/row_driver_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Screen one explicit F1 sensed row driver with AC, command and load steps; no complete-array or physical-force claim") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        for path in (config_path, Path(__file__), ROOT / "engineering/scripts/run_f1_spice_case.py",
                     ROOT / "engineering/scripts/f1_spice.py", ROOT / "engineering/scripts/check_f1_opa_model.py"):
            shutil.copyfile(path, inputs / path.name)
        parameters = [
            {"kind": "ac", "load_ohm": load, "capacitance_nf": cap, "wire_ohm": wire}
            for load, cap, wire in itertools.product(t["load_resistance_ohm_cases"], t["row_capacitance_nf_cases"],
                                                     cfg["interconnect"]["current_resistance_ohm_cases"])]
        parameters += [
            {"kind": "command_step", "load_ohm": load, "capacitance_nf": cap, "wire_ohm": 1}
            for load, cap in itertools.product((6.25, 62500), (.1, 12))]
        parameters += [
            {"kind": "load_step", "load_ohm": 1e9, "capacitance_nf": cap, "wire_ohm": 1, "current_a": current}
            for current, cap in itertools.product(t["current_step_a_cases"], (.1, 12))]
        cases = {}
        for index, p in enumerate(parameters):
            target = folder / f"case_{index:03d}"; target.mkdir()
            datum = cfg.get("dc_voltage_datum_v", 0)
            p["dc_voltage_datum_v"] = datum
            p["transient_voltage_datum_v"] = 0
            (target / "circuit.cir").write_text("\n".join(circuit(cfg, p, datum, steady=True))+"\n")
            additional = {}
            analyses = [{"name": "op", "command": "op", "vectors": ["output", "remote", "command"]}]
            if p["kind"] == "ac":
                analyses += [{"name": "ac", "command": "ac dec 120 1 100000000",
                              "vectors": ["frequency", "feedback", "inv"]}]
            else:
                source = "vcmd" if p["kind"] == "command_step" else "iload"
                initial = cfg["bias_v"]-datum if p["kind"] == "command_step" else 0
                final = initial + (t["command_step_v"] if p["kind"] == "command_step" else p["current_a"])
                (target / "physical_transient.cir").write_text("\n".join(circuit(cfg, p))+"\n")
                additional["physical_transient.cir"] = digest(target / "physical_transient.cir")
                analyses += [
                    {"name": "dc_initial", "command": f"dc {source} {initial} {initial} 1", "vectors": ["output", "remote"]},
                    {"name": "dc_final", "command": f"dc {source} {initial} {final} {(final-initial)/100}", "vectors": ["output", "remote"]},
                    {"action": "load_netlist", "netlist": "physical_transient.cir"},
                    {"name": "physical_startup_op", "command": "op", "vectors": ["output", "remote", "command"]},
                    {"name": "tran", "command": f"tran {t['maximum_step_s']} {t['stop_s']} 0 {t['maximum_step_s']}",
                     "vectors": ["time", "output", "remote", "command", "row_cmd", "monitor"]},
                ]
            case = {"netlist": "circuit.cir", "pspice_compatibility": True, "matrix_solver": "sparse",
                    "vendor_model": {"path": str(model.relative_to(ROOT)), "sha256": digest(model)},
                    "parameters": p, "analyses": analyses, "additional_netlist_hashes": additional}
            (target / "case.json").write_text(json.dumps(case, indent=2)+"\n")
            cases[target] = case
        rows = []; failures = []; record["workers"] = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {pool.submit(run_case, path): path for path in cases}
            for future in as_completed(pending):
                path = pending[future]
                receipt, error = future.result(); record["workers"].append(receipt)
                if error:
                    failures.append({"case": path.name, "error": error})
                    print("Failed", path.name, error[-220:], flush=True)
                    continue
                try:
                    row = evaluate(cases[path], json.loads((path / "output/results.json").read_text()), cfg)
                    row["directory"] = path.name
                    rows.append(row)
                    print(json.dumps({"case": path.name, "passed": row["passed"],
                                      "margin_deg": row.get("minimum_margin_deg"),
                                      "rise_us": row.get("rising_settling_s", 0)*1e6 if row.get("rising_settling_s") is not None else None,
                                      "output_resistance_ohm": row.get("incremental_output_resistance_ohm")}), flush=True)
                except Exception as error:
                    failures.append({"case": path.name, "error": type(error).__name__+": "+str(error)})
        report = {"schema": "yam-f1-row-driver-screen/1", "physical_specimens_tested": 0,
                  "configuration_sha256": digest(config_path), "vendor_model_sha256": digest(model),
                  "declared_cases": len(cases), "results": rows, "failures": failures,
                  "all_completed": not failures and len(rows) == len(cases),
                  "all_passed": not failures and len(rows) == len(cases) and all(row["passed"] for row in rows),
                  "limits": t["limits"]}
        (folder / "screen.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "completed": len(rows),
                            "passed": sum(row["passed"] for row in rows), "declared": len(cases),
                            "all_passed": report["all_passed"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
