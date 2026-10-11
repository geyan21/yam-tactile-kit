# F1 wrist capture — development instructions

This is the code and wiring contract for the planned F1 wrist board.
**The integrated F1 finger is unfinished and no physical F1 measurements
exist.** Circuit simulations and synthetic software checks do not establish
contact reliability, force accuracy or a 20 N rating.

The tactile element is the 0.10 mm pressure-sensitive conductive film
between patterned flexible electrodes. It belongs on the two nail patches
and four TPU patches. The film/electrodes form four rows and sixteen columns.
The amplifiers, ADC and Pico described here belong on the **separate wrist
board**. The finger's fixed fanout board connects the twelve foils to that
readout. Installed foil shapes, tails and the carrier are still being completed.

## Circuit identities

| Function | Selected candidate | Placement |
|---|---|---|
| Four row drivers | Four OPA392DBVR plus one TMUX1134PWR | Wrist board; buffer after each row-selection switch |
| Column current and voltage sense | Two ADG706BRUZ | Wrist board; both select the same column |
| Current amplifier | OPA392DBVR | Wrist board; separate current/sense feedback |
| Gain selection | TMUX1112PWR | Wrist board; select one of 499 Ω, 4.99 kΩ, 24.9 kΩ or 39.2 kΩ |
| Local parking / gain compensation | TMUX1101DBVR / TMUX1102DBVR | Wrist board, at the current amplifier |
| Main ADC and buffer | ADS8866IDGSR, OPA320AQDBVRQ1 | Wrist board; three 2.2 nF C0G filter capacitors and two 22 Ω series resistors |
| Reference | REF6033IDGKR | Wrist board; check output-capacitor derating and total ESR |
| Coarse electrical monitors | MCP3208-B/SL | Wrist board; local amplifier voltages, bias and divided supplies |
| Controller | Raspberry Pi Pico, RP2040, non-W | Two 1×20 sockets on the wrist board |

The single OPA392 ordering code is **OPA392DBVR**. The current manufacturer
OPA320 model identifies the Q1 family; the ADC-buffer candidate uses the
matching **OPA320AQDBVRQ1**.

TMUX1134 has no global enable pin. Its B inputs receive bias; A inputs
receive excitation. Four select pull-downs keep the rows at bias during
controller reset. The row amplifiers use 47 Ω output isolation, 4.7 kΩ sense
input resistors, 100 pF local feedback and 100 MΩ weak local feedback.

The nominal reference is 3.3 V. Separate dividers/buffers produce
approximately 1.65 V bias and 1.70 V excitation. Divider tolerance, buffer
offset, reference stability and the actual mounted array require measurements.
The 47 mΩ resistor at the reference is in series with its output capacitor.
Confirm at least 10 µF effective capacitance and the specified total ESR
before approving the reference implementation.

## Pico connections

Use the board's two socket pin tables, generated from the physical Pico
header numbering. These are GPIO numbers:

| Signals | GPIO |
|---|---|
| ROW0–ROW3 | GP0–GP3 |
| Column address A0–A3 | GP4–GP7 |
| Current-mux enable / sense-mux enable / column test | GP8 / GP9 / GP10 |
| GAIN0–GAIN3 | GP11–GP14 |
| PARK | GP15 |
| SPI receive / main ADC CONVST | GP16 / GP17 |
| SPI clock / SPI transmit / monitor chip select | GP18 / GP19 / GP20 |

Pico physical pin 40 supplies USB VBUS to the reference circuit.
Physical pin 36 supplies 3.3 V to the readout. The Pico's onboard regulator
is the selected 3.3 V source. Its unused VSYS, regulator-enable and ADC-reference
socket positions are left unconnected by this design.

The 50-contact cable uses the mating contract in `f1_wrist_development.json`.
For the identical bottom-contact connectors and selected same-side-contact
FFC, **wrist pin n corresponds to fanout pin 51−n** in the stated inspection
pose. The native connector-coordinate check supplies a complete continuity
checklist. That calculation does not measure actual continuity or verify the
installed cable route.

## Firmware files

`engineering/firmware/f1/` contains four files:

- `hardware.py`: GPIO, ADS8866 transactions and MCP3208 monitor transactions.
- `scan.py`: explicit row/column/gain sequencing and raw phase records.
- `main.py`: repeated capture with frame/configuration announcements.
- `config.json`: generated GPIO, timing, gain and development-check settings.

Generate a matching copy and four-file ZIP from the repository root:

```sh
/usr/bin/python3 engineering/scripts/prepare_f1_firmware.py
```

The command prints a new directory under
`build/engineering/prototypes/f1/firmware_runs/`. It does not connect to or
program a board. Copy the four files together to the selected Pico's
MicroPython filesystem when the hardware is ready for bench checks.
Record the firmware/configuration hashes with the specimen.
The API review used the
[MicroPython v1.26 RP2 reference](https://docs.micropython.org/en/v1.26.0/rp2/quickref.html)
and [SPI interface documentation](https://docs.micropython.org/en/v1.26.0/library/machine.SPI.html).
Record the actual MicroPython build used on the board; it has not been
exercised on physical hardware in this workspace.

The initial configuration uses **gain 0 at all 64 positions**. It gives the
broadest current span; it is not a validated contact setting. Inspect raw
noise and saturation using known electrical loads and physical force trials,
then deliberately change `gain_ids`. Its index is `row*16+column`. Preserve
each tested configuration. This development firmware has no automatic
force calibration or automatic gain selection.

The default 500 µs settling delay is a starting bench choice. The complete
coupled array, reference, layout and switching have not yet been shown to
settle within that delay.

## What one frame records

Every frame is preceded by a `hello` containing the full configuration.
That lets a recorder attach without resetting or sending commands to the
board. A frame then contains:

1. `frame_begin`.
2. One block of eight coarse monitor codes.
3. Sixteen separately labeled column-link tests.
4. Sixty-four pixel records, each containing baseline and excited raw ADC
   codes, per-sample device times, row, column and gain.
5. `frame_end`, including elapsed scan time.

Each pixel's baseline has all rows at bias. Only its selected row is then
excited. Address/gain changes occur while PARK is closed and the column
multiplexers are disabled. A one-hot gain is selected before enabling the
paths and releasing PARK. Excitation is removed after each observation.

ADS8866 uses three-wire CS mode with DIN tied high. The code waits 10 µs
for conversion, clocks sixteen bits at the selected 8 MHz setting, and
allows another 10 µs of acquisition. CONVST remains low after the read.
Before monitor traffic, an extra conversion is deliberately discarded while
CONVST is held high so the main ADC's data output remains high impedance.
Actual SPI timing and settling still require oscilloscope/logic-analyzer checks.

`inside_development_headroom` is a range observation.
`inside_development_window` compares a column test with the provisional
0.70–0.95 V drop window. Neither flag means that a sensor has passed physical
qualification.

The column test reaches the fanout's current/sense pickup. **It can pass with
the sensor foils unplugged.** It does not prove foil continuity, row-wire
continuity, correct film assembly, force accuracy or arbitrary fault coverage.
The code marks these records `tactile_observation: false`.

Pixel fields `force_n` and `contact` remain null until a separate measured
calibration/validation method exists.

## Record a real bench session

Use an environment with `pyserial`, a new output path, the actual specimen
identifier and that build's assembly manifest:

```sh
/usr/bin/python3 engineering/software/f1_record.py \
  --port ACTUAL_SENSOR_PORT \
  --specimen ACTUAL_SPECIMEN_ID \
  --condition ACTUAL_TEST_CONDITION \
  --geometry ACTUAL_ASSEMBLY_MANIFEST.json \
  --seconds 30 \
  --output results/f1/NEW_CAPTURE.jsonl
```

Use `--source-kind electrical_dummy` for resistor/load-box checks.
The physical option produces **unreviewed physical recording** metadata,
not proof of force performance. No live recording or programming was
performed while preparing these files.

The recorder writes raw messages, host receive times, structural validation
and a final receipt hash. It preserves malformed records and unfinished
frames. A complete matrix frame requires every distinct pixel and every
column check. Duplicates, stale sample times, wrong gains and mislabeled
electrical tests are rejected or flagged. Host backpressure changes timing;
retain per-sample times and frame duration when analyzing motion trials.

## Checks performed and remaining

Nine checks using synthetic I/O cover configuration bounds, switching
restrictions, ADC/monitor bus timing, excitation cleanup after read errors,
complete matrix membership, stream synchronization and exclusion of
electrical tests from tactile data. These checks do not exercise a physical
Pico, ADC, sensor film or gripper.

Finish and independently check the routed PCB, complete circuit/reference
and array models, fitted flexible electrodes, carrier and cable geometry.
Then verify supplies, actual waveforms, continuity and controlled faults
before collecting the common contact/force experiments through 20 N per
finger. Preserve missing, saturated and failed measurements.

Manufacturer references:
[Pico pinout](https://datasheets.raspberrypi.com/pico/Pico-R3-A4-Pinout.pdf),
[Pico datasheet](https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf),
[ADS8866](https://www.ti.com/lit/ds/symlink/ads8866.pdf),
[OPA392](https://www.ti.com/lit/ds/symlink/opa392.pdf),
[OPA320-Q1](https://www.ti.com/lit/ds/symlink/opa320-q1.pdf),
[REF60](https://www.ti.com/lit/ds/symlink/ref60.pdf),
[TMUX1134](https://www.ti.com/lit/ds/symlink/tmux1134.pdf).
