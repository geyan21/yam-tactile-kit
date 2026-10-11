"""Explicit, fixed-gain F1 bench scan with raw phase records."""


def checked_config(config):
    if config.get("schema") != "yam-f1-wrist-firmware/1":
        raise ValueError("Wrong F1 configuration schema")
    gains = config.get("gain_ids")
    if not isinstance(gains, list) or len(gains) != 64 or any(type(g) is not int or not 0 <= g <= 3 for g in gains):
        raise ValueError("Declare one gain 0-3 for every row-major matrix position")
    if type(config.get("samples_per_phase")) is not int or not 1 <= config["samples_per_phase"] <= 32:
        raise ValueError("Use 1-32 raw samples per phase")
    if type(config.get("settle_us")) is not int or not 500 <= config["settle_us"] <= 100000:
        raise ValueError("Development scan requires at least 500 us settling; this is not physical validation")
    if any(type(config.get(name)) is not int or config[name] < 10 for name in
           ("conversion_wait_us", "post_read_acquisition_wait_us")):
        raise ValueError("ADC timing is shorter than the declared driver study")
    if (type(config.get("adc_spi_hz")) is not int or not 1 <= config["adc_spi_hz"] <= 8000000
            or type(config.get("monitor_spi_hz")) is not int or not 1 <= config["monitor_spi_hz"] <= 1000000):
        raise ValueError("SPI setting exceeds this prototype's declared interface rates")
    if type(config.get("startup_wait_ms")) is not int or config["startup_wait_ms"] < 250:
        raise ValueError("Use the declared reference/ADC startup wait")
    if config.get("link_test_gain") != 1:
        raise ValueError("The development cable test window applies only to gain 1")
    expected_gpio = {"ROW0", "ROW1", "ROW2", "ROW3", "A0", "A1", "A2", "A3", "CUR_EN", "SNS_EN", "TEST_EN",
                     "GAIN0", "GAIN1", "GAIN2", "GAIN3", "PARK", "SPI_MISO", "ADC_CONV", "SPI_SCK", "SPI_MOSI", "MON_CS"}
    if set(config.get("gpio", {})) != expected_gpio:
        raise ValueError("GPIO contract is incomplete")
    if any(type(value) is not int or value not in list(range(23))+[26, 27, 28] for value in config["gpio"].values()):
        raise ValueError("GPIO assignment is not an exposed Pico pin")
    if len(set(config["gpio"].values())) != len(config["gpio"]):
        raise ValueError("GPIO assignments overlap")
    return config


class Scanner:
    def __init__(self, hardware, config):
        self.h = hardware
        self.config = checked_config(config)
        self.column = None
        self.gain = None
        self.rows = [0, 0, 0, 0]
        self.testing = False

    def rows_off(self):
        for row in range(4):
            self.h.set("ROW"+str(row), 0)
        self.rows = [0, 0, 0, 0]

    def select(self, column, gain):
        if type(column) is not int or not 0 <= column < 16 or type(gain) is not int or not 0 <= gain < 4:
            raise ValueError("Column or gain out of range")
        self.rows_off()
        self.h.set("TEST_EN", 0)
        self.testing = False
        self.h.set("PARK", 1)
        self.h.wait_us(10)
        self.h.set("CUR_EN", 0)
        self.h.set("SNS_EN", 0)
        for index in range(4):
            self.h.set("GAIN"+str(index), 0)
        for bit in range(4):
            self.h.set("A"+str(bit), (column >> bit) & 1)
        self.h.set("GAIN"+str(gain), 1)
        self.h.set("CUR_EN", 1)
        self.h.set("SNS_EN", 1)
        self.h.wait_us(10)
        self.h.set("PARK", 0)
        self.h.wait_us(self.config["settle_us"])
        self.column, self.gain = column, gain

    def phase(self):
        times, codes = [], []
        for index in range(self.config["samples_per_phase"]):
            sampled, code = self.h.read_main()
            if type(code) is not int or not 0 <= code <= 65535:
                raise ValueError("Invalid ADC word")
            times.append(sampled)
            codes.append(code)
        return {"time_us": times, "codes": codes}

    def pixel(self, frame, row, column, gain):
        if type(row) is not int or not 0 <= row < 4:
            raise ValueError("Row out of range")
        self.select(column, gain)
        baseline = self.phase()
        self.h.set("ROW"+str(row), 1)
        self.rows[row] = 1
        try:
            self.h.wait_us(self.config["settle_us"])
            active = self.phase()
        finally:
            self.rows_off()
        span = self.config["development_headroom_codes"]
        in_headroom = all(span[0] <= code <= span[1] for code in baseline["codes"]+active["codes"])
        return {"kind": "pixel", "frame": frame, "row": row, "column": column, "gain": gain,
                "baseline": baseline, "active": active,
                "inside_development_headroom": in_headroom,
                "force_n": None, "contact": None}

    def link_check(self, frame, column):
        self.select(column, self.config["link_test_gain"])
        baseline = self.phase()
        self.h.set("TEST_EN", 1)
        self.testing = True
        try:
            self.h.wait_us(self.config["settle_us"])
            active = self.phase()
        finally:
            self.h.set("TEST_EN", 0)
            self.testing = False
        drop_codes = sum(baseline["codes"])/len(baseline["codes"])-sum(active["codes"])/len(active["codes"])
        estimate = drop_codes*self.config["nominal_reference_v"]/65536
        low, high = self.config["development_link_drop_window_v"]
        return {"kind": "column_link_check", "frame": frame, "column": column, "gain": self.gain,
                "baseline": baseline, "test_enabled": active, "nominal_drop_v": estimate,
                "inside_development_window": low <= estimate <= high,
                "qualified_fault_coverage": False, "tactile_observation": False}

    def capture_frame(self, frame, emit):
        self.h.park()
        self.rows_off()
        started = self.h.time_us()
        emit({"kind": "frame_begin", "frame": frame, "time_us": started,
              "expected_pixels": 64, "expected_column_checks": 16})
        emit({"kind": "monitor", "frame": frame, "time_us": self.h.time_us(),
              "codes": self.h.read_monitors(), "remote_row_voltage_measurement": False})
        for column in range(16):
            emit(self.link_check(frame, column))
            for row in range(4):
                emit(self.pixel(frame, row, column, self.config["gain_ids"][row*16+column]))
        self.h.park()
        emit({"kind": "frame_end", "frame": frame, "time_us": self.h.time_us(),
              "elapsed_us": self.h.time_us()-started, "pixels": 64, "column_checks": 16,
              "physical_force_calibration": False})
