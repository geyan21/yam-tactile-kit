#!/usr/bin/python3
"""Replay one saved good case and one saved aborted case to check result handling."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--completed-case", type=Path, required=True)
    parser.add_argument("--aborted-case", type=Path, required=True)
    args = parser.parse_args()
    cases = [(args.completed_case.resolve(), True), (args.aborted_case.resolve(), False)]
    if not all(path.is_relative_to(ROOT / "build") for path, _ in cases):
        parser.error("Select preserved cases from the repository build tree")
    folder = ROOT / "build/engineering/prototypes/f1/worker_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Replay a completed and an aborted saved circuit to verify that partial ngspice output cannot become a passing result") as record:
        folder.mkdir(parents=True, exist_ok=False)
        rows = []
        for path, expected in cases:
            label = "completed_control" if expected else "aborted_control"
            command = ["/usr/bin/python3", str(ROOT / "engineering/scripts/run_f1_spice_case.py"),
                       str(path), "--output", str(folder / label)]
            started = time.monotonic()
            with (folder / f"{label}.log").open("w") as stream:
                process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
                stopped = False
                try:
                    result = process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    stopped = True
                    try:
                        result = process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        result = process.wait()
            output_exists = (folder / label / "results.json").exists()
            row = {"case": str(path.relative_to(ROOT)), "case_sha256": digest(path),
                   "command": command, "pid": process.pid, "exit_code": result,
                   "elapsed_s": time.monotonic()-started, "intentional_stop": stopped,
                   "expected_completed_result": expected, "completed_result_exists": output_exists,
                   "passed": bool(not stopped and ((result == 0 and output_exists) if expected
                                                   else (result != 0 and not output_exists)))}
            if not expected:
                log = (folder / f"{label}.log").read_text().lower()
                row["explicit_analysis_failure"] = any(text in log for text in
                    ("doanalyses:", "simulation(s) aborted", "stopped before its requested endpoint"))
                row["passed"] &= row["explicit_analysis_failure"]
            rows.append(row)
        report = {"schema": "yam-f1-worker-failure-handling/1", "physical_evidence": False,
                  "checks": rows, "passed": all(row["passed"] for row in rows),
                  "input_sha256": {name: digest(ROOT / "engineering/scripts" / name) for name in
                                   ("f1_spice.py", "run_f1_spice_case.py", Path(__file__).name)}}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = report
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), **report}, indent=2))
        if not report["passed"]:
            raise RuntimeError("The saved failure-handling controls did not pass")


if __name__ == "__main__":
    main()
