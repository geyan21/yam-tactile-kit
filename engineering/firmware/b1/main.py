"""B1 Pico firmware. Fixed magnetic heads, optional nail cells; no actuator control."""

import json
import time
from mlx90393 import MLX90393, SETTINGS, LSB_UT

PROTOCOL = "yam-b1/1"
FRAME_US = 50000  # 20 Hz target; actual scan and sample times are recorded


class ADS1115:
    def __init__(self, bus):
        self.bus = bus

    def read(self, channel):
        config = 0x8000 | ((4+channel) << 12) | 0x03E3
        self.bus.writeto_mem(0x48, 1, bytes((config >> 8, config & 255)))
        deadline = time.ticks_add(time.ticks_us(), 12000)
        while time.ticks_diff(deadline, time.ticks_us()) > 0:
            data = self.bus.readfrom_mem(0x48, 1, 2)
            word = (data[0] << 8) | data[1]
            if word & 0x7FFF != config & 0x7FFF:
                raise OSError("ADS1115 configuration changed")
            if word & 0x8000:
                data = self.bus.readfrom_mem(0x48, 0, 2)
                word = (data[0] << 8) | data[1]
                return word - 65536 if word & 0x8000 else word
            time.sleep_us(150)
        raise OSError("ADS1115 timeout")


def main():
    from machine import I2C, Pin
    with open("config.json") as stream:
        config = json.load(stream)
    nails = config.get("nail_cells")
    resistors = config.get("pull_down_ohm")
    if not isinstance(nails, bool) or not isinstance(resistors, list) or len(resistors) != 2 or any(
            isinstance(value, bool) or value not in (330,1000,10000,100000) for value in resistors):
        raise ValueError("Invalid nail configuration")
    bus = I2C(0, sda=Pin(4), scl=Pin(5), freq=100000)
    heads = [MLX90393(bus, i) for i in range(5)]
    for head in heads:
        head.initialize()
    adc = ADS1115(bus) if nails else None
    print(json.dumps({"type":"hello","protocol":PROTOCOL,"settings":SETTINGS,"lsb_ut":LSB_UT,
                      "nail_cells":nails,"force_calibrated":False,"target_frame_us":FRAME_US}))
    sequence = 0; elapsed_us = 0; previous_ms = time.ticks_ms()
    while True:
        start = time.ticks_us(); start_ms = time.ticks_ms()
        elapsed_us += time.ticks_diff(start_ms, previous_ms)*1000
        previous_ms = start_ms
        sensors = [None]*5; started = [None]*5; errors = []
        for i, head in enumerate(heads):
            try:
                head.start()
                started[i] = time.ticks_diff(time.ticks_us(), start)
            except OSError as error:
                errors.append("S%d:start:%s" % (i,error))
        # 5.30 ms typical TXYZ at FILT=2/OSR=2/OSR2=0; allow 8 ms.
        # A not-ready status is a fault, never a recycled sample.
        time.sleep_ms(8)
        for i, head in enumerate(heads):
            if started[i] is None:
                continue
            try:
                sensors[i] = {**head.read(), "channel":i, "start_us":started[i],
                              "read_us":time.ticks_diff(time.ticks_us(), start)}
            except OSError as error:
                errors.append("S%d:read:%s" % (i,error))
        nail_raw = [None]*4; nail_offset = [None]*4
        if adc:
            for channel in range(4):
                try:
                    nail_raw[channel] = adc.read(channel)
                    nail_offset[channel] = time.ticks_diff(time.ticks_us(), start)
                except OSError as error:
                    errors.append("nail:%d:%s" % (channel,error))
        scan_us = time.ticks_diff(time.ticks_us(), start)
        if scan_us > FRAME_US:
            errors.append("scan_overrun")
        print(json.dumps({"type":"sample","protocol":PROTOCOL,"seq":sequence,"device_us":elapsed_us,
                          "scan_us":scan_us,"settings":SETTINGS,"sensors":sensors,"errors":errors,
                          "nail_cells":nails,"nail_raw":nail_raw,"nail_offset_us":nail_offset,
                          "pull_down_ohm":resistors,"continuity_ohm":100000}))
        sequence += 1
        remaining = FRAME_US-time.ticks_diff(time.ticks_us(), start)
        if remaining > 0:
            time.sleep_us(remaining)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(json.dumps({"type":"fatal","protocol":PROTOCOL,"reason":str(error)}))
