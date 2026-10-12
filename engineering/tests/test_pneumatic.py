"""Synthetic protocol/driver faults; these are not physical P1 results."""

import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"engineering/software"))
from pneumatic_protocol import CONFIG, Decoder, PROTOCOL, nominal_pressure_pa


def firmware_module(name):
    spec = importlib.util.spec_from_file_location("p1_test_"+name, ROOT/("engineering/firmware/pneumatic/"+name+".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


elvr = firmware_module("elvr")
adc_module = firmware_module("ads1115")


def hello():
    return {"type": "hello", "protocol": PROTOCOL, "firmware": "P1.0",
            "boot_id": "0123456789abcdef-0123456789abcdef", "device_id": "0123456789abcdef",
            "config": copy.deepcopy(CONFIG), "source": "rp2040_i2c", "synthetic": False,
            "adc_lsb_v": .000125, "pressure_order": [2, 3, 4, 5],
            "adc_order": ["NAIL0", "NAIL1", "3V0", "3V3"],
            "force_calibrated": False, "pressure_calibrated": False}


def frame(seq=0):
    return {"type": "sample", "protocol": PROTOCOL, "boot_id": hello()["boot_id"],
            "seq": seq, "device_us": seq*20000, "scan_us": 9000,
            "offset_us": [100, 200, 300, 400, 2000, 4000, 6000, 8000],
            "pressure_raw": [13654]*4, "adc_raw": [2400, 2400, 24000, 26400], "errors": []}


class Bus:
    def __init__(self):
        self.mask = 0
        self.operations = []
        self.mux_wrong = False
        self.pressure = b"\x35\x55"
        self.configuration = None
        self.change_config = False

    def writeto(self, address, data):
        self.operations.append(("write", address, bytes(data)))
        self.mask = data[0]

    def readfrom(self, address, count):
        self.operations.append(("read", address, count))
        if address == 0x70:
            return bytes((3 if self.mux_wrong else self.mask,))
        return self.pressure

    def writeto_mem(self, address, register, data):
        self.configuration = (data[0] << 8) | data[1]

    def readfrom_mem(self, address, register, count):
        value = self.configuration ^ (0x1000 if self.change_config else 0) if register == 1 else 1234
        return bytes((value >> 8, value & 255))


class P1Drivers(unittest.TestCase):
    def test_pressure_word_uses_all_fifteen_bits(self):
        self.assertEqual(elvr.decode_word(b"\x60\x00"), 24576)
        self.assertEqual(elvr.decode_word(b"\x0a\xab"), 2731)
        for packet in (b"\x80\x00", b"\x00", b"\x00\x00\x00"):
            with self.assertRaises(OSError):
                elvr.decode_word(packet)

    def test_mux_readback_precedes_sensor_and_wrong_branch_aborts(self):
        bus = Bus()
        bank = elvr.PressureBank(bus)
        self.assertEqual(bank.read(3), 13653)
        self.assertEqual(bus.operations, [("write", 0x70, b"\x08"), ("read", 0x70, 1), ("read", 0x78, 2)])
        bus.operations.clear()
        bus.mux_wrong = True
        with self.assertRaises(OSError):
            bank.read(1)
        self.assertFalse(any(op[1] == 0x78 for op in bus.operations))

    def test_mux_disable_and_bounds(self):
        bus = Bus()
        bank = elvr.PressureBank(bus)
        bank.read(0)
        bank.disable()
        self.assertEqual(bus.mask, 0)
        self.assertIsNone(bank.selected)
        with self.assertRaises(ValueError):
            bank.select(4)

    def test_adc_checks_config_and_requires_new_conversion(self):
        bus = Bus()
        adc = adc_module.ADS1115(bus)
        with self.assertRaises(OSError):
            adc.result()
        adc.start(2)
        self.assertEqual(bus.configuration, 0xE3E3)
        self.assertTrue(adc.ready())
        self.assertEqual(adc.result(), 1234)
        with self.assertRaises(OSError):
            adc.result()
        adc.start(0)
        bus.change_config = True
        with self.assertRaises(OSError):
            adc.ready()


class P1Decoding(unittest.TestCase):
    def decoder(self):
        result = Decoder()
        result.accept(hello())
        return result

    def test_good_raw_frame_does_not_claim_contact_or_force(self):
        result = self.decoder().accept(frame())
        self.assertTrue(result["complete_finger_available"])
        self.assertAlmostEqual(result["signals"][0], 0., places=10)
        self.assertIsNone(result["force_n"])
        self.assertIsNone(result["contact"])
        self.assertTrue(all(cell["force_n"] is None for cell in result["cells"]))

    def test_nominal_pressure_display_endpoints(self):
        self.assertAlmostEqual(nominal_pressure_pa(2731), -30*249.088)
        self.assertAlmostEqual(nominal_pressure_pa(24576), 30*249.088)

    def test_missing_pressure_remains_unavailable(self):
        packet = frame()
        packet["pressure_raw"][2] = None
        packet["offset_us"][2] = None
        result = self.decoder().accept(packet)
        self.assertFalse(result["complete_finger_available"])
        self.assertIsNone(result["signals"][4])
        self.assertIsNone(result["force_n"])

    def test_pressure_supply_and_open_nail_faults(self):
        packet = frame()
        packet["adc_raw"][2] = 22000
        result = self.decoder().accept(packet)
        self.assertFalse(result["complete_finger_available"])
        self.assertIn("pressure_supply", result["cells"][2]["faults"])
        packet = frame()
        packet["adc_raw"][0] = 0
        result = self.decoder().accept(packet)
        self.assertIn("nail_continuity_or_headroom", result["cells"][0]["faults"])

    def test_near_endpoint_pressure_is_not_zero_or_clipped(self):
        packet = frame()
        packet["pressure_raw"][0] = 26000
        result = self.decoder().accept(packet)
        self.assertFalse(result["cells"][2]["available"])
        self.assertGreater(result["signals"][2], 30*249.088)
        self.assertIsNone(result["force_n"])

    def test_out_of_order_and_missing_frames(self):
        decoder = self.decoder()
        decoder.accept(frame())
        with self.assertRaises(ValueError):
            decoder.accept(frame())
        result = decoder.accept(frame(2))
        self.assertIn("acquisition_gap", result["cells"][0]["faults"])

    def test_hello_repetition_does_not_reset_sequence_check(self):
        decoder = self.decoder()
        decoder.accept(frame(20))
        decoder.accept(hello())
        with self.assertRaises(ValueError):
            decoder.accept(frame(19))

    def test_restart_invalidates_first_new_frame(self):
        decoder = self.decoder()
        decoder.accept(frame())
        changed = hello()
        changed["boot_id"] = changed["device_id"]+"-fedcba9876543210"
        decoder.accept(changed)
        packet = frame()
        packet["boot_id"] = changed["boot_id"]
        result = decoder.accept(packet)
        self.assertIn("device_restarted", result["cells"][0]["faults"])
        self.assertEqual(len(decoder.finish()["boots"]), 2)

    def test_configuration_synthetic_and_bad_timing_are_rejected(self):
        for key, value in (("synthetic", True), ("pressure_order", [5, 4, 3, 2])):
            packet = hello()
            packet[key] = value
            with self.assertRaises(ValueError):
                Decoder().accept(packet)
        packet = hello()
        packet["config"]["frame_us"] = True
        with self.assertRaises(ValueError):
            Decoder().accept(packet)
        packet = frame()
        packet["offset_us"][2] = 150
        result = self.decoder().accept(packet)
        self.assertIn("sample_order", result["cells"][0]["faults"])

    def test_raw_bit_width_and_pending_parse_failure(self):
        packet = frame()
        packet["pressure_raw"][0] = 32768
        with self.assertRaises(ValueError):
            self.decoder().accept(packet)
        decoder = self.decoder()
        decoder.invalidate("serial_timeout")
        result = decoder.accept(frame())
        self.assertIn("serial_timeout", result["cells"][0]["faults"])


if __name__ == "__main__":
    unittest.main()
