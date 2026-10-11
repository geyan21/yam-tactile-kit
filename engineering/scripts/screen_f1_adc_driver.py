#!/usr/bin/python3
"""Check the F1 ADC buffer with explicit sampling-charge and capacitance assumptions."""

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
from screen_f1_feedback import run_case, digest
from check_f1_opa_model import loop_measure, vector

CONFIG = ROOT / "engineering/designs/f1_adc_stage.json"


def circuit(cfg, level, reset, resistance, scale, transient, acquiring=False):
    s = cfg["screen"]
    source = (f"1.65 PWL(0 1.65 0.000002 1.65 0.000003 {level} {s['transient_stop_s']} {level})"
              if transient else str(level))
    test = "0" if transient else "0 AC 1"
    if transient:
        acq = (f"0 PULSE(0 3.3 {s['acquisition_start_s']} {s['sample_switch_transition_s']} "
               f"{s['sample_switch_transition_s']} {s['acquisition_duration_s']} {s['cycle_s']})")
        hold = "3.3 PULSE(3.3 0 0.000010 2n 2n 0.000009998 0.000020)"
    else:
        acq = "3.3" if acquiring else "0"
        hold = "0" if acquiring else "3.3"
    cs = cfg["adc"]["input_sample_capacitance_pf_typical_per_terminal"]*scale*1e-12
    cf = cfg["filter"]["differential_capacitance_pf"]*1e-12
    cm = cfg["filter"]["common_mode_capacitance_pf_per_terminal"]*1e-12
    lines = [
        "F1 ADC buffer and explicit sampled-capacitance approximation",
        f".temp {cfg['temperature_c']}",
        f".options reltol=1e-6 abstol=1p vntol=1n method={s.get('integration_method', 'trap')} maxord=2",
        f"VDD vcc 0 {cfg['supply_v']}", f"VIN source 0 {source}",
        f"VTEST inv output {test}",
        f"XAMP source inv vcc 0 output {cfg['buffer']['model_subcircuit']}",
        "VIMON output drive 0",
        f"RFLTP drive ainp {cfg['filter']['positive_series_ohm']}",
        f"RFLTN 0 ainn {cfg['filter']['negative_series_ohm']}",
        f"CFLT ainp ainn {cf:.12g}",
        f"CCMP ainp 0 {cm:.12g}", f"CCMN ainn 0 {cm:.12g}",
        f"VRESET reset 0 {reset}", f"VACQ acq 0 {acq}", f"VHOLD hold 0 {hold}",
        "SSAMPLEP ainp samplep acq 0 SWADC", "SSAMPLEN ainn samplen acq 0 SWADC",
        "SRESETP samplep reset hold 0 SWRESET", "SRESETN samplen reset hold 0 SWRESET",
        f".model SWADC VSWITCH(RON={resistance} ROFF=1e12 VON=2.2 VOFF=1.1)",
        ".model SWRESET VSWITCH(RON=10 ROFF=1e12 VON=2.2 VOFF=1.1)",
        f"CSAMPLEP samplep 0 {cs:.12g}", f"CSAMPLEN samplen 0 {cs:.12g}",
        "RLEAKP samplep 0 1e12", "RLEAKN samplen 0 1e12",
        ".save source output inv ainp ainn samplep samplen acq hold vimon#branch",
        ".end",
    ]
    return lines


def evaluate(case, report, cfg):
    p = case["parameters"]
    result = report["results"]
    row = dict(p)
    if p["kind"] == "ac":
        raw = result["ac"]
        gain = -vector(raw, "output")/vector(raw, "inv")
        frequency = vector(raw, "frequency").real
        crossings = loop_measure(frequency, gain)
        margin = min((r["phase_margin_deg"] for r in crossings), default=None)
        dc = float(vector(result["op"], "output")[0])
        row.update({"crossings": crossings, "minimum_margin_deg": margin, "dc_output_v": dc,
                    "passed": bool(abs(dc-p["input_v"]) < .001 and margin is not None
                                   and margin >= cfg["screen"]["minimum_voltage_return_margin_deg"])})
        return row
    raw = result["tran"]
    time = vector(raw, "time")
    output = vector(raw, "output")
    vp, vn = vector(raw, "ainp"), vector(raw, "ainn")
    samples = vector(raw, "samplep")-vector(raw, "samplen")
    controls = vector(raw, "acq")
    hold = vector(raw, "hold")
    windows = []
    s = cfg["screen"]
    expected = float(vector(result["dc"], "output")[-1])
    for index in range(1, 4):
        end = index*s["cycle_s"] + s["acquisition_start_s"]+s["acquisition_duration_s"]
        mask = (time > end-s["settling_window_before_sample_s"]) & (time < end)
        if not np.any(mask):
            raise ValueError("Missing declared sample window")
        windows.append({
            "cycle_index": index, "window_end_s": end,
            "maximum_sample_error_v": float(np.max(abs(samples[mask]-expected))),
            "maximum_pin_error_v": float(np.max(abs(vp[mask]-vn[mask]-expected))),
            "maximum_ainn_magnitude_v": float(np.max(abs(vn[mask]))),
            "acquisition_control_verified": bool(np.all(controls[mask] > 2.2) and np.all(hold[mask] < .8)),
        })
    error = max(w["maximum_sample_error_v"] for w in windows)
    physical = bool(np.all((output > -.05) & (output < cfg["supply_v"]+.05))
                    and np.all((vp > -.3) & (vp < cfg["adc"]["reference_v"]+.3))
                    and np.all((vn > -.3) & (vn < cfg["adc"]["reference_v"]+.3)))
    row.update({"dc_buffer_output_v": expected, "dc_offset_v": expected-p["input_v"],
                "windows": windows, "maximum_sample_error_v": error,
                "physically_plausible_output_and_input_limits": physical,
                "peak_buffer_current_a": float(np.max(abs(vector(raw, "vimon#branch")))),
                "passed": bool(physical and abs(expected-p["input_v"]) < .001
                               and error < s["settling_error_v_max"]
                               and all(w["acquisition_control_verified"] and w["maximum_ainn_magnitude_v"] < .1 for w in windows))})
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    model, configuration = args.model.resolve(), args.config.resolve()
    if not model.is_relative_to(ROOT / "build/engineering/prototypes/f1/model_sources") or not configuration.is_relative_to(ROOT):
        parser.error("Use the prepared F1 model cache and repository-owned configuration")
    cfg = json.loads(configuration.read_text())
    s = cfg["screen"]
    folder = ROOT / "build/engineering/prototypes/f1/adc_driver_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Evaluate the selected F1 ADC driver with a matching manufacturer amplifier model and explicitly approximate sample/hold capacitors") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        for path in (configuration, Path(__file__), ROOT / "engineering/scripts/run_f1_spice_case.py",
                     ROOT / "engineering/scripts/f1_spice.py", ROOT / "engineering/scripts/check_f1_opa_model.py"):
            shutil.copyfile(path, inputs / path.name)
        parameters = []
        for level, reset, resistance, scale in itertools.product(
                s["input_voltage_v_cases"], s["sample_reset_voltage_v_cases"],
                s["sampling_switch_resistance_ohm_assumed_cases"], s["sample_capacitance_scales"]):
            parameters.append({"kind": "transient", "input_v": level, "reset_v": reset,
                               "switch_resistance_ohm": resistance, "capacitance_scale": scale})
        for resistance, scale, acquiring in itertools.product(
                s["sampling_switch_resistance_ohm_assumed_cases"], s["sample_capacitance_scales"], (False, True)):
            parameters.append({"kind": "ac", "input_v": 1.65, "reset_v": 0,
                               "switch_resistance_ohm": resistance, "capacitance_scale": scale, "acquiring": acquiring})
        cases = {}
        for index, p in enumerate(parameters):
            case_dir = folder / f"case_{index:03d}"; case_dir.mkdir()
            transient = p["kind"] == "transient"
            deck = circuit(cfg, p["input_v"], p["reset_v"], p["switch_resistance_ohm"],
                           p["capacitance_scale"], transient, p.get("acquiring", False))
            (case_dir / "circuit.cir").write_text("\n".join(deck)+"\n")
            analyses = [{"name": "op", "command": "op", "vectors": ["output", "source"]}]
            if transient:
                analyses += [
                    {"name": "dc", "command": f"dc vin {p['input_v']} {p['input_v']} 1", "vectors": ["output", "source"]},
                    {"name": "tran", "command": f"tran {s['transient_maximum_step_s']} {s['transient_stop_s']} 0 {s['transient_maximum_step_s']}",
                     "vectors": ["time", "source", "output", "ainp", "ainn", "samplep", "samplen", "acq", "hold", "vimon#branch"]},
                ]
            else:
                analyses += [{"name": "ac", "command": "ac dec 120 1 100000000",
                              "vectors": ["frequency", "output", "inv"]}]
            case = {"netlist": "circuit.cir", "pspice_compatibility": True, "matrix_solver": "klu",
                    "vendor_model": {"path": str(model.relative_to(ROOT)), "sha256": digest(model)},
                    "parameters": p, "analyses": analyses, "physical_evidence": False}
            (case_dir / "case.json").write_text(json.dumps(case, indent=2)+"\n")
            cases[case_dir] = case
        rows = []; failures = []; record["workers"] = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {pool.submit(run_case, path): path for path in cases}
            for future in as_completed(pending):
                path = pending[future]
                receipt, error = future.result(); record["workers"].append(receipt)
                if error:
                    failures.append({"case": path.name, "error": error})
                    print("Failed", path.name, error[-250:], flush=True)
                    continue
                try:
                    row = evaluate(cases[path], json.loads((path / "output/results.json").read_text()), cfg)
                    row["directory"] = path.name
                    rows.append(row)
                    print(json.dumps({"case": path.name, "passed": row["passed"],
                                      "margin_deg": row.get("minimum_margin_deg"),
                                      "sample_error_uv": row.get("maximum_sample_error_v", 0)*1e6}), flush=True)
                except Exception as error:
                    failures.append({"case": path.name, "error": type(error).__name__+": "+str(error)})
        report = {"schema": "yam-f1-adc-driver-screen/1", "physical_specimens_tested": 0,
                  "configuration_sha256": digest(configuration), "vendor_model_sha256": digest(model),
                  "declared_cases": len(cases), "results": rows, "failures": failures,
                  "all_completed": not failures and len(rows) == len(cases),
                  "all_passed": not failures and len(rows) == len(cases) and all(row["passed"] for row in rows),
                  "limits": s["limits"]}
        (folder / "screen.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)),
                            "completed": len(rows), "passed": sum(row["passed"] for row in rows),
                            "declared": len(cases), "all_passed": report["all_passed"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
