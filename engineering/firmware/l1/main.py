"""L1.0 Pico raw bridge stream; no robot control and no automatic mechanical tare."""

import json
import time

from ina219 import INA219
from nau7802 import NAU7802

PROTOCOL = "yam-l1/1"


def main():
    from machine import I2C, Pin
    bus = I2C(0, sda=Pin(4), scl=Pin(5), freq=100000)
    monitor = INA219(bus)
    bridge = NAU7802(bus)
    monitor.initialize()
    bridge.initialize()
    supply = monitor.sample()
    if supply["errors"]:
        raise OSError("Excitation check failed: " + ",".join(supply["errors"]))
    print(json.dumps({"type": "diagnostic_start", "protocol": PROTOCOL,
                      "instruction": "Keep the fixture stationary; no force estimate is output during this check."}))
    diagnostic = bridge.startup_burnout_check(supply["reference_v_estimate"])
    print(json.dumps({"type": "startup_check", "protocol": PROTOCOL, "diagnostic": diagnostic}))
    if not diagnostic["passes_provisional_band"]:
        raise OSError("Startup bridge signal-path check failed")
    print(json.dumps({
        "type": "hello", "protocol": PROTOCOL, "firmware": "L1.0",
        "adc": "NAU7802", "gain": 128, "rate_sps": 80, "ldo_nominal_v": 4.2,
        "excitation_monitor": "INA219_0p1ohm", "mechanical_tare_performed": False,
        "force_calibrated": False, "analog_fault_coverage_qualified": False,
    }))
    sequence = 0
    elapsed_ms = 0
    previous_ms = time.ticks_ms()
    last_sample_ms = previous_ms
    while True:
        now = time.ticks_ms()
        elapsed_ms += time.ticks_diff(now, previous_ms)
        previous_ms = now
        errors = []
        raw = None
        try:
            raw = bridge.conversion()
            if raw is None:
                if time.ticks_diff(now, last_sample_ms) <= 200:
                    time.sleep_ms(1)
                    continue
                errors.append("bridge_conversion_timeout")
            supply = monitor.sample()
            errors += supply["errors"]
        except OSError as error:
            errors.append(str(error))
            supply = {"bridge_v": None, "bridge_current_ma": None}
        print(json.dumps({
            "type": "sample", "protocol": PROTOCOL, "seq": sequence,
            "device_us": elapsed_ms * 1000, "raw_counts": raw,
            "bridge_v": supply["bridge_v"], "bridge_current_ma": supply["bridge_current_ma"],
            "gain": 128, "rate_sps": 80, "errors": errors,
            "startup_check_passed": diagnostic["passes_provisional_band"],
            "startup_equivalent_ohm": diagnostic["equivalent_resistance_ohm"],
            "transport_and_supply_valid": not errors,
            "force_n": None, "fault_coverage_qualified": False,
        }))
        sequence += 1
        last_sample_ms = now
        if errors:
            time.sleep_ms(50)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(json.dumps({"type": "fatal", "protocol": PROTOCOL, "reason": str(error)}))
