import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.model import evaluate, validate


class DesignModelTests(unittest.TestCase):
    def setUp(self):
        self.design = json.loads((ROOT / "examples/design.example.json").read_text())

    def test_example_envelope_and_budget(self):
        result = evaluate(self.design)
        self.assertEqual((result["columns"], result["rows"], result["taxels"]), (2, 8, 16))
        self.assertEqual(result["electrode_nets"], 10)
        self.assertEqual((result["active_width_mm"], result["active_length_mm"]), (4, 16))
        self.assertAlmostEqual(result["opening_loss_mm"], 0.8)
        self.assertAlmostEqual(result["minimum_adapter_stiffness_n_per_mm"], 400)
        self.assertAlmostEqual(result["required_static_force_per_jaw_n"], 12.2583125)
        self.assertFalse(result["hardware_validated"])

    def test_force_independent_of_contact_position_and_end_moment(self):
        for contact in (15, 30, 55, 60):
            for moment in (-90, 0, 130):
                with self.subTest(contact=contact, moment=moment):
                    result = evaluate({**self.design, "contact_distance_mm": contact, "end_moment_nmm": moment})
                    self.assertAlmostEqual(result["recovered_normal_force_n"], 5)
        near = evaluate({**self.design, "contact_distance_mm": 15})
        far = evaluate({**self.design, "contact_distance_mm": 60})
        self.assertNotEqual(near["single_station_fixed_lever_force_n"], far["single_station_fixed_lever_force_n"])

    def test_narrow_face_and_overload_are_explicit(self):
        result = evaluate({**self.design, "face_width_mm": 3, "applied_force_n": 25})
        self.assertEqual((result["taxels"], result["rows"], result["electrode_nets"]), (0, 0, 0))
        self.assertTrue(any("No full" in issue for issue in result["issues"]))
        self.assertTrue(any("Applied force" in issue for issue in result["issues"]))

    def test_invalid_physical_domains_rejected(self):
        cases = [
            {"friction_coefficient": 0}, {"face_width_mm": math.nan},
            {"applied_force_n": math.inf}, {"cell_pitch_mm": True},
            {"contact_distance_mm": 10}, {"pad_length_mm": 80},
            {"nose_thickness_mm": 10}, {"pad_recess_mm": 5}, {"schema_version": True},
        ]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate({**self.design, **change})

    def test_deeper_recess_does_not_create_extra_opening(self):
        result = evaluate({**self.design, "pad_recess_mm": 1})
        self.assertEqual(result["opening_loss_mm"], 0)

    def test_measured_inputs_are_not_hardware_validation(self):
        result = evaluate({**self.design, "geometry_status": "measured_inputs"})
        self.assertFalse(result["hardware_validated"])


if __name__ == "__main__":
    unittest.main()
