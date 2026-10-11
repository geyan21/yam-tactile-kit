"""B1 MicroPython readout: Melexis 3901090393 rev012, volatile registers only."""

import struct
import time

ADDRESS = 0x0C
MUX_ADDRESS = 0x70
SETTINGS = {"gain_sel": 7, "resolution": 1, "dig_filt": 2, "osr": 2,
            "hallconf": 12, "temperature_compensation": False}
LSB_UT = (0.300, 0.300, 0.484)  # nominal at 25 C, Table 17
CONF1 = 0xE000  # INT output; I2C only; external trigger and TCMP disabled
CONF2 = (1 << 5) | (1 << 7) | (1 << 9) | (2 << 2) | 2


def select(bus, channel):
    if isinstance(channel, bool) or channel not in range(5):
        raise ValueError("B1 channel must be 0..4")
    mask = 1 << channel
    if bus.writeto(MUX_ADDRESS, bytes((mask,))) != 1:
        raise OSError("Incomplete mux write")
    if bus.readfrom(MUX_ADDRESS, 1) != bytes((mask,)):
        raise OSError("Mux state mismatch")


def unpack_measurement(data):
    if len(data) != 9:
        raise OSError("Incomplete TXYZ response")
    status = data[0]
    if status & 0x1C or status & 3 != 3 or status & 0xC0:
        raise OSError("MLX90393 measurement status 0x%02x" % status)
    # TCMP is off; RES=1 uses signed two's complement for X/Y/Z.
    temperature, x, y, z = struct.unpack(">Hhhh", data[1:])
    return {"status": status, "temperature_raw": temperature, "raw_xyz": [x, y, z]}


class MLX90393:
    def __init__(self, bus, channel):
        self.bus = bus
        self.channel = channel
        self.expected = None

    def command(self, payload, count=0, allow_reset=False):
        select(self.bus, self.channel)
        if self.bus.writeto(ADDRESS, payload, stop=len(payload) != 1) != len(payload):
            raise OSError("Incomplete sensor command")
        raw = self.bus.readfrom(ADDRESS, count+1)
        if len(raw) != count+1:
            raise OSError("Incomplete sensor reply")
        if raw[0] & 0x18 or (raw[0] & 4 and not allow_reset):
            raise OSError("MLX90393 command status 0x%02x" % raw[0])
        if count and 2*(raw[0] & 3)+2 != count:
            raise OSError("MLX90393 response length status mismatch")
        return raw

    def read_register(self, register):
        raw = self.command(bytes((0x50, register << 2)), 2)
        return (raw[1] << 8) | raw[2]

    def write_register(self, register, value):
        self.command(bytes((0x60, value >> 8, value & 255, register << 2)))
        time.sleep(.001)
        if self.read_register(register) != value:
            raise OSError("Register write verification failed")

    def initialize(self):
        self.command(b"\x80", allow_reset=True)
        time.sleep(.001)
        self.command(b"\xf0", allow_reset=True)
        time.sleep(.003)
        # Preserve unrelated factory bits in register zero.
        conf0 = (self.read_register(0) & ~0x7F) | 0x7C
        for register, value in ((0, conf0), (1, CONF1), (2, CONF2),
                                (4, 0), (5, 0), (6, 0)):
            self.write_register(register, value)
        self.expected = [conf0, CONF1, CONF2]

    def check_configuration(self):
        if self.expected is None or [self.read_register(i) for i in range(3)] != self.expected:
            raise OSError("Sensor configuration changed")

    def start(self):
        self.check_configuration()
        response = self.command(b"\x3f")
        if response[0] & 0x20 == 0:
            raise OSError("Single measurement command not accepted")

    def read(self):
        return unpack_measurement(self.command(b"\x4f", 8))
