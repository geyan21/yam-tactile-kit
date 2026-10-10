#!/usr/bin/python3
"""Rebuild the offline design lab and complete source archive."""

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT
from tactile_kit.build import build
from tactile_kit.records import execution


def main():
    reproduction = ROOT / "reproduction"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "build")
    parser.add_argument("--repository-url")
    args = parser.parse_args()
    design = args.design or (reproduction / "design.json" if reproduction.exists() else ROOT / "examples/design.example.json")
    calibration = args.calibration or (reproduction / "calibration.csv" if reproduction.exists() else ROOT / "examples/calibration.synthetic.csv")
    stored = json.loads((reproduction / "build.json").read_text()) if (reproduction / "build.json").exists() else {}
    repository_url = args.repository_url if args.repository_url is not None else stored.get("repository_url", "")
    with execution(args.output / "records", "Reproduce offline concept, calibration exercise, website and source archive") as record:
        receipt = build(ROOT, args.output, design, calibration, repository_url)
        record.update(receipt)
        print(json.dumps(receipt, indent=2))
        print(f"Website: {(args.output / 'site/index.html').resolve()}")


if __name__ == "__main__":
    main()
