#!/usr/bin/python3
"""Check the reviewed TI model's open-loop loading before F1 circuit use."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vector(result, name):
    data = result[name]
    values = np.asarray(data["values"])
    return values[:, 0]+1j*values[:, 1] if data["complex"] else values


def loop_measure(frequency, gain):
    unity_candidates = np.flatnonzero(np.diff(np.sign(20*np.log10(np.abs(gain)))) != 0)
    phase = np.unwrap(np.angle(gain))*180/np.pi
    crossings = []
    for i in unity_candidates:
        fraction = -np.log10(abs(gain[i])) / (np.log10(abs(gain[i+1]))-np.log10(abs(gain[i])))
        unity = 10**(np.log10(frequency[i]) + fraction*(np.log10(frequency[i+1])-np.log10(frequency[i])))
        p = phase[i] + fraction*(phase[i+1]-phase[i])
        crossings.append({"unity_frequency_hz": float(unity), "phase_margin_deg": float(180+p)})
    return crossings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    args = parser.parse_args()
    model_path = args.model.resolve()
    if not model_path.is_relative_to(ROOT / "build/engineering/prototypes/f1/model_sources"):
        parser.error("Select the reviewed model from the F1 cache")
    folder = ROOT / "build/engineering/prototypes/f1/opa_model_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Characterize the reviewed TI amplifier model with a loop injection and stated load capacitance before selecting F1 feedback components") as record:
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "inputs").mkdir()
        for path in (Path(__file__), ROOT / "engineering/scripts/f1_spice.py",
                     ROOT / "engineering/scripts/run_f1_spice_case.py"):
            shutil.copyfile(path, folder / "inputs" / path.name)
        summaries = []
        record["workers"] = []
        for load_pf in (10, 100, 1000):
            case_dir = folder / ("load_"+str(load_pf))
            case_dir.mkdir()
            deck = [
                "OPA392 model loading and loop-injection check",
                ".temp 25",
                "VDD vcc 0 3.3",
                "VBIAS bias 0 1.65",
                "VTEST feedback out 0 ac 1",
                "XAMP bias feedback vcc 0 out OPAx392",
                "RLOAD out bias 10000",
                f"CLOAD out 0 {load_pf*1e-12:.6g}",
                ".save out feedback",
                ".end"
            ]
            (case_dir / "circuit.cir").write_text("\n".join(deck)+"\n")
            case = {"netlist": "circuit.cir", "pspice_compatibility": True,
                    "vendor_model": {"path": str(model_path.relative_to(ROOT)), "sha256": digest(model_path)},
                    "analyses": [
                        {"name": "op", "command": "op", "vectors": ["out", "feedback"]},
                        {"name": "ac", "command": "ac dec 200 1 100000000",
                         "vectors": ["frequency", "out", "feedback"]}
                    ]}
            (case_dir / "case.json").write_text(json.dumps(case, indent=2)+"\n")
            command = ["/usr/bin/python3", str(ROOT / "engineering/scripts/run_f1_spice_case.py"), str(case_dir / "case.json")]
            with (case_dir / "worker.log").open("w") as stream:
                process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
                item = {"argv": command, "pid": process.pid}
                record["workers"].append(item)
                try:
                    code = process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    item["intentional_stop"] = "45 s limit on this owned circuit worker"
                    process.terminate(); process.wait(timeout=10)
                    raise
            item["returncode"] = code
            if code:
                print((case_dir / "worker.log").read_text()[-5000:])
                print("Preserved case:", case_dir)
                raise RuntimeError("Vendor model control case failed")
            result = json.loads((case_dir / "output/results.json").read_text())["results"]
            frequency = vector(result["ac"], "frequency").real
            output = vector(result["ac"], "out")
            feedback = vector(result["ac"], "feedback")
            gain = -output/feedback
            row = {"load_pf": load_pf,
                    "dc_output_v": float(vector(result["op"], "out")[0]),
                    "first_frequency_open_loop_db": float(20*np.log10(abs(gain[0]))),
                    "unity_crossings": loop_measure(frequency, gain)}
            summaries.append(row)
            print(json.dumps(row, indent=2), flush=True)
        report = {"schema": "yam-f1-opa-model-review/1", "results": summaries,
                  "vendor_model_sha256": digest(model_path),
                  "limits": [
                      "Vendor model revision 1.1 dates to August 2022 and cites the older datasheet revision C.",
                      "Current datasheet revision I distinguishes the phase margin of package variants; this model is not a qualification of every package.",
                      "The fixed case temperature is 25 C; ngspice's documented PSA compatibility mode supplies the vendor TEMP parameter and switch/function translations.",
                      "Loop injection is a numerical control case. Component variation, final circuit loading and physical measurements remain required."
                  ], "physical_evidence": False}
        (folder / "review.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = report
        print("Model review:", folder)


if __name__ == "__main__":
    main()
