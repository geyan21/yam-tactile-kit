"""K1 physical-hold integrity and monotone force math; all fixtures are software tests."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engineering/software"))
import capacitive_force as force
from engineering.tests.test_capacitive import packets


class ForceMathTests(unittest.TestCase):
    def test_force_axis_is_explicit_and_frozen(self):
        axis = {"frame": "source_finger_native", "unit_vector": [0, 0, 1]}
        self.assertEqual(force.load_axis(axis), axis)
        with self.assertRaises(ValueError):
            force.load_axis(None)
        with self.assertRaises(ValueError):
            force.load_axis({"frame": "source_finger_native", "unit_vector": [0, 0, 2]})
        with self.assertRaisesRegex(ValueError, "Force axis changed"):
            force.same_force_axis({"force_axis": axis}, {"force_axis": {"frame": "source_finger_native", "unit_vector": [0, 1, 0]}})

    def test_monotone_pooling_and_unclipped_guard(self):
        curve = force.knots([[4., 0], [4.1, 2], [4.2, 1], [5., 20]])
        self.assertEqual([p[1] for p in curve], [0, 1.5, 1.5, 20])
        model = {"knots_pf_n": [[4., 0], [4.1, 1], [6., 20]], "signal_guard_pf": .02}
        self.assertLess(force.cell_predict(model, 3.99), 0)
        self.assertGreater(force.cell_predict(model, 6.01), 20)
        self.assertIsNone(force.cell_predict(model, 6.03))
        with self.assertRaises(ValueError):
            force.knots([[4., 0], [4., 10], [4., 20]])

    def test_mixed_sum_and_unavailable_cell(self):
        cells = {site: {"knots_pf_n": [[5+i, 0], [5.2+i, 2], [7+i, 20]], "signal_guard_pf": .01}
                 for i, site in enumerate(force.SITES)}
        baseline = [5+i for i in range(6)]
        values = baseline[:]; values[0] += .5; values[3] += 1
        result = force.predict({"cells": cells}, values)
        self.assertAlmostEqual(result["total_force_n"], 15)
        values[5] += 3
        self.assertIsNone(force.predict({"cells": cells}, values)["total_force_n"])

    def test_actual_twenty_newtons_and_independent_holds_required(self):
        rows = [{"reference_n": n, "available": True} for n in force.LEVELS]
        self.assertFalse(force.coverage(rows, 3)[1])
        rows = [copy.deepcopy(r) for r in rows for _ in range(3)]
        self.assertTrue(force.coverage(rows, 3)[1])
        for row in rows:
            if row["reference_n"] == 20:
                row["reference_n"] = 19.9
        self.assertFalse(force.coverage(rows, 3)[1])


class HoldTests(unittest.TestCase):
    def fixture(self, base, evidence="physical_recording_unreviewed", fault=False):
        hello, sample = packets()
        raw = int(-1.5*524288)
        sample["banks"][0]["fdc"][0].update(raw=raw, msb=(raw & 0xFFFFFF) >> 8, lsb=(raw & 255) << 8)
        recording = base / "software_fixture.jsonl"
        with recording.open("w") as stream:
            stream.write(json.dumps({"type": "session", "schema": "yam-k1-recording/2", "protocol": force.PROTOCOL,
                                     "specimen": "SOFTWARE_ONLY", "session_id": "TEST_ONLY", "condition": "one_hold",
                                     "geometry_sha256": "a"*64, "evidence_kind": evidence})+"\n")
            stream.write(json.dumps({"host_elapsed_s": 0., "raw_line": json.dumps(hello)})+"\n")
            for i in range(651):
                packet = copy.deepcopy(sample)
                packet["seq"], packet["device_us"] = i, i*20000
                if fault and i == 200:
                    packet["banks"][0]["fdc"][0]["observed_fdc_config"] &= ~8
                stream.write(json.dumps({"host_elapsed_s": i*.02, "raw_line": json.dumps(packet),
                                         "decoded": {"complete_finger_available": True, "force_n": 12345}})+"\n")
            stream.write(json.dumps({"type": "record_end", "complete_duration": True, "duration_s": 13.})+"\n")
        manifest = {"schema": "yam-k1-force-trials/1", "evidence_kind": "physical", "phase": "train",
                    "specimen": "SOFTWARE_ONLY", "session_id": "TEST_ONLY", "geometry_sha256": "a"*64,
                    "reference_id": "TEST_REFERENCE", "reference_uncertainty_n": .01, "minimum_holds_per_level": 3,
                    "force_axis": {"frame": "source_finger_native", "unit_vector": [0, 0, 1]},
                    "trials": [{"id": "software", "condition_id": "one_hold", "region": "left_nail", "sites": ["CH0"],
                                "recording": recording.name, "recording_sha256": hashlib.sha256(recording.read_bytes()).hexdigest(),
                                "window_host_s": [2, 12], "reference_before_n": 5, "reference_after_n": 5}]}
        path = base / "trials.json"; path.write_text(json.dumps(manifest))
        return path

    def test_raw_is_redecoded_and_cached_force_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, rows = force.load_trials(self.fixture(Path(temporary)), "train")
        self.assertTrue(rows[0]["available"], rows[0]["faults"])
        self.assertEqual(rows[0]["samples"], 501)
        self.assertEqual(rows[0]["mean_pf"][0], 6.5)

    def test_electronics_cannot_enter_tactile_force_calibration(self):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
            force.load_trials(self.fixture(Path(temporary), evidence="electronics_test"), "train")
        with self.assertRaises(ValueError):
            force.load_trials(ROOT / "engineering/templates/capacitive_force_trials.json", "train")

    def test_converter_fault_invalidates_the_hold(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, rows = force.load_trials(self.fixture(Path(temporary), fault=True), "train")
        self.assertFalse(rows[0]["available"])
        self.assertIn("converter_configuration_or_data", rows[0]["faults"])


if __name__ == "__main__":
    unittest.main()
