# Build B2: one board for the magnetic finger

B2 keeps B1's five magnetic sensing positions, four magnets, compliant insert
and two N0 nail pads. It replaces five separate head boards and their wires
with one shaped PCB, two locating spacers and a removable backer.

This is an experimental hardware design. The fabrication receipt establishes
only the checks listed in that receipt. No assembled B2, force calibration,
20 N qualification, manufacturing yield or robot-task result is available.

[Bill of materials](../b2_bom.csv) · [PCB fabrication ZIP](../prototypes/b2/pcb/b2_main_fabrication.zip) · [Pico firmware ZIP](../prototypes/b2/b2_firmware.zip) · [Assembly drawings](../prototypes/b2/b2_review_drawings.pdf) · [Wiring diagram](../prototypes/b2/b2-wiring.svg) · [B2 page and CAD](https://geyan21.github.io/yam-tactile-kit/b2.html)

## Parts and sensor placement

| Part | Exact choice | Placement |
|---|---|---|
| S0–S3 / U1–U4 | Four MLX90393SLW-ABA-011 ICs | At the original B1 sensing poses beside the four TPU regions |
| S4 / U5 | One identical MLX90393 | Near the base at the original B1 reference pose |
| M0–M3 | Four S-03-01-N, N48, 3 × 1 mm axial magnets | Original B1 TPU pockets; north toward native +X |
| T0 / T1 | Two R1 N0 pressure-film laminates | Object-facing surfaces of the two nail prongs |
| U10 | TCA9548ARGER | Base bay on the same board; one branch selected at a time |
| U11 | ADS1115IDGSR | Same base bay; two nail signals and two reference checks |
| Pico | Raspberry Pi Pico RP2040 | Wrist or bench, joined by four bus conductors |

S0–S4 are sensor positions, not five boards in this design. TP1–TP5 are test
lands on the one PCB; **do not add a five-head wire harness**.

The controller packages use different pin-number patterns. U10 is the **RGE
QFN** version of TCA9548A; its pinout is not the TSSOP pinout. U11 is the **DGS
VSSOP** ADS1115. Use the exact BOM and assembly drawing.

The PCB component side faces the magnets and rigid frame. The backer faces
outward. The assembly manifest provides the native sensor poses and nominal
clearances. Those coordinates come from the retrieved geometry, not a physical
measurement of your installed drive.

## Check the fit before ordering or assembling a batch

1. Print the PCB fit reference, backer and both locating spacers. The PCB witness represents a 0.8 mm board; it is not a functional sensor or force part.
2. Confirm the original finger matches the source geometry. Check the root, side-fastener axes and nail shape against the real gripper.
3. Measure the two spacer shoulders and bores. The nominal shoulder is 4.85 mm OD, its bore is 3.2 mm, and the board bore is 5.0 mm. Each shoulder projects 0.65 mm into the 0.8 mm PCB. Correct an unsuitable print before clamping; do not force it through the board.
4. Check that spacer faces seat on rigid frame material. They must not squeeze a compliant TPU rib.
5. Place the board against the spacer faces, then the measured 0.10 mm seating film and backer. Use both original mounting axes with suitable nonmagnetic M3 hardware. Preserve the original finger's clamping and thread engagement. Inspect the bare board annuli and avoid bowing the PCB.
6. Check the full jaw opening range, drive housing and likely task approaches. Route the actual eight external conductors through the backer exits and check their bend and strain relief. Reported board/backer widths exclude these wires.

The new connecting webs bridge internal side windows so the single board has
usable mechanical and copper connections. The soft insert and its magnets
retain the B1 geometry. That does not prove identical loaded compliance;
measure it in the comparison.

## Fabricate and populate the PCB

Use only a package whose `pcb_checks.json` matches the fabrication ZIP and
reports no unresolved DRC violations or unconnected items. A `.step` witness
or the older B2 concept outline is not a fabrication file.

The board is 0.8 mm, four layers. Its In1 and back-layer ground pours surround
signal routes; neither is an uninterrupted shield plane. Review stackup, thin-board
handling, solder-mask registration and panelization with the fabricator.

Populate the BOM, check each pin-1 marker, and inspect every QFN exposed-pad
joint. The documented exposed-pad vias require an appropriate filled/capped
or tented process agreed with the assembler. Do not put an unreviewed open via
under stencil paste and assume its solder volume is controlled.

The source uses embedded footprints, explicit pin/net records and assembly
artwork. The generated circuit needs the same first-board power and functional
checks as a manually designed PCB.

## Connect the four-wire bus and nail leads

| Port | Pin | Signal | Destination |
|---|---|---|---|
| J1 | 1 | 3V3 | Pico 3V3 output |
| J1 | 2 | GND | Pico GND |
| J1 | 3 | SCL | Pico GP5 |
| J1 | 4 | SDA | Pico GP4 |
| J2 | 1 | 3V3 | T0 first electrode |
| J2 | 2 | T0 sense | T0 second electrode |
| J2 | 3 | 3V3 | T1 first electrode |
| J2 | 4 | T1 sense | T1 second electrode |

Solder insulated leads from the PCB's rear. Trim and inspect the component-side
ends against the available frame clearance. Fix cable strain relief to the
rigid support, keeping it away from moving TPU.

Install one 100 kΩ continuity resistor **across each nail pad at the fingertip**.
It must test both leads; a resistor placed beside the ADC would not do that.
The two PCB pull-downs are 10 kΩ. AIN2 and AIN3 each have a separate 10 kΩ/10 kΩ
divider for supply and reference checks.

Power at 3.3 V and inspect current before normal USB-powered operation. Check
SDA/SCL rise time and low levels on the assembled bus, including all pull-ups.
There are no 5 V logic connections in B2. Each MLX has address 0x0C on its own
mux branch; the mux is 0x70 and the nail ADC is 0x48.

## Firmware and recording

Generate the four-file Pico package:

```sh
/usr/bin/python3 engineering/scripts/prepare_b2_firmware.py
```

Copy `main.py`, `config.json`, `magnetic_main.py` and `mlx90393.py` from the
generated package to the Pico. The B2 entry point supplies protocol
`yam-b2/1`; it reuses the B1 acquisition implementation without modifying the
B1 program. Both nail cells are enabled in B2's complete-build configuration.
A missing or disconnected pad should be a recorded fault.

Select the actual serial port and an actual specimen ID:

```sh
/usr/bin/python3 engineering/software/prototype_record.py \
  --design B2 --port /dev/ttyACM0 --specimen B2-01 \
  --condition unloaded-motor-off --seconds 30 \
  --output results/B2-01/unloaded-motor-off.jsonl
```

The recorder never commands the gripper. It keeps raw messages, sensor timing,
configuration, faults and native-coordinate magnetic observations. Records
remain unreviewed until tied to the actual specimen and bench setup. It does
not output an invented force calibration.

## Decide whether B2 improves the gripper

Build matched B1 and B2 specimens using the same TPU process, magnet lot and
nail-pad construction. Begin with unloaded readout, contact and low-force
checks, then progress through the existing 10/15/20 N plan with the independent
reference. Test nail and soft contacts, loading/unloading, holds, motor/jaw
motion, steel proximity, cable motion and temperature. Retain failed runs.

Time assembly, rework, replacement and calibration. Include the cost of
replacing the entire board when one head fails. Three independent builds per
design are the initial pilot; one successful sample does not demonstrate
repeatable production.

Use `templates/b2_specimen.json`, `campaign/requirements.json` and the existing
B1 test conditions. B2's concrete digital benefit is a single board with fixed
head placement and four upstream bus conductors. Its force/contact performance,
repair cost and manufacturing advantage are still experimental questions.
