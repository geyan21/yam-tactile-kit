# Reproduce the F1 R4 digital package

Use the complete repository. Prepare the pinned source geometry and isolated
CAD/KiCad tools using `engineering/README.md`. The preserved R3 fanout,
fitted-foil and wrist modules are inputs to R4; keep their checkpoints intact.
The raw geometry source has its own attribution and license.

Run from the repository root. The CAD interpreter below is the repository's
explicit virtual-environment path, not the system Python. Every generator
prints a fresh directory under `build/engineering/prototypes/f1/`. Replace
uppercase run placeholders with those actual paths. Do not edit a generator
or its inputs while it is running.

## Finished terminal and flex files

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/screen_f1_finished_tips.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_f1_finished_foil_artwork.py TIP_REVIEW_RUN
/usr/bin/python3 engineering/scripts/check_f1_flex.py ARTWORK_RUN --export
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_f1_finished_terminals.py ARTWORK_RUN TIP_REVIEW_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/check_f1_finished_terminals.py TERMINAL_RUN
```

The native checker writes `summary.json` in the printed independent-check
directory. It preserves both unsuppressed coverlay findings and the scoped
unsoldered-window review. Copper errors and missing connections are not waived.
The current terminal clearance review includes via annuli.

## Skin, joins, tooling and complete assembly

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_f1_skin_r4.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_f1_film_patterns.py SKIN_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/join_f1_finished_foils.py SKIN_RUN TERMINAL_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/build_f1_skin_molds.py SKIN_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/check_f1_assembly_common.py --skin SKIN_RUN --terminals TERMINAL_RUN --foils JOINED_FOIL_RUN --workers 2
```

The mold generator can be split into disjoint `--sites` groups. Supply each
of the six sites exactly once when assembling the final mold set; CH2–CH5
each have both a base and a cover. Every run must use the same skin report.

Use `check_f1_assembly_common.py` for the current full check. It covers all
actual material parts and the same 0.001 mm³ overlap criterion as the older
distance-based checkers. It uses conservative coordinate bounds followed
by direct native solid intersection, and retains unresolved kernels as
findings. Four analytical solid cases check its overlap verdicts.
It does not claim measured or calculated minimum clearance distances.

## Electrical model, diagrams and tests

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/inspect_f1_routed_network.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/screen_f1_routed_matrix.py NETWORK_RUN
build/engineering/tools/cad-venv/bin/python engineering/scripts/draw_f1_r4.py --skin SKIN_RUN --terminals TERMINAL_RUN --foils JOINED_FOIL_RUN
/usr/bin/python3 engineering/scripts/review_f1_diagrams.py --browser /ABSOLUTE/PATH/TO/CHROME
/usr/bin/python3 -m unittest discover -s engineering/tests -p 'test_f1*.py'
```

The electrical screen is an ideal-feedback DC model with independent
resistors. The software tests use explicit synthetic fixtures. Neither is
physical sensor evidence.

## Freeze and rebuild the website

```sh
/usr/bin/python3 engineering/scripts/freeze_f1_r4.py \
  --skin SKIN_RUN --terminals TERMINAL_RUN --foils JOINED_FOIL_RUN \
  --patterns FILM_PATTERN_RUN --assembly COMPLETE_ASSEMBLY_RUN \
  --visuals VISUAL_RUN --artwork ARTWORK_RUN --native-check NATIVE_CHECK_RUN \
  --tip-review TIP_REVIEW_RUN --dc DC_SCREEN_RUN --network NETWORK_RUN \
  --molds MOLD_RUN \
  --destination build/engineering/prototypes/f1/reproduced-package
/usr/bin/python3 engineering/scripts/build_site.py
/usr/bin/python3 engineering/scripts/check_site.py
```

Choose a new destination for reproduction so the published frozen package
and older failed work remain intact. A newly generated package can have
different file hashes from timestamped CAD exports; compare its construction
and check reports as well as preserving its new provenance.

The supplied website uses `engineering/prototypes/f1/`. Installing a reviewed
replacement there is a separate revision operation; the reproduction command
above does not overwrite it. `provenance/source_runs.json` records the exact
inputs used for the distributed package.

The package retains explicit connector, sealing, strain-relief, cable,
motion and physical-performance limitations. A successful digital rebuild
does not qualify a fabricated sensor.
