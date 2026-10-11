"""C1 protocol, fault handling and ADC bit-read checks; no physical performance claims."""

import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import unittest
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"engineering/software"))
import c1_protocol
from c1_force import fit_numeric,predict,load_trials,level_coverage,PILOT_FORCE_LEVELS_N

spec = importlib.util.spec_from_file_location("c1_adc_test",ROOT/"engineering/firmware/c1/ads1232.py")
adc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adc)


def sample():
    return {"type":"sample","protocol":"yam-c1/1","hardware_revision":"C1.1",
            "seq":0,"device_us":0,"interval_us":None,"settings":dict(c1_protocol.SETTINGS),
            "adc_raw":[50000,-30000],"ready_skew_us":20,"read_us":300,
            "power":[{"address":64+i,"shunt_raw":137,"bus_raw":9602,
                      "shunt_ohm":.1,"configuration":0x019F} for i in range(2)],
            "shunts_on":[False,False],"electrical_self_test_passed":True,"errors":[]}


class ProtocolTests(unittest.TestCase):
    def test_preserves_raw_data_and_never_invents_force(self):
        frame = sample();saved = copy.deepcopy(frame)
        observation = c1_protocol.decode(frame)
        self.assertTrue(observation["valid"])
        self.assertEqual(frame,saved)
        self.assertIsNone(observation["force_n"])
        self.assertFalse(observation["force_calibrated"])
        self.assertAlmostEqual(observation["power"][0]["bridge_current_ma"],13.7)

    def test_rejects_other_designs_and_wrong_conversion_settings(self):
        for protocol in ("yam-b1/1","yam-b2/1","yam-c1/2"):
            with self.subTest(protocol=protocol),self.assertRaises(ValueError):
                c1_protocol.decode({**sample(),"protocol":protocol})
        for key,value in (("gain",64),("input_channel",True),("clock_hz",4915200)):
            frame = sample();frame["settings"][key] = value
            with self.subTest(setting=key),self.assertRaises(ValueError):
                c1_protocol.decode(frame)

    def test_open_short_and_missing_power_remain_unavailable(self):
        for shunt in (0,70,220):
            frame = sample();frame["power"][0]["shunt_raw"] = shunt
            observation = c1_protocol.decode(frame)
            self.assertFalse(observation["valid"])
            self.assertIn("bridge_current_0",observation["flags"])
        frame = sample();frame["power"][1] = None
        self.assertIn("missing_power_1",c1_protocol.decode(frame)["flags"])

    def test_shunt_diagnostics_and_missing_self_test_are_not_normal_samples(self):
        for state in ([True,False],[0,0],None):
            frame = sample();frame["shunts_on"] = state
            self.assertIn("shunt_active_or_unknown",c1_protocol.decode(frame)["flags"])
        frame = sample();frame["electrical_self_test_passed"] = False
        self.assertFalse(c1_protocol.decode(frame)["valid"])

    def test_rails_skew_and_missing_samples_are_flagged(self):
        frame = sample();frame["adc_raw"] = [-8388608,None]
        observation = c1_protocol.decode(frame)
        self.assertFalse(observation["valid"])
        self.assertEqual(observation["bridge_ratio_v_per_v"],[None,None])
        frame = sample();frame["ready_skew_us"] = 4000
        self.assertIn("adc_pair_skew",c1_protocol.decode(frame)["flags"])
        frame = sample();frame.update({"seq":2,"device_us":30000,"interval_us":30000})
        self.assertIn("sample_interval",c1_protocol.decode(frame)["flags"])

    def test_monitor_identity_is_checked(self):
        frame = sample();frame["power"][0]["address"] = 65
        with self.assertRaises(ValueError):
            c1_protocol.decode(frame)


class Clock:
    def __init__(self):
        self.now = 65530
    def ticks_us(self):
        value = self.now%65536
        self.now += 5
        return value
    def ticks_add(self,value,delta):
        return (value+delta)%65536
    def ticks_diff(self,a,b):
        return (a-b+32768)%65536-32768
    def sleep_us(self,value):
        self.now += value


class SerialClock:
    def __init__(self):
        self.level = 0;self.pulses = 0
    def value(self,value=None):
        if value is None:
            return self.level
        if value and not self.level:
            self.pulses += 1
        self.level = value


class DataPin:
    def __init__(self,clock,word,stuck=False):
        self.clock = clock;self.word = word;self.stuck = stuck
    def value(self):
        if self.stuck:
            return 0
        if self.clock.pulses==0:
            return 0
        if self.clock.pulses>=25:
            return 1
        return (self.word>>(24-self.clock.pulses))&1


class ADCTests(unittest.TestCase):
    def test_signed_word_boundaries(self):
        self.assertEqual(adc.signed24(0xFFFFFF),-1)
        self.assertEqual(adc.signed24(0x800000),-8388608)
        self.assertEqual(adc.signed24(0x7FFFFF),8388607)
        for invalid in (True,-1,1<<24,1.5):
            with self.subTest(value=invalid),self.assertRaises(ValueError):
                adc.signed24(invalid)

    def test_shared_read_has_25_pulses_and_handles_tick_wrap(self):
        previous = adc.time;clock = SerialClock();adc.time = Clock()
        try:
            pair = adc.Pair(clock,DataPin(clock,0xFFFFFF),DataPin(clock,0x7FFFFF),SerialClock())
            result = pair.read(timeout_us=1000)
            self.assertEqual(result["raw"],[-1,8388607])
            self.assertEqual(clock.pulses,25)
            self.assertEqual(result["ready_skew_us"],5)
            self.assertGreater(result["read_us"],100)
            self.assertLess(result["read_us"],500)
        finally:
            adc.time = previous

    def test_stuck_data_line_cannot_be_accepted_as_zero(self):
        previous = adc.time;clock = SerialClock();adc.time = Clock()
        try:
            pair = adc.Pair(clock,DataPin(clock,0,stuck=True),DataPin(clock,1),SerialClock())
            with self.assertRaises(OSError):
                pair.read(timeout_us=1000)
        finally:
            adc.time = previous


class CalibrationMathTests(unittest.TestCase):
    def test_independent_force_and_moment_data_fit_without_feature_leakage(self):
        # Algebraic software fixture only: no sensor specimens or physical results.
        features=[];forces=[]
        for force in (0,1,5,20):
            for moment in (-100,0,100):
                features.append([100000+400*force+50*moment,-100000-300*force+50*moment])
                forces.append(force)
        model = fit_numeric(features,forces)
        self.assertEqual(len(model["weights_n_per_count"]),2)
        self.assertAlmostEqual(predict(model,[100000+400*7+50*33,-100000-300*7+50*33]),7,6)

    def test_single_lever_calibration_is_rejected(self):
        with self.assertRaises(ValueError):
            fit_numeric([[v,2*v] for v in range(10)],list(range(10)))

    def test_prediction_requires_both_finite_features(self):
        model = {"offset_n":0,"weights_n_per_count":[1,-1]}
        for values in ([1],[1,float("nan")],[1,None]):
            with self.subTest(values=values),self.assertRaises(ValueError):
                predict(model,values)

    def test_full_range_and_independent_holds_are_required(self):
        rows = [{"available":True,"reference_n":level} for level in PILOT_FORCE_LEVELS_N for _ in range(3)]
        self.assertTrue(level_coverage(rows,{})[1])
        rows[-1]["available"] = False
        self.assertFalse(level_coverage(rows,{})[1])
        for manifest in ({"minimum_holds_per_level":1},{"required_force_levels_n":[0,20]}):
            with self.subTest(manifest=manifest),self.assertRaises(ValueError):
                level_coverage(rows,manifest)

    def test_dummy_electronics_cannot_become_physical_calibration(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            recording = base/"dummy.jsonl"
            recording.write_text(json.dumps({"type":"session","schema":"yam-c1-recording/1",
                "evidence_kind":"electrical_dummy_recording","specimen":"SOFTWARE_ONLY",
                "geometry_sha256":"b"*64,"condition":"dummy"})+"\n")
            manifest = {"schema":"yam-c1-force-trials/1","evidence_kind":"physical","phase":"train",
                        "specimen":"SOFTWARE_ONLY","geometry_sha256":"b"*64,
                        "reference_id":"SOFTWARE_ONLY","reference_uncertainty_n":.01,
                        "trials":[{"id":"t1","condition_id":"dummy","recording":"dummy.jsonl",
                                   "recording_sha256":hashlib.sha256(recording.read_bytes()).hexdigest(),
                                   "reference_before_n":0,"reference_after_n":0}]}
            path = base/"trials.json";path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,"raw recording identity"):
                load_trials(path,"train")
            manifest["trials"].append({**manifest["trials"][0],"id":"t2"})
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,"duplicates"):
                load_trials(path,"train")


if __name__=="__main__":
    unittest.main()
