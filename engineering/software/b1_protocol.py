"""Strict B1 packet decoder. Exposes magnetic field observations, never force."""

PROTOCOL = "yam-b1/1"
SETTINGS = {"gain_sel":7,"resolution":1,"dig_filt":2,"osr":2,
            "hallconf":12,"temperature_compensation":False}
LSB_UT = (.300, .300, .484)


def integer(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"Invalid {name}")
    return value


def decode(frame):
    if not isinstance(frame,dict) or frame.get("type")!="sample" or frame.get("protocol")!=PROTOCOL:
        raise ValueError("Not a B1 sample")
    seq=integer(frame.get("seq"),0,2**63-1,"seq")
    device=integer(frame.get("device_us"),0,2**63-1,"device_us")
    scan=integer(frame.get("scan_us"),0,10000000,"scan_us")
    if frame.get("settings")!=SETTINGS:
        raise ValueError("Unsupported magnetic configuration")
    errors=frame.get("errors")
    if not isinstance(errors,list) or any(not isinstance(flag,str) for flag in errors):
        raise ValueError("Invalid errors")
    flags=list(errors)
    if scan>50000:flags.append("scan_overrun")
    sensors=frame.get("sensors")
    if not isinstance(sensors,list) or len(sensors)!=5:
        raise ValueError("Expected five sensor slots")
    fields=[]; temperatures=[]
    for index,sensor in enumerate(sensors):
        if sensor is None:
            flags.append(f"missing:S{index}");fields.append(None);temperatures.append(None);continue
        if not isinstance(sensor,dict) or sensor.get("channel")!=index:
            raise ValueError("Channel order mismatch")
        status=integer(sensor.get("status"),0,255,"status")
        start=integer(sensor.get("start_us"),0,scan,"start_us")
        integer(sensor.get("read_us"),start,scan,"read_us")
        raw=sensor.get("raw_xyz")
        if not isinstance(raw,list) or len(raw)!=3:
            raise ValueError("Expected XYZ triplet")
        raw=[integer(value,-32768,32767,"magnetic code") for value in raw]
        temperatures.append(integer(sensor.get("temperature_raw"),0,65535,"temperature"))
        if status & 0x1C or status & 3 != 3 or status & 0xC0:
            flags.append(f"status:S{index}");fields.append(None)
        elif any(abs(value)>=30000 for value in raw):
            flags.append(f"near_rail:S{index}");fields.append(None)
        else:
            fields.append([value*factor for value,factor in zip(raw,LSB_UT)])
    nail_fields=None;excitation=None
    if not isinstance(frame.get("nail_cells"),bool):
        raise ValueError("Missing nail enable flag")
    if frame["nail_cells"]:
        raw=frame.get("nail_raw"); offsets=frame.get("nail_offset_us");resistors=frame.get("pull_down_ohm")
        if not isinstance(raw,list) or len(raw)!=4 or not isinstance(offsets,list) or len(offsets)!=4:
            raise ValueError("Expected four nail ADC slots")
        if not isinstance(resistors,list) or len(resistors)!=2 or any(
                isinstance(value,bool) or value not in (330,1000,10000,100000) for value in resistors) or frame.get("continuity_ohm")!=100000:
            raise ValueError("Nail resistor configuration invalid")
        nail_fields=[None,None]
        for i,value in enumerate(raw):
            if value is not None:
                integer(value,-32768,32767,"nail code");integer(offsets[i],0,scan,"nail time")
        if None in raw:
            flags.append("missing_nail_adc")
        else:
            voltage=[value*.000125 for value in raw];excitation=2*voltage[2]
            if not 3.0<=excitation<=3.6 or abs(voltage[3]/excitation-.5)>.02:
                flags.append("nail_supply_or_check")
            else:
                for i,value in enumerate(voltage[:2]):
                    if not 0<=value<.98*excitation:
                        flags.append(f"nail_short_or_invalid:{i}");continue
                    conductance=value/(excitation-value)/resistors[i]*1e6
                    if conductance<5:
                        flags.append(f"nail_open:{i}");continue
                    nail_fields[i]=conductance
    return {"seq":seq,"device_us":device,"scan_us":scan,"magnetic_local_ut":fields,
            "temperature_raw":temperatures,"nail_conductance_us":nail_fields,"excitation_v":excitation,
            "valid":not flags,"flags":flags,"force_n":None,"force_calibrated":False,
            "note":"Magnetic field is nominally scaled at 25 C. Nail conductance includes its 100k continuity resistor."}


def native_vectors(fields, poses):
    if len(fields)!=5 or len(poses)!=5:
        raise ValueError("Expected five sensor orientations")
    result=[]
    for field,pose in zip(fields,poses):
        if field is None:result.append(None);continue
        matrix=pose["rotation_sensor_to_native"]
        result.append([sum(row[j]*field[j] for j in range(3)) for row in matrix])
    return result
