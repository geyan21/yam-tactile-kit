#!/usr/bin/python3
"""Check ADC-driver time-step sensitivity and preserve comparison to completed trap runs."""

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
from screen_f1_feedback import digest, run_case
from screen_f1_adc_driver import evaluate
from check_f1_opa_model import vector


def late_trace_difference(first, second):
    a, b = (json.loads(path.read_text())["results"]["tran"] for path in (first, second))
    ta, tb = vector(a, "time"), vector(b, "time")
    # Compare settled parts of each acquisition window. Interpolation is only
    # used after edges, not to infer peak impulse agreement.
    phase = np.mod(ta, .00002)
    mask = (ta > .00002) & (phase > .000018) & (phase < .0000199)
    diffs = {}
    for name in ("output", "ainp", "ainn", "samplep", "samplen"):
        diffs[name] = float(np.max(abs(vector(a, name)[mask]-np.interp(ta[mask], tb, vector(b, name)))))
    return diffs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--trapezoidal", type=Path, required=True)
    args = parser.parse_args()
    reference, trap = args.reference.resolve(), args.trapezoidal.resolve()
    if not all(path.is_relative_to(ROOT / "build") for path in (reference, trap)):
        parser.error("Use saved repository-owned circuit runs")
    cfg = json.loads((reference / "inputs/f1_adc_stage.json").read_text())
    summary = json.loads((reference / "screen.json").read_text())
    trap_summary = json.loads((trap / "screen.json").read_text())
    if not summary["all_passed"] or digest(reference / "inputs/f1_adc_stage.json") != summary["configuration_sha256"]:
        raise ValueError("Use an unchanged completed reference run")
    destination = ROOT / "build/engineering/prototypes/f1/adc_numerics" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Cross-check F1 ADC settling with ten-times-smaller maximum steps and every completed matching trapezoidal transient; preserve unsuccessful source runs") as record:
        destination.mkdir(parents=True, exist_ok=False)
        inputs = destination / "inputs"; inputs.mkdir()
        for path in (Path(__file__), ROOT / "engineering/scripts/screen_f1_adc_driver.py",
                     ROOT / "engineering/scripts/run_f1_spice_case.py", ROOT / "engineering/scripts/f1_spice.py"):
            shutil.copyfile(path, inputs / path.name)
        cases = {}
        for index in (5, 9, 17, 23):
            name = f"case_{index:03d}"
            source = reference / name
            case = json.loads((source / "case.json").read_text())
            target = destination / name; target.mkdir()
            shutil.copyfile(source / "circuit.cir", target / "circuit.cir")
            for analysis in case["analyses"]:
                if analysis["name"] == "tran":
                    words = analysis["command"].split()
                    words[1] = words[4] = "2e-9"
                    analysis["command"] = " ".join(words)
            case["refinement"] = {"source_case_sha256": digest(source / "case.json"),
                                  "maximum_step_s": 2e-9, "circuit_unchanged": True}
            (target / "case.json").write_text(json.dumps(case, indent=2)+"\n")
            cases[target] = case
        refined = []; failures = []; record["workers"] = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {pool.submit(run_case, path): path for path in cases}
            for future in as_completed(pending):
                path = pending[future]
                receipt, error = future.result(); record["workers"].append(receipt)
                if error:
                    failures.append({"case": path.name, "error": error})
                    continue
                row = evaluate(cases[path], json.loads((path / "output/results.json").read_text()), cfg)
                diffs = late_trace_difference(reference / path.name / "output/results.json", path / "output/results.json")
                row.update({"case": path.name, "settled_trace_differences_v": diffs})
                row["passed"] &= max(diffs.values()) < 1e-6
                refined.append(row)
        trap_rows = []
        for row in trap_summary["results"]:
            if row["kind"] != "transient":
                continue
            name = row["directory"]
            # Only the integration option may differ between these circuits.
            decks = [(folder / name / "circuit.cir").read_text().splitlines() for folder in (reference, trap)]
            strip = lambda lines: [line for line in lines if not line.startswith(".options ")]
            if strip(decks[0]) != strip(decks[1]):
                raise ValueError(f"Different physical circuit in trap comparison: {name}")
            diffs = late_trace_difference(reference / name / "output/results.json", trap / name / "output/results.json")
            trap_rows.append({"case": name, "trapezoidal_screen_passed": row["passed"],
                              "settled_trace_differences_v": diffs,
                              "passed": bool(row["passed"] and max(diffs.values()) < 1e-6)})
        report = {
            "schema": "yam-f1-adc-numerics/1", "physical_evidence": False,
            "reference": str(reference.relative_to(ROOT)), "reference_sha256": digest(reference / "screen.json"),
            "trapezoidal": str(trap.relative_to(ROOT)), "trapezoidal_sha256": digest(trap / "screen.json"),
            "refined_cases": refined, "completed_trapezoidal_comparisons": trap_rows, "failures": failures,
            "unresolved_trapezoidal_workers": len(trap_summary["failures"]),
            "passed": bool(not failures and len(refined) == len(cases)
                           and all(row["passed"] for row in refined+trap_rows)),
            "limits": [
                "Compares settled acquisition windows; it does not establish matching impulse peaks at a two-nanosecond switch edge.",
                "Gear integration adds numerical damping. The separate AC screen and retained failed trapezoidal cases remain part of the evidence.",
                "The ADC model is an explicit switched-capacitor approximation. No hardware resolution, force accuracy or contact behavior is measured."
            ],
        }
        (destination / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(destination.relative_to(ROOT)), "passed": report["passed"],
                            "refined": len(refined), "completed_trapezoidal_compared": len(trap_rows),
                            "unresolved_trapezoidal_workers": report["unresolved_trapezoidal_workers"],
                            "max_settled_difference_v": max(
                                max(row["settled_trace_differences_v"].values()) for row in refined+trap_rows)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
