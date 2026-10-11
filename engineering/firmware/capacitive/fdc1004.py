"""K1 FDC1004 single-shot access. Raw capacitance registers, never force.

Use TI SNOSCY5C register fields. The older application example 0x0540 has
REPEAT set; this driver constructs RATE/MEAS fields with REPEAT explicitly 0.
"""

ADDRESS = 0x50
MEASUREMENT_CONFIG = (0x0C00, 0x2C00, 0x4C00, 0x7C00)
RATE_BITS = {100: 0x0400, 200: 0x0800, 400: 0x0C00}


def signed24(msb, lsb):
    if type(msb) is not int or type(lsb) is not int or not 0 <= msb <= 65535 or not 0 <= lsb <= 65535:
        raise ValueError("FDC1004 register words must be unsigned 16-bit integers")
    if lsb & 255:
        raise OSError("FDC1004 reserved result bits are nonzero")
    value = (msb << 8) | (lsb >> 8)
    return value - (1 << 24) if value & (1 << 23) else value


def capacitance_pf(raw):
    if type(raw) is not int or not -(1 << 23) <= raw < (1 << 23):
        raise ValueError("FDC1004 result must be signed 24-bit")
    return raw / 524288.0


class FDC1004:
    def __init__(self, bus, address=ADDRESS):
        if address != ADDRESS:
            raise ValueError("FDC1004 has fixed address 0x50")
        self.bus = bus
        self.address = address
        self.configured = False
        self.requested = None
        self.observed = None
        self.rate_bits = None
        self.calibration_words = None

    def word(self, register):
        data = self.bus.readfrom_mem(self.address, register, 2)
        if len(data) != 2:
            raise OSError("Incomplete FDC1004 register")
        return (data[0] << 8) | data[1]

    def write(self, register, value):
        self.bus.writeto_mem(self.address, register, bytes((value >> 8, value & 255)))

    def identity(self):
        if self.word(0xFE) != 0x5449 or self.word(0xFF) != 0x1004:
            raise OSError("Wrong FDC1004 manufacturer/device identity")

    def begin_reset(self):
        self.configured = False
        self.requested = None
        self.observed = None
        self.identity()
        self.write(0x0C, 0x8000)

    def reset_ready(self):
        return not (self.word(0x0C) & 0x8000)

    def configure(self, rate=400):
        self.configured = False
        if type(rate) is not int or rate not in RATE_BITS:
            raise ValueError("FDC1004 supports 100, 200 or 400 SPS")
        self.identity()
        if not self.reset_ready():
            raise OSError("FDC1004 reset is still active")
        self.rate_bits = RATE_BITS[rate]
        self.write(0x0C, self.rate_bits)
        # Keep actual calibration words. Do not overwrite factory settings
        # or hide a changed gain/offset behind the nominal code-to-pF scale.
        self.calibration_words = tuple(self.word(register) for register in range(0x0D, 0x15))
        if any(value == 0 for value in self.calibration_words[4:]):
            raise OSError("Degenerate FDC1004 gain setting")
        for slot, value in enumerate(MEASUREMENT_CONFIG):
            self.write(0x08 + slot, value)
            if self.word(0x08 + slot) != value:
                raise OSError("FDC1004 measurement setup did not read back")
        self.requested = None
        self.observed = None
        self.configured = True

    def check_setup(self):
        if not self.configured:
            raise OSError("FDC1004 needs setup/restart")
        try:
            self.identity()
            if tuple(self.word(register) for register in range(0x0D, 0x15)) != self.calibration_words:
                raise OSError("FDC1004 calibration words changed")
            if tuple(self.word(0x08 + slot) for slot in range(4)) != MEASUREMENT_CONFIG:
                raise OSError("FDC1004 measurement configuration changed")
        except OSError:
            self.configured = False
            self.requested = None
            self.observed = None
            raise

    def start(self, slot):
        if type(slot) is not int or not 0 <= slot < 4:
            raise ValueError("FDC1004 measurement slot must be 0..3")
        if not self.configured or self.requested is not None:
            raise OSError("FDC1004 is unavailable or its prior conversion is unconsumed")
        self.observed = None
        try:
            if self.word(0x08 + slot) != MEASUREMENT_CONFIG[slot]:
                raise OSError("FDC1004 input/CAPDAC configuration changed")
            done = 0x08 >> slot
            # Reading both words is required to clear a previous result.
            if self.word(0x0C) & done:
                self.word(2 * slot)
                self.word(2 * slot + 1)
                if self.word(0x0C) & done:
                    raise OSError("FDC1004 stale DONE did not clear")
            self.write(0x0C, self.rate_bits | (0x80 >> slot))
            self.requested = slot
        except OSError:
            self.configured = False
            self.requested = None
            raise

    def ready(self):
        if not self.configured or self.requested is None:
            raise OSError("No available FDC1004 conversion")
        try:
            value = self.word(0x0C)
            mask = 0x80 >> self.requested
            if value & 0xF300 or (value & 0x0C00) != self.rate_bits or (value & 0xF0) not in (0, mask):
                raise OSError("FDC1004 rate, repetition or enabled measurement changed")
            self.observed = value
            return bool(value & (0x08 >> self.requested))
        except OSError:
            self.configured = False
            self.requested = None
            self.observed = None
            raise

    def result(self):
        slot = self.requested
        if not self.configured or slot is None or self.observed is None or not self.observed & (0x08 >> slot):
            raise OSError("FDC1004 result requested before fresh DONE")
        try:
            msb, lsb = self.word(2 * slot), self.word(2 * slot + 1)
            raw = signed24(msb, lsb)
            if self.word(0x0C) & (0x08 >> slot):
                raise OSError("FDC1004 DONE remained set after paired reads")
            return {"slot": slot, "raw": raw, "msb": msb, "lsb": lsb,
                    "measurement_config": MEASUREMENT_CONFIG[slot],
                    "observed_fdc_config": self.observed}
        except OSError:
            self.configured = False
            raise
        finally:
            self.requested = None
            self.observed = None

    def timed_out(self):
        # A reset is required before reusing this board. Never allow a late
        # conversion from an uncertain transaction to appear as a new sample.
        self.configured = False
        self.requested = None
        self.observed = None
