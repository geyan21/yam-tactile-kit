#!/usr/bin/python3
"""Screen sealed-air volume, temperature and range sensitivity before designing P1 chambers."""

from datetime import datetime, timezone
import csv
import itertools
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest

CONFIG = ROOT / "engineering/designs/pneumatic_volume_screen.json"


def gauge(chamber, remote, change, pad_temperature, remote_temperature, initial_temperature, initial_pressure):
    if min(chamber, remote, chamber-change, pad_temperature, remote_temperature, initial_temperature) <= 0:
        raise ValueError("Volumes and absolute temperatures must remain positive")
    gas_amount_times_r = initial_pressure*(chamber+remote)/initial_temperature
    return gas_amount_times_r/((chamber-change)/pad_temperature+remote/remote_temperature)-initial_pressure


def main():
    config = json.loads(CONFIG.read_text())
    initial_t = config["initial_temperature_c"]+273.15
    initial_p = config["reference_pressure_pa"]
    folder = ROOT / "build/engineering/prototypes/pneumatic/volume_screens" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Screen P1 pressure-range and thermal sensitivity over declared chamber/tube/dead-volume assumptions; do not infer force performance") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        zero = gauge(30, 200, 0, initial_t, initial_t, initial_t, initial_p)
        compression = gauge(30, 200, 5, initial_t, initial_t, initial_t, initial_p)
        expected = initial_p*5/(230-5)
        thermal = gauge(30, 200, 0, initial_t+10, initial_t+10, initial_t, initial_p)
        controls = {"zero_error_pa": abs(zero), "isothermal_formula_error_pa": abs(compression-expected),
                     "uniform_temperature_error_pa": abs(thermal-initial_p*10/initial_t)}
        if max(controls.values()) > 1e-5:
            raise ValueError("Gas-law analytical control failed")
        rows = []
        choices = [config[name] for name in ("chamber_volumes_mm3", "tube_lengths_mm",
                   "unknown_sensor_and_fitting_volumes_mm3", "chamber_volume_changes_mm3",
                   "chamber_temperature_changes_c", "remote_temperature_changes_c")]
        for chamber, length, unknown, change, pad_delta, remote_delta in itertools.product(*choices):
            tube = math.pi*config["tube_id_mm"]**2/4*length
            remote = tube+unknown
            pressure = gauge(chamber, remote, change, initial_t+pad_delta,
                               initial_t+remote_delta, initial_t, initial_p)
            local_reference = gauge(chamber, remote, 0, initial_t+pad_delta,
                                   initial_t+remote_delta, initial_t, initial_p)
            wrist_reference = gauge(chamber, remote, 0, initial_t+remote_delta,
                                   initial_t+remote_delta, initial_t, initial_p)
            rows.append({"chamber_mm3": chamber, "tube_length_mm": length, "tube_mm3": tube,
                         "assumed_sensor_fitting_mm3": unknown, "volume_change_mm3": change,
                         "pad_temperature_change_c": pad_delta, "remote_temperature_change_c": remote_delta,
                         "gauge_pa": pressure, "local_reference_gauge_pa": local_reference,
                         "remote_reference_gauge_pa": wrist_reference,
                         "matched_local_reference_signal_pa": pressure-local_reference,
                         "remote_reference_signal_pa": pressure-wrist_reference})
        with (folder / "pressure_scenarios.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        summaries = []
        for inches in config["candidate_differential_ranges_in_h2o"]:
            span = inches*config["pascal_per_in_h2o"]
            # Each physical transducer must remain in range before any
            # numerical subtraction; a reference cannot recover clipped data.
            clipped = sum(abs(row["gauge_pa"]) > span for row in rows)
            summaries.append({"range_plus_minus_in_h2o": inches, "range_plus_minus_pa": span,
                             "pressure_scenarios_outside_range": clipped,
                             "matched_local_pair_outside_range": sum(max(abs(row["gauge_pa"]), abs(row["local_reference_gauge_pa"])) > span for row in rows),
                             "remote_reference_pair_outside_range": sum(max(abs(row["gauge_pa"]), abs(row["remote_reference_gauge_pa"])) > span for row in rows),
                             "pa_per_nominal_output_code": 2*span/(config["digital_max_code_3v"]-config["digital_min_code_3v"]),
                             "full_span_divided_by_nominal_resolution_pa": 2*span/2**config["nominal_high_resolution_bits"],
                             "low_force_detection_established": False})
        unloaded = [row for row in rows if row["volume_change_mm3"] == 0]
        worst_thermal = max(unloaded, key=lambda row: abs(row["remote_reference_signal_pa"]))
        inputs = [CONFIG, ROOT / config["source_review"], Path(__file__)]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        report = {"schema": "yam-pneumatic-volume-screen-result/1", "evidence_kind": "model_only",
                  "physical_specimens_tested": 0, "force_range_qualified": False,
                  "scenario_count": len(rows), "controls": controls, "range_screen": summaries,
                  "largest_no_load_remote_reference_artifact": worst_thermal,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": config["limits"]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "scenarios": len(rows),
                            "unloaded_reference_artifact_max_pa": worst_thermal["remote_reference_signal_pa"],
                            "force_qualified": False}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
