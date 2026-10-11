"""N1 nail bridges and four TPU cells. Raw acquisition only; no actuator commands."""

import json
import time
from ads1232 import Pair,CLOCK_HZ,CONVERSION_US
from ina219 import INA219
from pressure_scan import PressureScan

PROTOCOL="yam-nail/1"
REVISION="N1.1"
SETTINGS={"gain":128,"clock_hz":CLOCK_HZ,"conversion_cycles":61440,
          "input_channel":1,"bridge_count":2,"system_clock_hz":125000000}


def mean_samples(adcs,count=12):
    total=[0,0]
    for _ in range(count):
        reading=adcs.read()
        if reading["ready_skew_us"]>1000 or any(abs(value)>=8000000 for value in reading["raw"]):
            raise OSError("Invalid bridge data during electrical self-test")
        for index in range(2):
            total[index]+=reading["raw"][index]
    return [value/count for value in total]


def self_test(adcs,shunts):
    results=[]
    try:
        for pin in shunts:
            pin.value(0)
        for _ in range(5):
            adcs.read()
        for index,pin in enumerate(shunts):
            baseline=mean_samples(adcs)
            pin.value(1)
            for _ in range(5):
                adcs.read()
            active=mean_samples(adcs)
            pin.value(0)
            for _ in range(5):
                adcs.read()
            delta=[a-b for a,b in zip(active,baseline)]
            passed=140000<=delta[index]<=240000 and abs(delta[1-index])<=10000
            result={"bridge":index,"delta_counts":delta,"passed":passed}
            results.append(result)
            print(json.dumps({"type":"diagnostic","protocol":PROTOCOL,"test":"shunt","result":result}))
            if not passed:
                raise OSError("N1 electrical shunt check failed")
    finally:
        for pin in shunts:
            pin.value(0)
    return results


def load_pull_down():
    with open("config.json") as stream:
        values=json.load(stream)["pull_down_ohm"]
    if len(values)!=4 or any(type(value) is not int or value not in (330,1000,10000,100000) for value in values):
        raise ValueError("N1 config must specify the four installed pull-down resistors")
    return values


def main():
    import machine
    from machine import Pin,I2C
    import rp2
    pull_down=load_pull_down()
    machine.freq(125000000)
    if machine.freq()!=125000000:
        raise ValueError("N1 requires a 125 MHz RP2040 clock")

    @rp2.asm_pio(set_init=rp2.PIO.OUT_LOW)
    def adc_clock():
        wrap_target()
        set(pins,1)
        set(pins,0)
        wrap()

    shunts=(Pin(21,Pin.OUT,value=0),Pin(22,Pin.OUT,value=0))
    pdwn=Pin(20,Pin.OUT,value=0)
    sclk=Pin(17,Pin.OUT,value=0)
    data=(Pin(18,Pin.IN,Pin.PULL_UP),Pin(19,Pin.IN,Pin.PULL_UP))
    clock=rp2.StateMachine(0,adc_clock,freq=12500000,set_base=Pin(16))
    try:
        clock.active(1)
        bus=I2C(0,sda=Pin(4),scl=Pin(5),freq=400000)
        monitors=[INA219(bus,address) for address in (0x40,0x41)]
        for monitor in monitors:
            monitor.initialize()
        time.sleep_ms(20)
        for monitor in monitors:
            raw=monitor.sample()
            voltage=(raw["bus_raw"]>>3)*.004
            current=raw["shunt_raw"]*.1
            expected=1000*voltage/350
            if not 4.2<=voltage<=5.25 or not .65*expected<=current<=1.35*expected:
                raise OSError("N1 bridge excitation check failed")
        adcs=Pair(sclk,data[0],data[1],pdwn)
        adcs.initialize()
        diagnostic=self_test(adcs,shunts)
        pressure=PressureScan(bus)
        print(json.dumps({"type":"hello","protocol":PROTOCOL,"hardware_revision":REVISION,
                          "settings":SETTINGS,"electrical_self_test":diagnostic,"force_calibrated":False,
                          "pull_down_ohm":pull_down,"continuity_ohm":100000,
                          "soft_raw_order":["GND","GND","CH2","CH3","CH4","CH5","REF_A","REF_B"],
                          "note":"Electrical self-test does not verify bonding or calibrate force. Pressure inputs need four completed scan phases."}))
        sequence=0;elapsed=0;previous=None
        while True:
            errors=[]
            reading=adcs.read()
            current=reading.pop("ready_tick_us")
            interval=None if previous is None else time.ticks_diff(current,previous)
            if interval is not None:
                if interval<=0 or interval>CONVERSION_US*1.8:
                    errors.append("sample_interval")
                elapsed+=max(interval,0)
            previous=current
            power=[]
            for index,monitor in enumerate(monitors):
                try:
                    power.append(monitor.sample())
                except OSError as error:
                    power.append(None)
                    errors.append("monitor_%d:%s"%(index,error))
            soft=pressure.advance(elapsed,current)
            print(json.dumps({"type":"sample","protocol":PROTOCOL,"hardware_revision":REVISION,
                              "seq":sequence,"device_us":elapsed,"interval_us":interval,"settings":SETTINGS,
                              "adc_raw":reading["raw"],"ready_skew_us":reading["ready_skew_us"],
                              "read_us":reading["read_us"],"power":power,"shunts_on":[False,False],
                              "electrical_self_test_passed":True,"errors":errors,
                              "pressure":soft,"pull_down_ohm":pull_down,"continuity_ohm":100000}))
            sequence+=1
    finally:
        for pin in shunts:
            pin.value(0)
        pdwn.value(0)
        clock.active(0)


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError) as error:
        print(json.dumps({"type":"fatal","protocol":PROTOCOL,"reason":str(error),"force_calibrated":False}))
