"""Strict raw C1 frame validation. Physical force calibration is a separate step."""

PROTOCOL = "yam-c1/1"
SETTINGS = {"gain":128,"clock_hz":6250000,"conversion_cycles":61440,
            "input_channel":1,"bridge_count":2,"system_clock_hz":125000000}
PERIOD_US = 61440*1000000/6250000


def integer(value,minimum,maximum,name):
    if isinstance(value,bool) or not isinstance(value,int) or not minimum<=value<=maximum:
        raise ValueError("Invalid "+name)
    return value


def decode(frame):
    if not isinstance(frame,dict) or frame.get("type")!="sample" or frame.get("protocol")!=PROTOCOL:
        raise ValueError("Not a C1 sample")
    settings = frame.get("settings")
    if frame.get("hardware_revision")!="C1.1" or settings!=SETTINGS or any(type(v) is not int for v in settings.values()):
        raise ValueError("Unsupported C1 hardware or conversion settings")
    sequence = integer(frame.get("seq"),0,2**63-1,"sequence")
    device = integer(frame.get("device_us"),0,2**63-1,"device time")
    skew = integer(frame.get("ready_skew_us"),0,1000000,"ready skew")
    read_us = integer(frame.get("read_us"),0,1000000,"read duration")
    errors = frame.get("errors")
    if not isinstance(errors,list) or any(not isinstance(v,str) for v in errors):
        raise ValueError("Invalid error list")
    flags = list(errors)
    interval = frame.get("interval_us")
    if interval is None:
        if sequence!=0:
            flags.append("missing_interval")
    else:
        integer(interval,0,2**31-1,"sample interval")
        if not PERIOD_US*.5<=interval<=PERIOD_US*1.8:
            flags.append("sample_interval")
    if skew>1000:
        flags.append("adc_pair_skew")
    if read_us>PERIOD_US*.8:
        flags.append("slow_readout")
    shunts = frame.get("shunts_on")
    if not isinstance(shunts,list) or len(shunts)!=2 or any(value is not False for value in shunts):
        flags.append("shunt_active_or_unknown")
    if frame.get("electrical_self_test_passed") is not True:
        flags.append("electrical_self_test_missing")
    raw = frame.get("adc_raw")
    if not isinstance(raw,list) or len(raw)!=2:
        raise ValueError("Expected two ADC channels")
    ratios = []
    for i,value in enumerate(raw):
        if value is None:
            flags.append(f"missing_adc_{i}");ratios.append(None)
            continue
        integer(value,-8388608,8388607,"ADC word")
        if abs(value)>=8000000:
            flags.append(f"adc_rail_{i}");ratios.append(None)
        else:
            ratios.append(value/(8388608*256))
    power = frame.get("power")
    if not isinstance(power,list) or len(power)!=2:
        raise ValueError("Expected two bridge power slots")
    decoded_power = []
    for i,reading in enumerate(power):
        if reading is None:
            decoded_power.append(None);flags.append(f"missing_power_{i}")
            continue
        if not isinstance(reading,dict) or reading.get("address")!=0x40+i or reading.get("configuration")!=0x019F or reading.get("shunt_ohm")!=.1:
            raise ValueError("Unsupported bridge monitor configuration")
        bus = integer(reading.get("bus_raw"),0,65535,"bus word")
        shunt = integer(reading.get("shunt_raw"),-32768,32767,"shunt word")
        voltage = (bus>>3)*.004
        current_ma = shunt*.1
        expected = voltage*1000/350
        if not bus&2 or bus&1:
            flags.append(f"monitor_status_{i}")
        if not 4.2<=voltage<=5.25:
            flags.append(f"excitation_voltage_{i}")
        if not .65*expected<=current_ma<=1.35*expected:
            flags.append(f"bridge_current_{i}")
        decoded_power.append({"excitation_v_at_board":voltage,"bridge_current_ma":current_ma})
    return {"design_id":"C1","hardware_revision":"C1.1","seq":sequence,"device_us":device,
            "bridge_ratio_v_per_v":ratios,"power":decoded_power,"flags":sorted(set(flags)),
            "valid":not flags,"force_n":None,"force_calibrated":False,
            "note":"Ratios are electrical observations. Power checks and a shunt test do not prove gauge bonding or mechanical calibration."}
