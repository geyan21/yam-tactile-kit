"""Synthetic O1 force/contact math controls; no physical result is inferred."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"engineering/software"))
from optical_force import linear_fit, predict, fit_contact, contact_score, evaluate


class OpticalForceControls(unittest.TestCase):
    def test_signed_motion_contributes_and_envelope_is_enforced(self):
        rows = [{"mean_signal": [a, 0, -b], "stdev_signal": [.01]*3, "reference_n": 2*a+3*b}
                for a in range(4) for b in range(4)]
        model = linear_fit(rows)
        self.assertLess(model["coefficients"][1], 0)
        self.assertAlmostEqual(predict(model, [1.5, 0, -1.5]), 7.5)
        self.assertIsNone(predict(model, [1.5, 0, -20]))

    def test_constant_features_do_not_make_a_force_model(self):
        rows = [{"mean_signal": [0]*3, "stdev_signal": [0]*3, "reference_n": value} for value in (0, 1, 2, 5, 20)]
        with self.assertRaises(ValueError):
            linear_fit(rows)

    def test_negative_prediction_is_visible(self):
        model = {"center": [0, 0, 0], "scale": [1, 1, 1], "active_features": [0],
                 "coefficients": [1], "intercept_n": -.2, "signal_bounds": [[0, 2], [0, 0], [0, 0]]}
        self.assertEqual(predict(model, [0, 0, 0]), -.2)

    def test_training_overlap_produces_no_contact_detector(self):
        def hold(truth, samples):
            return {"contact_expected": truth, "mean_signal": [sum(s[0] for s in samples)/len(samples), 0, 0],
                    "stdev_signal": [.1]*3, "sample_features": samples}
        rows = [hold(False, [[0, 0, 0], [1, 0, 0]]), hold(True, [[.5, 0, 0], [2, 0, 0]])]
        model = fit_contact(rows)
        self.assertFalse(model["available"])
        self.assertIsNone(model["threshold"])
        rows[1] = hold(True, [[3, 0, 0], [4, 0, 0]])
        model = fit_contact(rows)
        self.assertTrue(model["available"])
        self.assertLess(contact_score(model, [0, 0, 0]), model["threshold"])
        self.assertGreater(contact_score(model, [3, 0, 0]), model["threshold"])

    def test_evaluation_cannot_reuse_training_session(self):
        manifest = {"specimen": "TEST", "geometry_sha256": "a"*64, "device_id": "TEST",
                    "camera_config_sha256": "b"*64, "marker_reference_sha256": "c"*64, "session_id": "same",
                    "force_axis": {"frame": "source_finger_native", "unit_vector": [0, 0, 1]},
                    "calibration_context": {}}
        saved = {"schema": "yam-o1-stationary-model/1", "evidence_kind": "physical",
                 **manifest, "training_session_id": "same"}
        with self.assertRaisesRegex(ValueError, "separate physical session"):
            evaluate(saved, manifest, [])


if __name__ == "__main__":
    unittest.main()
