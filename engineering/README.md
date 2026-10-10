# ENPIRE tactile engineering study

The first build is **R1: six replaceable resistive cells on the real ENPIRE finger contact profile**. Two cells follow the forked PETG nail; four sit on molded saddles matched to the serrated TPU surface. It is an experimental build, not a qualified gripper sensor.

**Available:** editable CAD generators; thirteen solid STEP/STL parts; a 1:1 electrode cut sheet; an exact wiring map; Pico firmware; a guided force-recording program; calibration with entire held-out load cycles; material recipes; a student test plan.

**Not yet available:** assembled prototype photographs, measured contact threshold, force accuracy, lifetime, or robot-task results. No sensor or material has won the comparison yet.

1. Read [the student starting packet](docs/START.md).
2. Inspect [the measured geometry and provenance](docs/GEOMETRY.md).
3. Build [R1](docs/BUILD_R1.md) and [its electronics](docs/ELECTRONICS.md).
4. Compare [materials](docs/MATERIALS.md) and follow [the test protocol](docs/TESTING.md).
5. Use [the sensor comparison](docs/COMPARISON.md) to decide the next integrated prototype.

The older root-force illustration remains in repository history and legacy files. It is not a fabricated force module.

## Reproduce the engineering files

Python 3.12 and the packages in `requirements.lock` are used for CAD. The generator checks the source mesh hashes, CAD validity, STEP round trips, and STL watertightness. These checks establish digital geometry only.

```sh
/usr/bin/python3 engineering/scripts/collect_geometry_sources.py
/usr/bin/python3 engineering/scripts/prepare_environment.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/analyze_baseline_meshes.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/analyze_contact_regions.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/measure_interfaces.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_r1_parts.py
```

Use an explicit interpreter path appropriate to your machine. The environment helper requires `uv`; it keeps downloads and tools inside `build/engineering/tools`. It does not modify system Python or a robot environment. Source collection reads public geometry; it does not execute upstream code.

Generated engineering outputs live under `build/engineering`. Published snapshots are under `engineering/release`; source code, generated files, and future bench results are separate.
