"""Synthetic stationary-record checks; no measured P1 performance is asserted."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"engineering/software"))
from capacitive_force import digest
from pneumatic_force import solve, linear_fit, predict, evaluate
from pneumatic_holds import extract
from pneumatic_protocol import PROTOCOL
from engineering.tests.test_pneumatic import hello, frame


class P1StationaryRecords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/"test-only.jsonl"
        self.manifest = {"specimen": "TEST-ONLY", "session_id": "TEST-ONLY-session", "geometry_sha256": "a"*64}
        self.trial = {"window_host_s": [2, 12], "condition_id": "TEST-ONLY-condition"}

    def write_recording(self, bad=None, kind="physical_recording_unreviewed"):
        header = {"type": "session", "schema": "yam-p1-recording/1", "protocol": PROTOCOL, **self.manifest,
                  "condition": self.trial["condition_id"], "evidence_kind": kind}
        rows = [header]
        def raw_entry(when, packet):
            # The claimed validation deliberately is not the authority.
            raw = (json.dumps(packet)+"\n").encode()
            return {"host_elapsed_s": when, "raw_hex": raw.hex(),
                    "validation": {"complete_finger_available": True}}
        rows.append(raw_entry(0, hello()))
        for index in range(501):
            packet = frame(index)
            if index == 200 and bad == "missing":
                packet["pressure_raw"][0] = None
                packet["offset_us"][0] = None
            when = 2+index*.02
            if bad == "gap" and index == 200:
                continue
            rows.append(raw_entry(when, packet))
        self.path.write_text("".join(json.dumps(row)+"\n" for row in rows))
        receipt = {"schema": "yam-p1-recording-receipt/1", **self.manifest,
                   "condition": self.trial["condition_id"], "device_id": hello()["device_id"],
                   "sha256": digest(self.path), "capture_complete": True, "requested_duration_s": 13}
        self.path.with_suffix(".jsonl.receipt.json").write_text(json.dumps(receipt))

    def test_complete_raw_window_is_rechecked(self):
        self.write_recording()
        result = extract(self.path, self.manifest, self.trial)
        self.assertTrue(result["available"], result["faults"])
        self.assertEqual(result["frames"], 501)
        self.assertEqual(len(result["mean_signal"]), 6)

    def test_forged_saved_validation_cannot_hide_missing_sensor(self):
        self.write_recording(bad="missing")
        result = extract(self.path, self.manifest, self.trial)
        self.assertFalse(result["available"])
        self.assertIn("missing_measurement", result["faults"])

    def test_skipped_frame_is_retained_as_a_failed_hold(self):
        self.write_recording(bad="gap")
        result = extract(self.path, self.manifest, self.trial)
        self.assertFalse(result["available"])
        self.assertIn("acquisition_gap", result["faults"])

    def test_receipt_hash_and_electronics_kind(self):
        self.write_recording()
        with self.path.open("a") as stream:
            stream.write(json.dumps({"host_elapsed_s": 12.5, "recording_error": "TEST"})+"\n")
        self.assertIn("missing_or_incomplete_capture_receipt", extract(self.path, self.manifest, self.trial)["faults"])
        self.write_recording(kind="electronics_test")
        with self.assertRaises(ValueError):
            extract(self.path, self.manifest, self.trial)


class P1LinearBaseline(unittest.TestCase):
    def test_small_solver_known_solution(self):
        self.assertAlmostEqual(solve([[3, 1], [1, 2]], [9, 8])[0], 2)
        self.assertAlmostEqual(solve([[3, 1], [1, 2]], [9, 8])[1], 3)

    def test_signed_pressure_can_contribute_to_positive_force(self):
        rows = [{"mean_signal": [nail, 0, -25*p, 0, 0, 0], "stdev_signal": [.01]*6,
                 "reference_n": .2*nail+1.25*p} for nail in range(5) for p in range(5)]
        model = linear_fit(rows)
        self.assertEqual(model["active_features"], [0, 2])
        self.assertLess(model["coefficients"][1], 0)
        self.assertLess(abs(predict(model, [4, 0, -100, 0, 0, 0])-5.8), .05)
        self.assertIsNone(predict(model, [4, 0, -200, 0, 0, 0]))

    def test_no_signal_response_is_not_a_valid_force_model(self):
        rows = [{"mean_signal": [0]*6, "stdev_signal": [0]*6, "reference_n": force} for force in (0, 1, 2, 5, 10, 20)]
        with self.assertRaises(ValueError):
            linear_fit(rows)

    def test_negative_estimate_is_never_silently_clipped(self):
        model = {"active_features": [0], "center": [0]*6, "scale": [1]*6, "coefficients": [1],
                 "intercept_n": 0, "signal_bounds": [[-10, 10]]*6}
        self.assertEqual(predict(model, [-2, 0, 0, 0, 0, 0]), -2)

    def test_evaluation_rejects_reuse_and_changed_context(self):
        common = {"specimen": "TEST", "geometry_sha256": "a"*64,
                  "force_axis": {"frame": "source_finger_native", "unit_vector": [0, 0, 1]},
                  "calibration_context": {"hose_set_id": "TEST"}}
        saved = {"schema": "yam-p1-stationary-model/1", "evidence_kind": "physical", **common,
                 "training_session_id": "train", "training_recording_sha256": ["b"*64]}
        manifest = {**common, "session_id": "train"}
        with self.assertRaisesRegex(ValueError, "separate physical session"):
            evaluate(saved, manifest, [])
        manifest["session_id"] = "test"
        with self.assertRaisesRegex(ValueError, "cannot be reused"):
            evaluate(saved, manifest, [{"recording_sha256": "b"*64}])
        manifest["calibration_context"] = {"hose_set_id": "different"}
        with self.assertRaisesRegex(ValueError, "context changed"):
            evaluate(saved, manifest, [])


if __name__ == "__main__":
    unittest.main()
