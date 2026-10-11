"""N1 raw-data and acquisition checks using software fixtures, never bench evidence."""

import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import unittest
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"engineering/software"))
sys.path.insert(0,str(ROOT/"engineering/firmware/nail"))
import nail_protocol
from nail_force import fit_model,predict_model,soft_predict,load_trials,REGIONS
import ads1115
import pressure_scan
from test_c1 import sample as bridge_sample


def sample():
    frame=bridge_sample()
    frame.update({"protocol":"yam-nail/1","hardware_revision":"N1.1","seq":12,
                  "device_us":120000,"interval_us":9830,"pull_down_ohm":[10000]*4,"continuity_ohm":100000})
    starts=[79000,89000,99000,109000,79100,89100,99100,109100]
    frame["pressure"]={"addresses":[72,73],"raw":[0,0,13200,13200,13200,13200,13200,13200],
                       "start_us":starts,"ready_observed_us":[value+9800 for value in starts],
                       "configuration":[0xC3E3,0xD3E3,0xE3E3,0xF3E3]*2,
                       "clock_us":122000,"errors":[]}
    return frame


class ProtocolTests(unittest.TestCase):
    def test_raw_identity_and_individual_times_are_preserved(self):
        frame=sample();before=copy.deepcopy(frame)
        observation=nail_protocol.decode(frame)
        self.assertTrue(observation["valid"])
        self.assertEqual(frame,before)
        self.assertIsNone(observation["force_n"])
        self.assertEqual(observation["nail"]["design_id"],"NAIL")
        self.assertEqual(observation["soft"]["sample_start_us"],[99000,109000,79100,89100])
        for value in observation["soft"]["conductance_us"]:
            self.assertAlmostEqual(value,100)

    def test_other_designs_cannot_enter_nail_recordings(self):
        for protocol in ("yam-c1/1","yam-b2/1","yam-r1/1"):
            with self.subTest(protocol=protocol),self.assertRaises(ValueError):
                nail_protocol.decode({**sample(),"protocol":protocol})

    def test_stale_pressure_does_not_become_fresh_bridge_data(self):
        frame=sample();frame["pressure"]["start_us"][2]=10000
        observation=nail_protocol.decode(frame)
        self.assertFalse(observation["valid"])
        self.assertTrue(observation["nail"]["valid"])
        self.assertIsNone(observation["soft"]["conductance_us"][0])
        self.assertIn("soft_stale_2",observation["flags"])

    def test_configuration_and_timestamp_mismatches_are_rejected(self):
        frame=sample();frame["pressure"]["configuration"][2]^=0x200
        with self.assertRaises(ValueError):
            nail_protocol.decode(frame)
        frame=sample();frame["pressure"]["ready_observed_us"][2]=98000
        with self.assertRaises(ValueError):
            nail_protocol.decode(frame)
        frame=sample();frame["pressure"]["raw"][2]=True
        with self.assertRaises(ValueError):
            nail_protocol.decode(frame)

    def test_missing_ground_and_supply_checks_prevent_a_valid_soft_reading(self):
        for index,value,flag in ((0,80,"soft_ground_check"),(7,12000,"soft_excitation_reference"),
                                 (6,None,"soft_missing_6")):
            frame=sample();frame["pressure"]["raw"][index]=value
            observation=nail_protocol.decode(frame)
            self.assertFalse(observation["valid"])
            self.assertIn(flag,observation["flags"])

    def test_open_short_and_bus_faults_remain_unavailable(self):
        for count in (0,26400):
            frame=sample();frame["pressure"]["raw"][2]=count
            observation=nail_protocol.decode(frame)
            self.assertFalse(observation["valid"])
            self.assertIsNone(observation["soft"]["conductance_us"][0])
        frame=sample();frame["pressure"]["errors"]=["injected_I2C_fault"]
        self.assertFalse(nail_protocol.decode(frame)["valid"])


class Bus:
    def __init__(self):
        self.config=0;self.value=0
    def writeto_mem(self,address,register,value):
        self.config=(value[0]<<8)|value[1]
    def readfrom_mem(self,address,register,length):
        value=self.config if register==1 else self.value
        return bytes((value>>8,value&255))


class ConverterTests(unittest.TestCase):
    def test_documented_single_shot_words_and_signed_limits(self):
        bus=Bus();adc=ads1115.ADS1115(bus,72)
        for channel,expected in enumerate((0xC3E3,0xD3E3,0xE3E3,0xF3E3)):
            adc.start(channel)
            self.assertEqual(bus.config,expected)
            self.assertTrue(adc.ready())
        bus.value=0x8000
        self.assertEqual(adc.result(),-32768)
        bus.value=0x7FFF
        self.assertEqual(adc.result(),32767)
        bus.config^=0x200
        with self.assertRaises(OSError):
            adc.ready()
        with self.assertRaises(ValueError):
            ads1115.configuration(True)


class Clock:
    def __init__(self):
        self.now=65530
    def ticks_us(self):
        value=self.now%65536
        self.now+=10
        return value
    def ticks_diff(self,a,b):
        return (a-b+32768)%65536-32768


class Converter:
    def __init__(self,number):
        self.number=number;self.channel=None;self.observed=None
        self.fail_read=False;self.fail_start=False
    def start(self,channel):
        if self.fail_start:
            raise OSError("software-only write fault")
        self.channel=channel
        self.observed=ads1115.configuration(channel)
    def ready(self):
        return not self.fail_read
    def result(self):
        return 100+self.number*4+self.channel


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.previous=pressure_scan.time
        self.clock=Clock()
        pressure_scan.time=self.clock
        self.adcs=[Converter(0),Converter(1)]
        self.scan=pressure_scan.PressureScan(None,converters=self.adcs)
        self.epoch=0
    def tearDown(self):
        pressure_scan.time=self.previous
    def advance(self):
        tick=self.clock.ticks_us()
        result=self.scan.advance(self.epoch,tick)
        self.clock.now+=9800;self.epoch+=9800
        return result
    def test_four_phases_fill_cache_without_changing_old_frames(self):
        initial=self.advance();saved=copy.deepcopy(initial)
        for _ in range(4):
            latest=self.advance()
        self.assertEqual(initial,saved)
        self.assertEqual(latest["raw"],list(range(100,108)))
        self.assertTrue(all(start<ready<=latest["clock_us"] for start,ready in
                            zip(latest["start_us"],latest["ready_observed_us"])))
        self.assertEqual(len(set(latest["start_us"])),8)
    def test_not_ready_clears_the_failed_input_instead_of_reusing_it(self):
        for _ in range(5):
            self.advance()
        phase=self.scan.phase
        self.adcs[0].fail_read=True
        result=self.advance()
        self.assertIsNone(result["raw"][phase])
        self.assertIsNone(result["start_us"][phase])
        self.assertIsNotNone(result["raw"][4+phase])
        self.assertTrue(result["errors"])
    def test_failed_start_clears_the_old_cached_value(self):
        for _ in range(5):
            self.advance()
        self.adcs[1].fail_start=True
        result=self.advance()
        self.assertIsNone(result["raw"][4+self.scan.phase])
        self.assertTrue(result["errors"])


class ForceMathTests(unittest.TestCase):
    def test_additive_baseline_handles_independent_nail_and_soft_loads(self):
        # Algebraic software fixture only; no physical force measurements.
        rows=[]
        for region in REGIONS:
            for force in (0,.2,.5,1,2,5,10,15,20):
                for repetition,moment in enumerate((-100,0,100)):
                    nail_force=force if region=="nail" else 0
                    nuisance=moment if region=="nail" else 0
                    soft=[10.]*4
                    if region!="nail":
                        soft[REGIONS.index(region)-1]+=5*force
                    rows.append({"available":True,"active_regions":[region],"reference_n":force,
                                 "mean_counts":[100000+300*nail_force+50*nuisance,-100000-200*nail_force+50*nuisance],
                                 "mean_conductance_us":soft,"conductance_stdev_us":[.1]*4,
                                 "mean_excitation_v":3.3,"recording_sha256":f"SOFTWARE_ONLY_{region}_{force}_{repetition}"})
        model=fit_model({},rows,[10000]*4)
        self.assertTrue(model["training_rmse_target_met"])
        row={"mean_counts":[100000+300*3+50*12,-100000-200*3+50*12],
             "mean_conductance_us":[20,15,10,10]}
        estimate,components=predict_model(model,row)
        self.assertAlmostEqual(estimate,6)
        self.assertAlmostEqual(components[0],3)

    def test_signal_guards_expose_zero_error_and_reject_unseen_range(self):
        curve={"knots":[[10,0],[20,2],[30,4]],"signal_guard_us":1}
        self.assertAlmostEqual(soft_predict(curve,9.5),-.1)
        self.assertAlmostEqual(soft_predict(curve,30.5),4.1)
        self.assertIsNone(soft_predict(curve,32))


class HoldReaderTests(unittest.TestCase):
    def fixture(self,base,inconsistent=False,dummy=False):
        # Temporary software-only stream. It never enters a public result set.
        header={"type":"session","schema":"yam-nail-recording/1","protocol":"yam-nail/1",
                "specimen":"SOFTWARE_ONLY","geometry_sha256":"a"*64,"condition":"software_fixture",
                "evidence_kind":"electrical_dummy_recording" if dummy else "physical_recording_unreviewed"}
        items=[header]
        for index in range(300):
            frame=sample();epoch=100000+index*9830
            frame.update({"seq":index,"device_us":epoch,"interval_us":None if index==0 else 9830})
            starts=[]
            for number in range(8):
                phase=number%4
                last=index-1-((index-1-phase)%4)
                starts.append(100000+last*9830+200+(100 if number>=4 else 0))
            frame["pressure"].update({"start_us":starts,"ready_observed_us":[start+8000 for start in starts],
                                      "clock_us":epoch+2000})
            if inconsistent and index==6:
                frame["pressure"]["raw"][2]+=1
            items.append({"frame":frame,"decoded":{"force_n":999999}})
        recording=base/"software.jsonl"
        recording.write_text("".join(json.dumps(item)+"\n" for item in items))
        checksum=hashlib.sha256(recording.read_bytes()).hexdigest()
        receipt={"schema":"yam-nail-recording-receipt/1","sha256":checksum,"capture_complete":True}
        recording.with_suffix(".jsonl.receipt.json").write_text(json.dumps(receipt))
        manifest={"schema":"yam-nail-force-trials/1","evidence_kind":"physical","phase":"train",
                  "specimen":"SOFTWARE_ONLY","geometry_sha256":"a"*64,"reference_id":"SOFTWARE_ONLY",
                  "reference_uncertainty_n":.01,"trials":[{"id":"software","condition_id":"software_fixture",
                    "active_regions":["nail"],"recording":recording.name,"recording_sha256":checksum,
                    "reference_before_n":3,"reference_after_n":3}]}
        path=base/"trials.json";path.write_text(json.dumps(manifest))
        return path

    def test_cache_is_counted_once_and_saved_decoded_force_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            _,rows,_=load_trials(self.fixture(Path(temporary)),"train")
            row=rows[0]
            self.assertTrue(row["available"],row["flags"])
            self.assertEqual(row["nail_frames"],300)
            self.assertTrue(all(73<=count<=75 for count in row["distinct_pressure_samples"]))
            self.assertEqual(row["mean_counts"],[50000,-30000])

    def test_changed_raw_sample_under_same_cache_identity_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            _,rows,_=load_trials(self.fixture(Path(temporary),inconsistent=True),"train")
            self.assertFalse(rows[0]["available"])
            self.assertIn("inconsistent_cached_pressure_sample",rows[0]["flags"])

    def test_dummy_recording_cannot_enter_physical_force_calibration(self):
        with tempfile.TemporaryDirectory() as temporary,self.assertRaisesRegex(ValueError,"dummies"):
            load_trials(self.fixture(Path(temporary),dummy=True),"train")


if __name__=="__main__":
    unittest.main()
