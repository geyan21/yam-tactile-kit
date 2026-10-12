"""P1 nail and supply ADC: checked single-shot ADS1115 conversions."""


def config_word(channel):
    if channel not in range(4):
        raise ValueError("ADS1115 channel must be 0..3")
    return 0x8000 | ((4+channel) << 12) | 0x0200 | 0x0100 | 0x00E0 | 0x0003


class ADS1115:
    def __init__(self, bus, address=0x48):
        self.bus, self.address = bus, address
        self.configuration = None
        self.ready_seen = False

    def word(self, register):
        value = self.bus.readfrom_mem(self.address, register, 2)
        if len(value) != 2:
            raise OSError("Incomplete ADS1115 register")
        return (value[0] << 8) | value[1]

    def start(self, channel):
        self.configuration = config_word(channel)
        self.ready_seen = False
        self.bus.writeto_mem(self.address, 1, bytes((self.configuration >> 8, self.configuration & 255)))

    def ready(self):
        if self.configuration is None:
            raise OSError("No ADS1115 conversion started")
        word = self.word(1)
        if (word & 0x7FFF) != (self.configuration & 0x7FFF):
            raise OSError("ADS1115 conversion configuration changed")
        self.ready_seen = bool(word & 0x8000)
        return self.ready_seen

    def result(self):
        if not self.ready_seen:
            raise OSError("ADS1115 result requested before ready")
        self.ready_seen = False
        word = self.word(0)
        return word-65536 if word & 32768 else word
