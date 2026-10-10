"""L1 bridge front end. MicroPython-compatible, with bounded initialization.

Register definitions: Nuvoton NAU7802 rev 1.7.
Initialization sequence cross-checked against SparkFun's NAU7802 library
at e15210f5b58f4c013239c65430dec74395961691 (MIT).
No mechanical tare is performed. Internal AFE calibration is distinct from tare.
"""

import time

ADDRESS = 0x2A
EXPECTED_CTRL1 = 0x0F  # LDO 4.2 V, gain 128
EXPECTED_CTRL2 = 0x30  # channel 1, 80 SPS, internal calibration mode
GAIN = 128


def signed24(data):
    if len(data) != 3:
        raise OSError("Incomplete 24-bit conversion")
    value = (data[0] << 16) | (data[1] << 8) | data[2]
    return value - 0x1000000 if value & 0x800000 else value


class NAU7802:
    def __init__(self, bus, clock=time):
        self.bus = bus
        self.clock = clock
        self.initialized = False

    def read8(self, register):
        data = self.bus.readfrom_mem(ADDRESS, register, 1)
        if len(data) != 1:
            raise OSError("Incomplete NAU7802 register")
        return data[0]

    def write8(self, register, value):
        self.bus.writeto_mem(ADDRESS, register, bytes((value & 255,)))

    def change_bit(self, register, mask, enabled):
        value = self.read8(register)
        self.write8(register, value | mask if enabled else value & ~mask)

    def wait_bit(self, register, mask, enabled, timeout_ms):
        start = self.clock.ticks_ms()
        while bool(self.read8(register) & mask) != enabled:
            if self.clock.ticks_diff(self.clock.ticks_ms(), start) > timeout_ms:
                raise OSError("NAU7802 status timeout")
            self.clock.sleep_ms(1)

    def initialize(self):
        if self.read8(0x1F) & 0x0F != 0x0F:
            raise OSError("Unexpected NAU7802 revision code")
        self.write8(0x00, 0x01)
        self.clock.sleep_ms(1)
        self.write8(0x00, 0x00)
        self.change_bit(0x00, 0x02, True)  # digital power
        self.change_bit(0x00, 0x04, True)  # analog power
        self.wait_bit(0x00, 0x08, True, 150)
        self.change_bit(0x00, 0x10, True)  # cycle start
        self.write8(0x01, EXPECTED_CTRL1)
        self.change_bit(0x00, 0x80, True)  # internal AVDD/LDO
        self.write8(0x02, EXPECTED_CTRL2)
        self.write8(0x15, self.read8(0x15) | 0x30)
        self.change_bit(0x1C, 0x80, True)
        self.change_bit(0x1B, 0x40, False)
        self.clock.sleep_ms(250)
        self.flush(10)
        # CALMOD remains 0: internal AFE calibration, never external offset.
        self.write8(0x02, EXPECTED_CTRL2 | 0x04)
        self.wait_bit(0x02, 0x04, False, 1500)
        if self.read8(0x02) & 0x08:
            raise OSError("NAU7802 internal calibration failed")
        self.verify_configuration()
        self.initialized = True

    def verify_configuration(self, allow_burnout=False):
        if self.read8(0x01) & 0x3F != EXPECTED_CTRL1:
            raise OSError("NAU7802 gain/LDO configuration changed")
        if self.read8(0x02) != EXPECTED_CTRL2:
            raise OSError("NAU7802 rate/channel/calibration state changed")
        if self.read8(0x00) & 0xDF != 0x9E:
            raise OSError("NAU7802 power/clock state changed")
        mode = self.read8(0x11)
        forbidden = 0xCB if allow_burnout else 0xCF
        if mode & forbidden:
            raise OSError("NAU7802 diagnostic or nonstandard I2C mode is active")
        if self.read8(0x1B) & 0x58:
            raise OSError("NAU7802 PGA inversion/bypass/LDO mode changed")

    def available(self):
        return bool(self.read8(0x00) & 0x20)

    def conversion(self, verify=True):
        if verify:
            self.verify_configuration()
        if not self.available():
            return None
        value = signed24(self.bus.readfrom_mem(ADDRESS, 0x12, 3))
        if abs(value) >= int(.98 * (1 << 23)):
            raise OSError("Bridge ADC is near its electrical rail")
        return value

    def flush(self, count):
        start = self.clock.ticks_ms()
        read = 0
        while read < count:
            if self.clock.ticks_diff(self.clock.ticks_ms(), start) > 1500:
                raise OSError("No fresh NAU7802 conversions")
            if self.available():
                self.conversion(verify=False)
                read += 1
            else:
                self.clock.sleep_ms(1)

    def mean_raw(self, count=16):
        start = self.clock.ticks_ms()
        values = []
        while len(values) < count:
            if self.clock.ticks_diff(self.clock.ticks_ms(), start) > 1500:
                raise OSError("Bridge diagnostic sample timeout")
            value = self.conversion(verify=False)
            if value is None:
                self.clock.sleep_ms(1)
            else:
                values.append(value)
        return sum(values) / len(values)

    def startup_burnout_check(self, reference_v):
        """Static wiring test using the specified internal 2.5 µA source.

        The acceptance band is provisional and must be qualified by fault
        injection on the actual board. This is not continuous short detection.
        """
        self.verify_configuration()
        before = self.mean_raw()
        try:
            self.change_bit(0x11, 0x04, True)
            self.clock.sleep_ms(100)
            self.flush(8)
            during = self.mean_raw()
        finally:
            self.change_bit(0x11, 0x04, False)
            self.clock.sleep_ms(100)
            self.flush(8)
        after = self.mean_raw()
        self.verify_configuration()
        change = during - (before + after) / 2
        volts = change * reference_v / (2 * GAIN * (1 << 23))
        resistance = volts / 2.5e-6
        stationary = change > 0 and abs(after-before) < .1 * change
        return {
            "before_counts": before,
            "during_counts": during,
            "after_counts": after,
            "change_counts": change,
            "equivalent_resistance_ohm": resistance,
            "stationary": stationary,
            "passes_provisional_band": stationary and 200 <= resistance <= 1200,
            "fault_coverage_qualified": False,
        }
