# ENPIRE / YAM tactile engineering study

[Visual website](https://geyan21.github.io/yam-tactile-kit/) · [Student starting packet](engineering/docs/START.md) · [Build R1](engineering/docs/BUILD_R1.md) · [Sensor comparison](engineering/docs/COMPARISON.md)

The goal is **reliable contact and grip-force feedback through 20 N per finger**, while retaining the thin ENPIRE nail for precise manipulation.

The current R1 design uses two shaped resistive cells on the PETG nail and four cast saddles matched to the actual TPU contact profile. The package contains thirteen STEP/STL tooling parts, full-size electrode patterns, a BOM, wiring, Pico firmware, a guided bench recorder, calibration analysis, material recipes, and a test protocol.

**Status: digital design and software checks completed; physical prototype assembly and validation pending.** No sensor/material winner, measured force accuracy, endurance, or robot-task success is claimed.

## Start here

1. [Measure and identify the actual finger](engineering/docs/GEOMETRY.md).
2. [Print tooling and assemble R1](engineering/docs/BUILD_R1.md).
3. [Wire, check, and record the sensor](engineering/docs/ELECTRONICS.md).
4. [Compare cover materials](engineering/docs/MATERIALS.md).
5. [Qualify contact, 20 N range, wear, replacement, and dexterity](engineering/docs/TESTING.md).

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

The previous v0.1 root-force visualization is preserved in Git history and legacy files. It is not the hardware developed in this engineering packet.
