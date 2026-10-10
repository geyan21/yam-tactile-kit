"""L1 protocol, register, and analysis tests. Fixtures are invented software inputs."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"engineering/firmware/l1"))
sys.path.insert(0,str(ROOT/"engineering/software"))
sys.path.insert(0,str(ROOT/"engineering/scripts"))
from nau7802 import NAU7802, signed24
from ina219 import INA219, CONFIGURATION
from l1_protocol import decode
from l1_calibrate import analyze, force_from_counts
from l1_validate_finger import analyze_finger
from l1_monitor import checked_model, estimate
from make_l1_plans import make_plan, make_finger_plan


class Clock:
    def __init__(self):self.now=0
    def ticks_ms(self):return self.now
    def ticks_diff(self,a,b):return a-b
    def sleep_ms(self,amount):self.now+=amount


class Bus:
    def __init__(self,raw=12345):
        self.registers={0x1F:0x0F}
        self.raw=raw;self.writes=[];self.stuck_calibration=False;self.cal_error=False
        self.monitor_config=CONFIGURATION;self.shunt=42;self.voltage_word=(1050<<3)|2
    def writeto_mem(self,address,register,data):
        self.writes.append((address,register,bytes(data)))
        if address==0x40:
            self.monitor_config=(data[0]<<8)|data[1]
            return
        value=data[0]
        if register==0 and value&1:
            self.registers={0x1F:self.registers[0x1F]}
        if register==2 and value&4 and not self.stuck_calibration:
            value=(value&~4)|(8 if self.cal_error else 0)
        self.registers[register]=value
    def readfrom_mem(self,address,register,size):
        if address==0x40:
            value={0:self.monitor_config,1:self.shunt&0xFFFF,2:self.voltage_word}[register]
            return bytes((value>>8,value&255))
        if register==0x12:
            extra=639132 if self.registers.get(0x11,0)&4 else 0
            value=(self.raw+extra)&0xFFFFFF
            return bytes((value>>16,(value>>8)&255,value&255))
        value=self.registers.get(register,0)
        if register==0 and value&6==6:value|=0x28
        return bytes((value,))


def sample():
    return {"type":"sample","protocol":"yam-l1/1","seq":4,"device_us":50000,
        "raw_counts":12345,"bridge_v":4.2,"bridge_current_ma":4.2,"gain":128,"rate_sps":80,
        "errors":[],"startup_check_passed":True,"startup_equivalent_ohm":500,
        "transport_and_supply_valid":True}


def analysis_fixture(moment_sensitivity=0):
    config=json.loads((ROOT/"engineering/designs/l1.json").read_text())
    plan=make_plan(config)
    metadata={"schema":"yam-l1-session/1","evidence_kind":"physical","specimen":"TEST-FIXTURE",
        "pose_id":"TEST-POSE","fixture":"combined_load_plate","plan":plan}
    rows=[]
    for trial in plan["trials"]:
        force=trial["target_n"]
        error_n=moment_sensitivity*force*trial["u_mm"]/1000
        rows.append({**trial,"specimen":"TEST-FIXTURE","pose_id":"TEST-POSE",
            "evidence_kind":"physical","valid":True,"reference_n":force,"reference_uncertainty_n":.01,
            "raw_counts_mean":12345+1000*(force+error_n),"gain":128,"rate_sps":80})
    return metadata,rows


def finger_fixture(scale=1,return_bias=0):
    base=analyze(*analysis_fixture())
    plan=make_finger_plan([
        {"id":"test_nail","u_mm":65,"v_mm":-25,"native_xyz_mm":[-7.65,-137.5,-4]},
        {"id":"test_tpu","u_mm":10,"v_mm":-25,"native_xyz_mm":[-7.65,-82.5,-4]},
    ])
    metadata={"schema":"yam-l1-session/1","evidence_kind":"physical","specimen":"TEST-FIXTURE",
              "pose_id":"FINGER-POSE","fixture":"integrated_enpire_l1","plan":plan}
    rows=[{**trial,"specimen":"TEST-FIXTURE","pose_id":"FINGER-POSE","evidence_kind":"physical",
           "valid":True,"reference_n":trial["target_n"],"reference_uncertainty_n":.01,
           "raw_counts_mean":25000+1000*(trial["target_n"]*scale+(return_bias if trial["phase"]=="unloading" else 0)),
           "gain":128,"rate_sps":80} for trial in plan["trials"]]
    return base,metadata,rows


class L1Tests(unittest.TestCase):
    def test_sign_extension(self):
        self.assertEqual(signed24(b"\xff\xff\xff"),-1)
        self.assertEqual(signed24(b"\x80\x00\x00"),-(1<<23))
        with self.assertRaises(OSError):signed24(b"\0\0")

    def test_initialization_uses_4v2_and_internal_calibration(self):
        bus=Bus();driver=NAU7802(bus,Clock());driver.initialize()
        self.assertEqual(bus.registers[1],0x0F)
        self.assertEqual(bus.registers[2],0x30)
        self.assertTrue(all(data[0]&3==0 for address,register,data in bus.writes if address==0x2A and register==2))
        self.assertEqual(driver.conversion(),12345)

    def test_unknown_device_rejected(self):
        bus=Bus();bus.registers[0x1F]=0
        with self.assertRaises(OSError):NAU7802(bus,Clock()).initialize()

    def test_afe_error_stops_initialization(self):
        bus=Bus();bus.cal_error=True
        with self.assertRaises(OSError):NAU7802(bus,Clock()).initialize()

    def test_afe_wait_has_deadline(self):
        bus=Bus();bus.stuck_calibration=True;clock=Clock()
        with self.assertRaises(OSError):NAU7802(bus,clock).initialize()
        self.assertLess(clock.now,2000)

    def test_startup_check_does_not_tare_load(self):
        bus=Bus(raw=300000);driver=NAU7802(bus,Clock());driver.initialize()
        result=driver.startup_burnout_check(4.2)
        self.assertTrue(result["passes_provisional_band"])
        self.assertAlmostEqual(result["equivalent_resistance_ohm"],500,places=2)
        self.assertEqual(driver.conversion(),300000)
        self.assertFalse(bus.registers[0x11]&4)

    def test_diagnostic_mode_cannot_leak_into_samples(self):
        bus=Bus();driver=NAU7802(bus,Clock());driver.initialize();bus.registers[0x11]=4
        with self.assertRaises(OSError):driver.conversion()

    def test_adc_rail_rejected(self):
        bus=Bus();driver=NAU7802(bus,Clock());driver.initialize();bus.raw=0x7FFFFF
        with self.assertRaises(OSError):driver.conversion()

    def test_excitation_monitor_units_and_open_lead(self):
        bus=Bus();monitor=INA219(bus);monitor.initialize()
        self.assertAlmostEqual(monitor.sample()["bridge_current_ma"],4.2)
        bus.shunt=0
        self.assertIn("bridge_excitation_current",monitor.sample()["errors"])

    def test_packet_is_raw_not_force(self):
        result=decode(sample());self.assertTrue(result["valid"]);self.assertIsNone(result["force_n"])

    def test_missing_startup_check_rejected(self):
        value=sample();value["startup_check_passed"]=False
        self.assertFalse(decode(value)["valid"])

    def test_missing_excitation_never_looks_unloaded(self):
        value=sample();value["bridge_current_ma"]=0
        self.assertFalse(decode(value)["valid"])

    def test_nonfinite_data_rejected(self):
        value=sample();value["raw_counts"]=float("nan")
        with self.assertRaises(ValueError):decode(value)
        self.assertIsNone(force_from_counts({"zero_counts":0,"counts_per_n":1},float("nan")))

    def test_perfect_fixture_is_only_bench_qualification(self):
        result=analyze(*analysis_fixture())
        self.assertTrue(result["bench_force_criterion_met"])
        self.assertFalse(result["robot_gripper_qualified"])
        self.assertFalse(result["moment_position_correction_applied"])

    def test_position_sensitive_cell_fails(self):
        result=analyze(*analysis_fixture(moment_sensitivity=.8))
        self.assertFalse(result["bench_force_criterion_met"])
        self.assertGreater(result["held_out_max_abs_error_n"],.5)

    def test_offcenter_data_cannot_enter_training(self):
        metadata,rows=analysis_fixture()
        for trial,row in zip(metadata["plan"]["trials"],rows):
            if row["split"]=="train":
                row["u_mm"]=trial["u_mm"]=10
        with self.assertRaisesRegex(ValueError,"center only"):analyze(metadata,rows)

    def test_incomplete_moment_plan_does_not_pass(self):
        metadata,rows=analysis_fixture()
        with self.assertRaisesRegex(ValueError,"incomplete"):analyze(metadata,rows[:-1])

    def test_lower_actual_force_does_not_qualify_twenty_newtons(self):
        metadata,rows=analysis_fixture()
        for row in rows:
            if row["reference_n"]==20:row["reference_n"]=19.5
        with self.assertRaisesRegex(ValueError,"20 N"):analyze(metadata,rows)

    def test_pose_change_rejected(self):
        metadata,rows=analysis_fixture();rows[-1]["pose_id"]="another-pose"
        with self.assertRaisesRegex(ValueError,"pose"):analyze(metadata,rows)

    def test_synthetic_report_rejected(self):
        metadata,rows=analysis_fixture();metadata["evidence_kind"]="synthetic"
        with self.assertRaisesRegex(ValueError,"physical"):analyze(metadata,rows)

    def test_finger_retains_cell_sensitivity_and_explicit_pose_zero(self):
        base,metadata,rows=finger_fixture()
        result=analyze_finger(base,metadata,rows)
        self.assertTrue(result["static_force_criterion_met"])
        self.assertEqual(result["model"]["counts_per_n"],base["model"]["counts_per_n"])
        self.assertEqual(result["model"]["zero_counts"],25000)
        self.assertFalse(result["robot_gripper_qualified"])

    def test_integration_error_is_not_fit_away(self):
        result=analyze_finger(*finger_fixture(scale=1.1))
        self.assertFalse(result["static_force_criterion_met"])
        self.assertAlmostEqual(result["held_out_max_abs_error_n"],2)

    def test_zero_return_is_not_automatically_tared(self):
        result=analyze_finger(*finger_fixture(return_bias=.3))
        self.assertFalse(result["static_force_criterion_met"])
        self.assertAlmostEqual(result["max_zero_return_error_n"],.3)

    def test_finger_cannot_use_replacement_cell_calibration(self):
        base,metadata,rows=finger_fixture();base["specimen"]="OTHER"
        with self.assertRaisesRegex(ValueError,"specimen"):analyze_finger(base,metadata,rows)

    def test_loaded_readings_cannot_define_the_finger_zero(self):
        base,metadata,rows=finger_fixture();rows[0]["reference_n"]=1
        with self.assertRaises(ValueError):analyze_finger(base,metadata,rows)

    def test_incomplete_finger_test_is_rejected(self):
        base,metadata,rows=finger_fixture()
        with self.assertRaisesRegex(ValueError,"incomplete"):analyze_finger(base,metadata,rows[:-1])

    def test_live_model_is_bound_to_pose(self):
        report=analyze_finger(*finger_fixture())
        with self.assertRaisesRegex(ValueError,"pose"):
            checked_model(report,"TEST-FIXTURE","OTHER","integrated_enpire_l1")
        self.assertEqual(checked_model(report,"TEST-FIXTURE","FINGER-POSE","integrated_enpire_l1"),report["model"])

    def test_invalid_bridge_never_becomes_live_zero_force(self):
        reading=decode(sample());reading["valid"]=False;reading["flags"]=["bridge_excitation_current"]
        result=estimate(reading,{"zero_counts":12345,"counts_per_n":1000})
        self.assertIsNone(result["force_n"]);self.assertFalse(result["valid"])

    def test_negative_sensitivity_is_supported(self):
        metadata,rows=analysis_fixture()
        for row in rows:row["raw_counts_mean"]=10000-1000*row["reference_n"]
        result=analyze(metadata,rows)
        self.assertTrue(result["bench_force_criterion_met"])
        self.assertAlmostEqual(force_from_counts(result["model"],-10000),20)

    def test_missing_intermediate_force_level_is_rejected(self):
        metadata,rows=analysis_fixture()
        rows[4]["reference_n"]=0
        with self.assertRaisesRegex(ValueError,"level"):analyze(metadata,rows)


if __name__=="__main__":
    unittest.main()
