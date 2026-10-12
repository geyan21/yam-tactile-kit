"""Decode the P1 raw stream without inferring calibrated force or contact."""

import hashlib
import json
from pathlib import Path

PROTOCOL = "yam-p1-raw/1"
CONFIG = json.loads((Path(__file__).resolve().parents[1]/"firmware/pneumatic/config.json").read_text())
PA_PER_IN_H2O = 249.088  # Conventional 4 °C conversion; nominal pressure display only.
RANGE_PA = 30*PA_PER_IN_H2O
LOW_CODE, HIGH_CODE = 2731, 24576


def config_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid "+name)
    return value


def nominal_pressure_pa(count):
    return ((count-LOW_CODE)/(HIGH_CODE-LOW_CODE)*2-1)*RANGE_PA


class Decoder:
    def __init__(self):
        self.hello = None
        self.last_sequence = self.last_time = None
        self.pending_faults = []
        self.boots = set()
        self.sample_count = self.unavailable_count = 0

    def invalidate(self, reason):
        self.pending_faults.append(reason)

    def accept(self, packet):
        if not isinstance(packet, dict) or packet.get("protocol") != PROTOCOL:
            raise ValueError("Not a P1 packet")
        boot = packet.get("boot_id")
        if not isinstance(boot, str) or not 12 <= len(boot) <= 80 or any(c not in "0123456789abcdef-" for c in boot):
            raise ValueError("Missing P1 boot identity")
        if packet.get("type") == "hello":
            if (config_hash(packet.get("config")) != config_hash(CONFIG)
                    or packet.get("source") != "rp2040_i2c" or packet.get("synthetic") is not False
                    or packet.get("adc_lsb_v") != .000125 or packet.get("pressure_order") != [2, 3, 4, 5]
                    or packet.get("adc_order") != ["NAIL0", "NAIL1", "3V0", "3V3"]
                    or packet.get("force_calibrated") is not False
                    or packet.get("pressure_calibrated") is not False):
                raise ValueError("Unreviewed P1 acquisition identity")
            device = packet.get("device_id")
            if not isinstance(device, str) or not device or not boot.startswith(device+"-"):
                raise ValueError("P1 device/boot identity mismatch")
            restarted = self.hello is not None and self.hello["boot_id"] != boot
            if self.hello is not None and not restarted and packet != self.hello:
                raise ValueError("P1 configuration changed within one boot")
            if self.hello is None or restarted:
                self.last_sequence = self.last_time = None
            if restarted:
                self.invalidate("device_restarted")
            self.hello = packet
            self.boots.add(boot)
            return {"type": "hello", "boot_id": boot, "restarted": restarted,
                    "configuration_sha256": config_hash(packet["config"])}
        if packet.get("type") != "sample" or self.hello is None or boot != self.hello["boot_id"]:
            raise ValueError("A matching P1 hello must precede samples")
        seq = integer(packet.get("seq"), 0, 2**63-1, "sequence")
        timestamp = integer(packet.get("device_us"), 0, 2**63-1, "device time")
        span = integer(packet.get("scan_us"), 1, 500000, "scan duration")
        if self.last_sequence is not None and (seq <= self.last_sequence or timestamp <= self.last_time):
            raise ValueError("Repeated or out-of-order P1 frame")
        faults = list(self.pending_faults)
        if self.last_sequence is not None and (seq != self.last_sequence+1 or timestamp-self.last_time > 100000):
            faults.append("acquisition_gap")
        if span > 100000:
            faults.append("slow_scan")
        errors = packet.get("errors")
        if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
            raise ValueError("Missing P1 acquisition error list")
        if errors:
            faults.append("acquisition_error")
        pressure, adc, offsets = (packet.get(name) for name in ("pressure_raw", "adc_raw", "offset_us"))
        if not all(isinstance(items, list) and len(items) == n for items, n in ((pressure, 4), (adc, 4), (offsets, 8))):
            raise ValueError("P1 needs four pressure and four ADC readings")
        raw = pressure+adc
        last_offset = -1
        for index, (value, offset) in enumerate(zip(raw, offsets)):
            if value is None or offset is None:
                faults.append("missing_measurement")
                continue
            integer(value, 0 if index < 4 else -32768, 32767, "raw conversion")
            integer(offset, 0, span, "sample offset")
            if offset <= last_offset:
                faults.append("sample_order")
            last_offset = offset
        volts = [v*.000125 if v is not None else None for v in adc]
        if volts[2] is None or not 2.85 <= volts[2] <= 3.15:
            faults.append("pressure_supply")
        if volts[3] is None or not 3.13 <= volts[3] <= 3.47:
            faults.append("logic_supply")
        features, cells = [], []
        for index in range(2):
            reasons = list(faults)
            ratio = (volts[index]/volts[3] if volts[index] is not None and volts[3] is not None and volts[3] > 0 else None)
            if ratio is None or not .035 < ratio < .985:
                reasons.append("nail_continuity_or_headroom")
            conductance = None if ratio is None or not 0 <= ratio < 1 else (
                ratio/(CONFIG["nail_pull_down_ohm"][index]*(1-ratio))-1/CONFIG["nail_continuity_ohm"])*1e6
            features.append(conductance)
            cells.append({"site": "CH"+str(index), "available": not reasons, "faults": sorted(set(reasons)),
                          "apparent_conductance_us": conductance, "force_n": None, "contact": None})
        for index, count in enumerate(pressure):
            reasons = list(faults)
            if count is None or not LOW_CODE+219 <= count <= HIGH_CODE-219:
                reasons.append("nominal_pressure_headroom")
            pressure_pa = nominal_pressure_pa(count) if count is not None else None
            features.append(pressure_pa)
            cells.append({"site": "CH"+str(index+2), "available": not reasons, "faults": sorted(set(reasons)),
                          "differential_pressure_nominal_pa": pressure_pa, "force_n": None, "contact": None})
        available = all(cell["available"] for cell in cells)
        self.last_sequence, self.last_time = seq, timestamp
        self.pending_faults = []
        self.sample_count += 1
        self.unavailable_count += not available
        return {"type": "sample", "protocol": PROTOCOL, "seq": seq, "device_us": timestamp,
                "boot_id": boot, "scan_us": span, "cells": cells,
                "supply_v": {"pressure": volts[2], "logic": volts[3]},
                "signals": features, "complete_finger_available": available,
                "force_n": None, "contact": None,
                "scope": "Raw acquisition and coarse electrical checks only. Nominal pressure is not pressure or force calibration."}

    def finish(self):
        return {"samples": self.sample_count, "unavailable_samples": self.unavailable_count,
                "boots": sorted(self.boots), "configuration_sha256": config_hash(CONFIG),
                "device_id": self.hello.get("device_id") if self.hello else None}
