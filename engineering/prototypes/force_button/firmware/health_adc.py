"""FB1 ADS1115: remote supply/return, local supply and ground reference.

Register acquisition is shared with the reviewed K1 implementation. Inputs,
channel meaning and acceptance checks are specific to FB1.
"""


def configuration(channel):
    if type(channel) is not int or not 0 <= channel <= 3:
        raise ValueError("ADS1115 channel must be 0..3")
    return 0x8000 | ((4+channel) << 12) | 0x0200 | 0x0100 | 0x00E0 | 0x0003


class HealthADC:
    def __init__(self, bus):
        self.bus = bus
        self.requested = None
        self.observed = None

    def word(self, register):
        data = self.bus.readfrom_mem(0x48, register, 2)
        if len(data) != 2:
            raise OSError("Incomplete health ADC word")
        return (data[0] << 8) | data[1]

    def start(self, channel):
        self.requested = None
        self.observed = None
        value = configuration(channel)
        self.bus.writeto_mem(0x48, 1, bytes((value >> 8, value & 255)))
        self.requested = value

    def ready(self):
        if self.requested is None:
            raise OSError("No health conversion")
        value = self.word(1)
        if (value & 0x7FFF) != (self.requested & 0x7FFF):
            self.requested = None
            raise OSError("Health ADC configuration changed")
        self.observed = value
        return bool(value & 0x8000)

    def result(self):
        if self.observed is None or not self.observed & 0x8000:
            raise OSError("Health result before ready")
        try:
            value = self.word(0)
            return {"raw": value-65536 if value & 32768 else value,
                    "configuration": self.observed}
        finally:
            self.requested = None
            self.observed = None
