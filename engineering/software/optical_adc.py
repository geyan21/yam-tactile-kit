"""Linux I2C ADS1115 readout for two N0 cells and their 3.3 V supply."""

import fcntl
import os
import time


class LinuxBus:
    def __init__(self, path="/dev/i2c-1", address=0x48):
        if path != "/dev/i2c-1" or address != 0x48:
            raise ValueError("The documented O1 wiring uses i2c-1, address 0x48")
        self.fd = os.open(path, os.O_RDWR)
        try:
            fcntl.ioctl(self.fd, 0x0703, address)
        except BaseException:
            os.close(self.fd); raise

    def write(self, register, value):
        data = bytes((register, value >> 8, value & 255))
        if os.write(self.fd, data) != 3:
            raise OSError("Incomplete I2C configuration write")

    def read(self, register):
        if os.write(self.fd, bytes((register,))) != 1:
            raise OSError("Incomplete I2C pointer")
        data = os.read(self.fd, 2)
        if len(data) != 2:
            raise OSError("Incomplete ADS1115 register")
        return int.from_bytes(data, "big")

    def close(self):
        os.close(self.fd)


def conversion(bus, channel, clock=time.monotonic, sleep=time.sleep):
    if type(channel) is not int or channel not in range(3):
        raise ValueError("O1 uses A0, A1 and A2 only")
    config = 0x8000 | ((4+channel) << 12) | 0x0200 | 0x0100 | 0x00E0 | 0x0003
    bus.write(1, config)
    start = clock()
    while clock()-start < .020:
        returned = bus.read(1)
        if (returned & 0x7fff) != (config & 0x7fff):
            raise OSError("ADS1115 mux/gain/rate readback changed")
        if returned & 0x8000:
            value = bus.read(0)
            return value-65536 if value & 32768 else value
        sleep(.0003)
    raise TimeoutError("ADS1115 conversion exceeded 20 ms")


def scan(bus):
    start = time.monotonic_ns()
    raw = [conversion(bus, channel) for channel in range(3)]
    return {"raw": raw, "start_monotonic_ns": start, "end_monotonic_ns": time.monotonic_ns()}
