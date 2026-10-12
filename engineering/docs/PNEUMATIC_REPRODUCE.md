# Reproduce the P1 digital package

Use the complete repository and the pinned source/CAD/KiCad setup in `engineering/README.md`. Run from its root. Every generator prints a new directory under `build/engineering/prototypes/pneumatic/`; substitute those paths for the uppercase placeholders below. Keep completed runs and do not edit a generator or its inputs while it runs.

## Geometry and fit

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/layout_pneumatic_wall_pairs.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_pneumatic_insert_witness.py LAYOUT_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/search_pneumatic_port_poses.py LAYOUT_RUN WITNESS_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/probe_pneumatic_slim_port.py LAYOUT_RUN WITNESS_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_pneumatic_ported_assembly.py \
  --layout LAYOUT_RUN --poses POSE_RUN --slim SLIM_RUN
```

The standard-fitting search intentionally exits with CH4 front unresolved. Its passing seven poses are combined with the separately checked slim CH4 front fitting. The assembly generator accepts exactly that unresolved set and requires every final material, guarded hose and capped-air-space check to pass.

The current assembly covers the nominal insert, ten plugs, metal tubes, bond envelopes, eight local hose segments and eight gas references. The closure test temporarily caps the intended metal outlets and checks eight separate cavities. It is not a physical leak test.

## Board, carrier, software and model

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_pneumatic_board.py
/usr/bin/python3 engineering/scripts/check_prototype_pcb.py BOARD_RUN \
  --name p1_readout --export --kicad-cli /ABSOLUTE/PATH/TO/KICAD-CLI
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_pneumatic_bench_parts.py --board BOARD_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/screen_pneumatic_pairs.py ASSEMBLY_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/review_pneumatic_integration.py \
  --assembly ASSEMBLY_RUN --bench BENCH_RUN --board BOARD_RUN
/usr/bin/python3 -I engineering/scripts/run_ci_tests.py --pattern 'test_pneumatic*.py'
```

The board writer supplies native PCB, embedded footprints and a pin/net list. KiCad exports fabrication files only after a complete clean check. The carrier is generated against that board's actual outline and holes. The separate gas model uses the final cavity volumes; its scenario failures remain visible.

## Visuals and package

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/draw_pneumatic_prototype.py \
  --assembly ASSEMBLY_RUN --bench BENCH_RUN --board BOARD_RUN --pairs PAIR_RUN
/usr/bin/python3 engineering/scripts/review_pneumatic_diagrams.py \
  --browser /ABSOLUTE/PATH/TO/CHROME --integration INTEGRATION_RUN
/usr/bin/python3 engineering/scripts/freeze_pneumatic.py \
  --assembly ASSEMBLY_RUN --bench BENCH_RUN --board BOARD_RUN --pairs PAIR_RUN \
  --integration INTEGRATION_RUN --visuals VISUAL_RUN --diagrams DIAGRAM_REVIEW_RUN \
  --destination build/engineering/prototypes/pneumatic/reproduced-package
/usr/bin/python3 engineering/scripts/build_site.py
/usr/bin/python3 engineering/scripts/check_site.py
```

`port_cut_and_hose_map.csv` is generated from the selected poses. The two 3D models show the finger and remote board separately. Component bodies, gas spaces and local hose references are labeled explicitly. The package's provenance records the source runs and checksums used for publication.

Reproduction exports can have different timestamps/hashes while retaining the same geometry. Keep the new results separate from the frozen prototype and compare the construction and check reports. The website uses `engineering/prototypes/pneumatic/`; the reproduction destination above does not replace that frozen package. A digital rebuild does not demonstrate printed-channel quality, seal strength, loaded clearance or physical sensing performance.
