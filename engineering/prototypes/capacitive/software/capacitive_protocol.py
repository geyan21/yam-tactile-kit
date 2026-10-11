"""K1 raw decoding with acquisition, supply and ground-return checks."""

PROTOCOL = "yam-k1/2"
TIMING = {"rate_sps": 400, "bus_hz": 400000, "quiet_us": 3000,
          "conversion_timeout_us": 15000, "minimum_frame_us": 20000, "hello_period_frames": 50}
BANK_SITES = ((0, 2, 3), (1, 4, 5))
MEASURE = (0x0C00, 0x2C00, 0x4C00, 0x7C00)


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid "+name)
    return value


class Decoder:
    def __init__(self):
        self.startup = None
        self.last_sequence = None
        self.last_time = None
        self.boot_id = None
        self.restarted = False

    def accept(self, packet):
        if not isinstance(packet, dict) or packet.get("protocol") != PROTOCOL:
            raise ValueError("Not a K1 packet")
        boot = packet.get("boot_id")
        if not isinstance(boot, str) or not 12 <= len(boot) <= 80 or any(c not in "0123456789abcdef-" for c in boot):
            raise ValueError("Missing K1 boot identity")
        if packet.get("type") == "hello":
            if (packet.get("rate_sps") != 400 or packet.get("capdac_enabled") is not False
                    or packet.get("raw_pF_divisor") != 524288 or packet.get("health_lsb_v") != .000125
                    or packet.get("force_calibrated") is not False or packet.get("contact_calibrated") is not False
                    or packet.get("timing") != TIMING):
                raise ValueError("Unreviewed K1 acquisition configuration")
            identity = packet.get("banks")
            if not isinstance(identity, list) or len(identity) != 2 or [b.get("sites") for b in identity] != [list(s) for s in BANK_SITES]:
                raise ValueError("Wrong K1 site allocation")
            for i, bank in enumerate(identity):
                for key, expected in (("bank", i), ("i2c_id", i), ("sda_gpio", 2*i), ("scl_gpio", 2*i+1)):
                    if type(bank.get(key)) is not int or bank[key] != expected:
                        raise ValueError("Wrong K1 bus identity")
            startup = packet.get("startup")
            if not isinstance(startup, list) or len(startup) != 2 or [r.get("bank") for r in startup] != [0, 1]:
                raise ValueError("Missing K1 startup identities")
            for row in startup:
                if type(row.get("ready")) is not bool:
                    raise ValueError("Missing startup state")
                words = row.get("calibration_words")
                if row["ready"]:
                    if not isinstance(words, list) or len(words) != 8:
                        raise ValueError("Missing converter calibration identity")
                    for value in words:
                        integer(value, 0, 65535, "calibration word")
                    if any(value == 0 for value in words[4:]):
                        raise ValueError("Degenerate converter gain")
            observed_startup = [{"bank": row["bank"], "ready": row["ready"],
                             "calibration_words": list(row["calibration_words"]) if row["calibration_words"] is not None else None}
                            for row in startup]
            restarted = self.boot_id is not None and self.boot_id != boot
            if self.boot_id == boot:
                if self.startup != observed_startup:
                    raise ValueError("K1 startup identity changed without a new boot")
            else:
                self.startup = observed_startup
                self.last_sequence = self.last_time = None
                self.restarted = restarted
                self.boot_id = boot
            return {"type": "hello", "protocol": PROTOCOL, "boot_id": boot, "restarted": restarted, "raw": packet}
        if packet.get("type") != "sample" or self.startup is None or boot != self.boot_id:
            raise ValueError("A K1 hello must precede samples")
        seq = integer(packet.get("seq"), 0, 2**63-1, "sequence")
        timestamp = integer(packet.get("device_us"), 0, 2**63-1, "timestamp")
        span = integer(packet.get("scan_us"), 1, 500000, "scan duration")
        if self.last_sequence is not None and (seq <= self.last_sequence or timestamp <= self.last_time):
            raise ValueError("Repeated or out-of-order K1 sample")
        gap = self.last_sequence is not None and (seq != self.last_sequence+1 or timestamp-self.last_time > 100000)
        banks = packet.get("banks")
        if not isinstance(banks, list) or len(banks) != 2 or [b.get("bank") for b in banks] != [0, 1]:
            raise ValueError("A K1 frame needs both bank identities")
        cells, reports = [], []
        for index, bank in enumerate(banks):
            reasons = []
            if not isinstance(bank.get("errors"), list):
                raise ValueError("Missing acquisition error field")
            if bank["errors"]:
                reasons.append("acquisition_error")
            initial = self.startup[index]
            if initial.get("ready") is not True or bank.get("calibration_words") != initial.get("calibration_words"):
                reasons.append("startup_or_calibration_changed")
            capacitance, volts = [], []
            for slot in range(4):
                for key in ("fdc", "health", "fdc_us", "health_us"):
                    if not isinstance(bank.get(key), list) or len(bank[key]) != 4:
                        raise ValueError("Incomplete K1 bank layout")
                result, health = bank["fdc"][slot], bank["health"][slot]
                if result is None or health is None:
                    reasons.append("missing_measurement")
                    capacitance.append(None); volts.append(None)
                    continue
                if not isinstance(result, dict) or not isinstance(health, dict):
                    raise ValueError("Invalid conversion record")
                when = integer(bank["fdc_us"][slot], 0, span, "FDC sample offset")
                integer(bank["health_us"][slot], 0, span, "health sample offset")
                if slot and bank["fdc_us"][slot-1] is not None and when <= bank["fdc_us"][slot-1]:
                    reasons.append("sample_order")
                raw = integer(result.get("raw"), -(1 << 23), (1 << 23)-1, "FDC raw result")
                msb = integer(result.get("msb"), 0, 65535, "FDC MSB")
                lsb = integer(result.get("lsb"), 0, 65535, "FDC LSB")
                encoded = ((msb << 8) | (lsb >> 8))
                encoded -= (1 << 24) if encoded & (1 << 23) else 0
                status = integer(result.get("observed_fdc_config"), 0, 65535, "FDC status")
                if (lsb & 255 or encoded != raw or type(result.get("slot")) is not int or result["slot"] != slot
                        or result.get("measurement_config") != MEASURE[slot]
                        or status & 0xF300 or (status & 0x0C00) != 0x0C00
                        or not status & (8 >> slot) or (status & 0xF0) not in (0, 0x80 >> slot)):
                    reasons.append("converter_configuration_or_data")
                cp = raw/524288.0
                if abs(cp) >= 14.9:
                    reasons.append("capacitance_headroom")
                capacitance.append(cp)
                counts = integer(health.get("raw"), -32768, 32767, "health ADC raw result")
                word = integer(health.get("configuration"), 0, 65535, "health ADC configuration")
                expected = 0x8000 | ((4+slot) << 12) | 0x0200 | 0x0100 | 0x00E0 | 0x0003
                if word != expected:
                    reasons.append("health_configuration")
                volts.append(counts*.000125)
            if volts[0] is None or not 3.05 <= volts[0] <= 3.55:
                reasons.append("supply")
            reference = capacitance[3]
            if reference is None or not 1.0 <= reference <= 14.0:
                reasons.append("reference_unavailable")
            if gap:
                reasons.append("acquisition_gap")
            if self.restarted:
                reasons.append("device_restarted")
            for slot, site in enumerate(BANK_SITES[index]):
                faults = list(reasons)
                if volts[slot+1] is None or abs(volts[slot+1]) > .005:
                    faults.append("ground_return")
                absolute = None if capacitance[slot] is None or reference is None else capacitance[slot]+reference
                if absolute is None or absolute < 1.0:
                    faults.append("capacitance_plausibility")
                cells.append({"site": "CH"+str(site), "bank": index, "slot": slot,
                              "available": not faults, "faults": sorted(set(faults)),
                              "differential_pf": capacitance[slot], "reference_pf": reference,
                              "sequential_reconstructed_pf": absolute,
                              "fdc_offset_us": bank["fdc_us"][slot],
                              "reference_offset_us": bank["fdc_us"][3],
                              "ground_return_v": volts[slot+1],
                              "contact": None, "force_n": None})
            reports.append({"bank": index, "supply_v": volts[0], "faults": sorted(set(reasons))})
        self.last_sequence, self.last_time = seq, timestamp
        self.restarted = False
        return {"type": "sample", "protocol": PROTOCOL, "seq": seq, "device_us": timestamp,
                "boot_id": boot,
                "scan_us": span, "cells": sorted(cells, key=lambda c: c["site"]), "banks": reports,
                "complete_finger_available": all(c["available"] for c in cells),
                "availability_scope": "Acquisition/configuration, supply/ground loops and coarse capacitance plausibility; no tactile qualification",
                "force_n": None, "raw": packet}
