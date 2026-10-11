"""Two ADS1232 converters sharing clock, power-down and serial clock.

TI SBAS350H: read 24 bits and use pulse 25 to return DRDY/DOUT high.
Pulse 26 is used only for explicit internal ADC offset calibration.
"""

import time

CLOCK_HZ = 6250000
CONVERSION_US = 61440*1000000/CLOCK_HZ


def signed24(value):
    if not isinstance(value,int) or isinstance(value,bool) or not 0<=value<1<<24:
        raise ValueError("Invalid 24-bit ADC word")
    return value-(1<<24) if value & (1<<23) else value


class Pair:
    def __init__(self,sclk,data_a,data_b,pdwn):
        self.sclk = sclk
        self.data = (data_a,data_b)
        self.pdwn = pdwn
        self.sclk.value(0)
        self.pdwn.value(0)

    def initialize(self):
        # External clock must already be stable. The required low-high-low-
        # high power-up sequence is intentionally longer than the minimum.
        self.sclk.value(0)
        self.pdwn.value(0)
        time.sleep_ms(20)
        self.pdwn.value(1);time.sleep_us(100)
        self.pdwn.value(0);time.sleep_us(100)
        self.pdwn.value(1)
        self.read(timeout_us=250000)
        # Remove ADC internal offset; this does not tare an external force.
        self.sclk.value(1);time.sleep_us(2)
        self.sclk.value(0);time.sleep_us(2)
        self.read(timeout_us=250000)

    def read(self,timeout_us=50000):
        start = time.ticks_us()
        deadline = time.ticks_add(start,timeout_us)
        ready = [None,None]
        while any(t is None for t in ready):
            for i,pin in enumerate(self.data):
                if ready[i] is None and pin.value()==0:
                    ready[i] = time.ticks_us()
            if time.ticks_diff(deadline,time.ticks_us())<=0:
                raise OSError("ADC data-ready timeout")
            if any(t is None for t in ready):
                time.sleep_us(20)
        skew = abs(time.ticks_diff(ready[0],ready[1]))
        values = [0,0]
        for _ in range(24):
            self.sclk.value(1);time.sleep_us(2)
            for i,pin in enumerate(self.data):
                values[i] = (values[i]<<1)|pin.value()
            self.sclk.value(0);time.sleep_us(2)
        self.sclk.value(1);time.sleep_us(2)  # pulse 25: force both data lines high
        self.sclk.value(0);time.sleep_us(2)
        if any(pin.value()!=1 for pin in self.data):
            raise OSError("ADC did not return data-ready high after pulse 25")
        first = ready[0] if time.ticks_diff(ready[0],ready[1])<=0 else ready[1]
        return {"raw":[signed24(value) for value in values],
                "ready_tick_us":ready[0],"ready_skew_us":skew,
                "read_us":time.ticks_diff(time.ticks_us(),first)}
