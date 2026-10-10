#!/usr/bin/python3
"""Fit supplied CSV data offline; never connect to or control a robot."""

import argparse
import hashlib
import json
from pathlib import Path

from _bootstrap import ROOT
from tactile_kit.calibration import fit_and_evaluate, read_samples
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "build/calibration-report.json")
    args = parser.parse_args()
    with execution(ROOT / "build/records", "Offline calibration fit and held-out evaluation") as record:
        report = fit_and_evaluate(read_samples(args.input))
        report["input_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        record.update({
            "dataset_kind": report["dataset_kind"],
            "input_sha256": report["input_sha256"],
            "output": str(args.output),
        })
        print(f"{report['dataset_kind']} data; held-out RMSE {report['held_out_rmse_n']:.6f} N")
        print(report["scope"])


if __name__ == "__main__":
    main()
