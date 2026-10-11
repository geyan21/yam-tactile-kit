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
