# R1 electronics and data collection

R1 uses six independent voltage dividers. This avoids matrix scan ghost paths in the first material experiment. It does not remove drift, hysteresis, or mechanical cross-coupling.

## Wire the readout

Use two **ADS1115**, not ADS1015, breakout boards at 3.3 V. The [TI ADS1115 data sheet](https://www.ti.com/lit/ds/symlink/ads1115.pdf) defines the single-ended inputs, configuration register, and 860 conversions/s maximum. That number is not the complete eight-channel frame rate.

| Pico connection | Connect to |
|---|---|
| 3V3 OUT, physical pin 36 | Both ADC VDD pins and sensor excitation |
| GND, e.g. physical pin 38 | Both ADC GND pins and every divider ground |
| GP4, physical pin 6 | Both SDA pins |
| GP5, physical pin 7 | Both SCL pins |
| USB | Bench computer only |
| ADC U1 ADDR | GND: address 0x48 |
| ADC U2 ADDR | 3.3 V: address 0x49 |

Consult the selected [Pico board pinout](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html) before wiring. Use the board's 3.3 V output, not VBUS. Breakout pullups must terminate at 3.3 V. Keep the I²C wiring short during bring-up.

For each sensor: **3.3 V → sensor → measurement node → 10 kΩ → GND**. Connect the measurement node to its ADC input. Add a **100 kΩ resistor in parallel with the film at the cell's two foil terminals**, outside its active contact patch. All resistor grounds and sensor excitation connections are common.

The cell-end resistor provides a known unloaded conduction path through both leads. Placing it at the ADC board would not check lead continuity. Reported conductance includes this resistor; keep it fitted during calibration and use.

| Channel | ADC input | Region |
|---|---|---|
| CH0 | U1 A0 | Negative-U nail tine |
| CH1 | U1 A1 | Positive-U nail tine |
| CH2 | U1 A2 | Distal TPU saddle |
| CH3 | U1 A3 | Mid-distal saddle |
| CH4 | U2 A0 | Mid-proximal saddle |
| CH5 | U2 A1 | Proximal saddle |
| Excitation monitor | U2 A2 | Midpoint of a separate 10 kΩ / 10 kΩ supply divider |
| Electrical check | U2 A3 | Midpoint of another 10 kΩ / 10 kΩ divider |

Ten 10 kΩ resistors are required: six cell pull-downs and four for the two reference dividers. Six additional 100 kΩ resistors go at the cell terminals. Use 1% or better and record actual values if absolute conductance matters.

## Firmware

Install stable MicroPython for the RP2040 Pico using its BOOTSEL USB method, then copy `engineering/firmware/r1/main.py` to the board as `main.py`. Follow the [MicroPython RP2 getting-started guide](https://docs.micropython.org/en/latest/rp2/tutorial/intro.html). Record the firmware version used.

Copy `config.json` as well as `main.py` to the Pico. It records the six physical pull-down resistor values. The firmware starts single-shot conversions on both ADCs for one input index at a time. It verifies configuration, waits for conversion-ready, and reports a missing conversion as a fault. Each JSON line carries eight raw counts, resistor values, sequence number, device time, per-channel acquisition offsets, scan time, and errors. The 50 Hz frame setting is a target to verify on hardware.

For example, install `mpremote==1.29.0` and `pyserial==3.5` in a dedicated bench virtual environment. The BOOTSEL drive accepts the MicroPython UF2 firmware; it is not where `main.py` is copied. Use [mpremote's serial filesystem commands](https://docs.micropython.org/en/latest/reference/mpremote.html) on the explicitly selected, dedicated Pico:

```sh
/path/to/bench-python -m mpremote connect /dev/ttyACM0 fs cp engineering/firmware/r1/config.json :config.json
/path/to/bench-python -m mpremote connect /dev/ttyACM0 fs cp engineering/firmware/r1/main.py :main.py
/path/to/bench-python -m mpremote connect /dev/ttyACM0 reset
```

These commands replace the two named files and restart that Pico. Back up any existing project on it first. Disconnect the firmware console before opening the bench recorder.

No automatic tare is performed. Booting while touching an object must not erase contact. No robot commands are sent.

## Electrical check

Run the bounded monitor to see all six electrical readings and save the raw stream:

```sh
/path/to/bench-python engineering/software/monitor.py \
  --port /dev/ttyACM0 --seconds 60 --output results/electrical-check-01.jsonl
```

Temporarily use a 10 kΩ resistor as each sensor. A node should be close to half the measured excitation; the decoded conductance should be about 100 µS. Check all six channels, not only the two reference dividers. The excitation estimate should be approximately 3.3 V.

With the completed cell attached and unloaded, its conductance should remain at least near the 10 µS continuity path. Disconnect and short one cell in turn: both must raise faults. The parallel resistor checks the leads, not the film's pressure response; perform an actual touch check before each session. When testing only two nail cells, temporarily terminate unused inputs with 100 kΩ from the input to 3.3 V so their open channels do not invalidate the frame.

At 20 N, a cell may become too conductive for a 10 kΩ pull-down. If its node exceeds 98% of the measured supply, reduce that channel's physical resistor to 1 kΩ, or 330 Ω if needed, and update `config.json`. Recheck low-force sensitivity. A resistor change starts a new calibration session; the analysis rejects mixed resistor configurations. Saturated readings must not be clipped and reported as 20 N.

## Record physical trials

Install `pyserial==3.5` in a dedicated bench environment. Select the exact device path; the recorder does not scan or open arbitrary serial devices. Use your organization's normal device-access permissions.

```sh
/path/to/bench-python engineering/software/bench.py \
  --port /dev/ttyACM0 --output results/R1-A01-session1 \
  --specimen R1-A01 --material DS10-0p4-lotA \
  --operator student --reference-id gauge-calibration-record \
  --reference-uncertainty-n 0.05 \
  --probe "recorded flat contact fixture, local normal" --max-force-n 20
```

The program prompts for actual reference-force readings, waits one second, records two seconds, then asks for the end reading. It saves raw frames and accepted/rejected trial records. Use `--max-force-n 5` for the first low-load check; this does not qualify the requested 20 N range. `q` or Ctrl-C stops and preserves completed data. Existing session directories are refused.

```sh
/path/to/bench-python engineering/software/calibrate.py \
  results/R1-A01-session1 \
  --output results/R1-A01-session1/calibration.json
```

The report is restricted to that specimen and configuration. Its static fit does not validate closed-loop robot behavior.
