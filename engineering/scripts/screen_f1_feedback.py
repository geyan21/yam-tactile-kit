#!/usr/bin/python3
"""Evaluate F1's actual proposed gain/current/sense feedback topology."""

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from check_f1_opa_model import loop_measure, vector

CONFIG = ROOT / "engineering/designs/f1_feedback_screen.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def circuit(cfg, gain_id, load_ohm, capacitance_nf, scale, transient):
    branch = cfg["gain_selection"]["branches"][gain_id]
    mux = cfg["column_multiplexers"]; selection = cfg["gain_selection"]
    park = cfg["local_park_feedback"]
    active_park = cfg.get("active_park_feedback")
    t = cfg["transient"]
    datum = cfg.get("spice_voltage_datum_v", 0)
    path = branch["resistance_ohm"] + selection["on_resistance_ohm_for_screen"] + mux["on_resistance_ohm_for_screen"] + cfg["interconnect"]["current_path_ohm_assumed"]
    step_a = t["nominal_output_step_v"] / path
    lines = [
        "F1 selected-column feedback development",
        f".temp {cfg['temperature_c']}",
        ".options reltol=0.0001 abstol=1p vntol=10n",
        f"VDD vcc 0 {cfg['supply_v']-datum}",
        f"VLOW low 0 {-datum}",
        f"VBIAS bias 0 {cfg['bias_v']-datum}",
        "VTEST inv feedback 0 ac 1",
        "XAMP bias inv vcc low amp_out OPAx392",
        f"RISO amp_out output {cfg['output_isolation_ohm']}",
        f"RPARK amp_out sense_d {park['resistance_ohm']}",
        f"CPARK amp_out feedback {park['capacitance_pf']*1e-12:.9g}",
        f"COUTLOAD output low {cfg['output_buffer_input_load_pf_assumed']*1e-12:.9g}",
    ]
    if active_park:
        p = active_park
        if transient:
            control = (f"DC 3.3 PWL(0 3.3 {p['release_s']:.9g} 3.3 "
                       f"{p['release_s']+t['rise_s']:.9g} 0 {t['stop_s']:.9g} 0)")
        else:
            control = "0"
        lines += [
            f"VPARK park_ctl low {control}",
            "SPARK amp_out park_link park_ctl low PARKSW",
            f".model PARKSW VSWITCH(RON={p['switch_on_resistance_ohm_assumed']} "
            f"ROFF={p['switch_off_resistance_ohm_assumed']} VON=2.2 VOFF=1.1)",
            f"RPLOCAL park_link feedback {p['series_resistance_ohm']}",
            f"CPARKD amp_out low {scale*p['switch_capacitance_pf_per_terminal_assumed']*1e-12:.9g}",
            f"CPARKS park_link low {scale*p['switch_capacitance_pf_per_terminal_assumed']*1e-12:.9g}"
        ]
    guess = cfg.get("operating_point_initial_guess", {})
    if guess.get("enabled"):
        offset = guess["model_offset_v_for_initial_guess"]
        output_guess = cfg["bias_v"]-datum + offset*(1+path/load_ohm)
        feedback_guess = cfg["bias_v"]-datum + offset
        lines.append(f".nodeset v(output)={output_guess:.12g} v(amp_out)={output_guess:.12g} v(inv)={feedback_guess:.12g} "
                     f"v(feedback)={feedback_guess:.12g} v(remote)={feedback_guess:.12g}")
    for item in selection["branches"]:
        i = item["id"]
        resistance = (selection["on_resistance_ohm_for_screen"] if i == gain_id else
                      selection["off_resistance_ohm_assumed"])
        lines += [
            f"RGAIN{i} output gain{i} {resistance:.9g}",
            f"CGD{i} output low {scale*selection['drain_capacitance_pf_assumed']*1e-12:.9g}",
            f"CGS{i} gain{i} low {scale*selection['source_capacitance_pf_assumed']*1e-12:.9g}",
            f"RF{i} gain{i} current_d {item['resistance_ohm']}",
            f"CF{i} gain{i} current_d {item['feedback_capacitance_pf']*1e-12:.9g}",
        ]
    lines += [
        f"RCURRENT current_d current_s {mux['on_resistance_ohm_for_screen']}",
        f"CCD current_d low {scale*mux['drain_capacitance_pf_assumed']*1e-12:.9g}",
        f"CCFIX current_d low {cfg.get('current_drain_shunt_capacitance_pf', 0)*1e-12:.9g}",
        f"CCS current_s low {scale*mux['source_capacitance_pf_assumed']*1e-12:.9g}",
        f"RCABLEI current_s remote {cfg['interconnect']['current_path_ohm_assumed']}",
        f"CSENSOR remote low {capacitance_nf*1e-9:.9g}",
        f"RLOAD remote bias {load_ohm}",
        f"RCABLES remote sense_s {cfg['interconnect']['sense_path_ohm_assumed']}",
        f"CSENSES sense_s low {scale*mux['source_capacitance_pf_assumed']*1e-12:.9g}",
        f"RSENSE sense_s sense_d {mux['on_resistance_ohm_for_screen']}",
        f"CSENSED sense_d low {scale*mux['drain_capacitance_pf_assumed']*1e-12:.9g}",
    ]
    compensation = cfg.get("low_gain_compensation")
    if compensation:
        c = compensation
        bypass = c["off_resistance_ohm_assumed"] if gain_id == 0 else c["on_resistance_ohm_assumed"]
        lines += [
            f"RBOOST sense_d comp_mid {c['additional_series_resistance_ohm']}",
            f"RBYPASS sense_d comp_mid {bypass}",
            f"CBOOSTD sense_d low {scale*c['drain_capacitance_pf_assumed']*1e-12:.9g}",
            f"CBOOSTS comp_mid low {scale*c['source_capacitance_pf_assumed']*1e-12:.9g}",
            f"RINPUT comp_mid feedback {cfg.get('sense_input_resistance_ohm', .01)}"
        ]
    else:
        lines.append(f"RINPUT sense_d feedback {cfg.get('sense_input_resistance_ohm', .01)}")
    if transient:
        lines.append(f"IIN bias remote PWL(0 0 {t['step_start_s']:.9g} 0 "
                     f"{t['step_start_s']+t['rise_s']:.9g} {step_a:.12g} {t['stop_s']:.9g} {step_a:.12g})")
    else:
        lines.append("IIN bias remote 0")
    lines += [".save output amp_out inv feedback remote current_d" + (" park_ctl" if active_park else ""), ".end"]
    return lines, step_a


def run_case(case_dir):
    command = ["/usr/bin/python3", str(ROOT / "engineering/scripts/run_f1_spice_case.py"),
               str(case_dir / "case.json")]
    receipt = {"argv": command}
    with (case_dir / "worker.log").open("w") as stream:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        receipt["pid"] = process.pid
        try:
            code = process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            receipt["intentional_stop"] = "45 s limit on this owned circuit worker"
            process.terminate(); process.wait(timeout=10)
            receipt["returncode"] = process.returncode
            return receipt, "worker_timeout"
    receipt["returncode"] = code
    return receipt, None if not code else (case_dir / "worker.log").read_text()[-3000:]


def make_case(cfg, model, gain_id, load_ohm, capacitance_nf, scale, transient):
    """Define a parked DC endpoint sweep and an actual parked transient start."""
    effective = copy.deepcopy(cfg)
    datum = (cfg.get("spice_voltage_datum_v", 0) if transient else
             cfg.get("ac_voltage_datum_v", cfg.get("spice_voltage_datum_v", 0)))
    effective["spice_voltage_datum_v"] = datum
    deck, current = circuit(effective, gain_id, load_ohm, capacitance_nf, scale, transient)
    dc_vectors = ["output", "amp_out", "remote", "feedback", "park_ctl"]
    additional_netlists = {}
    if transient:
        t = cfg["transient"]
        additional_netlists["physical_transient.cir"] = deck
        dc_datum = cfg.get("ac_voltage_datum_v", datum)
        dc_cfg = copy.deepcopy(cfg)
        dc_cfg["spice_voltage_datum_v"] = dc_datum
        deck, current = circuit(dc_cfg, gain_id, load_ohm, capacitance_nf, scale, False)
        analyses = [
            {"name": "park_release_dc", "command": "dc vpark 3.3 0 -0.1", "vectors": dc_vectors},
            {"name": "dc", "command": f"dc iin 0 {current:.12g} {current:.12g}", "vectors": dc_vectors},
            {"action": "load_netlist", "netlist": "physical_transient.cir"},
            {"name": "startup_op", "command": "op", "vectors": ["output", "amp_out", "park_ctl"]},
            {"name": "tran", "command": f"tran {t['maximum_step_s']:.9g} {t['stop_s']:.9g} 0 {t['maximum_step_s']:.9g}",
             "vectors": ["time", "output", "amp_out", "remote", "feedback", "park_ctl"]}
        ]
    else:
        points = cfg["voltage_return_ratio_screen"]
        analyses = [
            {"name": "park_release_dc", "command": "dc vpark 3.3 0 -0.1",
             "vectors": ["output", "amp_out", "feedback", "park_ctl"]},
            {"name": "op", "command": "op", "vectors": ["output", "amp_out", "remote", "feedback", "inv"]},
            {"name": "ac", "command": f"ac dec {points['points_per_decade']} {points['frequency_hz'][0]} {points['frequency_hz'][1]}",
             "vectors": ["frequency", "output", "feedback", "inv"]}
        ]
    case = {
        "netlist": "circuit.cir", "pspice_compatibility": True,
        "matrix_solver": cfg.get("matrix_solver", "sparse"),
        "bias_seed_mode": "none" if transient else "nodeset",
        "vendor_model": {"path": str(model.relative_to(ROOT)), "sha256": digest(model)},
        "parameters": {"gain_id": gain_id, "load_ohm": load_ohm, "capacitance_nf": capacitance_nf,
                       "capacitance_scale": scale, "transient": transient, "voltage_datum_v": datum},
        "analyses": analyses
    }
    if transient:
        case["parameters"]["dc_voltage_datum_v"] = dc_datum
        case["additional_netlists"] = additional_netlists
    return deck, case


def save_case(folder, deck, case):
    """Write all explicit circuit variants and record their immutable hashes."""
    (folder / "circuit.cir").write_text("\n".join(deck)+"\n")
    stored = copy.deepcopy(case)
    extra = stored.pop("additional_netlists", {})
    if extra:
        stored["additional_netlist_hashes"] = {}
    for name, lines in extra.items():
        path = folder / name
        if path.parent != folder or path.suffix != ".cir":
            raise ValueError("Use a simple additional circuit filename")
        path.write_text("\n".join(lines)+"\n")
        stored["additional_netlist_hashes"][name] = digest(path)
    (folder / "case.json").write_text(json.dumps(stored, indent=2)+"\n")
    return stored


def analyze(case, folder, cfg):
    result = json.loads((folder / "output/results.json").read_text())["results"]
    p = case["parameters"]
    datum = p.get("voltage_datum_v", cfg.get("spice_voltage_datum_v", 0))
    dc_datum = p.get("dc_voltage_datum_v", datum)
    active_park = cfg.get("active_park_feedback")
    park_dc_open = True
    if active_park:
        control = vector(result["park_release_dc"], "park_ctl")+dc_datum
        park_dc_open = bool(abs(control[-1]) < 1e-6 and abs(control[0]-3.3) < 1e-6)
    if p["transient"]:
        times = vector(result["tran"], "time")
        response = vector(result["tran"], "output")+datum
        amplifier = vector(result["tran"], "amp_out")+datum
        final = float(vector(result["dc"], "output")[-1])+dc_datum
        initial = float(vector(result["dc"], "output")[0])+dc_datum
        relative_t = times-(cfg["transient"]["step_start_s"]+cfg["transient"]["rise_s"])
        mask = relative_t >= 0
        error = np.abs(response[mask]-final)
        failures = np.flatnonzero(error > cfg["transient"]["settling_error_v"])
        if len(failures) and failures[-1] == len(error)-1:
            settled = None
        else:
            index = failures[-1]+1 if len(failures) else 0
            settled = float(relative_t[mask][index])
        amplitude = abs(final-initial)
        overshoot = max(0., float(np.max(np.abs(response[mask]-initial))/amplitude-1)) if amplitude else None
        park_timing = True
        if active_park:
            control = vector(result["tran"], "park_ctl")+datum
            early = times < active_park["release_s"]/2
            released = times > active_park["release_s"] + cfg["transient"]["rise_s"]*2
            park_timing = bool(np.all(control[early] > 2.2) and np.all(control[released] < .8))
        linear_headroom = bool(np.all((amplifier > .1) & (amplifier < cfg["supply_v"]-.1)))
        baseline_time = cfg["transient"]["step_start_s"] - cfg["transient"]["maximum_step_s"]*2
        baseline_error = float(abs(np.interp(baseline_time, times, response)-initial))
        return {**p, "dc_initial_v": initial, "dc_final_v": final,
                "settling_s": settled, "overshoot_fraction": overshoot,
                "minimum_output_v": float(response.min()), "maximum_output_v": float(response.max()),
                "minimum_amplifier_pin_v": float(amplifier.min()), "maximum_amplifier_pin_v": float(amplifier.max()),
                "park_dc_open": park_dc_open, "park_timing_verified": park_timing,
                "linear_headroom": linear_headroom, "baseline_error_v_before_step": baseline_error,
                "passed": park_dc_open and park_timing and linear_headroom and
                          baseline_error <= cfg["transient"]["settling_error_v"] and
                          settled is not None and settled <= cfg["transient"]["settling_time_limit_s"],
                "scope": "Response to a stated current step, not a force or event-detection result"}
    f = vector(result["ac"], "frequency").real
    gain = -vector(result["ac"], "feedback")/vector(result["ac"], "inv")
    crossings = loop_measure(f, gain)
    minimum_margin = min((p["phase_margin_deg"] for p in crossings), default=None)
    starting_phase = float(np.angle(gain[0], deg=True))
    dc_output = float(vector(result["op"], "output")[0])+datum
    dc_amplifier = float(vector(result["op"], "amp_out")[0])+datum
    regular_bias = .1 < dc_output < cfg["supply_v"]-.1 and .1 < dc_amplifier < cfg["supply_v"]-.1
    expected_low_frequency_sign = abs(starting_phase) < 45
    return {**p, "crossings": crossings, "minimum_margin_deg": minimum_margin,
            "dc_output_v": dc_output, "dc_remote_v": float(vector(result["op"], "remote")[0])+datum,
            "dc_amplifier_pin_v": dc_amplifier, "park_dc_open": park_dc_open,
            "first_frequency_return_gain": [float(gain[0].real), float(gain[0].imag)],
            "first_frequency_phase_deg": starting_phase,
            "regular_bias": regular_bias, "expected_low_frequency_sign": expected_low_frequency_sign,
            "high_frequency_return_magnitude": float(abs(gain[-1])),
            "passed": park_dc_open and regular_bias and expected_low_frequency_sign and minimum_margin is not None
                      and cfg["voltage_return_ratio_screen"]["minimum_margin_deg"] <= minimum_margin <= 180,
            "scope": "Voltage return-ratio development screen"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--quick", action="store_true", help="First candidate screen: four gains at the highest declared load capacitance")
    args = parser.parse_args()
    cfg_path = args.config.resolve(); model = args.model.resolve()
    if not cfg_path.is_relative_to(ROOT) or not model.is_relative_to(ROOT / "build/engineering/prototypes/f1/model_sources"):
        parser.error("Use repository-owned configuration and reviewed model paths")
    cfg = json.loads(cfg_path.read_text())
    folder = ROOT / "build/engineering/prototypes/f1/feedback_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Test the proposed F1 resistor/capacitor gain branches, separate current/sense multiplexers and local parked feedback") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        for path in (cfg_path, Path(__file__), ROOT / "engineering/scripts/f1_spice.py",
                     ROOT / "engineering/scripts/run_f1_spice_case.py",
                     ROOT / "engineering/scripts/check_f1_opa_model.py"):
            shutil.copyfile(path, inputs / path.name)
        cases = {}
        caps = [max(cfg["sensing_node_capacitance_nf_cases"])] if args.quick else cfg["sensing_node_capacitance_nf_cases"]
        loads = [25, 250000] if args.quick else cfg["sensing_node_resistance_ohm_cases"]
        scales = [max(cfg["capacitance_scales"])] if args.quick else cfg["capacitance_scales"]
        combinations = [(g, r, c, s, False) for g, r, c, s in itertools.product(range(4), loads, caps, scales)]
        combinations += [(g, r, cfg["transient"]["selected_capacitance_nf"],
                          cfg["transient"]["capacitance_scale"], True)
                         for g, r in itertools.product(range(4), cfg["transient"]["selected_loads_ohm"])]
        for i, (g, r, c, s, transient) in enumerate(combinations):
            directory = folder / f"case_{i:03d}"
            directory.mkdir()
            deck, case = make_case(cfg, model, g, r, c, s, transient)
            case = save_case(directory, deck, case)
            cases[directory] = case
        record["workers"] = []
        results = []; failures = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {pool.submit(run_case, directory): directory for directory in cases}
            for future in as_completed(pending):
                directory = pending[future]
                receipt, error = future.result()
                record["workers"].append(receipt)
                if error:
                    failures.append({"directory": directory.name, "error": error})
                    print("Failed", directory.name, error[-500:], flush=True)
                    continue
                row = {"directory": directory.name, **analyze(cases[directory], directory, cfg)}
                results.append(row)
                print(json.dumps({key: row[key] for key in (
                    "directory", "gain_id", "load_ohm", "transient", "passed")}), flush=True)
        report = {
            "schema": "yam-f1-feedback-screen/1",
            "physical_specimens_tested": 0, "force_accuracy_qualified": False,
            "scope": "Quick limiting-load screen" if args.quick else "Declared single-column parameter grid",
            "configuration_sha256": digest(inputs / cfg_path.name), "vendor_model_sha256": digest(model),
            "results": sorted(results, key=lambda item: item["directory"]), "failures": failures,
            "all_declared_cases_completed": not failures and len(results) == len(cases),
            "all_declared_screens_passed": not failures and all(row["passed"] for row in results),
            "remaining": cfg["remaining"]}
        (folder / "screen.json").write_text(json.dumps(report, indent=2)+"\n")
        record["summary"] = {key: report[key] for key in ("scope", "all_declared_cases_completed", "all_declared_screens_passed")}
        record["directory"] = str(folder.relative_to(ROOT))
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), "completed_cases": len(results),
                          "failed_workers": len(failures), **record["summary"]}, indent=2))


if __name__ == "__main__":
    main()
