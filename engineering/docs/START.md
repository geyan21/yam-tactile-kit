# Student starting packet

Start with [the separate design pages](https://geyan21.github.io/yam-tactile-kit/designs.html). [R1](https://geyan21.github.io/yam-tactile-kit/r1.html), [L1](https://geyan21.github.io/yam-tactile-kit/l1.html) and [B1](https://geyan21.github.io/yam-tactile-kit/b1.html) have prototype build packages. The directory marks concepts and reference-only approaches separately.

**First deliverable: one instrumented finger and a reproducible bench record.** Keep a second, unmodified finger as the control. Start off the robot.

**First read [which sensors to use and exactly where to place them](SENSORS.md).** It gives the concrete B1 recommendation, labels every sensing location and explains how the retained R1 and L1 alternatives differ.

R1 prioritizes detecting contact near the thin nail while preserving the existing hard frame. It is a cheap-to-iterate transducer candidate. Its drift, cover adhesion, wiring life, and force accuracy need measurement before it can be selected as the scalable design.

L1 is the complementary force experiment: a purchased strain-gauge cell in the complete finger load path. Begin its independent cell/plate tests alongside the R1 nail test. Machine the L1 gripper carrier only after the printed housing fit and cell moment tests pass. Use [Build L1](BUILD_L1.md), [L1 wiring](L1_ELECTRONICS.md) and [L1 test instructions](L1_TESTING.md).

B1 is the separate bending-aware design. It retains the thin hard nail and compliant TPU outside profile, adds four internal magnets, and uses fixed magnetic sensor heads. Start with [B1 assembly](BUILD_B1.md), [PCB and readout](B1_ELECTRONICS.md), and [an original-vs-B1 compliance comparison](B1_TESTING.md). Keep R1/L1 and an unmodified insert as controls. B1 does not include a force calibration or a B1 contact classifier without physical data.

## Choose the first bench deliverables

| Build | First deliverable | What it resolves |
|---|---|---|
| R1 thin nail laminate | Two N0 nail cells with raw low-force and coverage records | Can a thin, replaceable surface detect the contacts that matter? |
| L1 independent load cell | Cell/plate calibration with all displaced loads held out | Can this inexpensive force element tolerate the actual finger lever envelope? |
| L1 integrated finger | Aluminum carriers and a separate finger test using the same cell sensitivity | Does installation preserve useful force feedback at nail and TPU contacts? |
| B1 compliant insert | Modified TPU, retained magnets and fixed sensor heads with raw records | Does sensing preserve useful bending, return position and thin-tip access? |

## What to obtain

Use the exact parts and quantities in `engineering/bom.csv` for R1 and [the L1 parts list](../l1_bom.csv) for the root-force build. R1 needs a Raspberry Pi Pico, two ADS1115 breakout boards, ten 10 kΩ resistors, thin insulated wire, copper foil, polyimide tape, and 0.10 mm pressure-sensitive conductive film. Mechanical work needs the current ENPIRE finger, PETG mold tooling, silicone, and a calibrated force reference.

The requested range is **20 N per finger**. Use a reference with at least 25 N capacity and **stated uncertainty no worse than 0.05 N** over the tested range. Display resolution alone does not establish that. A suitable calibrated force gauge is preferable. A scale can be used for static vertical tests if its calibration, tare, orientation, and force conversion are documented.

The catalog listing for Adafruit 1361 conductive film was out of stock when checked on 2026-10-10. Treat it as the reference specification; obtain an equivalent uncreased 0.10 mm conductive film and record its manufacturer and lot. A substitution is a new material instance.

## First session

1. Download and print the cut sheet at 100%. Measure its 20 mm scale bar. Compare the nail silhouette and 21 mm mounting-pitch gauge with your finger.
2. Record the actual hard/soft source files, caliper measurements, and printer settings in `engineering/templates/specimen.json`. Photograph the unmodified contact side with a ruler.
3. Build the readout. Substitute a 10 kΩ resistor for each sensing cell. Each input should report about 100 µS. Both an open lead and a short must raise a fault. The completed cells each carry a 100 kΩ continuity resistor at their foil terminals.
4. Assemble only the two N0 nail cells first: the sealed insulating laminate without the additional silicone cover. This check needs no casting. Check each center and leading edge and record the added thickness. Compare the N1 silicone-covered variant later.
5. Cast and install the four saddle cells. Check all six individually, then move the finger through its passive compliance range while watching the signals.
6. Check 0–5 N first, then complete the 0–20 N qualification protocol with an appropriate contact fixture. Preserve rejected trials as well as accepted ones. A 5 N pass is preliminary only.

## Return these results

Provide the completed specimen sheet, source CAD hashes, assembly photographs, `session.json`, `trials.jsonl`, all raw trial files, and the calibration report. Include failures: delamination, saturated channels, inaccessible contact regions, or a cut pattern that does not fit.

The next revision depends on those measurements. If the nail cover defeats thin-edge tasks, reduce or replace the cover. If resistive drift fails the force criterion, evaluate it for contact location alongside L1's separately measured aggregate force. Do not solve either design's failures by relabelling software output as calibrated force.

Use [the shared contact protocol](CONTACT.md) after the finger is assembled. It supplies a setup template, randomized plans, a frozen-threshold workflow and live contact monitoring for both readouts. Keep the first short run labeled as a pilot; larger reliability claims require the corresponding evidence.
