#!/usr/bin/python3
"""Generate the explicitly synthetic, deterministic calibration exercise."""

import csv
from pathlib import Path
import random

from _bootstrap import ROOT
from tactile_kit.calibration import FIELDS
from tactile_kit.records import execution


def main():
    target = ROOT / "examples/calibration.synthetic.csv"
    rng = random.Random(20261010)
    with execution(ROOT / "build/records", "Generate synthetic calibration example; no hardware input") as record:
        count = 0
        with target.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            for position in (30, 45, 60, 55):
                for force in (0, 1, 2, 5, 10, 15, 20):
                    for end_moment in (-15, 0, 15):
                        count += 1
                        m1 = force * position + end_moment
                        m2 = force * (position - 12) + end_moment
                        writer.writerow({
                            "dataset_kind": "synthetic",
                            "sensor_id": "SYNTHETIC-DEMO-ONLY",
                            "sample_id": f"synthetic-{count:03d}",
                            "partition": "test" if position == 55 else "train",
                            "contact_z_mm": position,
                            "raw_1": f"{100 + 1.7 * m1 + rng.uniform(-0.12, 0.12):.6f}",
                            "raw_2": f"{-50 + 2.4 * m2 + rng.uniform(-0.12, 0.12):.6f}",
                            "reference_force_n": force,
                        })
        record.update({"rows": count, "dataset_kind": "synthetic", "output": str(target.relative_to(ROOT))})
        print(f"Wrote {count} synthetic samples to {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
