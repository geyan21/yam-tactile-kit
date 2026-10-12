#!/usr/bin/python3
"""Screen F1 DC array interaction with actual fanout networks and checked foil trace paths."""

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from tactile_kit.records import execution
from screen_f1_feedback import digest
from screen_f1_matrix import patterns

FOIL_PATHS = ROOT / "engineering/development/f1/fitted-foils-r3/review/foil_resistance.csv"


def edge(matrix, a, b, resistance):
    conductance = 1/resistance
    matrix[a, a] += conductance; matrix[b, b] += conductance
    matrix[a, b] -= conductance; matrix[b, a] -= conductance


def controlled_solve(matrix, controllers, commands):
    """Ideal feedback controls a sensed node by driving a different physical node."""
    count, nc = len(matrix), len(controllers)
    system = np.zeros((count+nc, count+nc))
    system[:count, :count] = matrix
    for index, (drive, sense) in enumerate(controllers):
        system[drive, count+index] = 1.
        system[count+index, sense] = 1.
    rhs = np.zeros((count+nc, commands.shape[1]))
    rhs[count:, :] = commands
    answer = np.linalg.solve(system, rhs)
    residual = float(np.max(np.abs(system @ answer-rhs)))
    balance = float(np.max(np.abs(np.sum(answer[count:, :], axis=0))))
    if residual > 1e-9 or balance > 1e-10:
        raise ValueError("Feedback network current/constraint residuals exceed the declared numerical bounds")
    return answer[:count], answer[count:], residual, balance


def controls():
    results = []
    for outside in (.1, 100.):
        matrix = np.zeros((6, 6))
        for a, b, r in ((0, 1, outside), (1, 2, .3), (2, 3, 1000), (3, 4, .6), (4, 5, outside)):
            edge(matrix, a, b, r)
        _, currents, residual, balance = controlled_solve(matrix, [(0, 1), (5, 4)], np.array([[.05], [0.]]))
        expected = .05/1000.9
        observed = currents[1, 0]
        if abs(expected/observed-1) > 1e-10:
            raise ValueError("Remote-feedback analytical control failed")
        results.append({"outside_feedback_path_ohm": outside, "expected_current_a": expected,
                        "observed_current_a": observed, "residual": residual, "balance": balance})
    return results


class ArrayModel:
    def __init__(self, network_rows, foil_rows, scenario, contact_ohm=.05, spreading_ohm=.01):
        self.excitation = .05
        self.rows, self.columns, self.branches = {}, {}, {}
        total = 0
        blocks = []
        for item in network_rows:
            if item["scenario"] != scenario:
                continue
            block = np.asarray(item["conductance_matrix_s"])
            blocks.append((total, block))
            number = int(item["net"][1:-2])
            entry = {"drive": total+item["cable_port"], "sense": total+item["sense_pickoff_port"],
                     "branches": {key: total+value for key, value in item["branch_ports"].items()}}
            (self.rows if item["net"].startswith("R") else self.columns)[number] = entry
            total += len(block)
        if set(self.rows) != set(range(4)) or set(self.columns) != set(range(16)):
            raise ValueError("Incomplete current-network set")
        self.local_rows = {(site, row): total+i for i, (site, row) in enumerate(
            (site, row) for site in range(6) for row in range(4))}
        total += 24
        self.local_columns = {column: total+column for column in range(16)}
        total += 16
        self.base = np.zeros((total, total))
        for offset, block in blocks:
            self.base[offset:offset+len(block), offset:offset+len(block)] += block
        self.column_site = {}
        key = "nominal_20c_trace_ohm" if scenario == "nominal" else "screen_50c_minimum_copper_width_trace_ohm"
        self.leads = []
        for item in foil_rows:
            site = int(item["site"][2:]); number = int(item["net"][1:])
            # The resistance CSV excludes barrel and electrode spreading.
            # Two transitions on each nail row receive a full 0.195 mm
            # barrel estimate with the requested 20 µm wall.
            rho = .00001724*(1 if scenario == "nominal" else 1+.00393*30)
            barrel = int(item["plated_transitions"])*rho*.195/(np.pi*.3*.020)
            resistance = float(item[key])+contact_ohm+spreading_ohm+barrel
            if item["role"] == "rows":
                a = self.rows[number]["branches"][item["site"]]
                b = self.local_rows[(site, number)]
            else:
                a = self.columns[number]["branches"]["electrode"]
                b = self.local_columns[number]
                self.column_site[number] = site
            edge(self.base, a, b, resistance)
            self.leads.append({"site": site, "net": item["net"], "foil_trace_ohm": float(item[key]),
                               "contact_ohm_assumed": contact_ohm, "electrode_spreading_allowance_ohm_assumed": spreading_ohm,
                               "foil_barrel_ohm_model": barrel, "total_local_lead_ohm": resistance})
        self.commands = np.zeros((5, 4)); self.commands[:4, :] = np.eye(4)*self.excitation
        self.row_controllers = [(self.rows[row]["drive"], self.rows[row]["sense"]) for row in range(4)]

    def observe(self, resistance, column):
        matrix = self.base.copy()
        for row, col in np.ndindex(4, 16):
            edge(matrix, self.local_rows[(self.column_site[col], row)], self.local_columns[col],
                 resistance[row, col])
        controllers = self.row_controllers+[(self.columns[column]["drive"], self.columns[column]["sense"])]
        _, current, residual, balance = controlled_solve(matrix, controllers, self.commands)
        return current[-1, :] / self.excitation, {"residual": residual, "balance": balance,
                                                  "maximum_row_current_a": float(np.max(np.abs(current[:4, :])))}

    def scan(self, resistance):
        output = np.zeros((4, 16)); row_current = 0.
        residual, balance = 0., 0.
        for column in range(16):
            output[:, column], check = self.observe(resistance, column)
            row_current = max(row_current, check["maximum_row_current_a"])
            residual = max(residual, check["residual"]); balance = max(balance, check["balance"])
        return output, {"maximum_row_current_a": row_current, "numerical_residual": residual, "current_balance": balance}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("network_run", type=Path)
    args = parser.parse_args()
    source = args.network_run.resolve()
    network = json.loads((source / "report.json").read_text())
    for name, expected in network["input_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Routed network inputs changed")
    with FOIL_PATHS.open() as stream:
        foil_rows = list(csv.DictReader(stream))
    folder = ROOT / "build/engineering/prototypes/f1/routed_matrix_screens" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Compare F1 multi-contact electrical interaction using the real fanout pickup locations and foil paths, retaining a separate ideal-feedback and independent-resistor scope") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [source / "report.json", FOIL_PATHS, Path(__file__), ROOT / "engineering/scripts/screen_f1_matrix.py"]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        numerical = controls()
        results = []
        for scenario in ("nominal", "hot_minimum"):
            model = ArrayModel(network["networks"], foil_rows, scenario)
            unloaded = np.full((4, 16), 1e6)
            baseline, _ = model.scan(unloaded)
            for pressed in (100., 1000., 10000.):
                sensitivity = np.zeros((4, 16))
                for row, column in np.ndindex(4, 16):
                    one = unloaded.copy(); one[row, column] = pressed
                    value, _ = model.observe(one, column)
                    sensitivity[row, column] = value[row]-baseline[row, column]
                if np.any(sensitivity <= 0):
                    raise ValueError("Nonpositive isolated-contact model response")
                cases = []
                for label, mask in patterns(4, 16).items():
                    resistance = np.where(mask, pressed, unloaded)
                    observed, check = model.scan(resistance)
                    relative = (observed-baseline)/sensitivity
                    empty = relative[~mask]
                    ghost = float(np.max(np.abs(empty))) if len(empty) else 0.
                    interaction = float(np.max(np.abs(relative[mask]-1)))
                    cases.append({"pattern": label, "response": relative.tolist(), "pressed_sites": np.argwhere(mask).tolist(),
                                  "maximum_ghost_fraction": ghost, "maximum_pressed_error_fraction": interaction,
                                  **check})
                maximum = max(max(case["maximum_ghost_fraction"], case["maximum_pressed_error_fraction"]) for case in cases)
                results.append({"scenario": scenario, "pressed_resistance_ohm": pressed,
                                "maximum_fraction": maximum, "meets_one_percent_electrical_screen": maximum <= .01,
                                "cases": cases, "lead_budget": model.leads})
                print(scenario+f" · {pressed} Ω: {maximum:.6f} interaction/ghost fraction", flush=True)
                (folder / "partial.json").write_text(json.dumps(results, indent=2)+"\n")
        fig, ax = plt.subplots(figsize=(9, 5), layout="constrained")
        for scenario in ("nominal", "hot_minimum"):
            selected = [row for row in results if row["scenario"] == scenario]
            ax.plot([row["pressed_resistance_ohm"] for row in selected], [row["maximum_fraction"]*100 for row in selected],
                       "o-", label=scenario)
        ax.axhline(1, color="#a4644a", ls="--")
        ax.set(xscale="log", ylabel="Maximum interaction / ghost response (%)",
               xlabel="Assumed pressed taxel resistance (Ω)",
               title="F1 actual routed-network DC screen\nNo resistance-to-force mapping; no physical measurements")
        ax.legend(loc="lower left")
        for suffix in ("png", "pdf"):
            fig.savefig(folder / ("routed_dc_screen."+suffix), dpi=160)
        plt.close(fig)
        report = {"schema": "yam-f1-routed-array-screen/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "controls": numerical, "results": results,
                  "limits": ["Ideal remote-feedback regulation at actual fanout pickoffs; upstream cable/wrist paths affect compliance and dynamics, not this ideal DC constraint.",
                             "Independent resistor taxels, no continuous-film lateral conduction or mechanical pressure distribution.",
                             "The 50 mΩ connector and 10 mΩ electrode-spreading allowances are stated electrical scenarios; delivered contacts and material must be measured.",
                             "No amplifier offset/leakage, saturation, gain switching, ADC errors or coupled transient validation is included.",
                             "The 1% electrical criterion is separate from the 1% physical contact-event target."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "scenarios": len(results),
                            "all_electrical_cases_pass": all(row["meets_one_percent_electrical_screen"] for row in results)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
