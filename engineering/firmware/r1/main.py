"""R1.0 Pico firmware. MicroPython; raw data only, no robot control.

TI ADS1115 SBAS444E registers: single-shot, ±4.096 V, 860 SPS,
four single-ended inputs. Two ADCs convert concurrently per input index.
Copy this file as main.py to a Pico after following the electronics guide.
"""

import json
import time

ADDRESSES = (0x48, 0x49)
LSB_V = 0.000125
FRAME_US = 20000
CONTINUITY_OHM = 100000


def config_word(channel):
    if channel not in (0, 1, 2, 3):
        raise ValueError("ADS1115 channel must be 0..3")
    return 0x8000 | ((4 + channel) << 12) | 0x0200 | 0x0100 | 0x00E0 | 0x0003


class ADS1115:
    def __init__(self, bus, address):
        self.bus = bus
        self.address = address
        self.configuration = None

    def word(self, register):
        raw = self.bus.readfrom_mem(self.address, register, 2)
        if len(raw) != 2:
            raise OSError("Incomplete ADS1115 register")
        return (raw[0] << 8) | raw[1]

    def start(self, channel):
        self.configuration = config_word(channel)
        self.bus.writeto_mem(self.address, 1, bytes((self.configuration >> 8, self.configuration & 255)))

    def ready(self):
        value = self.word(1)
        if value & 0x7FFF != self.configuration & 0x7FFF:
            raise OSError("ADS1115 configuration changed")
        return bool(value & 0x8000)

    def result(self):
        value = self.word(0)
        return value - 65536 if value & 32768 else value


def main():
    from machine import I2C, Pin
    try:
        with open("config.json") as stream:
            pull_down = json.load(stream)["pull_down_ohm"]
    except OSError:
        pull_down = [10000] * 6
    if len(pull_down) != 6 or any(value not in (330, 1000, 10000, 100000) for value in pull_down):
        print(json.dumps({"type": "fatal", "reason": "Invalid pull_down_ohm configuration"}))
        return
    bus = I2C(0, sda=Pin(4), scl=Pin(5), freq=400000)
    found = bus.scan()
    if not all(address in found for address in ADDRESSES):
        print(json.dumps({"type": "fatal", "reason": "Expected ADS1115 at 0x48 and 0x49", "found": found}))
        return
    converters = [ADS1115(bus, address) for address in ADDRESSES]
    print(json.dumps({
        "type": "hello", "protocol": "yam-r1/1", "firmware": "R1.0",
        "addresses": list(ADDRESSES), "lsb_v": LSB_V,
        "raw_order": ["48:A0", "48:A1", "48:A2", "48:A3", "49:A0", "49:A1", "49:A2", "49:A3"],
        "force_calibrated": False,
        "pull_down_ohm": pull_down,
        "continuity_ohm": CONTINUITY_OHM,
    }))
    sequence = 0
    elapsed_us = 0
    previous_start_ms = time.ticks_ms()
    while True:
        start = time.ticks_us()
        # Millisecond epoch extension tolerates long operator pauses or USB
        # back-pressure. Microsecond ticks are used only within a short scan.
        start_ms = time.ticks_ms()
        elapsed_us += time.ticks_diff(start_ms, previous_start_ms) * 1000
        previous_start_ms = start_ms
        values = [None] * 8
        offsets = [None] * 8
        errors = []
        for channel in range(4):
            pending = set()
            for number, converter in enumerate(converters):
                try:
                    converter.start(channel)
                    pending.add(number)
                except OSError:
                    errors.append("write:%d:%d" % (number, channel))
            deadline = time.ticks_add(time.ticks_us(), 15000)
            while pending and time.ticks_diff(deadline, time.ticks_us()) > 0:
                for number in tuple(pending):
                    try:
                        if converters[number].ready():
                            index = number * 4 + channel
                            values[index] = converters[number].result()
                            offsets[index] = time.ticks_diff(time.ticks_us(), start)
                            pending.remove(number)
                    except OSError:
                        errors.append("read:%d:%d" % (number, channel))
                        pending.remove(number)
                if pending:
                    time.sleep_us(100)
            for number in pending:
                errors.append("timeout:%d:%d" % (number, channel))
        scan_us = time.ticks_diff(time.ticks_us(), start)
        print(json.dumps({
            "type": "sample", "protocol": "yam-r1/1", "seq": sequence,
            "device_us": elapsed_us, "scan_us": scan_us, "offset_us": offsets,
            "raw": values, "errors": errors,
            "pull_down_ohm": pull_down,
            "continuity_ohm": CONTINUITY_OHM,
        }))
        sequence += 1
        remaining = FRAME_US - time.ticks_diff(time.ticks_us(), start)
        if remaining > 0:
            time.sleep_us(remaining)


if __name__ == "__main__":
    main()
