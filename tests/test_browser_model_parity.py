import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.model import evaluate


class BrowserModelParityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Optional Node interpreter is not installed")
    def test_browser_and_cli_agree_on_units_boundaries_and_invalid_inputs(self):
        base = json.loads((ROOT / "examples/design.example.json").read_text())
        cases = [base] + [
            {**base, **change} for change in [
                {"face_width_mm": 3}, {"face_width_mm": 10, "pad_length_mm": 25},
                {"contact_distance_mm": 30, "end_moment_nmm": -80},
                {"pad_stack_mm": 0.25, "pad_recess_mm": 0.5},
                {"friction_coefficient": 0}, {"schema_version": True},
                {"schema_version": 1.0}, {"nose_thickness_mm": 8},
                {"mass_kg": 2, "static_load_factor": 3},
            ]
        ]
        node = str(Path(shutil.which("node")).resolve())
        run = subprocess.run(
            [node, str(ROOT / "tests/evaluate_designs.cjs")],
            input=json.dumps(cases), capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        javascript = json.loads(run.stdout)
        for design, browser in zip(cases, javascript):
            with self.subTest(design=design):
                try:
                    python = evaluate(design)
                except ValueError:
                    self.assertFalse(browser["valid"])
                    continue
                self.assertTrue(browser["valid"])
                for key, expected in python.items():
                    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
                        self.assertAlmostEqual(browser["result"][key], expected, delta=1e-8)
                    else:
                        self.assertEqual(browser["result"][key], expected)
