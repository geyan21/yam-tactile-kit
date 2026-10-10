"""Shared R1 decoding. Conductance is an electrical measurement, not force."""

from __future__ import annotations

import math

PROTOCOL = "yam-r1/1"
PULL_DOWN_OHM = 10000.0
LSB_V = .000125


def decode(frame):
    if not isinstance(frame,dict):
        raise ValueError("Expected a JSON object")
    if frame.get("type") != "sample" or frame.get("protocol") != PROTOCOL:
        raise ValueError("Not a supported R1 sample")
    for name in ("seq", "device_us", "scan_us"):
        if not isinstance(frame.get(name), int) or isinstance(frame[name], bool) or frame[name] < 0:
            raise ValueError(f"Invalid {name}")
    raw = frame.get("raw")
    pull_down = frame.get("pull_down_ohm")
    if not isinstance(pull_down,list) or len(pull_down)!=6 or any(value not in (330,1000,10000,100000) for value in pull_down):
        raise ValueError("Missing or invalid physical pull-down resistor configuration")
    if frame.get("continuity_ohm") != 100000:
        raise ValueError("Expected a 100 kΩ parallel continuity resistor at each cell")
    offsets = frame.get("offset_us")
    if not isinstance(raw, list) or len(raw) != 8 or not isinstance(offsets, list) or len(offsets) != 8:
        raise ValueError("Expected eight ADC values and acquisition offsets")
    source_errors=frame.get("errors")
    if not isinstance(source_errors,list) or not all(isinstance(flag,str) for flag in source_errors):
        raise ValueError("Invalid error list")
    flags=list(source_errors)
    voltage = []
    for index, value in enumerate(raw):
        if value is None:
            voltage.append(None)
            flags.append(f"missing:{index}")
            continue
        if isinstance(value, bool) or not isinstance(value, int) or not -32768 <= value <= 32767:
            raise ValueError("ADC code outside signed 16-bit range")
        if not isinstance(offsets[index], int) or not 0 <= offsets[index] <= frame["scan_us"]:
            raise ValueError("Invalid acquisition offset")
        voltage.append(value * LSB_V)
    excitation = None if voltage[6] is None else 2 * voltage[6]
    if excitation is None or not 3.0 <= excitation <= 3.6:
        flags.append("excitation_out_of_range")
    if frame["scan_us"] > 20000:
        flags.append("scan_overrun")
    if excitation and voltage[7] is not None and abs(voltage[7] / excitation - .5) > .02:
        flags.append("check_divider_failed")
    conductance = []
    for index, value in enumerate(voltage[:6]):
        if excitation is None or not 3.0 <= excitation <= 3.6 or value is None or value < -.005:
            conductance.append(None)
            flags.append(f"invalid_voltage:{index}")
        elif value >= .98 * excitation:
            conductance.append(None)
            flags.append(f"short_or_saturation:{index}")
        else:
            total=max(0.0,value) / (excitation-max(0.0,value)) / pull_down[index] * 1e6
            if total < .5e6 / frame["continuity_ohm"]:
                conductance.append(None)
                flags.append(f"open_lead_or_missing_continuity_resistor:{index}")
            else:
                conductance.append(total)
    return {
        "seq": frame["seq"], "device_us": frame["device_us"],
        "scan_us": frame["scan_us"], "voltage_v": voltage,
        "excitation_v": excitation, "conductance_us": conductance,
        "valid": not flags, "flags": flags,
        "force_n": None,
        "pull_down_ohm": pull_down,
        "continuity_ohm": frame["continuity_ohm"],
        "note": "Conductance includes the parallel continuity resistor. Lead continuity does not prove pressure response; perform the selected-cell touch check.",
    }
