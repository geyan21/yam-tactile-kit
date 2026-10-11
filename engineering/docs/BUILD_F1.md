# F1: dense resistive matrix, with a separate fit and electronics packet

**F1 is still an integrated prototype in development.** Its sensor is a
0.10 mm pressure-sensitive conductive film between custom row and column
electrodes. The converter chips are on fixed electronics, not inside the
contact pads. No physical F1 finger has been built or measured here.

Use this page to reproduce the completed modules and the mechanical fit
experiment. Do not order the fitted sensor foils from the paper patterns:
they contain no electrode routing.

## Exactly what goes where

| Location | Sensor construction | What it provides |
| --- | --- | --- |
| Left nail prong, CH0 | Separate film island, four row electrodes and two column electrodes | Eight proposed electrical contact locations |
| Right nail prong, CH1 | Same construction on the second thin prong | Eight proposed locations |
| Four TPU regions, CH2–CH5 | Four separate film islands, each between four rows and three columns | Twelve proposed locations per region |
| Fixed finger side | Removable fanout with twelve Hirose FH12-6S-1SH(1)(98) connectors | Connects the twelve separate electrode foils |
| Wrist/base | Pico, OPA392 row/readout amplifiers, ADG706 current/sense multiplexers, switched gain/parking, ADS8866 ADC and reference circuit | Raw electrical acquisition |

The nail notch stays open. The two nail row foils use backside feeds;
the other ten foils use one copper layer. Nominal material targets are
25 µm polyimide, 35 µm rolled-annealed copper and 50 µm coverlay in covered
regions. Use a separate film island at each of the six sites.

The film reference is the same material class used by R1, exemplified by
[Adafruit 1361](https://www.adafruit.com/product/1361). Record the actual
supplier, lot and measured thickness. A generic conductive bag is not an
identified equivalent. Its force response, creep and lateral conduction
must be measured.

The current layer-reference geometry adds **0.455 mm at the nail** and
**0.72 mm at the TPU**, including the proposed mounting and protective
layers. Those are nominal CAD thicknesses, not measured compressed
thicknesses or a wear qualification.

## Which files are ready for which use

| Module | Ready use | Remaining limitation |
| --- | --- | --- |
| Flat electrode witnesses | Reproduce the twelve routed electrical coupons and their independent checks | Straight tails are not installed finger geometry |
| Original fanout | Inspect or fabricate the separately checked development PCB | Connector orientation differs from the R2 mechanical fit study |
| R2 fanout and carrier development | Review the revised upper connector orientation, carrier and fitted-tail interfaces | Use its own current check report; do not mix revisions |
| Wrist readout | Reproduce the checked PCB, candidate circuit and raw acquisition code | No assembled electronics or calibrated force result |
| Forming mandrels and layer bodies | Print forming tools and inspect the separate nominal layer cuts | Layer bodies are material references, not copper artwork |
| Tail fit patterns | Print at 100%, cut paper or approximately 0.1 mm polyester, and check access and routing | Connector seating, stiffeners, copper, slack and motion are unqualified |
| Circuit studies | Inspect the stated calculations and all saved failed attempts | Isolated models do not qualify the full coupled array |

The old fanout and R2 fanout are intentionally separate. The three upper
connector pairs turn toward the back in R2. The fitted-tail drawings must
be checked against R2's orientation and hole positions.

**R2's current copper route is rejected.** KiCad reports zero missing
connections and 95 violations, including a short and tracks below the
0.15 mm minimum. No R2 fabrication artwork is supplied. Use the printed
PCB reference for the mechanical experiment; do not fabricate or power
the rejected board in the routing study.

## First student build: mechanical fit

1. Print the carrier, PCB fit reference and six forming mandrels from the
   mechanical module. Keep the nominal layer and tail bodies as viewing
   references; they are not functional printed sensors.
2. Verify the original frame's two side-fastener axes. Fit the carrier to the
   rigid frame, then check the actual installed drive, housing and jaw travel.
   The exact installed drive has not been identified in this project.
3. Print each tail pattern at 100%. Measure its 50 mm scale bar before cutting.
   Mark the channel, row/column role and F.Cu side. The two foil faces point
   toward the film at the sensing patch.
4. Form each marked quarter bend smoothly. The current conductor-reference
   radius is 2.5 mm; the inner material surface is slightly smaller.
   Do not put a sharp crease at the dashed bend boundaries.
5. Fit actual FH12 connectors to a removable board or the corresponding
   placement fixture. Measure the seated tip position, contact-side
   orientation and height. The current drawings explicitly use midpoint
   assumptions for the unresolved mating datum.
6. Check all twelve tails together. Photograph the nail, both PCB faces and
   each crossing. Record rubbing, buckling, pinching and restricted access.
   A separately clear side view does not prove a clear 3D assembly.
7. Measure passive TPU displacement and tail motion before applying the
   campaign loads. The 3 mm motion allowance in the design work is an
   assumption, not a prediction at 20 N.

The carrier uses two M2 screws at the board's back edge so front standoffs do
not close the tail corridors. Support the removed board during connector
mating. Screw engagement, captive-nut fit, printed shrinkage, retention and
board bending need physical checks.

## Electronics and code

Read [F1 wiring and raw capture](F1_WRIST_CAPTURE.md) for the exact GPIO
assignment, gain/parking sequence, ADC timing and recorder commands.
The module includes `main.py`, `hardware.py`, `scan.py` and `config.json`.
The host source includes `f1_record.py` and `f1_protocol.py`.

The fifty-conductor cable contract is wrist pin **n** to fanout pin **51−n**
for the documented mating pose. Check every conductor with power off before
powering a board. The electrical test resistor checks the cable/readout at
the fanout pickup; it can pass with the tactile foils unplugged.

Firmware records raw matrix values, timestamps and separate electrical-test
observations. It leaves force and contact estimates unset. Do not substitute
the synthetic I/O checks or simulated resistance cases for physical data.

## Reproduce the digital work

Prepare the pinned source meshes and isolated CAD/KiCad tools using
`engineering/README.md`. Use the actual run directories printed by these
commands; generated results stay under `build/`.

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/develop_f1_stack_surfaces.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_f1_stack_parts.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/develop_f1_fanout_r2.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_f1_carrier.py PLACEMENT_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/develop_f1_tail_routes.py PLACEMENT_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_f1_tail_fit.py TAIL_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/check_f1_tail_fit.py FIT_RUN CARRIER_RUN STACK_RUN
```

The fit generator exports a separate developed pattern for every foil.
Curved row and column reference surfaces have different developed lengths;
copying one cut outline onto both layers is not the modeled construction.

## What would make F1 a good choice

F1 is worth comparing when dense contact location is useful enough to justify
custom flex manufacture and the extra electronics. Its current packaging is
more involved than the simpler six-zone designs. A dense map does not itself
establish reliable contact or accurate grip force.

Complete the fitted copper, mating/stiffener details, sealing, inextensible
tail slack, resistance budget and full-array/reference review. Then build
independent specimens and use the [common campaign](BUILD_ALL.md) to measure
contact errors, held-out force error through 20 N, drift, hysteresis, bending
artifacts, wear, assembly effort and precision-task access.

No measured ranking or physical winner is available yet.
