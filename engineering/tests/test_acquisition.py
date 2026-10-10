"""Desktop fault/data tests; none of these tests is physical sensor validation."""

import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"engineering/software"))
from signals import decode
from bench import plan
from calibrate import analyze, isotonic_knots, predict

spec=importlib.util.spec_from_file_location("r1_firmware",ROOT/"engineering/firmware/r1/main.py")
firmware=importlib.util.module_from_spec(spec)
spec.loader.exec_module(firmware)


def frame():
    return {"type":"sample","protocol":"yam-r1/1","seq":4,"device_us":80000,"scan_us":7000,
        "raw":[13200]*8,"offset_us":[1300,2900,4500,6100,6200,6300,6400,6500],"errors":[],"pull_down_ohm":[10000]*6,"continuity_ohm":100000}


def artificial_trial_fixture():
    """Invented exact numbers solely for algorithm tests; never exported as measurements."""
    return [{**item,"specimen":"TEST-FIXTURE","evidence_kind":"physical","valid":True,
        "reference_n":item["target_n"],"conductance_us":10+item["target_n"]*100,
        "reference_uncertainty_n":.01,"pull_down_ohm":[10000]*6,"continuity_ohm":100000} for item in plan([0])]


class AcquisitionTests(unittest.TestCase):
    def test_known_resistor_divider(self):
        result=decode(frame())
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["excitation_v"],3.3)
        self.assertAlmostEqual(result["conductance_us"][0],100.)
        self.assertIsNone(result["force_n"])

    def test_short_is_fault_not_large_force(self):
        item=frame();item["raw"][0]=26400
        result=decode(item)
        self.assertFalse(result["valid"])
        self.assertIsNone(result["conductance_us"][0])

    def test_missing_adc_not_zero_filled(self):
        item=frame();item["raw"][4]=None;item["offset_us"][4]=None
        result=decode(item)
        self.assertFalse(result["valid"])
        self.assertIsNone(result["conductance_us"][4])

    def test_invalid_supply_rejected(self):
        item=frame();item["raw"][6]=0
        self.assertFalse(decode(item)["valid"])

    def test_bad_timestamp_rejected(self):
        item=frame();item["offset_us"][0]=1000000
        with self.assertRaises(ValueError):
            decode(item)

    def test_bad_count_rejected(self):
        item=frame();item["raw"][0]=65535
        with self.assertRaises(ValueError):
            decode(item)

    def test_configuration_matches_data_sheet(self):
        self.assertEqual(firmware.config_word(0),0xC3E3)
        self.assertEqual(firmware.config_word(3),0xF3E3)
        with self.assertRaises(ValueError):
            firmware.config_word(4)

    def test_changed_adc_config_rejected(self):
        class Bus:
            def writeto_mem(self,address,register,data):
                self.configuration=data
            def readfrom_mem(self,address,register,length):
                return b"\x85\x83"
        device=firmware.ADS1115(Bus(),0x48)
        device.start(0)
        with self.assertRaises(OSError):
            device.ready()

    def test_signed_conversion(self):
        class Bus:
            def readfrom_mem(self,address,register,length):
                return b"\xff\xfd"
        self.assertEqual(firmware.ADS1115(Bus(),0x48).result(),-3)

    def test_whole_cycles_held_out(self):
        rows=plan([0,1])
        self.assertEqual(len(rows),102)
        self.assertFalse({r["group"] for r in rows if r["split"]=="train"} &
                         {r["group"] for r in rows if r["split"]=="test"})

    def test_calibration_no_extrapolation(self):
        knots=isotonic_knots([(1,0),(2,1),(3,2)])
        self.assertAlmostEqual(predict(knots,2.5),1.5)
        self.assertIsNone(predict(knots,4))

    def test_load_cycle_leakage_rejected(self):
        rows=artificial_trial_fixture()
        rows[-1]["group"]="cycle-1"
        with self.assertRaisesRegex(ValueError,"leakage"):
            analyze(rows)

    def test_incomplete_cycle_does_not_pass(self):
        rows=artificial_trial_fixture()
        rows[-3]["valid"]=False
        self.assertIn("incomplete",analyze(rows)["channels"][0]["status"])

    def test_synthetic_data_cannot_be_published_as_physical_report(self):
        rows=artificial_trial_fixture()
        for row in rows:
            row["evidence_kind"]="synthetic"
        with self.assertRaisesRegex(ValueError,"physical"):
            analyze(rows)

    def test_duplicate_trial_rejected(self):
        rows=artificial_trial_fixture()
        rows.append(copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            analyze(rows)

    def test_good_fixture_is_only_static_fit(self):
        result=analyze(artificial_trial_fixture())
        self.assertEqual(result["channels"][0]["held_out_rmse_n"],0)
        self.assertFalse(result["closed_loop_validated"])

    def test_five_newton_run_is_not_full_range_qualification(self):
        rows=[{**item,"specimen":"TEST-FIXTURE","evidence_kind":"physical","valid":True,
            "reference_n":item["target_n"],"conductance_us":10+item["target_n"]*100,
            "reference_uncertainty_n":.01,"pull_down_ohm":[10000]*6,"continuity_ohm":100000} for item in plan([0],5)]
        self.assertFalse(analyze(rows)["channels"][0]["meets_requested_range"])

    def test_resistor_change_rejects_mixed_calibration(self):
        rows=artificial_trial_fixture();rows[-1]["pull_down_ohm"]=[1000]*6
        with self.assertRaisesRegex(ValueError,"resistor configuration"):
            analyze(rows)

    def test_open_lead_is_not_unloaded_valid_signal(self):
        item=frame();item["raw"][0]=0
        result=decode(item)
        self.assertFalse(result["valid"])
        self.assertIsNone(result["conductance_us"][0])
        self.assertTrue(any("open_lead" in flag for flag in result["flags"]))

    def test_unloaded_continuity_resistor_is_valid(self):
        item=frame()
        # 3.3 V, 100 kΩ cell-end resistor, 10 kΩ pull-down: node is 0.3 V.
        item["raw"][:6]=[2400]*6
        result=decode(item)
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["conductance_us"][0],10.0)

    def test_nominal_label_does_not_replace_actual_twenty_newtons(self):
        rows=artificial_trial_fixture()
        for row in rows:
            if row["target_n"]==20:
                row["reference_n"]=19.5
        result=analyze(rows)["channels"][0]
        self.assertFalse(result["meets_requested_range"])
        self.assertEqual(result["status"],"requested load range incomplete")

    def test_supply_failure_with_negative_adc_offset_is_a_fault(self):
        item=frame();item["raw"][6]=0;item["raw"][0]=-1
        result=decode(item)
        self.assertFalse(result["valid"])
        self.assertTrue(all(value is None for value in result["conductance_us"]))

    def test_non_object_serial_packet_is_rejected(self):
        for value in (None,True,4,[], "sample"):
            with self.assertRaises(ValueError):
                decode(value)

    def test_guard_band_does_not_clamp_upper_force(self):
        knots=isotonic_knots([(1,0),(2,1),(3,2)])
        self.assertAlmostEqual(predict(knots,3.01,.02),2.01)
        self.assertIsNone(predict(knots,3.03,.02))

    def test_small_endpoint_noise_is_evaluated_not_hidden(self):
        rows=artificial_trial_fixture()
        for row in rows:
            row["conductance_stdev_us"]=.1
            if row["split"]=="test" and row["target_n"]==20:
                row["conductance_us"]+=1
        result=analyze(rows)["channels"][0]
        self.assertGreater(result["guard_band_trials"],0)
        self.assertTrue(any(p["predicted_n"]>20 for p in result["predictions"] if p["predicted_n"] is not None))

    def test_nonfinite_input_never_becomes_a_force_estimate(self):
        knots=isotonic_knots([(1,0),(2,1),(3,2)])
        for value in (float("nan"),float("inf"),None,True):
            self.assertIsNone(predict(knots,value,.02))


if __name__=="__main__":
    unittest.main()
