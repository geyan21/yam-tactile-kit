# F1 fanout — development checkpoint

This is the connector board for the proposed 64-location resistive tactile
finger. **It is one part of an unfinished F1 assembly.** The readout board,
installed flex routes, carrier and physical tests remain in development.
It establishes no contact reliability, force accuracy or 20 N rating.

The checked layout contains 42 components, 232 pads and four copper layers.
Independent KiCad 10.0.7 checking found zero rule violations and zero missing
connections. Exact evidence and artifact hashes are in `checkpoint.json`
and `checks/summary.json`.

- `pcb/`: editable native KiCad board, embedded footprints, pin table and geometry manifest.
- `checks/`: full independent DRC report and the board with refilled copper.
- `artwork/`: development Gerbers/drills, including mask, paste and silkscreen for both populated faces.
- `visuals/`: two board faces, native assembly SVGs and a PDF.
- `components.csv`: required values/packages and connector/IC identities. Passive manufacturer part selection is still open.

## Connections

`J0R`–`J5R` accept the six row foils on the outer board face.
`J0C`–`J5C` accept the six column foils on the inner face.
Each uses Hirose FH12-6S-1SH(1)(98), six positions at 1 mm pitch.
The original thin nail and four TPU patch locations are retained in the F1 plan.

`JW` is the Hirose FH12-50S-0.5SH(55) wrist link. Its 50 pin assignments are
explicit in `pcb/f1_fanout_pins.csv`. Four rows and sixteen columns each have
separate current and sense paths. All twenty zero-ohm sense links are fitted:
`RKR0`–`RKR3` and `RKC0`–`RKC15`.

`UT`, ADG706BRUZ, can connect a 10.0 kΩ test resistor from 3.3 V to a selected
column. Its enable and address inputs have 100 kΩ pull-downs. Future firmware
must park all rows at bias before enabling this electrical check and keep its
records separate from tactile observations. This checks the cable/readout
loop at the fanout, not continuity through each flexible sensor foil.

The candidate Molex 0151660545 cable has same-side contacts. Its complete
installed geometry and conductor mapping remain to be verified. Determine
the wrist-board pinout from both connector poses, then check every conductor
with power disconnected. The cable type alone does not establish pin-1-to-pin-1 wiring.

## Recheck the supplied board

From the repository root, prepare the official isolated KiCad tool if needed:

```sh
/usr/bin/python3 engineering/scripts/prepare_b1_eda.py --extract
/usr/bin/python3 engineering/scripts/check_f1_fanout.py engineering/development/f1/fanout/pcb --export
```

Checks and fresh exports go under `build/engineering/prototypes/f1/fanout_checks/`.
The supplied checkpoint is not modified.

To regenerate the geometry and routing, prepare the CAD environment and
original source meshes using `engineering/README.md`, then run:

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/check_f1_placement.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/develop_f1_fanout.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/route_f1_fanout.py ACTUAL_PLACEMENT_RUN
/usr/bin/python3 engineering/scripts/check_f1_fanout.py ACTUAL_ROUTING_RUN/board --export
```

Use the timestamped paths printed by the commands. The placement generator
also writes the reproducible alias selected by the default fanout configuration.
Each stage retains its inputs and failed attempts.

## Before an integrated prototype

The purchasing targets request 1 oz copper on all four layers. Obtain a
supplier-confirmed FR4 stack and verify the stated copper minima; default
0.5 oz inner copper is a different resistance budget. The fine features in
the screened board edge need a manufacturable contour/clearance review with
the carrier. The current drawing follows the sampled contact-access envelope.

Complete the fitted flex tails, conductor-plane unrolls, connector mating
geometry, fasteners, strain relief and actual-drive fit. Check the complete
board/cable/flex resistance network, analog stability, leakage, settling and
current/sense fault behavior. Add the wrist readout, firmware and raw acquisition.
Then fabricate specimens and perform the common contact and 20 N experiments.

The imported KiCad footprint library keeps its attribution and license in
`pcb/F1.pretty/`. Manufacturer documents are linked from the configurations;
their complete datasheets are not redistributed here.
