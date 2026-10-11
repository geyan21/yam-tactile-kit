"""B3 configuration and failure tests; synthetic packets are not force evidence."""

import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engineering/software"))
import recessed_protocol
import b1_protocol


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load("mlx90393_base", "engineering/firmware/b1/mlx90393.py")
sys.modules["mlx90393_base"] = base
driver = load("recessed_driver", "engineering/firmware/recessed/mlx90393.py")


def sample():
    return {
        "type": "sample", "protocol": "yam-b3/1", "seq": 1, "device_us": 50000,
        "scan_us": 40000, "settings": copy.deepcopy(recessed_protocol.SETTINGS),
        "errors": [], "sensors": [
            {"channel": i, "status": 3, "start_us": 1000 + i * 1500,
             "read_us": 15000 + i * 1000, "raw_xyz": [-100, 200, 1000],
             "temperature_raw": 46000} for i in range(5)
        ],
        "nail_cells": True, "nail_raw": [2400, 2400, 13200, 13200],
        "nail_offset_us": [25000, 27000, 29000, 31000],
        "pull_down_ohm": [10000, 10000], "continuity_ohm": 100000,
    }


class Bus:
    def __init__(self):
        self.registers = {0: 0xABFC}
        self.commands = []
        self.reply = b"\0"
        self.mask = b"\0"

    def writeto(self, address, payload, stop=True):
        if address == 0x70:
            self.mask = payload
        else:
            self.commands.append(payload)
            if payload[0] == 0x50:
                value = self.registers.get(payload[1] >> 2, 0)
                self.reply = bytes((0, value >> 8, value & 255))
            elif payload[0] == 0x60:
                self.registers[payload[3] >> 2] = (payload[1] << 8) | payload[2]
                self.reply = b"\0"
            else:
                self.reply = b"\x20" if payload == b"\x3f" else b"\x04"
        return len(payload)

    def readfrom(self, address, count):
        return self.mask if address == 0x70 else self.reply


class RecessedTests(unittest.TestCase):
    def test_gain5_sign_and_scale_preserve_raw_and_b1_configuration(self):
        frame = sample()
        original = copy.deepcopy(frame)
        b1_settings = copy.deepcopy(b1_protocol.SETTINGS)
        result = recessed_protocol.decode(frame)
        self.assertEqual(result["magnetic_local_ut"][0], [-50.1, 100.2, 807.0])
        self.assertTrue(result["valid"])
        self.assertEqual(result["design_id"], "RECESSED")
        self.assertIsNone(result["force_n"])
        self.assertFalse(result["force_calibrated"])
        self.assertEqual(frame, original)
        self.assertEqual(b1_protocol.SETTINGS, b1_settings)
        self.assertAlmostEqual(result["nail_conductance_us"][0], 10)

    def test_wrong_identity_gain_and_boolean_resolution_rejected(self):
        for protocol, key, value in (("yam-b2/1", "gain_sel", 5),
                                     ("yam-b3/1", "gain_sel", 7),
                                     ("yam-b3/1", "resolution", True)):
            frame = sample()
            frame["protocol"] = protocol
            frame["settings"][key] = value
            with self.subTest(protocol=protocol, key=key), self.assertRaises(ValueError):
                recessed_protocol.decode(frame)

    def test_missing_railed_and_bad_status_heads_remain_unavailable(self):
        frame = sample()
        frame["sensors"][0] = None
        frame["sensors"][1]["raw_xyz"][2] = 30000
        frame["sensors"][2]["status"] = 0x13
        result = recessed_protocol.decode(frame)
        self.assertFalse(result["valid"])
        self.assertEqual(result["magnetic_local_ut"][:3], [None] * 3)
        for flag in ("missing:S0", "near_rail:S1", "status:S2"):
            self.assertIn(flag, result["flags"])

    def test_disabled_or_broken_nail_cannot_count_as_valid_complete_finger(self):
        frame = sample()
        frame["nail_cells"] = False
        self.assertIn("nail_cells_disabled", recessed_protocol.decode(frame)["flags"])
        frame = sample()
        frame["nail_raw"][0] = 0
        result = recessed_protocol.decode(frame)
        self.assertFalse(result["valid"])
        self.assertIn("nail_open:0", result["flags"])

    def test_device_gain5_preserves_factory_bits_and_detects_configuration_loss(self):
        bus = Bus()
        head = driver.MLX90393(bus, 0)
        original = bus.registers[0]
        head.initialize()
        self.assertEqual(bus.registers[0], (original & ~0x7F) | 0x5C)
        self.assertEqual(driver.SETTINGS, recessed_protocol.SETTINGS)
        self.assertEqual(driver.LSB_UT, recessed_protocol.LSB_UT)
        head.start()
        self.assertEqual(bus.mask, b"\x01")
        self.assertTrue(all(command[0] in (0x80, 0xF0, 0x50, 0x60, 0x3F)
                            for command in bus.commands))
        bus.registers[0] ^= 0x20
        with self.assertRaises(OSError):
            head.start()


if __name__ == "__main__":
    unittest.main()
