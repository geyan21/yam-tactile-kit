"""Protocol/state checks using explicitly synthetic I/O, not sensor evidence."""

import copy
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "engineering/firmware/f1"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = load("f1_scan_checks", FIRMWARE / "scan.py")
protocol = load("f1_protocol_checks", ROOT / "engineering/software/f1_protocol.py")


class StateOracle:
    """Independent restrictions on when an electrical observation is admissible."""
    def __init__(self, config):
        self.config = config
        self.outputs = {}
        self.now = 0
        self.changed = 0
        self.fail_active = False
        self.park()

    def time_us(self):
        return self.now

    def wait_us(self, duration):
        self.now += duration

    def set(self, name, value):
        if self.outputs.get(name) == value:
            return
        if name.startswith("GAIN") and not self.outputs.get("PARK"):
            raise AssertionError("Gain changed outside PARK")
        if name in ("A0", "A1", "A2", "A3") and (
                not self.outputs.get("PARK") or self.outputs.get("CUR_EN") or self.outputs.get("SNS_EN")):
            raise AssertionError("Column changed while a multiplexer was enabled")
        self.outputs[name] = value
        self.changed = self.now

    def park(self):
        self.outputs = {key: 0 for key in self.config["gpio"]}
        self.outputs["PARK"] = 1
        self.changed = self.now

    def read_monitors(self):
        if not self.outputs["PARK"]:
            raise AssertionError("Monitor traffic was not parked")
        return [2048]*8

    def read_main(self):
        state = self.outputs
        if state["PARK"] or not state["CUR_EN"] or not state["SNS_EN"]:
            raise AssertionError("Acquisition without closed current/sense feedback")
        if sum(state["GAIN"+str(i)] for i in range(4)) != 1:
            raise AssertionError("Gain selection is not one-hot")
        row_count = sum(state["ROW"+str(i)] for i in range(4))
        if row_count > 1 or (state["TEST_EN"] and row_count):
            raise AssertionError("Test current and row excitation were mixed")
        if self.now-self.changed < self.config["settle_us"]:
            raise AssertionError("Acquisition began before the declared settling interval")
        if self.fail_active and (row_count or state["TEST_EN"]):
            raise OSError("Synthetic ADC failure during excitation")
        stamp = self.now
        self.now += 24
        return stamp, 32768-(16400 if state["TEST_EN"] else 6000 if row_count else 0)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((FIRMWARE / "config.json").read_text())

    def test_complete_frame_keeps_all_pixels_tests_and_unknown_force(self):
        self.config["gain_ids"] = [i % 4 for i in range(64)]
        hardware = StateOracle(self.config)
        records = []
        scan.Scanner(hardware, self.config).capture_frame(7, records.append)
        pixels = [r for r in records if r["kind"] == "pixel"]
        checks = [r for r in records if r["kind"] == "column_link_check"]
        self.assertEqual({(r["row"], r["column"]) for r in pixels},
                         {(r, c) for r in range(4) for c in range(16)})
        self.assertEqual(len(pixels), 64)
        self.assertEqual({r["column"] for r in checks}, set(range(16)))
        self.assertTrue(all(r["contact"] is None and r["force_n"] is None for r in pixels))
        self.assertTrue(all(r["tactile_observation"] is False and not r["qualified_fault_coverage"] for r in checks))
        self.assertEqual(records[0]["kind"], "frame_begin")
        self.assertEqual(records[-1]["kind"], "frame_end")
        self.assertEqual(hardware.outputs["PARK"], 1)
        self.assertFalse(any(hardware.outputs["ROW"+str(i)] for i in range(4)))

    def test_active_pixel_error_turns_row_excitation_off(self):
        hardware = StateOracle(self.config)
        hardware.fail_active = True
        scanner = scan.Scanner(hardware, self.config)
        with self.assertRaises(OSError):
            scanner.pixel(0, 2, 9, 3)
        self.assertFalse(any(hardware.outputs["ROW"+str(i)] for i in range(4)))

    def test_electrical_test_error_disables_the_test_path(self):
        hardware = StateOracle(self.config)
        hardware.fail_active = True
        with self.assertRaises(OSError):
            scan.Scanner(hardware, self.config).link_check(0, 5)
        self.assertEqual(hardware.outputs["TEST_EN"], 0)

    def test_bad_gain_timing_and_pin_contracts_are_rejected(self):
        cases = []
        for name, value in (("settle_us", 100), ("conversion_wait_us", 8),
                            ("adc_spi_hz", 0), ("link_test_gain", 3)):
            config = copy.deepcopy(self.config); config[name] = value
            cases.append(config)
        config = copy.deepcopy(self.config); config["gain_ids"][8] = True; cases.append(config)
        config = copy.deepcopy(self.config); config["gpio"]["PARK"] = config["gpio"]["ROW0"]; cases.append(config)
        for config in cases:
            with self.assertRaises(ValueError):
                scan.checked_config(config)


class HardwareBusTests(unittest.TestCase):
    def test_adc_and_monitor_bus_timing_and_return_to_main_mode(self):
        config = json.loads((FIRMWARE / "config.json").read_text())
        state = {"time": 0, "pins": {}, "rises": [], "reads": []}
        def wait(us):
            state["time"] += us
        class Pin:
            IN, OUT, PULL_DOWN = 0, 1, 2
            def __init__(self, number, mode=None, pull=None, value=None):
                self.number = number
                state["pins"].setdefault(number, 0)
                if value is not None:
                    state["pins"][number] = value
            def value(self, value=None):
                if value is None:
                    return state["pins"][self.number]
                prior = state["pins"][self.number]
                state["pins"][self.number] = value
                if self.number == config["gpio"]["ADC_CONV"] and value == 1 and prior == 0:
                    state["rises"].append(state["time"])
        class SPI:
            MSB = 0
            def __init__(self, *args, **kwargs):
                self.init(**kwargs)
            def init(self, **kwargs):
                self.baudrate = kwargs["baudrate"]
            def readinto(self, buffer, value):
                assert state["pins"][config["gpio"]["ADC_CONV"]] == 0
                assert state["pins"][config["gpio"]["MON_CS"]] == 1
                assert state["time"]-state["rises"][-1] >= 10
                assert self.baudrate == 8000000
                state["reads"].append(state["time"])
                buffer[:] = b"\x51\x2a"
                wait(2)
            def write_readinto(self, tx, rx):
                assert state["pins"][config["gpio"]["ADC_CONV"]] == 1
                assert state["pins"][config["gpio"]["MON_CS"]] == 0
                assert self.baudrate == 1000000
                rx[:] = b"\x00\x09\x23"
                wait(24)
        fake_time = types.SimpleNamespace(sleep_us=wait, sleep_ms=lambda ms: wait(ms*1000),
                                          ticks_us=lambda: state["time"], ticks_diff=lambda a, b: a-b)
        with patch.dict(sys.modules, {"machine": types.SimpleNamespace(Pin=Pin, SPI=SPI), "time": fake_time}):
            hardware_module = load("f1_hardware_bus_checks", FIRMWARE / "hardware.py")
        hardware = hardware_module.Hardware(config)
        first = hardware.read_main()
        self.assertEqual(first[1], 0x512a)
        self.assertEqual(state["pins"][config["gpio"]["ADC_CONV"]], 0)
        hardware.read_main()
        self.assertGreaterEqual(state["rises"][1]-state["rises"][0], 22)
        self.assertEqual(hardware.read_monitors(), [0x923]*8)
        self.assertEqual(hardware.read_main()[1], 0x512a)
        self.assertEqual(state["pins"][config["gpio"]["ADC_CONV"]], 0)
        self.assertEqual(len(state["rises"]), 4)  # Three requested samples and one discarded monitor-entry conversion.


class StreamTests(unittest.TestCase):
    def records(self):
        config = json.loads((FIRMWARE / "config.json").read_text())
        hardware = StateOracle(config)
        messages = [{"kind": "hello", "schema": protocol.PROTOCOL, "sensor_only": True,
                     "force_calibration_loaded": False, "fault_check_qualified": False,
                     "next_frame": 0, "configuration": config}]
        scan.Scanner(hardware, config).capture_frame(0, messages.append)
        return messages

    def test_stream_requires_all_matrix_positions(self):
        messages = self.records()
        decoder = protocol.FrameAssembler()
        for message in messages:
            result = decoder.accept(message)
        self.assertTrue(result["complete"])
        self.assertFalse(result["physical_force_accuracy_established"])
        self.assertEqual(decoder.finish()["complete_frames"], 1)
        decoder = protocol.FrameAssembler()
        dropped = False
        for message in messages:
            if message["kind"] == "pixel" and not dropped:
                dropped = True
                continue
            result = decoder.accept(message)
        self.assertFalse(result["complete"])
        self.assertEqual(decoder.finish()["incomplete_frames"], 1)

    def test_duplicate_and_stale_observations_are_rejected(self):
        decoder = protocol.FrameAssembler()
        for message in self.records():
            decoder.accept(message)
            if message["kind"] == "pixel":
                with self.assertRaises(ValueError):
                    decoder.accept(message)
                break
        self.assertEqual(decoder.finish()["complete_frames"], 0)

    def test_electrical_checks_cannot_become_tactile_records(self):
        decoder = protocol.FrameAssembler()
        for original in self.records():
            message = copy.deepcopy(original)
            if message["kind"] == "column_link_check":
                message["tactile_observation"] = True
                with self.assertRaises(ValueError):
                    decoder.accept(message)
                break
            decoder.accept(message)

    def test_capture_can_synchronize_at_hello_without_port_commands(self):
        decoder = protocol.FrameAssembler()
        self.assertFalse(decoder.accept({"kind": "pixel"})["accepted"])
        for message in self.records():
            result = decoder.accept(message)
        self.assertTrue(result["complete"])


if __name__ == "__main__":
    unittest.main()
