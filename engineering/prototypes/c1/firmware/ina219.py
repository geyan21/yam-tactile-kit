"""Per-bridge raw excitation monitoring. TI SBOS448G; SOIC-8 wiring."""

CONFIGURATION = 0x019F


class INA219:
    def __init__(self,bus,address):
        if address not in (0x40,0x41):
            raise ValueError("C1 INA219 address must be 0x40 or 0x41")
        self.bus = bus
        self.address = address

    def read16(self,register):
        data = self.bus.readfrom_mem(self.address,register,2)
        if len(data)!=2:
            raise OSError("Incomplete current-monitor read")
        return (data[0]<<8)|data[1]

    def initialize(self):
        self.bus.writeto_mem(self.address,0,bytes((CONFIGURATION>>8,CONFIGURATION&255)))
        if self.read16(0)!=CONFIGURATION:
            raise OSError("Current-monitor configuration failed")

    def sample(self):
        if self.read16(0)!=CONFIGURATION:
            raise OSError("Current-monitor configuration changed")
        shunt = self.read16(1)
        if shunt & 0x8000:
            shunt -= 0x10000
        bus = self.read16(2)
        return {"address":self.address,"shunt_raw":shunt,"bus_raw":bus,
                "shunt_ohm":0.1,"configuration":CONFIGURATION}
