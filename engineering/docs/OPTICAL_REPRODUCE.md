# Reproduce the O1 digital package

Use the complete repository and pinned CAD/KiCad/source setup in `engineering/README.md`. Run from its root with the explicit interpreters shown there. Each generator preserves a new run directory under `build/engineering/prototypes/optical/`. Replace uppercase run placeholders with its printed path. Keep completed runs and their inputs unchanged.

## Optical path, frame, camera and gel

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/search_optical_path.py \
  --config engineering/designs/optical_path_refinement.json
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_optical_core_witness.py SEARCH_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/screen_optical_camera_space.py \
  --search SEARCH_RUN --core CORE_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_optical_root_bay.py \
  --core CORE_RUN --camera CAMERA_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_optical_gel_cartridge.py BAY_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_optical_gel_tools.py SEARCH_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/screen_optical_refraction.py SEARCH_RUN
```

The current refined search selects one neutral layout from 315 candidates. The frame, camera bay and cartridge stages check matching input hashes, retained mount/nail regions, material intersections and ray-centre obstructions. The refraction screen deliberately preserves its three distal edge exits; it is not a physical coverage qualification.

`optical_cad.py` permits only bounded STL precision cleanup when an otherwise valid STEP produces coincident tessellation vertices. It records the original mesh, removed degeneracies and maximum displacement. It does not fill holes or replace an invalid CAD solid.

## Light board and complete assembly

Use the prepared KiCad Python interpreter for the native board writer, and the CAD environment for routing:

```sh
/ABSOLUTE/PATH/TO/KICAD-PYTHON engineering/scripts/write_optical_led_board.py \
  build/engineering/prototypes/optical/reproduced-placement
/usr/bin/python3 engineering/scripts/check_prototype_pcb.py \
  build/engineering/prototypes/optical/reproduced-placement \
  --name o1_blue_ring --kicad-cli /ABSOLUTE/PATH/TO/KICAD-CLI
build/engineering/tools/cad-venv/bin/python engineering/scripts/route_optical_led_board.py \
  build/engineering/prototypes/optical/reproduced-placement
/ABSOLUTE/PATH/TO/KICAD-PYTHON engineering/scripts/write_optical_led_board.py \
  build/engineering/prototypes/optical/reproduced-board --routing ROUTE_RUN/routing.json
/usr/bin/python3 engineering/scripts/check_optical_led_board.py \
  build/engineering/prototypes/optical/reproduced-board --kicad-cli /ABSOLUTE/PATH/TO/KICAD-CLI
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_optical_assembly.py \
  --cartridge CARTRIDGE_RUN --board build/engineering/prototypes/optical/reproduced-board
/usr/bin/python3 -I engineering/scripts/run_ci_tests.py --pattern 'test_optical*.py'
```

The first placement has expected unrouted connections; it must have zero other DRC findings before routing. Fabrication exports require zero final violations and unconnected items. The complete assembly includes the checked light board, carrier, actual hardware envelopes, coating and two N0 nail interfaces.

## Visuals, evidence and website

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/draw_optical_prototype.py \
  --assembly ASSEMBLY_RUN --tools TOOL_RUN \
  --board build/engineering/prototypes/optical/reproduced-board --refraction REFRACTION_RUN
/usr/bin/python3 engineering/scripts/review_optical_diagrams.py \
  --browser /ABSOLUTE/PATH/TO/CHROME --visuals VISUAL_RUN
/usr/bin/python3 engineering/scripts/freeze_optical.py \
  --assembly ASSEMBLY_RUN --tools TOOL_RUN \
  --board build/engineering/prototypes/optical/reproduced-board \
  --refraction REFRACTION_RUN --visuals VISUAL_RUN --diagrams DIAGRAM_RUN \
  --destination build/engineering/prototypes/optical/reproduced-package
/usr/bin/python3 -I engineering/scripts/check_tracked_prototypes.py
/usr/bin/python3 engineering/scripts/build_site.py
/usr/bin/python3 engineering/scripts/check_site.py
```

The frozen packet retains selected-run reports, input hashes, original mesh-cleanup evidence, CAD, molds, cut patterns, PCB/fabrication files, BOM, source software and build/test documents. The website uses `engineering/prototypes/optical/`; the separate reproduction destination above preserves the published snapshot.

New timestamps can change artifact hashes without changing geometry. Compare the declared checks and dimensions, retain unsuccessful runs, and record any revision separately. Primary supplier PDFs remain linked rather than republished as new artwork.
