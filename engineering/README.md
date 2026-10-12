# ENPIRE tactile engineering study

The website has [a separate page for each design](https://geyan21.github.io/yam-tactile-kit/designs.html). Edit `design_catalog.json` to update the shared page fields. `scripts/design_pages.py` generates the directory, individual pages and functional diagrams during the standard site build; the physics/CAD snapshots remain separate.

The R1 placement drawing is generated from the frozen R1 assembly by `scripts/draw_r1_page_map.py`, using the CAD environment's Python. The site build itself still needs only the standard library.

The [all-design campaign](docs/BUILD_ALL.md) now has twelve digital prototype packages: **R1** local resistive cells, **L1** root force, **B1** magnetic heads, **B2.1** consolidated magnetic electronics, **C1.1** a custom strain-sensing root, **N1.1** a bare sensing nail, **B3.1** a recessed magnetic board, **FB1.1** a packaged force button, **K1.2** capacitive cells, **F1.1 R4** a dense resistive matrix, **P1.0** paired air channels and **O1.0** fixed optics with compliant gel. All require physical assembly and testing.

**Available:** editable CAD generators; checked STEP/STL parts, tools and component references; electrode cut sheets; assembly drawings; BOMs; editable PCBs and checked Gerbers/drills; firmware and raw recorders; force-analysis tools; material recipes; and student test plans.

**Not yet available:** assembled prototype photographs, measured contact threshold, force accuracy, lifetime, or robot-task results. No sensor or material has won the comparison yet.

[P1](docs/BUILD_PNEUMATIC.md) supplies 112 CAD parts/references, four remote
ELVR transducers, a checked 40-component readout, eight labeled hoses and two
thin N0 nail cells. Its separate electrical, physical-test and reproduction
guides retain the gas model's range failures and common-pressure ambiguity.

[O1](docs/BUILD_OPTICAL.md) supplies 87 CAD parts/tools/references, a fixed
Camera Module 3 Wide and PET mirror, a retained Solaris gel with 42 marker
dots, a checked blue-light ring and two thin N0 nail cells. Separate wiring,
optical setup, physical force/contact evaluation and reproduction guides
accompany its package. The 32 mm extension and optical/edge-coverage limits
are explicit; no physical performance is claimed.

1. Read [the student starting packet](docs/START.md).
2. Inspect [the measured geometry and provenance](docs/GEOMETRY.md).
3. Build [R1](docs/BUILD_R1.md) and [its electronics](docs/ELECTRONICS.md).
4. Compare [materials](docs/MATERIALS.md) and follow [the test protocol](docs/TESTING.md).
5. Use [the sensor comparison](docs/COMPARISON.md) to decide the next integrated prototype.

For L1, follow [assembly](docs/BUILD_L1.md), [electronics](docs/L1_ELECTRONICS.md) and [the two-stage force protocol](docs/L1_TESTING.md). The older illustrative root-force block is unrelated to the new source-matched carrier.

For B1, follow [assembly](docs/BUILD_B1.md), [electronics](docs/B1_ELECTRONICS.md) and [bending/contact/force tests](docs/B1_TESTING.md). No B1 force coefficients are supplied without measured data.

Start with [sensor choice and placement](docs/SENSORS.md) for the exact IC, magnets, two nail pads, and their labeled locations. Its SVG, coordinate files and page are generated from the unchanged release by `scripts/explain_sensor_placement.py`; edit `templates/sensor_guide.md` for the explanatory text, then regenerate with the CAD environment's Python.

The [architecture study](docs/ARCHITECTURE.md) assesses scalability and alternatives. `concepts/` retains the earlier B2/C1 explorations; `prototypes/b2/` and `prototypes/c1/` contain their later build packages. These are checked independently of the preserved R1/L1/B1 release. `research/` contains sources and scale-validation plans; `campaign/` preserves the full twelve-design objective and comparison requirements.

`prototypes/nail/` contains N1.1: a separate bare sensing nail, revised frame
and combined readout package. It reuses the C1 bridge PCB and R1 CH2–CH5
interfaces. [BUILD_NAIL.md](docs/BUILD_NAIL.md) gathers the exact sensor
locations, wiring and assembly steps.

`prototypes/recessed/` contains B3.1: a separate recessed frame and tapered
spacers, the retained B2 PCB and B1 TPU/magnets, and two N0 nail cells.
[BUILD_RECESSED.md](docs/BUILD_RECESSED.md) gives exact sensor locations,
gain-5 wiring/readout, fabrication and the paired B2/B3 experiment.

The current [F1 R4 package](prototypes/f1/README.md) contains 96 CAD
parts/references, twelve checked flexes, retained covers and molds, matching
electronics, manufacturing instructions and stationary-force tools.
[Build F1](docs/BUILD_F1.md) is the current starting point. Its physical
mating, seals, slack and performance remain unqualified.

Preserved F1 development modules include the
[checked connector board](development/f1/fanout/README.md) and the
[selected-column readout study](development/f1/readout-study/README.md).
The latter includes its exact circuit, plots, replayable cases and unresolved
simulation failures. The [ADC and row support studies](development/f1/support-studies/README.md)
now preserve their current model checks and unsuccessful earlier runs.
The [wrist capture guide](docs/F1_WRIST_CAPTURE.md) gives exact components,
Pico connections, firmware and raw recording. These individual historical
modules are not physical performance results.
The [checked wrist-board module](development/f1/wrist/README.md) now includes
its native PCB, fabrication files, drawings, cable checklist and firmware.
Its 135-component board passes independent copper/connectivity DRC.
The current [R3 interface and fit packet](development/f1/r3/README.md) adds a
checked 42-component fanout with 959 tracks, 155 vias, zero native DRC findings
and a reserved inner ground plane. Its local bypass/sense paths and fifty-pin
correspondence are checked. It includes 44 matching CAD solids and twelve
fit patterns.

The separate [R3 fitted-foil module](development/f1/fitted-foils-r3/README.md)
adds twelve routed electrode foils with independent copper/connectivity
checks, a 64-location contact map and forty trace-resistance estimates.
Use the later R4 package for proposed manufacturing and routed-DC updates.
Physical mating, object/motion behavior and qualification remain unfinished.

The earlier [K1 capacitive development module](development/capacitive/k1/README.md)
contains 49 current CAD parts, post-sheet tooling, corrected conforming supports,
a checked 23-component readout board and raw firmware/recording code. Its
eighteen declared support-fit comparisons pass. Electrode fabrication,
retention, vents, cables, enclosure and physical force/contact testing remain.
The later [K1.2 package](prototypes/capacitive/README.md) adds the checked
electrode foils, retained plates/stops, molds, terminal tools, bank enclosures
and static-force workflow. Use [the K1 guide](docs/BUILD_CAPACITIVE.md) for
the current scope and next steps.

The [FB1.1 force-button prototype](prototypes/force_button/README.md) supplies
54 CAD parts/references, a checked two-layer FMA board, raw Pico acquisition,
static calibration tools and a bonded-metal structural comparison. Its
current guides are 0.50 mm spring steel. The earlier 0.40 mm study is retained
because it lacked margin for the provisional motion target.
Use [the FB1 build guide](docs/BUILD_FORCE_BUTTON.md) and
[physical test procedure](docs/FORCE_BUTTON_TESTING.md).

The earlier [R2 fit module](development/f1/mechanics/README.md) contains 44 checked
CAD solids, twelve printable tail patterns, a sensor-placement drawing,
an interactive-viewer model, and 654 passing declared static pair checks.
Its connector cavities, stiffeners, fitted copper, tail slack and physical
performance remain unqualified. The earlier crossing is retained with its
two exact involved solids.

Use [the current F1 build guide](docs/BUILD_F1.md) for the R4 student
procedure. [F1 development](docs/F1_DEVELOPMENT.md) retains the historical
circuit and layout checkpoints.

The full offline packet retains local downloads. The hosted Pages build
uses versioned GitHub Release assets for its four large archives so the
visual site remains within the Pages size limit. `prepare_pages_distribution.py`
stages the two distributions; the Actions publication step verifies asset
checksums before deploying the page links.

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

## Reproduce B1 separately

Start from the checked-out release and collect the original geometry with the existing helper. Keep the R1/L1 snapshots intact; do not rerun their freezers for a B1-only change.

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/analyze_b1_interfaces.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_b1_parts.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/model_b1_field.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/draw_b1.py
/usr/bin/python3 engineering/scripts/build_b1_pcb.py
/usr/bin/python3 engineering/scripts/check_b1_pcb.py --kicad-cli /usr/bin/kicad-cli --export
/usr/bin/python3 engineering/scripts/collect_b1_sources.py \
  https://media.melexis.com/-/media/files/documents/datasheets/mlx90393-datasheet-melexis.pdf \
  https://www.supermagnete.de/eng/data_sheet_S-03-01-N.pdf
build/engineering/tools/cad-venv/bin/python engineering/scripts/freeze_b1_release.py
/usr/bin/python3 -m unittest discover -s engineering/tests -v
/usr/bin/python3 engineering/scripts/build_site.py
/usr/bin/python3 engineering/scripts/check_site.py
```

Use KiCad 10 for the PCB check, or obtain the project-local official tool with `prepare_b1_eda.py --extract`. Its download provenance is recorded. The B1 freezer verifies `r1_l1_snapshot_manifest.json` before adding the new files. A full intentional R1/L1 regeneration needs a separately reviewed new baseline manifest; do not overwrite the retained baseline casually.

## Reproduce B2.1 separately

Follow [BUILD_B2.md](docs/BUILD_B2.md). The component and magnet poses come from
the retained B1 release. The new board has a wider routing band inside the
same outer side profile, with separate locating spacers and a removable backer.

After collecting the geometry sources and preparing the existing CAD
environment, run:

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_b2_pcb.py
/usr/bin/python3 engineering/scripts/check_prototype_pcb.py \
  build/engineering/prototypes/b2/pcb --name b2_main --export
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_b2_parts.py
/usr/bin/python3 engineering/scripts/prepare_b2_firmware.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/draw_b2.py
/usr/bin/python3 engineering/scripts/freeze_b2_prototype.py
/usr/bin/python3 -m unittest discover -s engineering/tests -p test_b2.py -v
/usr/bin/python3 engineering/scripts/build_site.py
/usr/bin/python3 engineering/scripts/check_site.py
```

The checker defaults to the project-local KiCad tool prepared for B1. Supply
`--kicad-cli /usr/bin/kicad-cli` to use an installed KiCad 10 instead. Every
check keeps its own timestamped directory, including failed attempts.

`prototype_pcb.py` writes explicit embedded footprints and nets;
`prototype_route.py` supplies bounded routing; KiCad independently checks the
result. `prototype_cad.py` verifies solids and exports. The separate B2 snapshot
contains fabrication files, firmware, visualizations and their input hashes.
These are digital checks; the physical comparison remains open.

## Reproduce C1.1 separately

Follow [BUILD_C1.md](docs/BUILD_C1.md) for the physical assembly and
[C1_TESTING.md](docs/C1_TESTING.md) for stationary-hold calibration. Read
[C1_ANALYSIS.md](docs/C1_ANALYSIS.md) for the structural model's limits.

After collecting the geometry and preparing the CAD and KiCad tools:

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_c1_parts.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_c1_pcb.py
/usr/bin/python3 engineering/scripts/check_prototype_pcb.py \
  build/engineering/prototypes/c1/pcb --name c1_readout --export
/usr/bin/python3 engineering/scripts/prepare_c1_fea.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/verify_structural_numerics.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/run_c1_fea.py \
  --mesh-mm 1.5 --gauge-mesh-mm 0.7 --solve-timeout 600
build/engineering/tools/cad-venv/bin/python engineering/scripts/run_c1_fea.py \
  --mesh-mm 1.5 --gauge-mesh-mm 0.5 --solve-timeout 600
```

The structural tool helper downloads official Gmsh and CalculiX builds and a
required runtime into the project cache. It records their hashes and uses the
runtime only in its solver subprocess. The models use one CPU and enforce a
400,000-displacement-degree-of-freedom mesh limit. Runs and input files are
preserved in separate timestamped directories.

Select the two completed run directories from their `latest.json` files under
`build/engineering/prototypes/c1/fea/mesh_1p5_gauge_0p7/` and
`mesh_1p5_gauge_0p5/`. Replace `COARSE_RUN` and `FINE_RUN` below with those
actual paths:

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/summarize_c1_analysis.py \
  --coarse COARSE_RUN --fine FINE_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/assess_c1_tolerances.py \
  FINE_RUN --realizations 16
/usr/bin/python3 engineering/scripts/make_c1_packet.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/draw_c1.py
/usr/bin/python3 engineering/scripts/freeze_c1_prototype.py \
  --tolerance-report FINE_RUN/tolerance_scenarios.json
/usr/bin/python3 -m unittest discover -s engineering/tests -p test_c1.py -v
/usr/bin/python3 engineering/scripts/build_site.py
/usr/bin/python3 engineering/scripts/check_site.py
```

Use an explicit interpreter path appropriate to the checkout. The freezer
requires current CAD and PCB hashes, clean independent DRC, numerical
verification, structural convergence and the declared motion screen. It does
not manufacture a specimen or qualify force accuracy. Full solver input decks
are included in `prototypes/c1/c1_structural_inputs.zip`; large raw solver
outputs remain preserved locally and can be regenerated.

## Reproduce N1.1 separately

Prepare the existing CAD environment, collect the source meshes, and prepare
the same Gmsh/CalculiX tools used for C1. Keep all retained snapshots intact.

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/prepare_source_brep.py \
  --part hard_frame
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_nail_parts.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/check_nail_fasteners.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/run_nail_fea.py \
  --mesh-mm 1.5 --web-mm 0.7 --mesh-optimizer elastic-direct --solve-timeout 600
build/engineering/tools/cad-venv/bin/python engineering/scripts/run_nail_fea.py \
  --mesh-mm 1.35 --web-mm 0.5 --mesh-optimizer elastic-direct --solve-timeout 600
```

Each structural run preserves its inputs in a timestamped directory under
`build/engineering/prototypes/nail/fea/`. Select the completed coarse/fine
directories from their `latest.json` files and substitute them below.

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/summarize_nail_analysis.py \
  --coarse COARSE_RUN --fine FINE_RUN
/usr/bin/python3 engineering/scripts/finalize_nail_metadata.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/check_nail_fasteners.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/draw_nail.py
/usr/bin/python3 engineering/scripts/make_nail_packet.py
```

The metadata finalizer changes release labels only after checking that the
physical parameters and geometry files match the reviewed runs. Original run
configurations remain preserved. Use the last passing eight-check report in
`build/engineering/prototypes/nail/fastener_checks/` as `FASTENER_REPORT`:

```sh
/usr/bin/python3 engineering/scripts/freeze_nail_prototype.py \
  --fastener-checks FASTENER_REPORT
/usr/bin/python3 -m unittest discover -s engineering/tests -p test_nail.py -v
/usr/bin/python3 engineering/scripts/build_site.py
/usr/bin/python3 engineering/scripts/check_site.py
```

The isolated mesh worker saves stages and pre-optimization geometry. It and
the solver use one CPU each, with explicit time/mesh limits and execution
records. The published structural ZIP contains the complete solver decks and
frozen inputs; visualization meshes and raw solver outputs are regenerated
when needed.

N1's static force baseline uses only preserved physical holds. It does not
turn a structural calculation or dummy-resistor recording into a measured
sensor result. Follow [NAIL_TESTING.md](docs/NAIL_TESTING.md) for the actual
training, validation and remaining qualification work.

## Reproduce B3.1 separately

Collect the original geometry and prepare the existing CAD environment. Use
the retained B1/B2 snapshots; B3 does not require a new circuit board design.
Keep those packages intact.

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/prepare_source_brep.py \
  --part hard_frame
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_recessed_parts.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/check_recessed_clearance.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/screen_recessed_fields.py
/usr/bin/python3 engineering/scripts/prepare_recessed_firmware.py
/usr/bin/python3 engineering/scripts/make_recessed_packet.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/draw_recessed.py
/usr/bin/python3 engineering/scripts/freeze_recessed_prototype.py
/usr/bin/python3 -m unittest discover -s engineering/tests -p test_recessed.py -v
/usr/bin/python3 engineering/scripts/build_site.py
/usr/bin/python3 engineering/scripts/check_site.py
```

The freezer verifies the preserved releases, five CAD exports, protected
source regions, full spacer seating, head/solder clearances, sampled field
range, firmware settings and current visualization inputs. Failed CAD
iterations and field runs remain under the working build directory. Before
changing evaluated geometry, use `archive_prototype_state.py --design recessed
--label REVISION_LABEL` with a lowercase descriptive label.

B3 has no structural force prediction or measured force calibration. The
prescribed side-motion envelope is not a 20 N or travel rating.
[RECESSED_ANALYSIS.md](docs/RECESSED_ANALYSIS.md) separates the digital
findings from the remaining [physical tests](docs/RECESSED_TESTING.md).
