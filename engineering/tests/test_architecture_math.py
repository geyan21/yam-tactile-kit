"""Check analytical identities and accounting. No synthetic test is hardware evidence."""

import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"engineering/software"))
from architecture_math import beam_response,force_with_station_gain_error,batch_cost

CONFIG=json.loads((ROOT/"engineering/designs/architecture_study.json").read_text())["c1"]


class ArchitectureMathTests(unittest.TestCase):
    def test_force_reconstruction_independent_of_distal_contact_arm(self):
        for force in (.2,1,5,20):
            for arm in (0,10,50,110):
                self.assertAlmostEqual(beam_response(CONFIG,force,arm)["recovered_force_ideal_n"],force,places=10)

    def test_pure_end_moment_does_not_become_force(self):
        self.assertAlmostEqual(beam_response(CONFIG,0,0,2500)["recovered_force_ideal_n"],0,places=10)

    def test_multiple_distal_contacts_sum_force(self):
        forces=[3,7,2];arms=[10,80,110]
        total=beam_response(CONFIG,sum(forces),0,sum(f*a for f,a in zip(forces,arms)))
        self.assertAlmostEqual(total["recovered_force_ideal_n"],12,places=10)

    def test_tip_displacement_matches_independent_moment_integration(self):
        result=beam_response(CONFIG,20,110)
        length=CONFIG["active_length_mm"]
        ei=CONFIG["youngs_modulus_mpa_assumed"]*CONFIG["beam_width_mm"]*CONFIG["beam_thickness_mm"]**3/12
        n=10000;dx=length/n
        theta=sum(20*(length-(i+.5)*dx+110)*dx/ei for i in range(n))
        displacement=sum((length-(i+.5)*dx)*20*(length-(i+.5)*dx+110)*dx/ei for i in range(n))+110*theta
        self.assertAlmostEqual(displacement,result["added_contact_displacement_mm"],places=8)

    def test_small_residual_gain_error_remains_visible(self):
        response=beam_response(CONFIG,20,110)
        self.assertGreater(force_with_station_gain_error(response,.001)-20,.2)

    def test_yield_and_calibration_labor_are_not_free(self):
        result=batch_cost(10,40,.8,20,30,100,10)
        self.assertEqual(result["attempted_units"],13)
        self.assertEqual(result["modeled_total"],815)
        self.assertEqual(result["modeled_per_good_unit"],81.5)

    def test_invalid_cost_assumptions_rejected(self):
        for bad in (0,-1,1.1,float("nan"),True):
            with self.assertRaises(ValueError):batch_cost(10,40,bad,20,30)

    def test_blank_quote_template_cannot_publish_zero_costs(self):
        with tempfile.TemporaryDirectory(prefix="architecture-quote-check-") as directory:
            output=Path(directory)/"costs.json"
            result=subprocess.run([sys.executable,str(ROOT/"engineering/software/architecture_cost.py"),
                "--input",str(ROOT/"engineering/research/quote_template.json"),"--output",str(output)],
                capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,2)
            self.assertIn("Supply actual quote/timing assumptions",result.stderr)
            self.assertFalse(output.exists())


if __name__=="__main__":unittest.main()
