import copy
import csv
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.calibration import FIELDS, fit_and_evaluate, read_samples


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.samples = read_samples(ROOT / "examples/calibration.synthetic.csv")

    def test_known_synthetic_relationship_and_new_contact_position(self):
        result = fit_and_evaluate(self.samples)
        self.assertEqual(result["dataset_kind"], "synthetic")
        self.assertEqual(result["training_positions_mm"], [30, 45, 60])
        self.assertEqual(result["held_out_positions_mm"], [55])
        self.assertEqual((result["training_samples"], result["held_out_samples"]), (63, 21))
        self.assertAlmostEqual(result["model"]["raw_1_coefficient"], 1 / (1.7 * 12), delta=0.0001)
        self.assertAlmostEqual(result["model"]["raw_2_coefficient"], -1 / (2.4 * 12), delta=0.0001)
        self.assertLess(result["held_out_rmse_n"], 0.01)
        self.assertFalse(result["hardware_qualified"])

    def test_test_labels_do_not_leak_into_fitting(self):
        changed = copy.deepcopy(self.samples)
        for row in changed:
            if row["partition"] == "test":
                row["reference_force_n"] += 3
        original = fit_and_evaluate(self.samples)
        result = fit_and_evaluate(changed)
        self.assertEqual(result["model"], original["model"])
        self.assertGreater(result["held_out_rmse_n"], 2.9)

    def test_single_position_calibration_is_rejected(self):
        for row in self.samples:
            row["contact_z_mm"] = 40
        with self.assertRaisesRegex(ValueError, "positions"):
            fit_and_evaluate(self.samples)

    def test_rank_deficient_channels_are_rejected(self):
        for row in self.samples:
            row["raw_2"] = row["raw_1"] * 2
        with self.assertRaisesRegex(ValueError, "rank-deficient"):
            fit_and_evaluate(self.samples)

    def test_csv_rejects_nonfinite_and_mixed_sensor_identity(self):
        for changed_key, changed_value in (("raw_1", "nan"), ("sensor_id", "another-sensor"), ("sample_id", self.samples[1]["sample_id"])):
            with self.subTest(key=changed_key), tempfile.TemporaryDirectory() as directory:
                rows = copy.deepcopy(self.samples)
                rows[0][changed_key] = changed_value
                path = Path(directory) / "invalid.csv"
                with path.open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
                with self.assertRaises(ValueError):
                    read_samples(path)


if __name__ == "__main__":
    unittest.main()
