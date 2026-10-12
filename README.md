# ENPIRE / YAM tactile engineering study

[**Design directory — one clear page per design**](https://geyan21.github.io/yam-tactile-kit/designs.html): [R1](https://geyan21.github.io/yam-tactile-kit/r1.html), [L1](https://geyan21.github.io/yam-tactile-kit/l1.html), [B1](https://geyan21.github.io/yam-tactile-kit/b1.html), [B2](https://geyan21.github.io/yam-tactile-kit/b2.html), [C1](https://geyan21.github.io/yam-tactile-kit/c1.html), [rigid nail](https://geyan21.github.io/yam-tactile-kit/rigid-nail.html), and the separately labeled alternatives. Every page includes sensor choice, placement, files, status and next steps.

[Visual website](https://geyan21.github.io/yam-tactile-kit/) · [Which sensors go where](engineering/docs/SENSORS.md) · [Build B1](engineering/docs/BUILD_B1.md) · [Student starting packet](engineering/docs/START.md) · [Build R1](engineering/docs/BUILD_R1.md) · [Build L1](engineering/docs/BUILD_L1.md)

The goal is **reliable contact and grip-force feedback through 20 N per finger**, while retaining the thin ENPIRE nail for precise manipulation.

[Build and compare all twelve designs](engineering/docs/BUILD_ALL.md) tracks the full campaign and common test targets. [B2.1](engineering/docs/BUILD_B2.md) has a routed PCB, checked mounting parts and raw acquisition package. [C1.1](engineering/docs/BUILD_C1.md) adds a metal strain root, eight selected gauges, readout PCB and physical calibration tools. The [architecture study](engineering/docs/ARCHITECTURE.md) retains the earlier B2/C1 concepts and research evidence.

**Concrete B1 prototype recommendation:** five MLX90393SLW-ABA-011 heads fixed beside four magnets embedded in the bending TPU, plus two thin N0 pressure-film pads on the object-facing nail prongs. The [sensor placement guide](engineering/docs/SENSORS.md) labels every head, magnet and pad and supplies exact coordinates. Physical qualification remains pending.

Eight separate digital prototype packages are supplied:

| Prototype | Design | First measurement |
|---|---|---|
| R1 local tactile skin | Two shaped nail cells and four cast saddles matched to the actual TPU profile | Thin-tip contact coverage, force drift and wear |
| L1 root normal force | A purchased TAL220B cell between the original finger and two aluminum carriers | Held-out off-center loads, followed by an integrated-finger test using the same calibration slope |
| B1 magnetic bending insert | Four magnets in the TPU, five fixed magnetic heads, new side spine and custom PCB; original hard frame and thin nail retained | Original-vs-B1 bending, magnet retention, interference, then physical force calibration |
| B2 consolidated magnetic PCB | Same sensor/magnet poses on one checked PCB with two locating spacers, a removable backer and two N0 nail pads | Installed fit, first-board operation, then matched B1/B2 contact, force and assembly-time tests |
| C1 differential-strain root | Transverse aluminum beam, eight CEA-13-062UWA-350 gauges, fixed/floating carriers and dual-ADS1232 readout | Actual drive fit, bonded-gauge operation, real joint compliance, then independent force/lever calibration and validation |
| N1 bare sensing nail | Steel fork with two full shear bridges, revised frame and side carriers, plus four retained R1 TPU cells | Fit, bonding, whole-finger motion, then separate and mixed-contact force tests |
| B3 recessed magnetic board | Separate recessed frame and tapered spacers move the retained B2 board inward 2.439 mm; B1 TPU and N0 nail pads retained | Frame seating/stiffness, full drive and cable clearance, gain-5 readout, then paired B2/B3 force/contact tests |
| FB1 packaged force button | Four-leaf root guide, selected Honeywell FMA, flat plunger, adjustable stops and checked sensor PCB | Preload and coupling, real clamp/cable effects, held-out finger force and low-force contact reliability |

The package contains checked STEP/STL parts and component/hardware references; R1 electrode patterns; carrier/fixture drawings; editable PCBs and checked fabrication files; BOMs and wiring; Pico firmware; raw recorders; material recipes; and staged tests through 20 N. FB1.1 adds 54 CAD parts/references and a two-layer FMA PCB. N1 reuses the C1 bridge board; B3 reuses the B2 board with its own gain-5 firmware. R1/L1/B1 and the earlier concept snapshots remain preserved. The later packages are separate under `engineering/prototypes/`.

**Status: ten packages have passed their stated digital checks; pneumatic and optical designs remain in development. Physical assembly and validation are pending.** No sensor/material winner, measured force accuracy, endurance, or robot-task success is claimed.

For the new bending-aware option, use [B1 assembly](engineering/docs/BUILD_B1.md), [PCB/wiring/code](engineering/docs/B1_ELECTRONICS.md), and [bending and force tests](engineering/docs/B1_TESTING.md). B1 raw magnetic data are not calibrated force; optional R1 nail cells supply hard-tip contact coverage.

Use [B2's build guide](engineering/docs/BUILD_B2.md) for consolidated magnetic sensing, [C1 assembly](engineering/docs/BUILD_C1.md) for the strain-root alternative, [N1 assembly](engineering/docs/BUILD_NAIL.md) for the bare sensing nail, [B3 assembly](engineering/docs/BUILD_RECESSED.md) for the narrower recessed board, and [FB1 assembly](engineering/docs/BUILD_FORCE_BUTTON.md) for the packaged force button. Each has its own test instructions and evidence limits. The [all-design campaign](engineering/docs/BUILD_ALL.md) identifies the two remaining designs and the physical evidence still required.

The [F1 R4 guide](engineering/docs/BUILD_F1.md) identifies the pressure-film
stack, six sensing sites, twelve checked flexes, retained covers and molds,
fixed fanout and wrist readout. Its bench package includes 96 CAD
parts/references, manufacturing instructions, raw acquisition and physical
stationary-force tools. Actual mating, adhesion, sealing, slack, full-array
behavior and contact/force performance remain unmeasured.

The [K1 capacitive guide](engineering/docs/BUILD_CAPACITIVE.md) covers the
complete K1.2 bench package: checked flexes, retained plates/stops, molds,
bank cases, readout and static-force tools. Physical fabrication, installed
bracket/harness fit and validation remain.

## Start here

1. [Measure and identify the actual finger](engineering/docs/GEOMETRY.md).
2. [Print tooling and assemble R1](engineering/docs/BUILD_R1.md).
3. [Wire, check, and record the sensor](engineering/docs/ELECTRONICS.md).
4. [Compare cover materials](engineering/docs/MATERIALS.md).
5. [Qualify contact, 20 N range, wear, replacement, and dexterity](engineering/docs/TESTING.md).

In parallel, [build L1's cell fixture and carrier](engineering/docs/BUILD_L1.md), [wire its dedicated readout](engineering/docs/L1_ELECTRONICS.md), and [run the cell/plate and integrated-finger tests](engineering/docs/L1_TESTING.md). Both prototypes remain unbuilt and unqualified.

The [shared contact test](engineering/docs/CONTACT.md) supplies saved setup files, randomized physical trial plans, frozen thresholds, live R1/L1 monitoring and per-region error bounds. It keeps failures and unavailable readings in the evidence, and distinguishes a short pilot from a larger reliability test.

The website provides individual STEP/STL downloads, an offline guide, all source code, and a complete portable ZIP. Geometry generators and editable design parameters are under [`engineering`](engineering/README.md).

## Rebuild the webpage

The published CAD snapshot is included. Building the website requires only Python 3.10+:

```sh
/usr/bin/python3 -m unittest discover -s engineering/tests -v
/usr/bin/python3 engineering/scripts/build_site.py
/usr/bin/python3 engineering/scripts/check_site.py
```

Open `build/site/index.html`, or use a local static file server. Interactive geometry and report inspection also work from the extracted offline website.

Full CAD regeneration uses the separate locked environment described in [engineering/README.md](engineering/README.md). It verifies the original mesh hashes, CAD solid validity, STEP round trips, and closed STL exports. Those are digital checks, not physical tests.

## Evidence and provenance

The input meshes come from a pinned community YAM baseline, corroborated by the original MakerWorld file sizes. Exact original-file identity and physical fit must still be checked. Attribution belongs to Wenli Xiao / ENPIRE; see [geometry provenance](engineering/docs/GEOMETRY.md) and the generated release notice.

The previous v0.1 root-force illustration remains in history and legacy files. The current L1 package uses a specific purchased cell, source-matched carriers, actual CAD and explicit bench plans. Neither the old illustration nor the new digital checks are physical performance evidence.
