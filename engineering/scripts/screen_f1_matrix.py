#!/usr/bin/python3
"""Explore F1 matrix ghost response with finite drivers, traces and column path."""

from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/prototypes/f1"


def observe(resistance, row, column, params, clamped):
    nr, nc = resistance.shape
    patches = params["patch_columns"]
    start_columns = nr * (1 + len(patches))
    size = start_columns + nc
    matrix = np.zeros((size, size)); rhs = np.zeros(size)

    def edge(i, j, ohms):
        conductance = 1 / ohms
        matrix[i, i] += conductance; matrix[j, j] += conductance
        matrix[i, j] -= conductance; matrix[j, i] -= conductance

    def source(i, voltage, ohms):
        conductance = 1 / ohms
        matrix[i, i] += conductance; rhs[i] += voltage * conductance

    for r in range(nr):
        if r == row or clamped:
            source(r, params["excitation_above_bias_v"] if r == row else 0,
                   params["row_driver_resistance_ohm_assumed"])
        for patch, columns in enumerate(patches):
            local = nr + patch * nr + r
            edge(r, local, params["row_branch_trace_resistance_ohm_assumed"])
            for c in columns:
                edge(local, start_columns + c, resistance[r, c])
    source(start_columns + column, 0, params["selected_column_path_resistance_ohm_assumed"])
    volts = np.linalg.solve(matrix, rhs)
    residual = float(np.max(np.abs(matrix @ volts - rhs)))
    current = volts[start_columns + column] / params["selected_column_path_resistance_ohm_assumed"]
    driver_currents = [
        ((params["excitation_above_bias_v"] if r == row else 0) - volts[r])
        / params["row_driver_resistance_ohm_assumed"] if r == row or clamped else 0
        for r in range(nr)
    ]
    balance = abs(sum(driver_currents) - current)
    if residual > 1e-10 or balance > 1e-9:
        raise ValueError("Matrix solve failed nodal or external-current balance")
    return float(current / params["excitation_above_bias_v"]), {
        "kcl_residual_a": residual, "external_balance_a": float(balance),
        "maximum_driver_current_a": float(max(abs(value) for value in driver_currents)),
    }


def scan(resistance, params, clamped):
    result = np.empty_like(resistance)
    residual = balance = maximum_current = 0.
    for row, column in np.ndindex(resistance.shape):
        result[row, column], check = observe(resistance, row, column, params, clamped)
        residual = max(residual, check["kcl_residual_a"])
        balance = max(balance, check["external_balance_a"])
        maximum_current = max(maximum_current, check["maximum_driver_current_a"])
    return result, {"kcl_residual_a": residual, "external_balance_a": balance,
                    "maximum_driver_current_a": maximum_current}


def patterns(rows, columns):
    single = np.zeros((rows, columns), dtype=bool); single[1, 5] = True
    row = np.zeros_like(single); row[2, :] = True
    column = np.zeros_like(single); column[:, 5] = True
    block = np.zeros_like(single); block[1:3, 4:7] = True
    corners = np.zeros_like(single); corners[0, 4] = corners[3, 6] = True
    return {"single": single, "row": row, "column": column, "block": block,
            "two_separated": corners, "all": np.ones_like(single)}


def evaluate(params, clamped, pressed_ohms):
    nr = params["rows"]; nc = sum(map(len, params["patch_columns"]))
    base = np.full((nr, nc), params["unloaded_taxel_resistance_ohm_assumed"])
    unloaded, _ = scan(base, params, clamped)
    single_delta = np.empty_like(base)
    # A hypothetical one-contact calibration at each position isolates
    # interaction from a fixed per-channel sensitivity error in this model.
    for row, column in np.ndindex(base.shape):
        lone = base.copy(); lone[row, column] = pressed_ohms
        value, _ = observe(lone, row, column, params, clamped)
        single_delta[row, column] = value - unloaded[row, column]
    if np.any(single_delta <= 0):
        raise ValueError("One-contact model calibration is nonpositive")
    cases = []
    for name, mask in patterns(nr, nc).items():
        resistance = np.where(mask, pressed_ohms, base)
        measured, check = scan(resistance, params, clamped)
        normalized = (measured - unloaded) / single_delta
        untouched = normalized[~mask]
        ghost = max(0., float(untouched.max())) if untouched.size else 0.
        absolute_ghost = float(np.abs(untouched).max()) if untouched.size else 0.
        interaction = float(np.abs(normalized[mask] - 1).max())
        cases.append({"pattern": name, "pressed_positions": np.argwhere(mask).tolist(),
                      "maximum_positive_ghost_fraction": ghost,
                      "maximum_absolute_unpressed_change_fraction": absolute_ghost,
                      "maximum_pressed_interaction_error_fraction": interaction,
                      "normalized_response": normalized.tolist(), **check})
    maximum = max(max(case["maximum_positive_ghost_fraction"],
                      case["maximum_pressed_interaction_error_fraction"]) for case in cases)
    _, limiting_pattern, limiting_metric = max(
        (case[key], case["pattern"], key) for case in cases
        for key in ("maximum_positive_ghost_fraction", "maximum_pressed_interaction_error_fraction"))
    return {"inactive_rows": "clamped" if clamped else "floating",
            "pressed_resistance_ohm": pressed_ohms, "cases": cases,
            "maximum_ghost_or_interaction_fraction": maximum,
            "limiting_pattern": limiting_pattern, "limiting_metric": limiting_metric,
            "model_interaction_screen_met": maximum <= params["model_interaction_screen_fraction"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=ROOT / "engineering/designs/f1_electrical_screen.json")
    args = parser.parse_args()
    cfg_path = args.config.resolve()
    if not cfg_path.is_relative_to(ROOT):
        parser.error("Use a reviewed configuration inside this checkout")
    cfg = json.loads(cfg_path.read_text())
    folder = OUTPUT / "electrical_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Compare F1 matrix electrical interaction using stated resistor networks, single-contact model calibration and current-balance checks; no physical force inference") as record:
        folder.mkdir(parents=True, exist_ok=False)
        for path in (cfg_path, Path(__file__)):
            shutil.copyfile(path, folder / path.name)
        one = {**cfg, "rows": 1, "patch_columns": [[0]]}
        value, check = observe(np.array([[1000.]]), 0, 0, one, True)
        expected = 1 / (1000 + cfg["row_driver_resistance_ohm_assumed"]
                        + cfg["row_branch_trace_resistance_ohm_assumed"]
                        + cfg["selected_column_path_resistance_ohm_assumed"])
        relative = abs(value / expected - 1)
        if relative > 1e-10:
            raise ValueError("Single-resistor series-circuit check failed")
        # With all taxel resistances equal and inactive rows clamped, sum KCL
        # over the rows. Floating unselected columns draw no net current.
        # The selected column therefore has G=1/(R + Rdriver + Rbranch + nr*Rcol).
        uniform_error = 0.
        columns = sum(map(len, cfg["patch_columns"]))
        for resistance in cfg["pressed_taxel_resistance_ohm_cases"]:
            full = np.full((cfg["rows"], columns), resistance)
            expected = 1 / (resistance + cfg["row_driver_resistance_ohm_assumed"]
                            + cfg["row_branch_trace_resistance_ohm_assumed"]
                            + cfg["rows"] * cfg["selected_column_path_resistance_ohm_assumed"])
            for row, column in ((0, 0), (cfg["rows"] - 1, columns - 1)):
                value, _ = observe(full, row, column, cfg, True)
                uniform_error = max(uniform_error, abs(value / expected - 1))
        if uniform_error > 1e-10:
            raise ValueError("Uniform-matrix analytic current check failed")
        results = [evaluate(cfg, clamped, resistance)
                   for clamped in (False, True)
                   for resistance in cfg["pressed_taxel_resistance_ohm_cases"]]
        ideal_cfg = {**cfg, "row_driver_resistance_ohm_assumed": .0001,
                     "row_branch_trace_resistance_ohm_assumed": .0001,
                     "selected_column_path_resistance_ohm_assumed": .0001}
        limit_case = evaluate(ideal_cfg, True, 1000.)
        if limit_case["maximum_ghost_or_interaction_fraction"] > .0001:
            raise ValueError("The near-ideal clamped-row control has unexpected interaction")
        report = {
            "schema": "yam-f1-electrical-development/1",
            "evidence_kind": "lumped_electrical_simulation", "physical_specimens_tested": 0,
            "force_accuracy_qualified": False, "fabrication_ready": False,
            "assumptions": cfg, "results": results,
            "numerical_checks": {"single_resistor_relative_error": relative,
                                 "uniform_matrix_relative_error": uniform_error,
                                 "near_ideal_control_maximum_interaction_fraction": limit_case["maximum_ghost_or_interaction_fraction"],
                                 "passed": True},
            "source_hashes": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in (cfg_path, Path(__file__))},
            "limits": cfg["notes"] + [
                "The positionwise one-contact normalization is part of the simulated comparison, not a physical sensor calibration.",
                "A passing electrical interaction screen does not establish force accuracy or contact-event probability."
            ],
        }
        (folder / "screen.json").write_text(json.dumps(report, indent=2) + "\n")
        (OUTPUT / "f1_electrical_development.json").write_text(json.dumps(report, indent=2) + "\n")
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
        for label, color in (("floating", "#b07c43"), ("clamped", "#307e78")):
            selected = [row for row in results if row["inactive_rows"] == label]
            axes[0].plot([row["pressed_resistance_ohm"] for row in selected],
                         [100 * row["maximum_ghost_or_interaction_fraction"] for row in selected],
                         marker="o", label=label, color=color)
        axes[0].axhline(100 * cfg["model_interaction_screen_fraction"], color="#7c8b91", ls="--", label="1% model criterion")
        axes[0].set_xscale("log"); axes[0].set_yscale("log")
        axes[0].set_xlabel("Assumed pressed resistance (Ω) · no force mapping")
        axes[0].set_ylabel("Maximum modeled interaction or ghost (%)")
        axes[0].legend(fontsize=9); axes[0].grid(alpha=.2)
        example = next(row for row in results if row["inactive_rows"] == "clamped"
                       and row["pressed_resistance_ohm"] == 1000.)["cases"][3]
        image = axes[1].imshow(example["normalized_response"], vmin=0, vmax=1.05, aspect="auto", cmap="viridis")
        axes[1].set_xlabel("Column"); axes[1].set_ylabel("Row")
        axes[1].set_title("Clamped rows · 1 kΩ block pattern")
        fig.colorbar(image, ax=axes[1], label="Relative to each modeled one-contact response")
        fig.suptitle("F1 electrical exploration · ideal amplifiers, finite paths, no physical measurements")
        fig.savefig(OUTPUT / "f1_electrical_development.svg")
        fig.savefig(OUTPUT / "f1_electrical_development.png", dpi=150)
        plt.close(fig)
        for name in ("f1_electrical_development.svg", "f1_electrical_development.png"):
            shutil.copyfile(OUTPUT / name, folder / name)
        summary = [{key: row[key] for key in ("inactive_rows", "pressed_resistance_ohm",
                    "maximum_ghost_or_interaction_fraction", "limiting_pattern", "limiting_metric",
                    "model_interaction_screen_met")} for row in results]
        record["summary"] = summary; record["run"] = str(folder.relative_to(ROOT))
        print(json.dumps({"numerical_checks": report["numerical_checks"], "cases": summary}, indent=2))


if __name__ == "__main__":
    main()
