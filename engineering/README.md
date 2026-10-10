# ENPIRE tactile engineering study

The build study has two prototypes. **R1** places six replaceable resistive cells on the real ENPIRE contact profile. **L1** routes the complete finger's normal load through a purchased strain-gauge cell and aluminum carriers. Both require physical assembly and testing.

**Available:** editable CAD generators; 23 checked STEP/STL solids including one purchased-cell reference; a 1:1 electrode cut sheet; L1 carrier/fixture drawings; both BOMs and wiring diagrams; Pico firmware; raw recorders; held-out force analysis; material recipes; and student test plans.

**Not yet available:** assembled prototype photographs, measured contact threshold, force accuracy, lifetime, or robot-task results. No sensor or material has won the comparison yet.

1. Read [the student starting packet](docs/START.md).
2. Inspect [the measured geometry and provenance](docs/GEOMETRY.md).
3. Build [R1](docs/BUILD_R1.md) and [its electronics](docs/ELECTRONICS.md).
4. Compare [materials](docs/MATERIALS.md) and follow [the test protocol](docs/TESTING.md).
5. Use [the sensor comparison](docs/COMPARISON.md) to decide the next integrated prototype.

For L1, follow [assembly](docs/BUILD_L1.md), [electronics](docs/L1_ELECTRONICS.md) and [the two-stage force protocol](docs/L1_TESTING.md). The older illustrative root-force block is unrelated to the new source-matched carrier.

## File map

| Files | Role |
|---|---|
| `designs/r1.json`, `designs/l1.json` | Editable design choices; changing the purchased cell requires renewed fixture/interface review |
| `release/r1/cad`, `release/l1/cad` | Checked STEP masters and STL exports |
| `bom.csv`, `l1_bom.csv` | Quantities, specifications and supplier references |
| `firmware/r1`, `firmware/l1` | Separate Pico programs; no actuator commands |
| `software/bench.py`, `software/calibrate.py` | R1 raw capture and held-out channel calibration |
| `software/l1_bench.py`, `l1_calibrate.py`, `l1_validate_finger.py`, `l1_monitor.py` | L1 cell/plate experiment, fixed-sensitivity finger validation and live recording |
| `software/contact_bench.py`, `contact_report.py`, `contact_monitor.py` | Shared R1/L1 contact recording, frozen-threshold evaluation and live decisions |
| `templates`, `docs` | Specimen records, assembly, material recipes and test instructions |
| `scripts`, `tests`, `web` | Reproduction tools, software checks and portable website |

Generated results belong under ignored `build/` and `results/`; never put invented benchmark results into the physical-evidence fields.

Use [the shared contact workflow](docs/CONTACT.md) to compare contact presence across sensor/material variants. The rolling-window implementation is shared by training, evaluation and live monitoring. Statistical counts refer to independent physical presentations, not frames.

## Reproduce the engineering files

Python 3.12 and the packages in `requirements.lock` are used for CAD. The generator checks the source mesh hashes, CAD validity, STEP round trips, and STL watertightness. These checks establish digital geometry only.

```sh
/usr/bin/python3 engineering/scripts/collect_geometry_sources.py
/usr/bin/python3 engineering/scripts/prepare_environment.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/analyze_baseline_meshes.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/analyze_contact_regions.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/measure_interfaces.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_r1_parts.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/freeze_release.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/measure_root_interface.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_l1_parts.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/screen_l1_stiffness.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/draw_l1.py
/usr/bin/python3 engineering/scripts/make_l1_plans.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/freeze_l1_release.py --refresh-r1
/usr/bin/python3 -m unittest discover -s engineering/tests -v
/usr/bin/python3 engineering/scripts/build_site.py
/usr/bin/python3 engineering/scripts/check_site.py
```

Use an explicit interpreter path appropriate to your machine. The environment helper requires `uv`; it keeps downloads and tools inside `build/engineering/tools`. It does not modify system Python or a robot environment. Source collection reads public geometry; it does not execute upstream code.

Generated engineering outputs live under `build/engineering`. Published snapshots are under `engineering/release`; source code, generated files, and future bench results are separate.

For an L1-only revision, preserve the current R1 release and use `freeze_l1_release.py` without `--refresh-r1`. It verifies every preserved R1 source/output hash before adding L1. `--refresh-r1` is for the intentional full R1 regeneration shown above.

The site builder uses only the frozen release and Python's standard library. The downloadable source is tested in a fresh temporary directory without the CAD environment. Browser checks use an explicitly selected local browser and an owned loopback server. Execution records capture commands, process identities, timestamps and intentional stops.
