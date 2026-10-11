"""FB1 force/status decoding and independent mechanical limiting cases."""

import importlib.util
import copy
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engineering/software"))
import force_button_force as force
spec = importlib.util.spec_from_file_location("fb1_fma", ROOT / "engineering/firmware/force_button/fma.py")
fma = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fma)
protocol_spec = importlib.util.spec_from_file_location("fb1_protocol", ROOT / "engineering/software/force_button_protocol.py")
protocol = importlib.util.module_from_spec(protocol_spec)
protocol_spec.loader.exec_module(protocol)
health_spec = importlib.util.spec_from_file_location("fb1_health", ROOT / "engineering/firmware/force_button/health_adc.py")
health = importlib.util.module_from_spec(health_spec)
health_spec.loader.exec_module(health)


def word(status, counts):
    return bytes(((status << 6) | (counts >> 8), counts & 255))


def packets():
    boot = "1234567890abcdef-0011223344556677"
    hello = {"type": "hello", "protocol": "yam-fb1/1", "boot_id": boot,
             "configuration": copy.deepcopy(protocol.SETTINGS), "health_lsb_v": .000125,
             "force_calibrated": False, "contact_calibrated": False}
    sample = {"type": "sample", "protocol": "yam-fb1/1", "boot_id": boot, "seq": 0,
              "device_us": 0, "scan_us": 8500, "errors": [], "sensor": fma.decode(word(0, 8192)),
              "sensor_us": 8300, "health_us": [1800, 3700, 5600, 7500],
              "health": [{"raw": value, "configuration": health.configuration(i)}
                         for i, value in enumerate((26400, 0, 26400, 0))]}
    return hello, sample


class ForceButtonProtocolTests(unittest.TestCase):
    def test_midspan_sensor_force_is_not_finger_force(self):
        result = fma.decode(word(0, 8192))
        self.assertTrue(result["fresh"])
        self.assertAlmostEqual(result["factory_nominal_sensor_n"], 12.5)
        self.assertIsNone(result["whole_finger_force_n"])

    def test_all_statuses_are_preserved(self):
        for status, name in enumerate(("new_data", "command_mode", "stale_data", "diagnostic")):
            result = fma.decode(word(status, 4096))
            self.assertEqual(result["status_name"], name)
            self.assertEqual(result["raw_force_counts"], 4096)
            self.assertEqual(result["fresh"], status == 0)
            if status:
                self.assertIsNone(result["factory_nominal_sensor_n"])

    def test_out_of_span_is_not_clamped(self):
        low = fma.decode(word(0, 0))
        high = fma.decode(word(0, 16383))
        self.assertLess(low["factory_nominal_sensor_n"], 0)
        self.assertGreater(high["factory_nominal_sensor_n"], 25)
        self.assertFalse(low["within_nominal_catalog_span"])
        self.assertFalse(high["within_nominal_catalog_span"])

    def test_incomplete_or_wrong_packet_rejected(self):
        for data in (b"", b"\0", b"\0\0\0", [0, 0], None):
            with self.assertRaises(ValueError):
                fma.decode(data)

    def test_reads_do_not_write_commands(self):
        class Bus:
            def __init__(self):
                self.calls = []
            def readfrom(self, address, length):
                self.calls.append((address, length))
                return word(0, 8192)
        bus = Bus()
        device = fma.FMA(bus)
        self.assertTrue(device.read()["fresh"])
        self.assertEqual(bus.calls, [(0x28, 2)])
        with self.assertRaises(ValueError):
            fma.FMA(bus, 0x48)

    def test_stale_read_does_not_reuse_the_last_force(self):
        class Bus:
            def __init__(self):
                self.values = iter((word(0, 8192), word(2, 8192)))
            def readfrom(self, address, length):
                return next(self.values)
        device = fma.FMA(Bus())
        self.assertIsNotNone(device.read()["factory_nominal_sensor_n"])
        self.assertIsNone(device.read()["factory_nominal_sensor_n"])


class ForceButtonFrameTests(unittest.TestCase):
    def test_sensor_board_matches_mechanical_interface(self):
        cfg = json.loads((ROOT / "engineering/designs/force_button_fb1.json").read_text())
        pcb = json.loads((ROOT / "engineering/designs/force_button_electronics.json").read_text())
        mechanism = cfg["mechanism"]
        axis = pcb["force_axis_xy_mm"]
        bounds = [min(p[i] for p in pcb["outline_mm"]) for i in range(2)]
        bounds += [max(p[i] for p in pcb["outline_mm"]) for i in range(2)]
        self.assertEqual([v-axis[i % 2] for i, v in enumerate(bounds)],
                         mechanism["sensor_board_bounds_about_force_axis_mm"])
        self.assertEqual(pcb["thickness_mm"], mechanism["sensor_board_thickness_mm"])
        self.assertEqual([[h["center_mm"][i]-axis[i] for i in range(2)] for h in pcb["holes"]],
                         mechanism["sensor_board_mount_offsets_mm"])
        self.assertEqual(pcb["parts"][0]["value"], cfg["sensor"]["part"])
        self.assertEqual(pcb["parts"][0]["vent_diameter_mm"], mechanism["sensor_pcb_vent_mm"])

    def test_settings_match_firmware_and_board(self):
        cfg = json.loads((ROOT / "engineering/firmware/force_button/config.json").read_text())
        pcb = json.loads((ROOT / "engineering/designs/force_button_electronics.json").read_text())
        self.assertEqual(cfg, protocol.SETTINGS)
        self.assertEqual(cfg["bus_hz"], pcb["controller"]["bus_hz"])
        self.assertEqual(cfg["sensor_address"], pcb["controller"]["sensor_address"])
        self.assertEqual(cfg["health_address"], pcb["controller"]["adc_address"])

    def test_raw_available_does_not_mean_calibrated(self):
        hello, packet = packets()
        decoder = protocol.Decoder()
        decoder.accept(hello)
        output = decoder.accept(packet)
        self.assertTrue(output["available"])
        self.assertEqual(output["factory_nominal_sensor_n"], 12.5)
        self.assertIsNone(output["whole_finger_force_n"])
        self.assertIsNone(output["contact"])

    def test_supply_and_ground_faults(self):
        for channel, counts, fault in ((0, 0, "remote_supply"), (1, 26400, "ground_return"),
                                       (2, 24000, "controller_supply"), (3, 500, "ground_reference")):
            hello, packet = packets()
            packet["health"][channel]["raw"] = counts
            decoder = protocol.Decoder(); decoder.accept(hello)
            output = decoder.accept(packet)
            self.assertFalse(output["available"])
            self.assertIn(fault, output["faults"])

    def test_stale_diagnostic_missing_and_out_of_range(self):
        for result, fault in ((fma.decode(word(1, 8192)), "sensor_command_mode"),
                              (fma.decode(word(2, 8192)), "sensor_stale_data"),
                              (fma.decode(word(3, 8192)), "sensor_diagnostic"),
                              (None, "missing_sensor"),
                              (fma.decode(word(0, 16383)), "sensor_outside_catalog_span")):
            hello, packet = packets(); packet["sensor"] = result
            decoder = protocol.Decoder(); decoder.accept(hello)
            output = decoder.accept(packet)
            self.assertFalse(output["available"])
            self.assertIn(fault, output["faults"])
            self.assertIsNone(output["whole_finger_force_n"])

    def test_repeated_hello_cannot_hide_sequence_gap(self):
        hello, packet = packets()
        decoder = protocol.Decoder(); decoder.accept(hello); decoder.accept(packet)
        decoder.accept(hello)
        packet["seq"], packet["device_us"] = 2, 20000
        self.assertIn("acquisition_gap", decoder.accept(packet)["faults"])
        with self.assertRaises(ValueError):
            decoder.accept(packet)

    def test_reboot_is_preserved(self):
        hello, packet = packets()
        decoder = protocol.Decoder(); decoder.accept(hello); decoder.accept(packet)
        hello["boot_id"] = packet["boot_id"] = "abcabcabcabc-9988776655443322"
        self.assertTrue(decoder.accept(hello)["restarted"])
        self.assertIn("device_restarted", decoder.accept(packet)["faults"])

    def test_wrong_adc_configuration_and_sample_order(self):
        hello, packet = packets()
        packet["health"][1]["configuration"] ^= 0x1000
        packet["sensor_us"] = 100
        decoder = protocol.Decoder(); decoder.accept(hello)
        output = decoder.accept(packet)
        self.assertIn("health_configuration", output["faults"])
        self.assertIn("sensor_sample_order", output["faults"])


class HealthDriverTests(unittest.TestCase):
    def test_readiness_and_configuration_are_required(self):
        class Bus:
            config = 0
            ready = False
            def writeto_mem(self, address, register, data):
                self.config = int.from_bytes(data, "big")
            def readfrom_mem(self, address, register, count):
                value = (self.config if self.ready else self.config & 0x7FFF) if register == 1 else 0xFFFF
                return value.to_bytes(2, "big")
        bus = Bus(); adc = health.HealthADC(bus)
        adc.start(1)
        self.assertFalse(adc.ready())
        with self.assertRaises(OSError):
            adc.result()
        bus.ready = True
        self.assertTrue(adc.ready())
        self.assertEqual(adc.result()["raw"], -1)
        with self.assertRaises(OSError):
            adc.result()
        adc.start(0)
        bus.config ^= 0x1000
        with self.assertRaises(OSError):
            adc.ready()


class ForceCalibrationTests(unittest.TestCase):
    def test_known_linear_force_model(self):
        loads = [0, .2, .5, 1, 2, 5, 10, 15, 20]
        model = force.fit_numeric([4200+350*v for v in loads], loads)
        self.assertAlmostEqual(model["slope_n_per_count"], 1/350)
        self.assertAlmostEqual(force.predict(model, 5950), 5)
        for values in ([1]*9, [1000-35*v for v in loads], [float("nan")]*9):
            with self.assertRaises(ValueError):
                force.fit_numeric(values, loads)

    def fixture(self, base, fault=False, complete=True):
        hello, sample = packets()
        header = {"type": "session", "schema": "yam-fb1-recording/1", "evidence_kind": "physical_recording_unreviewed",
                  "specimen": "SOFTWARE_TEST_ONLY", "session_id": "SOFTWARE_TEST_SESSION",
                  "geometry_sha256": "a"*64, "condition": "software_hold"}
        recording = base / "software_fixture.jsonl"
        with recording.open("w") as stream:
            stream.write(json.dumps(header)+"\n")
            stream.write(json.dumps({"host_elapsed_s": 0., "raw_line": json.dumps(hello)})+"\n")
            for i in range(650):
                packet = copy.deepcopy(sample)
                packet["seq"], packet["device_us"] = i, i*10000
                if fault and i == 300:
                    packet["sensor"] = fma.decode(word(2, 8192))
                stream.write(json.dumps({"host_elapsed_s": i*.01, "raw_line": json.dumps(packet),
                                         "decoded": {"available": True, "raw_force_counts": 123456}})+"\n")
            if complete:
                stream.write(json.dumps({"type": "record_end", "complete_duration": True, "duration_s": 6.5})+"\n")
        manifest = {"schema": "yam-fb1-force-trials/1", "evidence_kind": "physical", "phase": "train",
                    "specimen": header["specimen"], "session_id": header["session_id"],
                    "geometry_sha256": header["geometry_sha256"], "reference_id": "SOFTWARE_TEST_REFERENCE",
                    "reference_uncertainty_n": .01, "minimum_holds_per_level": 3,
                    "trials": [{"id": "software_fixture", "region": "left_nail", "condition_id": "software_hold",
                                "recording": recording.name, "recording_sha256": hashlib.sha256(recording.read_bytes()).hexdigest(),
                                "window_host_s": [2, 5], "reference_before_n": 12.5, "reference_after_n": 12.5}]}
        path = base / "trials.json"; path.write_text(json.dumps(manifest))
        return path

    def test_reader_redecodes_raw_and_ignores_saved_predictions(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, rows = force.load_trials(self.fixture(Path(temporary)), "train")
        self.assertTrue(rows[0]["available"], rows[0]["faults"])
        self.assertEqual(rows[0]["mean_counts"], 8192)
        self.assertEqual(rows[0]["samples"], 301)

    def test_stale_sample_and_interrupted_recording_cannot_pass(self):
        for fault, complete, expected in ((True, True, "sensor_stale_data"), (False, False, "incomplete_recording")):
            with tempfile.TemporaryDirectory() as temporary:
                _, rows = force.load_trials(self.fixture(Path(temporary), fault, complete), "train")
            self.assertFalse(rows[0]["available"])
            self.assertIn(expected, rows[0]["faults"])

    def test_coverage_counts_holds_not_frames(self):
        rows = [{"reference_n": value, "available": True, "samples": 10000} for value in force.LEVELS]
        _, complete = force.coverage(rows, 3)
        self.assertFalse(complete)
        with self.assertRaises(ValueError):
            force.load_trials(ROOT / "engineering/templates/force_button_force_trials.json", "train")

    def test_nominal_twenty_newton_label_cannot_qualify_a_lower_actual_load(self):
        rows = [{"reference_n": value, "available": True} for value in force.LEVELS for _ in range(3)]
        self.assertTrue(force.coverage(rows, 3)[1])
        for row in rows:
            if row["reference_n"] == 20:
                row["reference_n"] = 19.8
        coverage, passed = force.coverage(rows, 3)
        self.assertFalse(passed)
        self.assertEqual(coverage[-1]["independent_holds"], 0)


if __name__ == "__main__":
    unittest.main()
