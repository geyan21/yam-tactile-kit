"""N1 ADS1115 single-shot access; raw counts and checked conversion settings."""


def configuration(channel):
    if type(channel) is not int or not 0<=channel<=3:
        raise ValueError("ADS1115 input must be 0..3")
    return 0x8000|((4+channel)<<12)|0x0200|0x0100|0x00E0|0x0003


class ADS1115:
    def __init__(self,bus,address):
        self.bus=bus
        self.address=address
        self.requested=None
        self.observed=None

    def word(self,register):
        data=self.bus.readfrom_mem(self.address,register,2)
        if len(data)!=2:
            raise OSError("Incomplete ADS1115 register")
        return (data[0]<<8)|data[1]

    def start(self,channel):
        value=configuration(channel)
        self.bus.writeto_mem(self.address,1,bytes((value>>8,value&255)))
        self.requested=value
        self.observed=None

    def ready(self):
        if self.requested is None:
            raise OSError("No ADS1115 conversion was started")
        value=self.word(1)
        if (value&0x7FFF)!=(self.requested&0x7FFF):
            raise OSError("ADS1115 configuration changed")
        self.observed=value
        return bool(value&0x8000)

    def result(self):
        if self.observed is None or not self.observed&0x8000:
            raise OSError("ADS1115 result requested before ready")
        value=self.word(0)
        return value-65536 if value&32768 else value
