"""FB1 Honeywell FMAMSDXX025WC2C3: read-only force/status interface.

Source: Honeywell I2C communications 008291 and FMA data-sheet transfer C.
This is a nominal sensor conversion, not installed-finger calibration.
"""

PART = "FMAMSDXX025WC2C3"
ADDRESS = 0x28
FULL_SCALE_N = 25.0
COUNT_BASIS = 16384.0
STATUS = ("new_data", "command_mode", "stale_data", "diagnostic")


def decode(data):
    if not isinstance(data, (bytes, bytearray)) or len(data) != 2:
        raise ValueError("FMA requires exactly two force/status bytes")
    status = data[0] >> 6
    raw = ((data[0] & 0x3F) << 8) | data[1]
    fresh = status == 0
    nominal = ((raw/COUNT_BASIS-.2)/.6)*FULL_SCALE_N if fresh else None
    return {"status": status, "status_name": STATUS[status], "fresh": fresh,
            "raw_force_counts": raw,
            "factory_nominal_sensor_n": nominal,
            "within_nominal_catalog_span": bool(fresh and .2*COUNT_BASIS <= raw <= .8*COUNT_BASIS),
            "whole_finger_force_n": None}


class FMA:
    def __init__(self, bus, address=ADDRESS):
        if type(address) is not int or address != ADDRESS:
            raise ValueError("The selected FMA ordering code uses I2C address 0x28")
        self.bus = bus
        self.address = address

    def read(self):
        # No register pointer, configuration writes or command-mode entry.
        return decode(self.bus.readfrom(self.address, 2))
