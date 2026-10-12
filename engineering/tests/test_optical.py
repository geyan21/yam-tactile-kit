"""Synthetic image/electronics checks only; these are not physical O1 results."""

import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"engineering/software"))
from optical_core import establish_reference, observe, pgm_bytes, read_pgm, nail_signals, metadata_faults, validate_config
from optical_adc import conversion


DETECTION = {"threshold": 80, "area_min_px": 8, "area_max_px": 80, "minimum_contrast": 30,
             "expected_markers": 6, "maximum_motion_px": 10, "area_ratio_min": .4, "area_ratio_max": 2.5,
             "maximum_clipped_fraction": .1}


def image(dx=0, dy=0, missing=False, bright=190):
    width, height = 100, 75
    pixels = bytearray([bright])*(width*height)
    for i, (cx, cy) in enumerate(((20, 20), (50, 20), (80, 20), (20, 55), (50, 55), (80, 55))):
        if missing and i == 2:
            continue
        for y in range(height):
            for x in range(width):
                if (x-cx-dx)**2+(y-cy-dy)**2 <= 9:
                    pixels[y*width+x] = 20
    return width, height, bytes(pixels)


def camera_config():
    return json.loads((ROOT/"engineering/templates/optical_camera.json").read_text())


def metadata():
    return {"SensorTimestamp": 1000000000, "ExposureTime": 6000, "AnalogueGain": 1.,
            "LensPosition": 10., "ColourGains": [1., 1.], "FrameDuration": 100000}


class OpticalMarkerChecks(unittest.TestCase):
    def setUp(self):
        self.ref = {"detection": DETECTION, "markers": establish_reference(image(), DETECTION)}

    def test_known_translation_and_area_are_recovered(self):
        result = observe(image(2, -1), self.ref)
        self.assertTrue(result["available"], result["faults"])
        for row in result["markers"]:
            self.assertAlmostEqual(row["dx"], 2)
            self.assertAlmostEqual(row["dy"], -1)
            self.assertAlmostEqual(row["log_area_ratio"], 0)

    def test_missing_marker_is_unavailable_not_zero_force(self):
        result = observe(image(missing=True), self.ref)
        self.assertFalse(result["available"])
        self.assertIn("marker_count_changed", result["faults"])
        self.assertIsNone(result["features"])

    def test_outside_reference_motion_is_not_extrapolated(self):
        result = observe(image(dx=11), self.ref)
        self.assertFalse(result["available"])
        self.assertIn("marker_outside_reference_search", result["faults"])

    def test_clipped_image_is_not_accepted(self):
        self.assertIn("image_saturated", observe(image(bright=255), self.ref)["faults"])

    def test_incomplete_baseline_is_refused(self):
        with self.assertRaises(ValueError):
            establish_reference(image(missing=True), DETECTION)

    def test_lossless_image_length_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"test.pgm"
            path.write_bytes(pgm_bytes(*image()))
            self.assertEqual(read_pgm(path), image())
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                read_pgm(path)


class OpticalRawChecks(unittest.TestCase):
    def test_nail_continuity_and_signed_headroom(self):
        count = lambda volts: round(volts*32768/4.096)
        no_contact = nail_signals([count(.3), count(.3), count(3.3)])
        self.assertTrue(no_contact["available"])
        self.assertAlmostEqual(no_contact["signals"][0], 10, places=2)
        self.assertFalse(nail_signals([0, count(.3), count(3.3)])["available"])
        self.assertFalse(nail_signals([count(3.25), count(.3), count(3.3)])["available"])
        self.assertFalse(nail_signals([-5, count(.3), count(3.3)])["available"])

    def test_adc_mux_readback_and_twos_complement(self):
        class Bus:
            def write(self, register, value):
                self.config = value
            def read(self, register):
                return self.config if register == 1 else 65531
        self.assertEqual(conversion(Bus(), 1), -5)
        class Wrong(Bus):
            def read(self, register):
                return self.config ^ 0x1000
        with self.assertRaises(OSError):
            conversion(Wrong(), 1)

    def test_adc_timeout_is_bounded(self):
        class Bus:
            def write(self, register, value):
                self.config = value
            def read(self, register):
                return self.config & 0x7fff
        now = [0.]
        def clock():
            now[0] += .005
            return now[0]
        with self.assertRaises(TimeoutError):
            conversion(Bus(), 0, clock=clock, sleep=lambda _: None)

    def test_fixed_settings_and_freshness(self):
        cfg, meta = camera_config(), metadata()
        self.assertEqual(metadata_faults(meta, cfg, 1050000000), [])
        self.assertIn("camera_frame_age", metadata_faults(meta, cfg, 1300000000))
        self.assertIn("camera_timestamp_not_increasing", metadata_faults(meta, cfg, 1050000000, 1000000000))
        meta["LensPosition"] = 7.
        self.assertIn("camera_control_changed_LensPosition", metadata_faults(meta, cfg, 1050000000))

    def test_bad_roi_and_nonfinite_controls_are_rejected(self):
        cfg = camera_config()
        cfg["save_roi"] = [0, 0, 9999, 20]
        with self.assertRaises(ValueError):
            validate_config(cfg)
        cfg = camera_config(); cfg["analogue_gain"] = math.nan
        with self.assertRaises(ValueError):
            validate_config(cfg)


if __name__ == "__main__":
    unittest.main()
