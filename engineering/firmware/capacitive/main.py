"""K1 Pico acquisition. Copy with the two drivers/config after bench wiring checks."""

import json
import os
import time

from fdc1004 import FDC1004
from health_adc import HealthADC

PROTOCOL = "yam-k1/2"
TIMING = {"rate_sps": 400, "bus_hz": 400000, "quiet_us": 3000,
          "conversion_timeout_us": 15000, "minimum_frame_us": 20000, "hello_period_frames": 50}
EXPECTED_BANKS = (
    {"bank": 0, "sites": [0, 2, 3], "i2c_id": 0, "sda_gpio": 0, "scl_gpio": 1},
    {"bank": 1, "sites": [1, 4, 5], "i2c_id": 1, "sda_gpio": 2, "scl_gpio": 3},
)


def main():
    from machine import I2C, Pin, unique_id
    with open("config.json") as stream:
        cfg = json.load(stream)
    if (cfg["protocol"] != PROTOCOL or tuple(cfg["banks"]) != EXPECTED_BANKS
            or any(type(cfg.get(k)) is not int or cfg[k] != value for k, value in TIMING.items())):
        raise ValueError("Use the reviewed K1 prototype wiring and timing")
    boot_id = unique_id().hex()+"-"+os.urandom(8).hex()
    converters, health, startup = [], [], []
    for bank in EXPECTED_BANKS:
        bus = I2C(bank["i2c_id"], sda=Pin(bank["sda_gpio"]), scl=Pin(bank["scl_gpio"]), freq=cfg["bus_hz"])
        device, adc = FDC1004(bus), HealthADC(bus)
        entry = {"bank": bank["bank"], "ready": False, "calibration_words": None}
        try:
            device.begin_reset()
            deadline = time.ticks_add(time.ticks_ms(), 200)
            while not device.reset_ready():
                if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                    raise OSError("FDC reset timeout")
                time.sleep_ms(1)
            device.configure(cfg["rate_sps"])
            entry["ready"] = True
            entry["calibration_words"] = list(device.calibration_words)
        except OSError as error:
            device.timed_out()
            entry["error"] = str(error)
        converters.append(device)
        health.append(adc)
        startup.append(entry)
    hello = {"type": "hello", "protocol": PROTOCOL, "firmware": "K1.2 development",
                      "boot_id": boot_id, "timing": TIMING,
                      "banks": list(EXPECTED_BANKS), "startup": startup,
                      "rate_sps": cfg["rate_sps"], "capdac_enabled": False,
                      "raw_pF_divisor": 524288, "health_lsb_v": 0.000125,
                      "contact_calibrated": False, "force_calibrated": False}
    sequence, elapsed_us = 0, 0
    previous_ms = time.ticks_ms()
    while True:
        start = time.ticks_us()
        if sequence % cfg["hello_period_frames"] == 0:
            print(json.dumps(hello))
        now_ms = time.ticks_ms()
        elapsed_us += time.ticks_diff(now_ms, previous_ms)*1000
        previous_ms = now_ms
        frames = [{"bank": bank["bank"], "fdc": [None]*4, "health": [None]*4,
                   "fdc_us": [None]*4, "health_us": [None]*4, "errors": [],
                   "calibration_words": list(converters[i].calibration_words) if converters[i].calibration_words else None}
                  for i, bank in enumerate(EXPECTED_BANKS)]
        for slot in range(4):
            pending_fdc, pending_adc = set(), set()
            for i, (device, adc) in enumerate(zip(converters, health)):
                try:
                    adc.start(slot)
                    pending_adc.add(i)
                except OSError as error:
                    frames[i]["errors"].append("health_start:%d:%s" % (slot, error))
                try:
                    device.start(slot)
                    pending_fdc.add(i)
                except OSError as error:
                    frames[i]["errors"].append("fdc_start:%d:%s" % (slot, error))
            deadline = time.ticks_add(time.ticks_us(), cfg["conversion_timeout_us"])
            # Avoid bus transitions through the nominal conversion interval.
            time.sleep_us(cfg["quiet_us"])
            while (pending_fdc or pending_adc) and time.ticks_diff(deadline, time.ticks_us()) > 0:
                for i in tuple(pending_fdc):
                    try:
                        if converters[i].ready():
                            frames[i]["fdc"][slot] = converters[i].result()
                            frames[i]["fdc_us"][slot] = time.ticks_diff(time.ticks_us(), start)
                            pending_fdc.remove(i)
                    except OSError as error:
                        converters[i].timed_out()
                        frames[i]["errors"].append("fdc_read:%d:%s" % (slot, error))
                        pending_fdc.remove(i)
                for i in tuple(pending_adc):
                    try:
                        if health[i].ready():
                            frames[i]["health"][slot] = health[i].result()
                            frames[i]["health_us"][slot] = time.ticks_diff(time.ticks_us(), start)
                            pending_adc.remove(i)
                    except OSError as error:
                        frames[i]["errors"].append("health_read:%d:%s" % (slot, error))
                        pending_adc.remove(i)
                if pending_fdc or pending_adc:
                    time.sleep_us(100)
            for i in pending_fdc:
                converters[i].timed_out()
                frames[i]["errors"].append("fdc_timeout:%d" % slot)
            for i in pending_adc:
                frames[i]["errors"].append("health_timeout:%d" % slot)
        for i, device in enumerate(converters):
            try:
                device.check_setup()
            except OSError as error:
                frames[i]["errors"].append("fdc_setup:%s" % error)
        print(json.dumps({"type": "sample", "protocol": PROTOCOL, "seq": sequence,
                          "boot_id": boot_id,
                          "device_us": elapsed_us, "scan_us": time.ticks_diff(time.ticks_us(), start),
                          "banks": frames}))
        sequence += 1
        remaining = cfg["minimum_frame_us"]-time.ticks_diff(time.ticks_us(), start)
        if remaining > 0:
            time.sleep_us(remaining)


if __name__ == "__main__":
    main()
