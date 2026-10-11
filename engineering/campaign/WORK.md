# Build and compare all twelve designs

The requested end state is twelve physically built designs, a common measured
comparison, and a defensible choice for reliable contact and 20 N per-finger
normal-force feedback while preserving thin-tip precision access.

The existing R1/L1/B1 releases are retained. New development lives in
`engineering/prototypes/`, with editable parameters in `engineering/designs/`
and generators in `engineering/scripts/`. Generated working results stay under
`build/engineering/prototypes/`. A new package is published only with its actual
checks and explicit remaining work.

No physical performance winner has been established. No physical specimens
have been reported or tested in this workspace.

The current F1 mechanical checkpoint is `engineering/development/f1/mechanics/`:
44 checked CAD solids, twelve printable fit patterns, individual surface
unrolls, a clear sensor-placement drawing and a viewer model. Its 654 declared
static comparisons pass; twelve connector cavities/mating interfaces, fitted
copper, stiffeners, sealing, own-layer joins, slack and loaded/physical
behavior remain. The previous CH2-column/CH3-row crossing is preserved with
its two exact involved CAD solids. Checkpoint SHA-256:
`47a164c4664b48dc48f02ac3d5ac7f7860df3298c113753b49983396e1105113`.

The R2 placement reverses the three upper connector pairs and uses two back
mounting holes. Carrier and nominal tail fit use that placement. Several
custom routing orders remain unsuccessful; their complete partial results
are retained. The bundled-Java Freerouting study completed all connections.
Its independent KiCad check at
`build/engineering/prototypes/f1/fanout_r2_checks/20261011T140347.358728Z`
rejects the board with 95 findings: 87 undersized tracks, one short, one
hole-clearance finding, three courtyard overlaps, one malformed outline
segment and two silkscreen-edge findings. No R2 artwork was exported.
The rejected PCB and complete evidence are preserved separately at
`engineering/development/f1/r2-routing-study/`.

The two native CLI attempts are also retained under `build/`: the release's
native serialization failed on ComponentOutline, then on required
ObstacleArea geometry. The JVM bundle preserves both drawings and keepouts.
The SES importer restores an empty mounting-package string token and records
the 0.1 µm session-grid tolerance; the source pad nets remain unchanged.

F1's dedicated webpage and `docs/BUILD_F1.md` now describe the available
modules and actual fit procedure. The source/website packager includes
development modules and licenses. Hosted Pages staging moves the four large
download archives to immutable commit-specific GitHub Release assets while
the offline packet keeps local download links. Publication and browser checks
must be completed before calling this web update deployed. Local verification
has passed 151 software/clean-source checks, 43 main browser checks and 105
separate-page browser checks. The earlier 45-second clean-build timeout is
retained; nested compressed files now use ZIP storage, and the bounded clean
reproduction test passes.

The paragraphs below retain earlier milestones and their then-current work.
The completed digital package count remains seven; F1 is not yet the eighth.

B2.1 now has a completed digital prototype package: routed four-layer PCB,
zero KiCad DRC/connectivity findings, four checked CAD parts, firmware, a raw
recorder and actual-mesh visuals. Its build and physical tests remain pending.
C1.1 now adds nine checked CAD parts, a dual-bridge readout PCB, raw acquisition
and physical static-calibration tools. Its linear bonded-joint model passed
the declared numerical checks and calculated 0.094 mm added tip motion at
20 N; the actual assembly remains unbuilt.

N1.1 adds a bare steel nail with two shear bridges, two carriers, a revised
frame and four retained R1 TPU cells. Its readout, static calibration tools
and checked digital package are separate. No physical N1 measurements exist.
B3.1 adds a separately recessed frame and two identical tapered spacers,
retains the B2 PCB, B1 magnetic TPU and two N0 nail pads, and supplies gain-5
firmware and raw recording. Five CAD solids, protected material, full spacer
seating, 42 head/solder checks and sampled magnetic range passed. The board
moves inward 2.439 mm. Actual drive/cable motion, frame stiffness, assembly
and contact/force performance still need physical tests.

Seven digital packages are available. The five remaining designs below and
the common measured comparison remain in scope.

The initial F1 development established an actual-geometry 4 × 16 contact allocation: eight
pixels on each tapered nail prong and twelve on each of four R1 saddle
surfaces. That first allocation was not routed artwork. Its lumped electrical study
demonstrates why inactive rows need a controlled bias. With the first assumed
paths, 100 Ω and 1 kΩ cases fail the provisional 1% interaction screen.
The next circuit work is post-switch row buffering, separate selected-column
current/sense feedback, and feasible FPC resistance budgets. Offset, leakage,
stability, material spreading and actual force remain unqualified.
The revised target-path model reaches a worst interaction of 0.741% over
the stated 100 Ω / 1 kΩ / 10 kΩ cases. This is a target-resistance calculation,
not evidence that a fabricated circuit meets the budget. Detailed development
decisions and unresolved work are recorded in `docs/F1_DEVELOPMENT.md`.

F1 now also has twelve routed flat flex witnesses with complete row/column
connections, explicit coverlay openings and development Gerbers. All twelve
pass independent copper, outline and connectivity checks. Both unsuppressed
and scoped unsoldered-coverlay reports are retained; a synthetic copper-short
probe confirms that the allowance does not hide copper shorts. The actual
routed contact map has 64 regions, minimum area 5.1199 mm².

These are not the complete F1 package. Installed flex routes, separate
neutral-plane unrolls, carrier, connector/readout boards, analog checks and
acquisition software remain. The selected integration direction is recorded
in `designs/f1_integration_development.json`; it uses a removable fixed-finger
connector board and a separate wrist/base readout. Its placement candidates
and mating geometry still require verification.

F1 now also has a checked connector-board development module at
`engineering/development/f1/fanout/`. Its four-layer layout has 42 components,
232 pads, 2,221 track segments and 274 vias. Independent KiCad checking
reports zero violations and zero missing connections. The module includes
both populated faces' artwork, native source, pin tables, component values
and visuals. Twenty sense links and a switched electrical-test path are
implemented in the layout. This remains part of F1 development; it does
not increase the seven completed digital prototype packages or the zero
physical specimens.

The next F1 work is the wrist analog/ADC board, complete resistance and
stability checks, fitted flex unrolls/tails, and a manufacturable board/carrier
contour. Actual-drive fit and the common physical experiments remain required.

The selected-column readout study is preserved separately at
`engineering/development/f1/readout-study/`. It includes a circuit drawing,
explicit component values, all 104 nominal cases, all 96 independent
time-domain attempts and all twelve wire-break attempts. The nominal grid
passes its declared screen; only 83 of 96 independent probes completed.
Eight wire-break decisions are supported provisionally; four cases lack
valid complete results. Those limitations are retained in the checkpoint.
The worker now rejects aborted/partial analyses, checked against an actual
saved successful case and an actual saved abort.

This is not a completed wrist board or an eighth integrated prototype.
Four row-driver loops, the full coupled array, reference/ADC drive, switching
protocol, PCB, fitted flex and mechanics remain. The active ordering code is
OPA392DBVR; the extra `I` in the original saved simulation label is documented
as an ordering-label correction, with no circuit/model change.

The ADC and row stages now have a separate checked archive at
`engineering/development/f1/support-studies/`: 32 ADC cases and 26 one-row
cases, four smaller-step ADC replays, ten comparisons with completed
trapezoidal transients, and four unsuccessful predecessor runs. The archive
verifier checks 18 files and 1,097 members. These model results do not
qualify the complete coupled array, reference circuit or physical board.

The wrist placement has 135 components and 498 pads. Its nominal component,
pad, mounting and bypass-distance screens pass; copper routing and independent
DRC are still in progress. The native connector correspondence checks all
50 conductors for the stated mating pose. Physical cable continuity and
installed routing have not been measured.

Four-file Pico firmware and a raw host recorder now exist under
`engineering/firmware/f1/` and `engineering/software/f1_*`. Nine checks with
synthetic I/O cover sequencing, bus timing, interrupted acquisition and
complete matrix membership. The code has not been programmed onto a physical
board. It emits raw counts and timestamps, with force/contact values unset.
`docs/F1_WRIST_CAPTURE.md` explains exact component choices, pin mapping and
the limits of the cable-test path.

The first complete wrist route reached 2,607 segments and 396 vias. Its
independent KiCad check at
`build/engineering/prototypes/f1/wrist_checks/20261011T111907.129113Z`
reported zero missing connections and no copper findings, but eight
courtyard overlaps and two connector-label findings. It was not exported.

The eight part positions and connector label have been revised. Native
courtyard geometry is now included in the placement check, with line stroke
excluded from the actual courtyard boundary. The revised placement at
`build/engineering/prototypes/f1/wrist_runs/20261011T112432.874863Z`
passes body, pad, courtyard, mount and bypass-distance checks. Its fresh
routing run at `routing_runs/20261011T112505.865842Z` completes 2,561 segments
and 412 vias. Independent KiCad checking at
`build/engineering/prototypes/f1/wrist_checks/20261011T113253.067479Z`
reports zero violations and zero missing connections. Both populated faces'
fabrication and assembly files were exported.

The wrist router can resume an unchanged saved placement, preserving the
original partial run. A checked mask optimization returns identical track
and via masks for the tested actual-board cases. Restricted inner-ground-layer
crossings are used only after normal layers cannot route a connection; their
lengths are recorded for ground-plane review. Keep the failed routes and
the first DRC report. Do not count the wrist module as a finished F1 finger.

The downloadable wrist development module is now
`engineering/development/f1/wrist/`. Its 187 files include native PCB/library,
Gerbers/drills, full DRC, drawings, native cable correspondence, a blank
continuity checklist and four-file firmware. The verifier finds no missing,
extra or changed files. The actual inner-plane plot is retained with eleven
signal-net crossover inventories totaling 47.625 mm; ground connectivity
passes DRC, while analog return behavior and EMC remain unmeasured.

Next: complete reference/bias and full-array electrical checks, actual
board/cable/flex resistance, formed flex and neutral-plane unrolls, carrier
and strain relief, and the complete F1 assembly. The other four unfinished
designs and every physical build/comparison remain in scope.

## Work sequence

1. B2 digital package completed; fabricate, assemble and measure it.
2. C1 digital package completed; verify drive fit, machine, bond, assemble and measure it.
3. N1 and B3 digital packages completed; fabricate, assemble and physically test both.
4. Develop the resistive matrix, capacitive, pneumatic, optical and packaged
   force-button prototypes, including their contact and mounting interfaces.
5. Supply the common fixtures, raw-data contracts and held-out comparison tools.
6. Publish each package and its visuals on its own existing design page.
7. The student fabricates and assembles the specimens, preserves failed builds,
   and records the specified physical experiments.
8. Analyze the recorded measurements, revise failing designs, and publish the
   resulting recommendations with the limits of the evidence.

`requirements.json` retains the full list and quantitative comparison targets.
The 0.1 mm added-tip-motion screen is an engineering assumption for review, not
an accuracy requirement explicitly supplied by the user. The user's requested
range is 20 N per finger.

## Completion rules

An unrouted PCB, a bare sensor coupon, a component datasheet, a valid STEP file,
or a passing software test does not complete an integrated physical prototype.
Missing measurements remain missing. Planned or simulated values cannot enter
the measured ranking. A design can fail a declared requirement; retain the
evidence and explain whether a revision is warranted.
