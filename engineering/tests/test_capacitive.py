"""K1 raw converter transactions: fresh completion, sign and fault integrity."""

import importlib.util
import copy
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("k1_fdc1004", ROOT / "engineering/firmware/capacitive/fdc1004.py")
fdc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fdc)
protocol_spec = importlib.util.spec_from_file_location("k1_protocol", ROOT / "engineering/software/capacitive_protocol.py")
protocol = importlib.util.module_from_spec(protocol_spec)
protocol_spec.loader.exec_module(protocol)


def packets():
    calibration = [0]*4+[0x4000]*4
    hello = {"type": "hello", "protocol": "yam-k1/1", "rate_sps": 400, "capdac_enabled": False,
             "raw_pF_divisor": 524288, "health_lsb_v": .000125,
             "force_calibrated": False, "contact_calibrated": False,
             "banks": [{"bank": i, "sites": list(sites), "i2c_id": i, "sda_gpio": i*2, "scl_gpio": i*2+1}
                       for i, sites in enumerate(protocol.BANK_SITES)],
             "startup": [{"bank": i, "ready": True, "calibration_words": calibration[:]} for i in range(2)]}
    sample = {"type": "sample", "protocol": "yam-k1/1", "seq": 0, "device_us": 0, "scan_us": 16000, "banks": []}
    for i in range(2):
        bank = {"bank": i, "errors": [], "calibration_words": calibration[:], "fdc": [], "health": [],
                "fdc_us": [3000, 6500, 10000, 13500], "health_us": [3100, 6600, 10100, 13600]}
        for slot, value in enumerate((-2, 3, 4, 8)):
            raw = value*524288
            unsigned = raw & 0xFFFFFF
            bank["fdc"].append({"slot": slot, "raw": raw, "msb": unsigned >> 8, "lsb": (unsigned & 255) << 8,
                                "measurement_config": protocol.MEASURE[slot],
                                "observed_fdc_config": 0x0C00 | (0x80 >> slot) | (8 >> slot)})
            bank["health"].append({"raw": 26400 if slot == 0 else 0,
                                   "configuration": 0x8000 | ((4+slot) << 12) | 0x03E3})
        sample["banks"].append(bank)
    return hello, sample


class FakeBus:
    def __init__(self):
        self.registers = {0xFE: 0x5449, 0xFF: 0x1004, 0x0C: 0}
        self.registers.update({i: 0 for i in range(0x0D, 0x11)})
        self.registers.update({i: 0x4000 for i in range(0x11, 0x15)})
        self.registers.update({i: 0x1C00 for i in range(0x08, 0x0C)})
        self.writes = []
        self.reads = []
        self.pending = None
        self.keep_done = False
        self.fail_write = False
        self.short_read = False

    def writeto_mem(self, address, register, payload):
        if address != 0x50 or len(payload) != 2:
            raise AssertionError("Wrong bus transaction")
        if self.fail_write:
            raise OSError("disconnected")
        value = (payload[0] << 8) | payload[1]
        self.writes.append((register, value))
        self.registers[register] = value
        if register == 0x0C and value == 0x8000:
            self.registers[register] = 0
        elif register == 0x0C and value & 0xF0:
            self.pending = [bool(value & (0x80 >> i)) for i in range(4)].index(True)

    def readfrom_mem(self, address, register, count):
        self.reads.append(register)
        if self.short_read:
            return b"\x00"
        value = self.registers.get(register, 0)
        if register < 8 and register % 2 and not self.keep_done:
            self.registers[0x0C] &= ~(0x08 >> (register // 2))
        return bytes((value >> 8, value & 255))

    def complete(self, raw):
        unsigned = raw & 0xFFFFFF
        self.registers[2 * self.pending] = unsigned >> 8
        self.registers[2 * self.pending + 1] = (unsigned & 255) << 8
        self.registers[0x0C] |= 0x08 >> self.pending


class ConverterTests(unittest.TestCase):
    def make(self, rate=400):
        bus = FakeBus()
        converter = fdc.FDC1004(bus)
        converter.begin_reset()
        converter.configure(rate)
        return bus, converter

    def test_signed_word_and_picofarad_boundaries(self):
        self.assertEqual(fdc.signed24(0x7FFF, 0xFF00), 8388607)
        self.assertEqual(fdc.signed24(0x8000, 0), -8388608)
        self.assertEqual(fdc.capacitance_pf(fdc.signed24(0xFC00, 0)), -0.5)
        self.assertEqual(fdc.capacitance_pf(fdc.signed24(0x0C00, 0)), 1.5)
        with self.assertRaises(OSError):
            fdc.signed24(0, 1)
        with self.assertRaises(ValueError):
            fdc.capacitance_pf(True)

    def test_single_shot_words_never_set_repeat(self):
        bus, converter = self.make(100)
        converter.start(1)
        self.assertEqual(bus.writes[-1], (0x0C, 0x0440))
        self.assertFalse(bus.writes[-1][1] & 0x100)
        self.assertEqual(tuple(bus.registers[i] for i in range(8, 12)),
                         (0x0C00, 0x2C00, 0x4C00, 0x7C00))

    def test_wait_then_paired_read_cannot_be_reused(self):
        bus, converter = self.make()
        converter.start(2)
        self.assertFalse(converter.ready())
        with self.assertRaises(OSError):
            converter.result()
        bus.complete(-131072)
        self.assertTrue(converter.ready())
        result = converter.result()
        self.assertEqual(result["raw"], -131072)
        self.assertEqual(result["slot"], 2)
        self.assertNotIn("force_n", result)
        self.assertEqual(bus.reads[-3:], [4, 5, 0x0C])
        with self.assertRaises(OSError):
            converter.result()

    def test_stale_done_must_clear_before_trigger(self):
        bus, converter = self.make()
        bus.registers[0x0C] |= 8
        bus.keep_done = True
        count = len(bus.writes)
        with self.assertRaises(OSError):
            converter.start(0)
        self.assertEqual(len(bus.writes), count)
        self.assertFalse(converter.configured)

    def test_changed_input_or_capdac_is_fault(self):
        bus, converter = self.make()
        bus.registers[8] ^= 0x1000
        with self.assertRaises(OSError):
            converter.start(0)
        self.assertIsNone(converter.requested)

    def test_repetition_rate_and_wrong_measurement_are_faults(self):
        for changed in (0x0D88, 0x0888, 0x0CC8, 0x2C88, 0x0E88):
            bus, converter = self.make()
            converter.start(0)
            bus.registers[0x0C] = changed
            with self.assertRaises(OSError):
                converter.ready()
            self.assertFalse(converter.configured)
            self.assertIsNone(converter.requested)

    def test_bad_result_does_not_survive_next_call(self):
        bus, converter = self.make()
        converter.start(0)
        bus.complete(10)
        converter.ready()
        bus.registers[1] |= 1
        with self.assertRaises(OSError):
            converter.result()
        self.assertIsNone(converter.requested)
        self.assertFalse(converter.configured)

    def test_timeout_requires_setup(self):
        bus, converter = self.make()
        converter.start(0)
        converter.timed_out()
        bus.complete(0)
        with self.assertRaises(OSError):
            converter.start(0)

    def test_write_failure_and_calibration_change_are_not_valid_zero(self):
        bus, converter = self.make()
        bus.fail_write = True
        with self.assertRaises(OSError):
            converter.start(0)
        self.assertIsNone(converter.requested)
        bus, converter = self.make()
        bus.registers[0x11] += 1
        with self.assertRaises(OSError):
            converter.check_setup()
        self.assertFalse(converter.configured)

    def test_identity_and_short_read_rejected(self):
        bus = FakeBus()
        bus.registers[0xFF] = 0xFFFF
        with self.assertRaises(OSError):
            fdc.FDC1004(bus).begin_reset()
        self.assertEqual(bus.writes, [])
        bus, converter = self.make()
        bus.short_read = True
        with self.assertRaises(OSError):
            converter.start(0)
        self.assertFalse(converter.configured)


class ProtocolTests(unittest.TestCase):
    def decode(self, change=None):
        hello, sample = packets()
        if change:
            change(sample)
        decoder = protocol.Decoder()
        decoder.accept(hello)
        return decoder.accept(sample)

    def test_complete_raw_frame_is_not_force_or_contact(self):
        result = self.decode()
        self.assertTrue(result["complete_finger_available"])
        self.assertEqual([c["site"] for c in result["cells"]], ["CH0", "CH1", "CH2", "CH3", "CH4", "CH5"])
        self.assertEqual(result["cells"][0]["sequential_reconstructed_pf"], 6)
        self.assertIsNone(result["force_n"])
        self.assertTrue(all(c["force_n"] is None and c["contact"] is None for c in result["cells"]))

    def test_broken_ground_return_is_unavailable(self):
        result = self.decode(lambda p: p["banks"][0]["health"][1].update(raw=26400))
        self.assertFalse(result["complete_finger_available"])
        self.assertIn("ground_return", result["cells"][0]["faults"])
        self.assertAlmostEqual(result["cells"][0]["ground_return_v"], 3.3)

    def test_missing_reference_invalidates_its_bank(self):
        result = self.decode(lambda p: p["banks"][0]["fdc"].__setitem__(3, None))
        self.assertTrue(all(not c["available"] for c in result["cells"] if c["bank"] == 0))
        self.assertTrue(all(c["available"] for c in result["cells"] if c["bank"] == 1))

    def test_supply_fault_and_missing_health_are_not_clear_contact(self):
        for change in (lambda p: p["banks"][0]["health"][0].update(raw=20000),
                       lambda p: p["banks"][0]["health"].__setitem__(0, None)):
            result = self.decode(change)
            self.assertFalse(result["complete_finger_available"])
            self.assertIn("supply", result["cells"][0]["faults"])

    def test_zero_reconstructed_capacitance_fails_plausibility(self):
        def change(packet):
            row = packet["banks"][0]["fdc"][0]
            raw = -8*524288
            row.update(raw=raw, msb=(raw & 0xFFFFFF) >> 8, lsb=0)
        result = self.decode(change)
        self.assertFalse(result["cells"][0]["available"])
        self.assertIn("capacitance_plausibility", result["cells"][0]["faults"])

    def test_changed_coefficients_and_configuration_preserve_faults(self):
        for change in (lambda p: p["banks"][0]["calibration_words"].__setitem__(4, 0x4001),
                       lambda p: p["banks"][0]["fdc"][1].update(observed_fdc_config=0x0D44),
                       lambda p: p["banks"][0]["health"][1].update(configuration=0xC3E3)):
            self.assertFalse(self.decode(change)["complete_finger_available"])

    def test_repeated_packets_and_gaps_are_not_independent_samples(self):
        hello, sample = packets()
        decoder = protocol.Decoder(); decoder.accept(hello); decoder.accept(sample)
        with self.assertRaises(ValueError):
            decoder.accept(sample)
        later = copy.deepcopy(sample)
        later.update(seq=2, device_us=20000)
        result = decoder.accept(later)
        self.assertFalse(result["complete_finger_available"])
        self.assertIn("acquisition_gap", result["cells"][0]["faults"])

    def test_incomplete_identity_and_noninteger_counts_are_rejected(self):
        hello, sample = packets()
        bad = copy.deepcopy(hello)
        bad["startup"][0]["calibration_words"] = None
        with self.assertRaises(ValueError):
            protocol.Decoder().accept(bad)
        decoder = protocol.Decoder(); decoder.accept(hello)
        sample["banks"][0]["fdc"][0]["raw"] = True
        with self.assertRaises(ValueError):
            decoder.accept(sample)


if __name__ == "__main__":
    unittest.main()
