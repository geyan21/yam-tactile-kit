"""P1.0 raw bench acquisition; no actuator interface or automatic tare."""

import json
import os
import time
from elvr import PressureBank
from ads1115 import ADS1115

PROTOCOL = "yam-p1-raw/1"


def main():
    from machine import I2C, Pin, unique_id
    from binascii import hexlify
    with open("config.json") as stream:
        cfg = json.load(stream)
    if (cfg["sensor_part"] != "ELVR-L30D-F1RD-C-NI3H" or cfg["sensor_address"] != 0x78
            or cfg["pressure_sites"] != [2, 3, 4, 5] or cfg["i2c_hz"] != 100000
            or cfg["nail_pull_down_ohm"] != [10000, 10000]
            or cfg["nail_continuity_ohm"] != 100000):
        raise ValueError("Use the documented P1.0 sensor/board configuration")
    reset = Pin(cfg["mux_reset_gpio"], Pin.IN)
    def reset_mux():
        reset.init(Pin.OUT, value=0)
        time.sleep_ms(1)
        reset.init(Pin.IN)  # External 10k pulls RESET to the 3V0 domain.
        time.sleep_ms(1)
    reset_mux()
    pressure_bus = I2C(0, sda=Pin(cfg["pressure_sda_gpio"]), scl=Pin(cfg["pressure_scl_gpio"]), freq=cfg["i2c_hz"])
    nail_bus = I2C(1, sda=Pin(cfg["nail_sda_gpio"]), scl=Pin(cfg["nail_scl_gpio"]), freq=cfg["i2c_hz"])
    bank = PressureBank(pressure_bus, cfg["sensor_address"], cfg["mux_address"])
    adc = ADS1115(nail_bus, cfg["nail_adc_address"])
    time.sleep_ms(60)  # Exceeds the specified 25 ms maximum startup time.
    bank.disable()
    boot_id = hexlify(unique_id()).decode()+"-"+hexlify(os.urandom(8)).decode()
    hello = {"type": "hello", "protocol": PROTOCOL, "firmware": "P1.0", "boot_id": boot_id,
                      "device_id": hexlify(unique_id()).decode(), "config": cfg,
                      "adc_lsb_v": .000125, "source": "rp2040_i2c",
                      "pressure_order": [2, 3, 4, 5],
                      "adc_order": ["NAIL0", "NAIL1", "3V0", "3V3"],
                      "force_calibrated": False, "pressure_calibrated": False,
                      "synthetic": False}
    sequence, elapsed_us = 0, 0
    previous_ms = time.ticks_ms()
    while True:
        if sequence % 50 == 0:
            print(json.dumps(hello))
        start = time.ticks_us()
        now_ms = time.ticks_ms()
        elapsed_us += time.ticks_diff(now_ms, previous_ms)*1000
        previous_ms = now_ms
        pressure, adc_raw, offsets, errors = [None]*4, [None]*4, [None]*8, []
        for index in range(4):
            try:
                pressure[index] = bank.read(index)
                offsets[index] = time.ticks_diff(time.ticks_us(), start)
            except (OSError, ValueError) as error:
                errors.append("pressure:%d:%s" % (index, error))
                reset_mux()
        try:
            bank.disable()
        except OSError as error:
            errors.append("mux_disable:"+str(error))
            reset_mux()
        for index in range(4):
            try:
                adc.start(index)
                deadline = time.ticks_add(time.ticks_us(), 15000)
                while not adc.ready():
                    if time.ticks_diff(deadline, time.ticks_us()) <= 0:
                        raise OSError("ADS1115 conversion timeout")
                    time.sleep_us(100)
                adc_raw[index] = adc.result()
                offsets[index+4] = time.ticks_diff(time.ticks_us(), start)
            except (OSError, ValueError) as error:
                errors.append("adc:%d:%s" % (index, error))
        scan_us = time.ticks_diff(time.ticks_us(), start)
        print(json.dumps({"type": "sample", "protocol": PROTOCOL, "seq": sequence,
                          "boot_id": boot_id,
                          "device_us": elapsed_us, "scan_us": scan_us, "offset_us": offsets,
                          "pressure_raw": pressure, "adc_raw": adc_raw, "errors": errors}))
        sequence += 1
        remaining = cfg["frame_us"]-time.ticks_diff(time.ticks_us(), start)
        if remaining > 0:
            time.sleep_us(remaining)


if __name__ == "__main__":
    main()
