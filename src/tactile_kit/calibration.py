"""Small two-channel least-squares exercise with an explicit held-out partition."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import math
from pathlib import Path
import statistics


FIELDS = [
    "dataset_kind", "sensor_id", "sample_id", "partition",
    "contact_z_mm", "raw_1", "raw_2", "reference_force_n",
]


def read_samples(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or set(reader.fieldnames) != set(FIELDS):
            raise ValueError(f"CSV columns must be exactly: {', '.join(FIELDS)}")
        rows = []
        for row in reader:
            if row["dataset_kind"] not in {"synthetic", "measured"}:
                raise ValueError("dataset_kind must be synthetic or measured")
            if row["partition"] not in {"train", "test"}:
                raise ValueError("partition must be train or test")
            if not row["sensor_id"].strip() or not row["sample_id"].strip():
                raise ValueError("sensor_id and sample_id cannot be empty")
            for key in ("contact_z_mm", "raw_1", "raw_2", "reference_force_n"):
                row[key] = float(row[key])
                if not math.isfinite(row[key]):
                    raise ValueError(f"{key} must be finite")
            if row["contact_z_mm"] <= 0 or row["reference_force_n"] < 0:
                raise ValueError("Contact distance must be positive and reference force nonnegative")
            rows.append(row)
    if len({row["dataset_kind"] for row in rows}) != 1:
        raise ValueError("Use exactly one dataset_kind per file")
    if len({row["sensor_id"] for row in rows}) != 1:
        raise ValueError("Calibrate exactly one sensor_id per file")
    if len({row["sample_id"] for row in rows}) != len(rows):
        raise ValueError("sample_id values must be unique")
    return rows


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    augmented = [row[:] + [value] for row, value in zip(matrix, vector)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-9:
            raise ValueError("Calibration is rank-deficient: vary load position or applied moment")
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        divisor = augmented[col][col]
        augmented[col] = [value / divisor for value in augmented[col]]
        for row in range(3):
            if row != col:
                scale = augmented[row][col]
                augmented[row] = [
                    value - scale * other for value, other in zip(augmented[row], augmented[col])
                ]
    return [row[3] for row in augmented]


def fit_and_evaluate(rows: list[dict]) -> dict:
    train = [row for row in rows if row["partition"] == "train"]
    test = [row for row in rows if row["partition"] == "test"]
    if len(train) < 6 or len(test) < 3:
        raise ValueError("At least 6 training and 3 held-out samples are required")
    if len({row["contact_z_mm"] for row in train}) < 2:
        raise ValueError("Training must include at least two contact positions")
    means = [statistics.mean(row[key] for row in train) for key in ("raw_1", "raw_2")]
    scales = [statistics.pstdev(row[key] for row in train) for key in ("raw_1", "raw_2")]
    if min(scales) < 1e-12:
        raise ValueError("Both raw channels must vary in the training data")
    features = [
        [(row["raw_1"] - means[0]) / scales[0], (row["raw_2"] - means[1]) / scales[1], 1.0]
        for row in train
    ]
    matrix = [[sum(x[a] * x[b] for x in features) for b in range(3)] for a in range(3)]
    vector = [sum(x[a] * row["reference_force_n"] for x, row in zip(features, train)) for a in range(3)]
    solution = _solve(matrix, vector)
    a, b = solution[0] / scales[0], solution[1] / scales[1]
    intercept = solution[2] - a * means[0] - b * means[1]
    predictions = []
    for row in test:
        predicted = a * row["raw_1"] + b * row["raw_2"] + intercept
        predictions.append({
            "sample_id": row["sample_id"],
            "contact_z_mm": row["contact_z_mm"],
            "reference_force_n": row["reference_force_n"],
            "predicted_force_n": predicted,
            "error_n": predicted - row["reference_force_n"],
        })
    errors = [row["error_n"] for row in predictions]
    measured = rows[0]["dataset_kind"] == "measured"
    return {
        "schema_version": 1,
        "dataset_kind": rows[0]["dataset_kind"],
        "sensor_id": rows[0]["sensor_id"],
        "hardware_qualified": False,
        "scope": (
            "Offline fit of supplied measurements. Independent physical qualification still required."
            if measured else
            "Synthetic demonstration only. These errors are not measured sensor performance."
        ),
        "model": {"raw_1_coefficient": a, "raw_2_coefficient": b, "offset_n": intercept},
        "training_samples": len(train),
        "held_out_samples": len(test),
        "training_positions_mm": sorted({row["contact_z_mm"] for row in train}),
        "held_out_positions_mm": sorted({row["contact_z_mm"] for row in test}),
        "held_out_rmse_n": math.sqrt(statistics.mean(error * error for error in errors)),
        "held_out_max_abs_error_n": max(abs(error) for error in errors),
        "held_out_predictions": predictions,
    }
