"""One checked pressure input index per nail-bridge frame, with retained times."""

import time
from ads1115 import ADS1115


class PressureScan:
    def __init__(self,bus,converters=None):
        self.adcs=converters or [ADS1115(bus,address) for address in (0x48,0x49)]
        self.phase=None
        self.pending=[False,False]
        self.pending_start=[None,None]
        self.raw=[None]*8
        self.starts=[None]*8
        self.observed=[None]*8
        self.configurations=[None]*8

    def clear(self,index):
        self.raw[index]=None
        self.starts[index]=None
        self.observed[index]=None
        self.configurations[index]=None

    def advance(self,epoch_us,bridge_tick):
        def now():
            return epoch_us+time.ticks_diff(time.ticks_us(),bridge_tick)
        errors=[]
        if self.phase is not None:
            for number,adc in enumerate(self.adcs):
                index=number*4+self.phase
                if not self.pending[number]:
                    self.clear(index)
                    continue
                try:
                    if not adc.ready():
                        raise OSError("conversion not ready at next bridge frame")
                    self.raw[index]=adc.result()
                    self.starts[index]=self.pending_start[number]
                    self.observed[index]=now()
                    self.configurations[index]=adc.observed
                except OSError as error:
                    self.clear(index)
                    errors.append("pressure_read_%d:%s"%(index,error))
        self.phase=0 if self.phase is None else (self.phase+1)%4
        for number,adc in enumerate(self.adcs):
            index=number*4+self.phase
            self.pending[number]=False
            try:
                start=now()
                adc.start(self.phase)
                self.pending_start[number]=start
                self.pending[number]=True
            except OSError as error:
                self.clear(index)
                self.pending_start[number]=None
                errors.append("pressure_start_%d:%s"%(index,error))
        return {"addresses":[0x48,0x49],"raw":list(self.raw),"start_us":list(self.starts),
                "ready_observed_us":list(self.observed),"configuration":list(self.configurations),
                "clock_us":now(),"errors":errors,
                "timing_scope":"Conversion start and observed-ready times; cached values retain their own acquisition interval."}
