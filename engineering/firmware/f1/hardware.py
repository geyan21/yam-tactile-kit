"""Pico sensor-only I/O for the F1 wrist prototype. No actuator interface."""

from machine import Pin, SPI
from time import sleep_us, sleep_ms, ticks_us, ticks_diff


class Hardware:
    def __init__(self, config):
        self.config = config
        gpio = config["gpio"]
        # Establish the parked state before enabling any current/sense path.
        self.outputs = {"PARK": Pin(gpio["PARK"], Pin.OUT, value=1)}
        for name in ("ROW0", "ROW1", "ROW2", "ROW3", "GAIN0", "GAIN1", "GAIN2", "GAIN3",
                     "CUR_EN", "SNS_EN", "TEST_EN", "A0", "A1", "A2", "A3"):
            self.outputs[name] = Pin(gpio[name], Pin.OUT, value=0)
        self.mon_cs = Pin(gpio["MON_CS"], Pin.OUT, value=1)
        self.conv = Pin(gpio["ADC_CONV"], Pin.OUT, value=1)
        self.spi = SPI(0, baudrate=config["adc_spi_hz"], polarity=0, phase=0,
                       bits=8, firstbit=SPI.MSB,
                       sck=Pin(gpio["SPI_SCK"]), mosi=Pin(gpio["SPI_MOSI"]),
                       miso=Pin(gpio["SPI_MISO"], Pin.IN, Pin.PULL_DOWN))
        self._mode = "main"
        self._last_tick = ticks_us()
        self._elapsed = 0
        self._main_buffer = bytearray(2)
        self._mon_tx = bytearray(3)
        self._mon_rx = bytearray(3)
        sleep_ms(config["startup_wait_ms"])

    def time_us(self):
        now = ticks_us()
        delta = ticks_diff(now, self._last_tick)
        if delta < 0:
            raise RuntimeError("Device clock interval is ambiguous; restart this capture")
        self._elapsed += delta
        self._last_tick = now
        return self._elapsed

    def set(self, name, value):
        if name not in self.outputs or value not in (0, 1):
            raise ValueError("Unknown sensor output or logic value")
        self.outputs[name].value(value)

    def wait_us(self, duration):
        sleep_us(duration)

    def read_main(self):
        if self._mode != "main":
            self.mon_cs.value(1)
            self.spi.init(baudrate=self.config["adc_spi_hz"], polarity=0, phase=0)
            self._mode = "main"
        # A falling edge may expose an unused previous conversion. The next
        # rising edge starts the requested sample and tri-states DOUT.
        self.conv.value(0)
        sleep_us(1)
        sampled = self.time_us()
        self.conv.value(1)
        sleep_us(self.config["conversion_wait_us"])
        self.conv.value(0)
        self.spi.readinto(self._main_buffer, 0)
        code = (self._main_buffer[0] << 8) | self._main_buffer[1]
        # DOUT is high impedance after clock 16. Keep CONVST low and allow
        # acquisition; raising it here would start another conversion.
        sleep_us(self.config["post_read_acquisition_wait_us"])
        return sampled, code

    def read_monitors(self):
        self.mon_cs.value(1)
        self.conv.value(1)  # Discard this conversion; maintain DOUT high-Z.
        sleep_us(self.config["conversion_wait_us"])
        self.spi.init(baudrate=self.config["monitor_spi_hz"], polarity=0, phase=0)
        self._mode = "monitor"
        values = []
        for channel in range(8):
            self._mon_tx[0] = 0x06 | (channel >> 2)
            self._mon_tx[1] = (channel & 3) << 6
            self._mon_tx[2] = 0
            # These are coarse monitor readings, not precision remote senses.
            # Preserve the final raw code after a discarded acquisition.
            for attempt in range(2):
                self.mon_cs.value(0)
                self.spi.write_readinto(self._mon_tx, self._mon_rx)
                self.mon_cs.value(1)
                sleep_us(100)
            values.append(((self._mon_rx[1] & 0x0f) << 8) | self._mon_rx[2])
        return values

    def park(self):
        for row in range(4):
            self.set("ROW"+str(row), 0)
        self.set("TEST_EN", 0)
        self.set("PARK", 1)
        self.set("CUR_EN", 0)
        self.set("SNS_EN", 0)
        for gain in range(4):
            self.set("GAIN"+str(gain), 0)
        self.mon_cs.value(1)
        self.conv.value(1)
