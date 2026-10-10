# ENPIRE / YAM tactile engineering study

[Visual website](https://geyan21.github.io/yam-tactile-kit/) · [Student starting packet](engineering/docs/START.md) · [Build R1](engineering/docs/BUILD_R1.md) · [Build L1](engineering/docs/BUILD_L1.md) · [Sensor comparison](engineering/docs/COMPARISON.md)

The goal is **reliable contact and grip-force feedback through 20 N per finger**, while retaining the thin ENPIRE nail for precise manipulation.

Two prototype packages are supplied:

| Prototype | Design | First measurement |
|---|---|---|
| R1 local tactile skin | Two shaped nail cells and four cast saddles matched to the actual TPU profile | Thin-tip contact coverage, force drift and wear |
| L1 root normal force | A purchased TAL220B cell between the original finger and two aluminum carriers | Held-out off-center loads, followed by an integrated-finger test using the same calibration slope |

The package contains 23 checked STEP/STL solids, including one purchased-cell reference; full-size R1 electrode patterns; carrier/fixture drawings; separate BOMs and wiring; Pico firmware; raw recorders and calibration tools; material recipes; and staged tests through 20 N. The L1 carrier adds 20 mm of reach and a larger root envelope; printed fit checks precede machining.

**Status: digital design and software checks completed; physical prototype assembly and validation pending.** No sensor/material winner, measured force accuracy, endurance, or robot-task success is claimed.

## Start here

1. [Measure and identify the actual finger](engineering/docs/GEOMETRY.md).
2. [Print tooling and assemble R1](engineering/docs/BUILD_R1.md).
3. [Wire, check, and record the sensor](engineering/docs/ELECTRONICS.md).
4. [Compare cover materials](engineering/docs/MATERIALS.md).
5. [Qualify contact, 20 N range, wear, replacement, and dexterity](engineering/docs/TESTING.md).

In parallel, [build L1's cell fixture and carrier](engineering/docs/BUILD_L1.md), [wire its dedicated readout](engineering/docs/L1_ELECTRONICS.md), and [run the cell/plate and integrated-finger tests](engineering/docs/L1_TESTING.md). Both prototypes remain unbuilt and unqualified.

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
