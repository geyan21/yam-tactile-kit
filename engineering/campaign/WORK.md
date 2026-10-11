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
