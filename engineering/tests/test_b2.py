"""Identity and failure behavior for the B2 recorder; no physical sensor claims."""

import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"engineering/software"))
import b2_protocol


def sample():
    return {
        "type":"sample","protocol":"yam-b2/1","seq":0,"device_us":0,"scan_us":16000,
        "settings":{"gain_sel":7,"resolution":1,"dig_filt":2,"osr":2,
                    "hallconf":12,"temperature_compensation":False},
        "errors":[],"sensors":[{"channel":i,"status":0x23,"start_us":i*100,
                               "read_us":10000+i*100,"raw_xyz":[100,-50,25],"temperature_raw":47000}
                              for i in range(5)],
        "nail_cells":True,"nail_raw":[2400,2400,13200,13200],
        "nail_offset_us":[11000,12000,13000,14000],
        "pull_down_ohm":[10000,10000],"continuity_ohm":100000,
    }


class B2ProtocolTests(unittest.TestCase):
    def test_identity_is_checked_before_shared_decoder(self):
        frame = sample()
        for wrong in ("yam-b1/1","yam-b2/2",None):
            with self.subTest(protocol=wrong), self.assertRaises(ValueError):
                b2_protocol.decode({**frame,"protocol":wrong})

    def test_keeps_raw_frame_and_never_invents_force(self):
        frame = sample();preserved = copy.deepcopy(frame)
        result = b2_protocol.decode(frame)
        self.assertEqual(frame,preserved)
        self.assertTrue(result["valid"])
        self.assertEqual(result["design_id"],"B2")
        self.assertIsNone(result["force_n"])
        self.assertFalse(result["force_calibrated"])
        self.assertAlmostEqual(result["nail_conductance_us"][0],10)

    def test_missing_head_and_disconnected_nail_remain_faults(self):
        frame = sample()
        frame["sensors"][2] = None
        frame["nail_raw"][0] = 0
        result = b2_protocol.decode(frame)
        self.assertFalse(result["valid"])
        self.assertIsNone(result["magnetic_local_ut"][2])
        self.assertIsNone(result["nail_conductance_us"][0])
        self.assertIn("missing:S2",result["flags"])
        self.assertIn("nail_open:0",result["flags"])

    def test_configuration_and_rail_faults_cannot_enter_as_valid_data(self):
        frame = sample();frame["settings"]["gain_sel"] = 1
        with self.assertRaises(ValueError):
            b2_protocol.decode(frame)
        frame = sample();frame["sensors"][0]["raw_xyz"][1] = 32767
        result = b2_protocol.decode(frame)
        self.assertFalse(result["valid"])
        self.assertIn("near_rail:S0",result["flags"])


if __name__ == "__main__":
    unittest.main()
