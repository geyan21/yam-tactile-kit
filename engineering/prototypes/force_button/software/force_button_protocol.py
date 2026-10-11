"""FB1 raw-data checks, without implying installed-force calibration."""

PROTOCOL = "yam-fb1/1"
PART = "FMAMSDXX025WC2C3"
SETTINGS = {"protocol": PROTOCOL, "part": PART, "i2c_id": 0, "sda_gpio": 4, "scl_gpio": 5,
            "bus_hz": 100000, "sensor_address": 40, "health_address": 72,
            "minimum_frame_us": 10000, "health_timeout_us": 6000, "hello_period_frames": 100}


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid "+name)
    return value


class Decoder:
    def __init__(self):
        self.boot_id = None
        self.last_sequence = self.last_time = None
        self.restarted = False

    def accept(self, packet):
        if not isinstance(packet, dict) or packet.get("protocol") != PROTOCOL:
            raise ValueError("Not an FB1 packet")
        boot = packet.get("boot_id")
        if not isinstance(boot, str) or not 12 <= len(boot) <= 80 or any(c not in "0123456789abcdef-" for c in boot):
            raise ValueError("Missing FB1 boot identity")
        if packet.get("type") == "hello":
            if (packet.get("configuration") != SETTINGS or packet.get("health_lsb_v") != .000125
                    or packet.get("force_calibrated") is not False or packet.get("contact_calibrated") is not False):
                raise ValueError("Unreviewed FB1 acquisition settings")
            restarted = self.boot_id is not None and self.boot_id != boot
            if self.boot_id != boot:
                self.last_sequence = self.last_time = None
                self.restarted = restarted
            self.boot_id = boot
            return {"type": "hello", "protocol": PROTOCOL, "boot_id": boot, "restarted": restarted}
        if packet.get("type") != "sample" or self.boot_id is None or boot != self.boot_id:
            raise ValueError("A matching FB1 hello must precede samples")
        seq = integer(packet.get("seq"), 0, 2**63-1, "sequence")
        timestamp = integer(packet.get("device_us"), 0, 2**63-1, "device time")
        duration = integer(packet.get("scan_us"), 1, 100000, "scan duration")
        if self.last_sequence is not None and (seq <= self.last_sequence or timestamp <= self.last_time):
            raise ValueError("Repeated or out-of-order FB1 sample")
        faults = []
        if self.last_sequence is not None and (seq != self.last_sequence+1 or timestamp-self.last_time > 50000):
            faults.append("acquisition_gap")
        if self.restarted:
            faults.append("device_restarted")
        if not isinstance(packet.get("errors"), list) or any(not isinstance(v, str) for v in packet["errors"]):
            raise ValueError("Missing acquisition error field")
        if packet["errors"]:
            faults.append("acquisition_error")
        if not isinstance(packet.get("health"), list) or len(packet["health"]) != 4:
            raise ValueError("Four health channels required")
        if not isinstance(packet.get("health_us"), list) or len(packet["health_us"]) != 4:
            raise ValueError("Four health timestamps required")
        volts, previous = [], -1
        for channel, item in enumerate(packet["health"]):
            if item is None:
                volts.append(None); faults.append("missing_health")
                continue
            if not isinstance(item, dict):
                raise ValueError("Invalid health result")
            when = integer(packet["health_us"][channel], 0, duration, "health time")
            if when <= previous:
                faults.append("health_sample_order")
            previous = when
            raw = integer(item.get("raw"), -32768, 32767, "health counts")
            conf = integer(item.get("configuration"), 0, 65535, "health configuration")
            expected = 0x8000 | ((4+channel) << 12) | 0x0200 | 0x0100 | 0x00E0 | 0x0003
            if conf != expected:
                faults.append("health_configuration")
            volts.append(raw*.000125)
        effective = None if volts[0] is None or volts[1] is None else volts[0]-volts[1]
        if effective is None or not 3.05 <= effective <= 3.55:
            faults.append("remote_supply")
        if volts[1] is None or abs(volts[1]) > .005:
            faults.append("ground_return")
        if volts[2] is None or not 3.05 <= volts[2] <= 3.55:
            faults.append("controller_supply")
        if volts[3] is None or abs(volts[3]) > .005:
            faults.append("ground_reference")
        counts = status = nominal = None
        result = packet.get("sensor")
        if result is None:
            faults.append("missing_sensor")
        elif not isinstance(result, dict):
            raise ValueError("Invalid sensor result")
        else:
            status = integer(result.get("status"), 0, 3, "FMA status")
            counts = integer(result.get("raw_force_counts"), 0, 16383, "FMA counts")
            names = ("new_data", "command_mode", "stale_data", "diagnostic")
            if (result.get("status_name") != names[status] or result.get("fresh") is not (status == 0)
                    or result.get("whole_finger_force_n") is not None):
                raise ValueError("Inconsistent FMA decoding")
            when = integer(packet.get("sensor_us"), 0, duration, "sensor time")
            if when <= previous:
                faults.append("sensor_sample_order")
            if status:
                faults.append("sensor_"+names[status])
            else:
                nominal = ((counts/16384.0-.2)/.6)*25
                if not .2*16384 <= counts <= .8*16384:
                    faults.append("sensor_outside_catalog_span")
        self.last_sequence, self.last_time, self.restarted = seq, timestamp, False
        return {"type": "sample", "protocol": PROTOCOL, "boot_id": boot, "seq": seq, "device_us": timestamp,
                "scan_us": duration, "available": not faults, "faults": sorted(set(faults)),
                "raw_force_counts": counts, "status": status, "factory_nominal_sensor_n": nominal,
                "remote_supply_v": effective, "ground_return_v": volts[1], "health_volts": volts,
                "whole_finger_force_n": None, "contact": None,
                "scope": "Raw FMA acquisition and limited supply checks; not contact, force or mechanical qualification"}
