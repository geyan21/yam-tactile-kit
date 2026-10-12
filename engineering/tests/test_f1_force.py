"""Synthetic protocol/calculation tests only; these are not physical force results."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engineering/software"))
sys.path.insert(0, str(ROOT / "engineering/tests"))
import f1_force as force
import f1_holds as holds
from test_f1_scan import StateOracle, scan


class RawHoldTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "synthetic_protocol_fixture.jsonl"
        self.manifest = {"specimen": "SYNTHETIC-TEST-ONLY", "session_id": "SYNTHETIC-SESSION",
                         "geometry_sha256": "a"*64}
        self.trial = {"condition_id": "SYNTHETIC-CONDITION", "window_host_s": [2., 12.]}
        self.config = json.loads((ROOT / "engineering/firmware/f1/config.json").read_text())
        hardware = StateOracle(self.config)
        scanner = scan.Scanner(hardware, self.config)
        self.rows = [{
            "type": "session", "schema": "yam-f1-recording/2", "protocol": holds.PROTOCOL,
            "evidence_kind": "physical_recording_unreviewed", **self.manifest,
            "condition": self.trial["condition_id"],
            "fixture_warning": "Synthetic test fixture exercising the physical-input parser; never physical evidence.",
        }]
        for index in range(32):
            messages = [{"kind": "hello", "schema": holds.PROTOCOL, "sensor_only": True,
                         "force_calibration_loaded": False, "fault_check_qualified": False,
                         "next_frame": index, "configuration": copy.deepcopy(self.config)}]
            scanner.capture_frame(index, messages.append)
            for number, message in enumerate(messages):
                self.rows.append({"host_elapsed_s": index*.5+number/len(messages)*.4, "message": message})

    def write(self, complete=True):
        self.path.write_text("".join(json.dumps(row)+"\n" for row in self.rows))
        receipt = {"schema": "yam-f1-recording-receipt/2", "sha256": holds.digest(self.path),
                   "capture_complete": complete, "requested_duration_s": 16.,
                   **self.manifest, "condition": self.trial["condition_id"]}
        self.path.with_suffix(".jsonl.receipt.json").write_text(json.dumps(receipt))

    def test_replays_full_frames_without_trusting_recorded_verdicts(self):
        self.write()
        result = holds.extract(self.path, self.manifest, self.trial)
        self.assertTrue(result["available"], result["faults"])
        self.assertEqual(len(result["mean_pixel_na"]), 64)
        self.assertAlmostEqual(result["median_frame_interval_s"], .5)
        expected_pixel = 6000*3.3/65536/499*1e9
        self.assertAlmostEqual(result["mean_signal_na"][0], 8*expected_pixel)
        self.assertAlmostEqual(result["mean_signal_na"][4], 12*expected_pixel)

    def test_missing_pixel_stays_an_unavailable_hold(self):
        self.rows = [row for row in self.rows if not (
            row.get("message", {}).get("kind") == "pixel"
            and row["message"]["frame"] == 8 and row["message"]["row"] == 1 and row["message"]["column"] == 4)]
        for row in self.rows[1:]:
            row["validation"] = {"accepted": True, "flags": []}  # Deliberately dishonest saved verdict.
        self.write()
        result = holds.extract(self.path, self.manifest, self.trial)
        self.assertFalse(result["available"])
        self.assertIn("incomplete_matrix_frame", result["faults"])

    def test_saturation_receipt_and_dummy_data_cannot_pass(self):
        for row in self.rows[1:]:
            message = row["message"]
            if message["kind"] == "pixel" and message["frame"] == 8:
                message["active"]["codes"] = [0]*4
                message["inside_development_headroom"] = False
                break
        self.write(complete=False)
        result = holds.extract(self.path, self.manifest, self.trial)
        self.assertFalse(result["available"])
        self.assertIn("missing_or_incomplete_recording_receipt", result["faults"])
        self.assertTrue(any("headroom" in value for value in result["faults"]))
        self.rows[0]["evidence_kind"] = "electrical_dummy_recording"
        self.write()
        with self.assertRaisesRegex(ValueError, "physical"):
            holds.extract(self.path, self.manifest, self.trial)

    def test_changed_gain_map_is_detected_even_with_valid_frames(self):
        for row in self.rows[1:]:
            message = row["message"]
            if message["kind"] == "hello" and message["next_frame"] >= 8:
                message["configuration"]["gain_ids"] = [1]*64
            elif message["kind"] == "pixel" and message["frame"] >= 8:
                message["gain"] = 1
        self.write()
        result = holds.extract(self.path, self.manifest, self.trial)
        self.assertIn("missing_or_changed_scan_configuration", result["faults"])
        self.assertFalse(result["available"])

    def test_route_membership_distinguishes_ch4_and_ch5(self):
        pixels = []
        for row in range(4):
            for column in range(16):
                pixels.append({"row": row, "column": column, "gain": 0,
                               "baseline": {"codes": [10000]}, "active": {"codes": [10000-column]}})
        values, sites = holds.frame_signals(pixels, self.config)
        self.assertAlmostEqual(sites[4], sum(values[r*16+c] for r in range(4) for c in (13, 14, 15)))
        self.assertGreater(sites[4], sites[5])


def example_rows():
    """Explicitly synthetic summaries for branch tests; no artifacts are published."""
    rows = []
    for index, site in enumerate(force.SITES):
        for level in force.LEVELS:
            for repeat in range(3):
                signals = [100.]*6
                signals[index] += level*10
                rows.append({"id": f"SYNTHETIC-{site}-{level}-{repeat}", "sites": [site],
                             "available": True, "faults": [], "reference_n": level,
                             "reference_bound_n": .01, "configuration_sha256": "b"*64,
                             "mean_signal_na": signals, "stdev_signal_na": [.01]*6,
                             "recording_sha256": f"SYNTHETIC-{len(rows)}"})
    return rows


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"minimum_holds_per_level": 3, "session_id": "synthetic-train"}

    def test_known_linear_case_and_unclipped_out_of_range(self):
        model = force.fit(self.manifest, example_rows())
        self.assertTrue(model["training_target_met"])
        self.assertAlmostEqual(force.cell_predict(model["cells"]["CH3"], 173.), 7.3)
        self.assertIsNone(force.cell_predict(model["cells"]["CH3"], 400.))
        self.assertLess(force.cell_predict(model["cells"]["CH3"], 99.99), 0.)

    def test_19_point_8_n_does_not_qualify_20_n(self):
        rows = example_rows()
        for row in rows:
            if row["reference_n"] == 20:
                row["reference_n"] = 19.8
        with self.assertRaisesRegex(ValueError, "0..20"):
            force.fit(self.manifest, rows)

    def test_failed_hold_and_changed_configuration_prevent_fit(self):
        rows = example_rows()
        rows[0]["available"] = False
        with self.assertRaisesRegex(ValueError, "Unavailable"):
            force.fit(self.manifest, rows)
        rows[0]["available"] = True
        rows[0]["configuration_sha256"] = "c"*64
        with self.assertRaisesRegex(ValueError, "frozen"):
            force.fit(self.manifest, rows)

    def test_reusing_training_session_is_rejected(self):
        model = force.fit(self.manifest, example_rows())
        identity = {"evidence_kind": "physical", "protocol": holds.PROTOCOL, "geometry_sha256": "a"*64,
                    "specimen": "SYNTHETIC-ONLY",
                    "force_axis": {"frame": "source_finger_native", "unit_vector": [0., 0., 1.]}}
        model.update(identity)
        test = {**self.manifest, **identity}
        with self.assertRaisesRegex(ValueError, "held-out"):
            force.evaluate(model, test, [])

    def test_complete_independent_plan_passes_but_one_missing_hold_fails(self):
        model = force.fit(self.manifest, example_rows())
        identity = {"evidence_kind": "physical", "protocol": holds.PROTOCOL, "geometry_sha256": "a"*64,
                    "specimen": "SYNTHETIC-ONLY",
                    "force_axis": {"frame": "source_finger_native", "unit_vector": [0., 0., 1.]}}
        model.update(identity)
        regions = ("left_nail", "right_nail", "distal_tpu", "middle_tpu", "middle_tpu", "proximal_tpu")
        conditions = [{"condition_id": "single-"+site, "sites": [site], "region": regions[i]}
                      for i, site in enumerate(force.SITES)]
        conditions += [
            {"condition_id": "both-nails", "sites": ["CH0", "CH1"], "region": "nail_edges_notch"},
            {"condition_id": "two-tpu", "sites": ["CH2", "CH3"], "region": "mixture"},
            {"condition_id": "mixed", "sites": ["CH0", "CH2"], "region": "mixture"}]
        test = {**self.manifest, **identity, "session_id": "synthetic-held-out", "required_conditions": conditions}
        rows = []
        for condition in conditions:
            for level in force.LEVELS:
                for repeat in range(3):
                    signals = [100.]*6
                    for site in condition["sites"]:
                        signals[force.SITES.index(site)] += level*10/len(condition["sites"])
                    rows.append({**condition, "id": f"SYNTHETIC-TEST-{len(rows)}",
                                 "recording_sha256": f"SYNTHETIC-NEW-{len(rows)}", "available": True,
                                 "faults": [], "reference_n": level, "reference_bound_n": .01,
                                 "configuration_sha256": "b"*64, "mean_signal_na": signals})
        result = force.evaluate(model, test, copy.deepcopy(rows))
        self.assertTrue(result["passed_static_screen"])
        self.assertAlmostEqual(result["rmse_n"], 0.)
        rows[0]["available"] = False
        rows[0]["faults"] = ["synthetic_missing_frame"]
        result = force.evaluate(model, test, copy.deepcopy(rows))
        self.assertFalse(result["passed_static_screen"])
        self.assertEqual(result["unavailable_holds"], 1)


if __name__ == "__main__":
    unittest.main()
