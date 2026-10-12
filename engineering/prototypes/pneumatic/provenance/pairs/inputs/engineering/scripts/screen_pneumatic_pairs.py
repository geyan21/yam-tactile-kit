#!/usr/bin/python3
"""Screen actual P1 front/back cavity pairs, including common-pressure cancellation."""

import argparse
from datetime import datetime, timezone
import csv
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT/"build/engineering/tools/pneumatic-matplotlib"))
sys.path.insert(0, str(ROOT/"src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from screen_pneumatic_volume import gauge
from screen_f1_feedback import digest
from tactile_kit.records import execution

CONFIG = ROOT/"engineering/designs/pneumatic_pair_screen.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", type=Path)
    args = parser.parse_args()
    source = args.assembly.resolve()
    if not source.is_relative_to(ROOT/"build"):
        parser.error("Use the generated P1 assembly from this checkout")
    plan = json.loads((source/"report.json").read_text())
    if not plan["passed_nominal_checks"]:
        raise ValueError("Resolve the nominal assembly before using its cavity volumes")
    cfg = json.loads(CONFIG.read_text())
    channels = {row["id"]: row["air_volume_before_hose_sensor_mm3"] for row in plan["ports"]}
    initial_t, initial_p = cfg["initial_temperature_c"]+273.15, cfg["initial_pressure_pa"]
    def pressure(chamber, remote, change, local_delta=0, remote_delta=0):
        return gauge(chamber, remote, change, initial_t+local_delta, initial_t+remote_delta, initial_t, initial_p)
    folder = ROOT/"build/engineering/prototypes/pneumatic/pair_screens"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Evaluate P1's actual paired cavity volumes under declared gas/temperature assumptions, including nonzero common compression with unchanged differential output; no force prediction") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        rows, cancellation = [], []
        for site, length, unknown, back_factor in itertools.product(
                range(2, 6), cfg["free_tube_air_lengths_mm"], cfg["unknown_sensor_fitting_volume_each_mm3"],
                cfg["remote_back_volume_multiplier"]):
            front, back = channels[f"p1_ch{site}_front"], channels[f"p1_ch{site}_back"]
            remote_f = math.pi*cfg["tube_inner_diameter_mm"]**2/4*length+unknown
            remote_b = remote_f*back_factor
            for (change_f, change_b), (delta_f, delta_b, delta_r) in itertools.product(
                    cfg["front_back_volume_changes_mm3"], cfg["front_back_remote_temperature_changes_c"]):
                pf, pb = pressure(front, remote_f, change_f, delta_f, delta_r), pressure(back, remote_b, change_b, delta_b, delta_r)
                rows.append({"site": site, "front_cavity_mm3": front, "back_cavity_mm3": back,
                             "free_tube_air_length_mm": length, "unknown_each_port_mm3": unknown,
                             "back_remote_multiplier": back_factor, "remote_front_mm3": remote_f, "remote_back_mm3": remote_b,
                             "front_volume_change_mm3": change_f, "back_volume_change_mm3": change_b,
                             "front_temperature_change_c": delta_f, "back_temperature_change_c": delta_b,
                             "remote_temperature_change_c": delta_r, "front_gauge_pa": pf, "back_gauge_pa": pb,
                             "differential_pa": pf-pb, "outside_nominal_range": abs(pf-pb) > cfg["selected_range_plus_minus_pa"]})
            fraction = cfg["equal_total_volume_compression_fraction"]
            change_f, change_b = fraction*(front+remote_f), fraction*(back+remote_b)
            pf, pb = pressure(front, remote_f, change_f), pressure(back, remote_b, change_b)
            cancellation.append({"site": site, "free_tube_air_length_mm": length,
                             "unknown_each_port_mm3": unknown, "back_remote_multiplier": back_factor,
                             "front_volume_change_mm3": change_f, "back_volume_change_mm3": change_b,
                             "front_gauge_pa": pf, "back_gauge_pa": pb, "differential_pa": pf-pb})
        for name, data in (("scenarios", rows), ("common_compression", cancellation)):
            with (folder/(name+".csv")).open("w", newline="") as stream:
                writer = csv.DictWriter(stream, list(data[0]), lineterminator="\n")
                writer.writeheader(); writer.writerows(data)
        numerical_controls = {
            "isothermal_formula_error": abs(pressure(30, 200, 5)-initial_p*5/225),
            "equal_fraction_compression_error": abs(cancellation[0]["front_gauge_pa"]-initial_p*fraction/(1-fraction)),
            "common_compression_differential_max_abs_pa": max(abs(v["differential_pa"]) for v in cancellation)}
        if max(numerical_controls.values()) > 1e-5:
            raise ValueError("Gas-law analytical control failed")
        fig, axes = plt.subplots(1, 2, figsize=(12, 5.4), layout="constrained")
        front, back = channels["p1_ch2_front"], channels["p1_ch2_back"]
        lengths = list(range(20, 251, 5))
        for changes, label, color in (((5, 0), "Front compresses 5 mm³", "#276c8d"),
                                     ((5, 5), "Both compress 5 mm³", "#755597"),
                                     ((5, -5), "Front −5 / back +5 mm³ volume", "#a47339")):
            values = []
            for length in lengths:
                remote = math.pi*cfg["tube_inner_diameter_mm"]**2/4*length+100
                values.append(pressure(front, remote, changes[0])-pressure(back, remote, changes[1]))
            axes[0].plot(lengths, values, color=color, label=label)
        axes[0].axhline(cfg["selected_range_plus_minus_pa"], color="#ac4141", ls="--", label="Nominal +30 inH₂O limit")
        axes[0].legend(fontsize=8)
        axes[0].set(xlabel="Free hose air length at each port (mm)", ylabel="Differential pressure (Pa)",
                    title="CAD CH2 cavity pair · 100 mm³ unknown volume/port")
        common = cancellation[0]
        axes[1].plot([0, 1], [0, common["front_gauge_pa"]], "o-", label="Front pressure", color="#276c8d")
        axes[1].plot([0, 1], [0, common["back_gauge_pa"]], "o--", label="Back pressure", color="#755597")
        axes[1].plot([0, 1], [0, common["differential_pa"]], "o-", label="Measured difference", color="#327a62")
        axes[1].set_xticks([0, 1], ["Initial", "Both total volumes −2%"])
        axes[1].set(ylabel="Gauge / differential pressure (Pa)", title="A differential sensor cannot observe this common mode")
        axes[1].legend(fontsize=8)
        for axis in axes:
            axis.grid(alpha=.15)
        fig.suptitle("P1 ideal-gas sensitivity · scenario inputs, not measured force\n"
                     "Back channel is active; hose volume and thermal gradients matter", fontsize=12)
        for extension in ("png", "svg", "pdf"):
            fig.savefig(folder/("p1_pressure_sensitivity."+extension), dpi=160)
        plt.close(fig)
        zero_load = [row for row in rows if row["front_volume_change_mm3"] == row["back_volume_change_mm3"] == 0]
        inputs = [CONFIG, Path(__file__), ROOT/"engineering/scripts/screen_pneumatic_volume.py", source/"report.json"]
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        report = {"schema": "yam-p1-paired-volume-result/1", "physical_specimens_tested": 0,
                  "evidence_kind": "model_only", "force_range_qualified": False, "scenario_count": len(rows),
                  "scenarios_outside_nominal_range": sum(row["outside_nominal_range"] for row in rows),
                  "zero_deformation_thermal_case_max_abs_pa": max(abs(row["differential_pa"]) for row in zero_load),
                  "controls": numerical_controls, "common_compression_examples": cancellation,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs}, "limits": cfg["limits"]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "scenarios": len(rows),
                            "out_of_nominal_range": report["scenarios_outside_nominal_range"],
                            "thermal_differential_max_abs_pa": report["zero_deformation_thermal_case_max_abs_pa"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
