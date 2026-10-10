# ENPIRE / YAM tactile engineering study

[Visual website](https://geyan21.github.io/yam-tactile-kit/) · [Which sensors go where](engineering/docs/SENSORS.md) · [Build B1](engineering/docs/BUILD_B1.md) · [Student starting packet](engineering/docs/START.md) · [Build R1](engineering/docs/BUILD_R1.md) · [Build L1](engineering/docs/BUILD_L1.md)

The goal is **reliable contact and grip-force feedback through 20 N per finger**, while retaining the thin ENPIRE nail for precise manipulation.

[Magnetic scalability and alternative designs](engineering/docs/ARCHITECTURE.md) compares the current pilot with a consolidated B2 board concept and a C1 differential-strain force coupon. It includes primary-source evidence, calculations, concept CAD, and a cost/validation plan. B2 has no routed PCB; C1 has no completed gripper adapter.

**Concrete B1 prototype recommendation:** five MLX90393SLW-ABA-011 heads fixed beside four magnets embedded in the bending TPU, plus two thin N0 pressure-film pads on the object-facing nail prongs. The [sensor placement guide](engineering/docs/SENSORS.md) labels every head, magnet and pad and supplies exact coordinates. Physical qualification remains pending.

Three separate prototype packages are supplied:

| Prototype | Design | First measurement |
|---|---|---|
| R1 local tactile skin | Two shaped nail cells and four cast saddles matched to the actual TPU profile | Thin-tip contact coverage, force drift and wear |
| L1 root normal force | A purchased TAL220B cell between the original finger and two aluminum carriers | Held-out off-center loads, followed by an integrated-finger test using the same calibration slope |
| B1 magnetic bending insert | Four magnets in the TPU, five fixed magnetic heads, new side spine and custom PCB; original hard frame and thin nail retained | Original-vs-B1 bending, magnet retention, interference, then physical force calibration |

The package contains 28 checked STEP/STL solids, including three purchased/component references; R1 electrode patterns; carrier/fixture drawings; B1 editable PCB and checked fabrication files; separate BOMs and wiring; Pico firmware; raw recorders; material recipes; and staged tests through 20 N. B1 adds no reach but adds side thickness. R1/L1 CAD and geometry sources remain hash-verified and unchanged.

**Status: digital design and software checks completed; physical prototype assembly and validation pending.** No sensor/material winner, measured force accuracy, endurance, or robot-task success is claimed.

For the new bending-aware option, use [B1 assembly](engineering/docs/BUILD_B1.md), [PCB/wiring/code](engineering/docs/B1_ELECTRONICS.md), and [bending and force tests](engineering/docs/B1_TESTING.md). B1 raw magnetic data are not calibrated force; optional R1 nail cells supply hard-tip contact coverage.

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
