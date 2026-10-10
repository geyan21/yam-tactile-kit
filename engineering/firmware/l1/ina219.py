"""INA219 raw shunt/bus monitoring for the L1 excitation supply.

TI SBOS448G: 10 µV/shunt count, 4 mV/bus count. A 0.1 Ω breakout
shunt is required. It monitors excitation continuity, not mechanical force.
"""

ADDRESS = 0x40
CONFIGURATION = 0x019F  # 16 V bus, ±40 mV shunt, 12-bit conversions, continuous


class INA219:
    def __init__(self, bus):
        self.bus = bus

    def read16(self, register):
        data = self.bus.readfrom_mem(ADDRESS, register, 2)
        if len(data) != 2:
            raise OSError("Incomplete INA219 register")
        return (data[0] << 8) | data[1]

    def initialize(self):
        self.bus.writeto_mem(ADDRESS, 0x00, bytes((CONFIGURATION >> 8, CONFIGURATION & 255)))
        if self.read16(0x00) != CONFIGURATION:
            raise OSError("INA219 configuration did not latch")

    def sample(self):
        if self.read16(0x00) != CONFIGURATION:
            raise OSError("INA219 configuration changed")
        shunt = self.read16(0x01)
        if shunt & 0x8000:
            shunt -= 0x10000
        bus = self.read16(0x02)
        voltage = (bus >> 3) * .004
        shunt_v = shunt * .00001
        current_ma = shunt_v / .1 * 1000
        errors = []
        if not bus & 0x02:
            errors.append("excitation_monitor_not_ready")
        if not 3.9 <= voltage <= 4.5:
            errors.append("bridge_excitation_voltage")
        if not 2.0 <= current_ma <= 6.5:
            errors.append("bridge_excitation_current")
        return {
            "bridge_v": voltage,
            "reference_v_estimate": voltage + shunt_v,
            "bridge_current_ma": current_ma,
            "errors": errors,
        }
