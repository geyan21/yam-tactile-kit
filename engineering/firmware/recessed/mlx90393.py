"""B3 gain-5 driver; the unchanged B1 transport is packaged as mlx90393_base."""

from mlx90393_base import MLX90393 as BaseMLX90393, CONF1, CONF2
import time

SETTINGS = {"gain_sel": 5, "resolution": 1, "dig_filt": 2, "osr": 2,
            "hallconf": 12, "temperature_compensation": False}
LSB_UT = (0.501, 0.501, 0.807)  # rev012 Table 17, nominal at 25 C


class MLX90393(BaseMLX90393):
    def initialize(self):
        self.command(b"\x80", allow_reset=True)
        time.sleep(.001)
        self.command(b"\xf0", allow_reset=True)
        time.sleep(.003)
        # Replace only GAIN_SEL/HALLCONF; retain unrelated factory bits.
        conf0 = (self.read_register(0) & ~0x7F) | (5 << 4) | 0xC
        for register, value in ((0, conf0), (1, CONF1), (2, CONF2),
                                (4, 0), (5, 0), (6, 0)):
            self.write_register(register, value)
        self.expected = [conf0, CONF1, CONF2]
