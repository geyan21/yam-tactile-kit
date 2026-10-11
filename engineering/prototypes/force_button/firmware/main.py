"""FB1 Pico raw acquisition; this firmware never controls an actuator."""

import json
import os
import time

from fma import FMA, PART
from health_adc import HealthADC

PROTOCOL = "yam-fb1/1"
EXPECTED = {"protocol": PROTOCOL, "part": PART, "i2c_id": 0, "sda_gpio": 4, "scl_gpio": 5,
            "bus_hz": 100000, "sensor_address": 40, "health_address": 72,
            "minimum_frame_us": 10000, "health_timeout_us": 6000, "hello_period_frames": 100}


def main():
    from machine import I2C, Pin, unique_id
    with open("config.json") as stream:
        cfg = json.load(stream)
    if cfg != EXPECTED:
        raise ValueError("Use the reviewed FB1 wiring and timing")
    bus = I2C(0, sda=Pin(4), scl=Pin(5), freq=100000)
    sensor, health = FMA(bus), HealthADC(bus)
    boot_id = unique_id().hex()+"-"+os.urandom(8).hex()
    hello = {"type": "hello", "protocol": PROTOCOL, "firmware": "FB1.1 development",
             "boot_id": boot_id, "configuration": cfg, "health_lsb_v": .000125,
             "force_calibrated": False, "contact_calibrated": False}
    # Manufacturer startup limit is 3 ms. The longer wait is a design choice.
    time.sleep_ms(10)
    seq, elapsed_us = 0, 0
    previous_ms = time.ticks_ms()
    while True:
        start = time.ticks_us()
        now_ms = time.ticks_ms()
        elapsed_us += time.ticks_diff(now_ms, previous_ms)*1000
        previous_ms = now_ms
        if seq % cfg["hello_period_frames"] == 0:
            print(json.dumps(hello))
        packet = {"type": "sample", "protocol": PROTOCOL, "boot_id": boot_id,
                  "seq": seq, "device_us": elapsed_us, "health": [None]*4,
                  "health_us": [None]*4, "sensor": None, "sensor_us": None, "errors": []}
        for channel in range(4):
            try:
                health.start(channel)
                deadline = time.ticks_add(time.ticks_us(), cfg["health_timeout_us"])
                time.sleep_us(1200)
                while not health.ready():
                    if time.ticks_diff(deadline, time.ticks_us()) <= 0:
                        raise OSError("health conversion timeout")
                    time.sleep_us(100)
                packet["health"][channel] = health.result()
                packet["health_us"][channel] = time.ticks_diff(time.ticks_us(), start)
            except OSError as error:
                packet["errors"].append("health_%d:%s" % (channel, error))
        try:
            packet["sensor"] = sensor.read()
            packet["sensor_us"] = time.ticks_diff(time.ticks_us(), start)
        except (OSError, ValueError) as error:
            packet["errors"].append("sensor:%s" % error)
        packet["scan_us"] = time.ticks_diff(time.ticks_us(), start)
        print(json.dumps(packet))
        seq += 1
        remaining = cfg["minimum_frame_us"]-time.ticks_diff(time.ticks_us(), start)
        if remaining > 0:
            time.sleep_us(remaining)


if __name__ == "__main__":
    main()
