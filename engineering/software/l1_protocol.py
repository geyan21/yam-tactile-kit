"""Strict parsing for the experimental root-force bridge. Raw validity is not qualification."""

import math


def decode(frame):
    if not isinstance(frame,dict) or frame.get("type")!="sample" or frame.get("protocol")!="yam-l1/1":
        raise ValueError("Expected an L1 sample object")
    for field in ("seq","device_us"):
        value=frame.get(field)
        if not isinstance(value,int) or isinstance(value,bool) or value<0:
            raise ValueError(f"Invalid {field}")
    errors=frame.get("errors")
    if not isinstance(errors,list) or any(not isinstance(value,str) for value in errors):
        raise ValueError("Invalid error list")
    flags=list(errors)
    raw=frame.get("raw_counts")
    if raw is None:
        flags.append("missing_bridge_conversion")
    elif not isinstance(raw,int) or isinstance(raw,bool) or not -(1<<23)<=raw<(1<<23):
        raise ValueError("Invalid signed 24-bit bridge count")
    elif abs(raw)>=.98*(1<<23):
        flags.append("adc_near_rail")
    if frame.get("gain")!=128 or frame.get("rate_sps")!=80:
        flags.append("unexpected_adc_configuration")
    for field,lo,hi in (("bridge_v",3.9,4.5),("bridge_current_ma",2.0,6.5)):
        value=frame.get(field)
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or not lo<=value<=hi:
            flags.append(field)
    resistance=frame.get("startup_equivalent_ohm")
    if frame.get("startup_check_passed") is not True or not isinstance(resistance,(int,float)) or not math.isfinite(resistance) or not 200<=resistance<=1200:
        flags.append("startup_signal_check")
    if frame.get("transport_and_supply_valid") is not True:
        flags.append("device_reports_invalid")
    return {
        "seq":frame["seq"],"device_us":frame["device_us"],"raw_counts":raw,
        "bridge_v":frame.get("bridge_v"),"bridge_current_ma":frame.get("bridge_current_ma"),
        "valid":not flags,"flags":flags,"force_n":None,
        "fault_coverage_qualified":False,
    }
