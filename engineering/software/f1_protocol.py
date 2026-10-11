"""Validate F1 stream structure without turning raw counts into force evidence."""

import importlib.util
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("f1_scan_configuration", ROOT / "engineering/firmware/f1/scan.py")
scan_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan_config)

PROTOCOL = "yam-f1-raw-stream/1"


def integer(value, name, low=0, high=2**63-1):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid "+name)
    return value


class FrameAssembler:
    def __init__(self):
        self.config = None
        self.active = None
        self.expected_frame = None
        self.announced_frame = None
        self.epoch = 0
        self.complete_frames = 0
        self.incomplete_frames = 0
        self.next_flags = []

    def invalidate(self, reason):
        if self.active is not None:
            self.active["flags"].append(reason)

    def phase(self, data):
        if not isinstance(data, dict):
            raise ValueError("Phase is not a record")
        times, codes = data.get("time_us"), data.get("codes")
        count = self.config["samples_per_phase"]
        if not isinstance(times, list) or not isinstance(codes, list) or len(times) != count or len(codes) != count:
            raise ValueError("Phase does not contain the declared raw samples")
        for stamp, code in zip(times, codes):
            integer(stamp, "sample time")
            integer(code, "ADC code", high=65535)
            if stamp <= self.active["last_sample_us"]:
                raise ValueError("Sample times are stale, repeated or reversed")
            self.active["last_sample_us"] = stamp
        return codes

    def accept(self, message):
        if not isinstance(message, dict):
            raise ValueError("Device message is not an object")
        kind = message.get("kind")
        if kind == "hello":
            if message.get("schema") != PROTOCOL or message.get("sensor_only") is not True:
                raise ValueError("Unexpected device protocol")
            if message.get("force_calibration_loaded") is not False or message.get("fault_check_qualified") is not False:
                raise ValueError("This decoder does not accept unreviewed calibration/qualification claims")
            config = scan_config.checked_config(message["configuration"])
            frame = integer(message.get("next_frame"), "announced frame")
            flags = []
            if self.active is not None:
                self.incomplete_frames += 1
                flags.append("previous_frame_incomplete")
                self.active = None
            if self.expected_frame is not None and frame != self.expected_frame:
                self.epoch += 1
                flags.append("device_restart_or_frame_gap")
            self.config, self.announced_frame = config, frame
            self.next_flags = flags
            return {"accepted": True, "kind": kind, "epoch": self.epoch, "flags": flags}
        if self.config is None:
            return {"accepted": False, "kind": kind, "flags": ["waiting_for_configuration"]}
        if kind == "error":
            self.invalidate("firmware_error")
            return {"accepted": False, "kind": kind, "flags": ["firmware_error"]}
        frame = integer(message.get("frame"), "frame")
        if kind == "frame_begin":
            if frame != self.announced_frame or self.active is not None:
                raise ValueError("Frame did not follow its configuration announcement")
            if message.get("expected_pixels") != 64 or message.get("expected_column_checks") != 16:
                raise ValueError("Unexpected matrix dimensions")
            started = integer(message.get("time_us"), "frame start")
            self.active = {"frame": frame, "started": started, "last_sample_us": started-1,
                           "pixels": set(), "checks": set(), "monitor": False, "flags": list(self.next_flags)}
            return {"accepted": True, "kind": kind, "frame": frame, "epoch": self.epoch, "flags": self.next_flags}
        active = self.active
        if active is None or frame != active["frame"]:
            raise ValueError("Message is outside its declared frame")
        if kind == "monitor":
            codes = message.get("codes")
            if active["monitor"] or not isinstance(codes, list) or len(codes) != 8:
                raise ValueError("Missing/duplicate monitor block")
            if message.get("remote_row_voltage_measurement") is not False:
                raise ValueError("Coarse local monitors were mislabeled as remote voltages")
            for code in codes:
                integer(code, "monitor code", high=4095)
            active["monitor"] = True
        elif kind == "column_link_check":
            column = integer(message.get("column"), "column", high=15)
            if column in active["checks"] or message.get("gain") != 1:
                raise ValueError("Duplicate column check or unsupported test gain")
            if message.get("tactile_observation") is not False or message.get("qualified_fault_coverage") is not False:
                raise ValueError("Electrical test was mislabeled as tactile or qualified evidence")
            baseline = self.phase(message.get("baseline"))
            test = self.phase(message.get("test_enabled"))
            drop = (sum(baseline)/len(baseline)-sum(test)/len(test))*self.config["nominal_reference_v"]/65536
            claimed = message.get("nominal_drop_v")
            # Permit normal MCU JSON/float rounding; raw ADC words remain
            # the authoritative quantity, not this displayed voltage.
            if type(claimed) not in (int, float) or not math.isfinite(claimed) or abs(claimed-drop) > 1e-5:
                raise ValueError("Reported voltage drop differs from raw counts")
            low, high = self.config["development_link_drop_window_v"]
            inside = low <= drop <= high
            if message.get("inside_development_window") is not inside:
                raise ValueError("Reported test-window result differs from raw counts")
            if not inside:
                active["flags"].append("column_test_outside_development_window:"+str(column))
            active["checks"].add(column)
        elif kind == "pixel":
            row = integer(message.get("row"), "row", high=3)
            column = integer(message.get("column"), "column", high=15)
            gain = integer(message.get("gain"), "gain", high=3)
            if (row, column) in active["pixels"]:
                raise ValueError("Duplicate matrix position")
            if gain != self.config["gain_ids"][row*16+column]:
                raise ValueError("Pixel gain differs from announced configuration")
            if message.get("force_n") is not None or message.get("contact") is not None:
                raise ValueError("Raw stream must not invent force/contact calibration")
            baseline = self.phase(message.get("baseline"))
            measured = self.phase(message.get("active"))
            low, high = self.config["development_headroom_codes"]
            inside = all(low <= code <= high for code in baseline+measured)
            if message.get("inside_development_headroom") is not inside:
                raise ValueError("Reported headroom differs from raw counts")
            if not inside:
                active["flags"].append("pixel_outside_development_headroom:"+str(row)+","+str(column))
            active["pixels"].add((row, column))
        elif kind == "frame_end":
            ended = integer(message.get("time_us"), "frame end")
            integer(message.get("elapsed_us"), "frame duration")
            if ended < active["last_sample_us"] or message.get("physical_force_calibration") is not False:
                raise ValueError("Invalid frame end time or calibration claim")
            complete = len(active["pixels"]) == 64 and len(active["checks"]) == 16 and active["monitor"]
            if message.get("pixels") != 64 or message.get("column_checks") != 16 or not complete:
                self.incomplete_frames += 1
                active["flags"].append("incomplete_matrix_frame")
            else:
                self.complete_frames += 1
            result = {"accepted": complete, "kind": kind, "frame": frame, "epoch": self.epoch,
                      "complete": complete, "pixels": len(active["pixels"]), "column_checks": len(active["checks"]),
                      "flags": active["flags"], "force_calibrated": False,
                      "physical_force_accuracy_established": False}
            self.active = None
            self.expected_frame = frame+1
            return result
        else:
            raise ValueError("Unknown device message kind")
        return {"accepted": True, "kind": kind, "frame": frame, "epoch": self.epoch, "flags": []}

    def finish(self):
        if self.active is not None:
            self.incomplete_frames += 1
            self.active = None
        return {"complete_frames": self.complete_frames, "incomplete_frames": self.incomplete_frames,
                "force_calibrated": False}
