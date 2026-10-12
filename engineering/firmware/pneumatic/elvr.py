"""P1: direct ELVR reads and one-at-a-time TCA9548A channel selection.

DS-0375 Rev C: two bytes, most significant byte first, 15-bit pressure
word. This is not a Honeywell status/14-bit format. No generic bus scan:
some scan implementations omit the specified 0x78 address.
"""


def decode_word(data):
    if len(data) != 2:
        raise OSError("ELVR incomplete pressure word")
    if data[0] & 0x80:
        raise OSError("ELVR reserved high bit set")
    return (data[0] << 8) | data[1]


class PressureBank:
    def __init__(self, bus, address=0x78, mux_address=0x70):
        self.bus, self.address, self.mux_address = bus, address, mux_address
        self.selected = None

    def select(self, index):
        if index not in range(4):
            raise ValueError("P1 has four pressure branches")
        self.selected = None
        mask = 1 << index
        self.bus.writeto(self.mux_address, bytes((mask,)))
        returned = self.bus.readfrom(self.mux_address, 1)
        if returned != bytes((mask,)):
            raise OSError("TCA9548A channel readback mismatch")
        self.selected = index

    def disable(self):
        self.selected = None
        self.bus.writeto(self.mux_address, b"\x00")
        if self.bus.readfrom(self.mux_address, 1) != b"\x00":
            raise OSError("TCA9548A failed to disconnect branches")

    def read(self, index):
        self.select(index)
        return decode_word(self.bus.readfrom(self.address, 2))
