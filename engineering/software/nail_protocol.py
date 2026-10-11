"""Decode N1 without inventing force or treating cached pressure data as fresh."""

import c1_protocol

PROTOCOL="yam-nail/1"
REVISION="N1.1"
SETTINGS=dict(c1_protocol.SETTINGS)
SOFT_MAX_AGE_US=50000
SOFT_CHANNELS=(2,3,4,5)
LSB_V=.000125


def integer(value,name,low=0,high=None):
    if type(value) is not int or value<low or (high is not None and value>high):
        raise ValueError("Invalid integer: "+name)
    return value


def config_word(channel):
    return 0x8000|((4+channel)<<12)|0x0200|0x0100|0x00E0|0x0003


def decode_soft(frame):
    part=frame.get("pressure")
    if not isinstance(part,dict) or part.get("addresses")!=[72,73] or any(type(value) is not int for value in part["addresses"]):
        raise ValueError("Expected both N1 pressure ADC identities")
    arrays={name:part.get(name) for name in ("raw","start_us","ready_observed_us","configuration")}
    if any(not isinstance(value,list) or len(value)!=8 for value in arrays.values()):
        raise ValueError("N1 pressure data need eight values with individual acquisition intervals")
    pull_down=frame.get("pull_down_ohm")
    if not isinstance(pull_down,list) or len(pull_down)!=4 or any(type(value) is not int or value not in (330,1000,10000,100000) for value in pull_down):
        raise ValueError("N1 needs four known pull-down resistors")
    if type(frame.get("continuity_ohm")) is not int or frame["continuity_ohm"]!=100000:
        raise ValueError("N1 needs the stated remote continuity resistors")
    clock=integer(part.get("clock_us"),"pressure clock")
    if not 0<=clock-frame["device_us"]<=20000:
        raise ValueError("Pressure clock is outside the current bridge frame")
    errors=part.get("errors")
    if not isinstance(errors,list) or any(not isinstance(value,str) for value in errors):
        raise ValueError("Pressure errors must be retained as a list")
    flags=list(errors)
    available=[False]*8
    ages=[None]*8
    for index in range(8):
        values=[arrays[name][index] for name in arrays]
        if any(value is None for value in values):
            flags.append("soft_missing_%d"%index)
            continue
        count=integer(arrays["raw"][index],"pressure count",-32768,32767)
        start=integer(arrays["start_us"][index],"pressure start")
        ready=integer(arrays["ready_observed_us"][index],"observed ready")
        actual=integer(arrays["configuration"][index],"pressure configuration",0,65535)
        if actual!=config_word(index%4):
            raise ValueError("Pressure input/configuration mismatch")
        if not start<=ready<=clock:
            raise ValueError("Pressure acquisition interval is inconsistent")
        ages[index]=clock-start
        if ages[index]>SOFT_MAX_AGE_US:
            flags.append("soft_stale_%d"%index)
            continue
        available[index]=True
    housekeeping=all(available[index] for index in (0,1,6,7)) and not errors
    excitation=None
    if housekeeping:
        if any(abs(arrays["raw"][index]*LSB_V)>.005 for index in (0,1)):
            flags.append("soft_ground_check")
            housekeeping=False
        references=[2*arrays["raw"][index]*LSB_V for index in (6,7)]
        excitation=sum(references)/2
        if not all(3.0<=value<=3.6 for value in references) or abs(references[0]-references[1])>.03*excitation:
            flags.append("soft_excitation_reference")
            housekeeping=False
    conductance=[];channel_valid=[]
    for channel,index in enumerate(SOFT_CHANNELS):
        valid=housekeeping and available[index]
        value=None
        if valid:
            ratio=arrays["raw"][index]*LSB_V/excitation
            if not 0<ratio<.98:
                flags.append("soft_rail_CH%d"%index)
                valid=False
            else:
                value=1e6*ratio/(pull_down[channel]*(1-ratio))
                if value<5:
                    flags.append("soft_open_CH%d"%index)
                    valid=False
        conductance.append(value if valid else None)
        channel_valid.append(valid)
    return {"valid":all(channel_valid) and not flags,"channel_valid":channel_valid,
            "conductance_us":conductance,"excitation_v":excitation,"flags":sorted(set(flags)),
            "sample_start_us":[arrays["start_us"][index] for index in SOFT_CHANNELS],
            "ready_observed_us":[arrays["ready_observed_us"][index] for index in SOFT_CHANNELS],
            "sample_age_us":[ages[index] for index in SOFT_CHANNELS],
            "pull_down_ohm":list(pull_down),"continuity_ohm":100000}


def decode(frame):
    if not isinstance(frame,dict) or frame.get("protocol")!=PROTOCOL or frame.get("hardware_revision")!=REVISION:
        raise ValueError("Expected an N1 frame with its own protocol and revision")
    # Reuse the retained C1 electrical validation on a temporary bridge-only
    # view. The original N1 frame and recording identity remain unchanged.
    view={**frame,"protocol":c1_protocol.PROTOCOL,"hardware_revision":"C1.1"}
    bridge=c1_protocol.decode(view)
    bridge={**bridge,"design_id":"NAIL","hardware_revision":REVISION,"readout_hardware_revision":"C1.1"}
    soft=decode_soft(frame)
    return {"seq":bridge["seq"],"device_us":bridge["device_us"],
            "valid":bridge["valid"] and soft["valid"],
            "flags":sorted(set(["nail:"+value for value in bridge["flags"]]+soft["flags"])),
            "nail":bridge,"soft":soft,"force_n":None,"force_calibrated":False,
            "scope":"Two raw nail bridges and four local TPU conductances; force requires physical calibration."}
