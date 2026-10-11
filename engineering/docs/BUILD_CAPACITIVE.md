# K1: capacitive cells on the ENPIRE finger

**K1 has cell tooling, conforming supports, a checked readout PCB and raw
acquisition code. The complete tactile finger remains unfinished.**
There are no physical specimens or measured 20 N results.

The sensor is a compression capacitor. A patterned SYLGARD 184 sheet sits
between a covered sensing electrode and a grounded stainless spreader.
Compression changes capacitance. The FDC1004 converts that electrical
response; it does not supply a calibrated force value by itself.

![Cell positions](../development/capacitive/k1/visuals/k1_cell_placement.png)

## Exactly what to use and where

| Location | Selected development construction | Readout connection |
| --- | --- | --- |
| Left nail, CH0 | One thin compression cell over the nail face | Board A, JS0 |
| Right nail, CH1 | A separate cell on the other prong; keep the notch open | Board B, JS0 |
| Distal TPU, CH2 | Cell on its conforming rigid support | Board A, JS1 |
| Next TPU region, CH3 | Separate cell and support | Board A, JS2 |
| Next TPU region, CH4 | Separate cell and support | Board B, JS1 |
| Proximal TPU, CH5 | Separate cell and support | Board B, JS2 |
| Protected reference, two copies | Unloaded post-sheet capacitor at each readout board | Its board's JREF / CIN4 |
| Readout boards, two copies | FDC1004DGSR plus ADS1115IDGSR and passive components | Fixed electronics away from the contact surfaces |

![Capacitive stack](../development/capacitive/k1/visuals/k1_stack.svg)

The molding target is a **0.05 mm base with 0.15 mm high, 0.60 mm diameter
posts**. The proposed spreader is 0.30 mm stainless. The requested two-copper
flex stack is 0.136 mm including its core and coverlays. These are manufacturing
targets and nominal geometry, not measurements of delivered parts.

Use [Dow SYLGARD 184](https://www.dow.com/en-us/pdp.sylgard-184-silicone-elastomer-kit.01064291z.html)
at the manufacturer's 10:1 ratio. The candidate cure is 100 °C for 35 minutes
after the part reaches temperature. Use compatible metal/glass tooling for
that process and record the actual cure and dimensions.
The [bulk-material study](https://uhra.herts.ac.uk/id/eprint/3211/1/906746.pdf)
shows why cure and loading mode matter; its tensile modulus is not a
calibration of these small compression posts.

The nominal nail addition is **0.786 mm**. The TPU figure of **1.736 mm is above
the R1 smoothed-saddle datum**; the conforming fitting base lies below that
datum. It is not the total addition to bare TPU. Compare actual task access
with the thinner alternatives before selecting this approach.

## Files available now

Use the [module scope and file list](../development/capacitive/k1/README.md)
and [current parts table](../development/capacitive/k1/parts.csv).

The current set contains 49 STEP/STL parts. It includes seven casting patterns
(the reference is used twice), laser stencils, backing spacers, shaped metal
spreaders, forming tools, electrode/cover envelopes and the corrected
conforming supports. Six formed post-sheet STL files are additional viewing
references. Use the flat casting masters for manufacture.

The four earlier slab-only supports remain in `history/`. The current supports
reach the retained TPU fitting geometry and reserve a 0.05 mm flex bond.
Their eighteen declared source/peer/electrode comparisons pass. Print and fit
them on the actual finger before committing to the complete assembly.

The electrode envelopes are not copper artwork, and printing them does not
produce a functional capacitor. Stops, retention, vents/sealing, grounded
spreader joints, the guarded cable installation and enclosure remain.

## PCB, wiring and code

![Readout layout](../development/capacitive/k1/visuals/k1_readout.png)

One board has 23 components and serves three pressure cells plus a reference.
Build two copies using the
[component list](../development/capacitive/k1/pcb_components.csv),
[native pin table](../development/capacitive/k1/pcb/k1_readout_pins.csv)
and checked artwork. KiCad reports zero violations and zero missing connections.
The declared 0.15 mm spacing applies only between native package pads;
routed clearances remain 0.20 mm, with 0.25 mm via drills.

| Interface | Pin order |
| --- | --- |
| JP | 1 = 3V3, 2 = GND, 3 = SDA, 4 = SCL |
| JS0 / JS1 / JS2 | 1 = CIN, 2 = driven SHLD1, 3 = ground drive to the spreader, 4 = independent ground return |
| JREF | 1 = CIN4, 2 = SHLD2, 3 = GND, 4 = GND |

The two spreader-ground connections must be separate physical bonds so the
health loop passes through the metal plate. The driven shield is separate
from ground. Cable design and termination details still need completion.
[TI's FDC1004 data sheet](https://www.ti.com/lit/ds/symlink/fdc1004.pdf)
describes the shielding and differential-input requirements.

Connect board A to Pico GP0/GP1 and board B to GP2/GP3 for SDA/SCL respectively.
Both use address 0x50 for FDC1004 and 0x48 for ADS1115, so they require separate
buses. Use the Pico's 3V3 output and ground.

Copy all four files from `engineering/firmware/capacitive/` to the dedicated
bench Pico. The code reads differences against CIN4, then the reference
itself. It records raw words and separate sample times. The host decoder
checks configuration, supply, ground loops, missing/stale data and coarse
capacitance plausibility. No contact or force inference is enabled.

```sh
/usr/bin/python3 -m venv build/engineering/tools/k1-capture-venv
build/engineering/tools/k1-capture-venv/bin/python -m pip install pyserial==3.5
build/engineering/tools/k1-capture-venv/bin/python engineering/software/capacitive_record.py \
  --port PORT --specimen ID --condition CONDITION \
  --seconds 30 --output NEW_RECORDING.jsonl
```

Replace the port and identifiers with the actual setup. Keep raw recordings,
failed readings, specimen identity, reference-load measurements and photos.
Capacitance plausibility cannot guarantee detection of every cable fault.

## First student work and qualification

1. Inspect the actual printed support fit, post height/diameter, base thickness
   and formed spreader curvature. Record shrinkage and springback.
2. Bring up the readout independently with measured fixed capacitors. Label
   those records as electronics tests; they are not tactile measurements.
3. Complete the electrode, stop, retention, vent, bond and cable details.
   Keep electrode contacts insulated and the reference protected from load.
4. Measure unloaded noise, drift, cable movement and all wire-disconnection
   cases before fitting a contact threshold.
5. Calibrate independent specimens with the common reference loads and probe
   shapes through 20 N. Record bottoming, loading/unloading differences,
   temperature effects, no-contact bending, tip movement and precision tasks.
6. Evaluate held-out specimens/sessions using the [all-design campaign](BUILD_ALL.md).

The uniform post model fits the converter range in its stated scenarios.
Its revised shield-load estimates are about 336 and 373 pF. These calculations
omit finite plate loading, friction, viscoelasticity and measured parasitics;
they do not establish force accuracy or reliable grasping.

## Reproduce the current digital modules

For a fresh Linux checkout, prepare the project-local tools and source solids.
The shared structural-tool cache supplies Gmsh for the post-sheet surface mesh.
Keep the supplied R1 release files as the retained geometry basis.

```sh
/usr/bin/python3 engineering/scripts/collect_geometry_sources.py
/usr/bin/python3 engineering/scripts/prepare_environment.py
/usr/bin/python3 engineering/scripts/prepare_b1_eda.py --extract
/usr/bin/python3 engineering/scripts/prepare_c1_fea.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/prepare_source_brep.py --part hard_frame
```

The generation commands print fresh output directories; use those exact directories
for `CELLS`, `PLACEMENT`, `NATIVE` and `ROUTE` below.

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/screen_capacitive_k1.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_capacitive_k1_parts.py --reference
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_capacitive_saddles.py CELLS
/usr/bin/python3 engineering/scripts/design_capacitive_board.py
build/engineering/tools/b1-kicad/AppDir/bin/python3.11 engineering/scripts/write_capacitive_board.py PLACEMENT/specification.json NATIVE
/usr/bin/python3 engineering/scripts/check_prototype_pcb.py NATIVE --name k1_readout --kicad-cli build/engineering/tools/b1-kicad/AppDir/bin/kicad-cli
build/engineering/tools/cad-venv/bin/python engineering/scripts/route_capacitive_board.py NATIVE
build/engineering/tools/b1-kicad/AppDir/bin/python3.11 engineering/scripts/write_capacitive_board.py PLACEMENT/specification.json ROUTE/native --routing ROUTE/routing.json
/usr/bin/python3 engineering/scripts/check_prototype_pcb.py ROUTE/native --name k1_readout --export --kicad-cli build/engineering/tools/b1-kicad/AppDir/bin/kicad-cli
/usr/bin/python3 engineering/scripts/verify_capacitive_checkpoint.py
```
