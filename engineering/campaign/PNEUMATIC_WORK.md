# P1 pneumatic development

Work is isolated in `build/pneumatic-worktree`, branch `design/pneumatic-p1`.
The checkout shares only the pinned public source-geometry cache via
`build/engineering/sources`; generated results stay in this checkout's build
directory. The explicit CAD interpreter is the canonical kit's
`build/repo/build/engineering/tools/cad-venv/bin/python`.

No P1 physical specimen, completed assembly or force calibration exists.

The first source-material survey is
`build/engineering/prototypes/pneumatic/channel_space/20261012T032116.463531Z`.
It reproduces the original constant-width TPU volume from its YZ section
with 1.82e-12 mm³ error. It tests 1.0, 1.5 and 2.0 mm circular channels with
a 0.6 mm source-wall assumption at the four R1 contact-region midpoints.

Single 1.0 mm sections fit at all four sampled sites. Single 1.5 mm sections
fit at CH2–CH4 but not CH5. The 2.0 mm sections do not fit at these sample
locations. The initial pair search requires a continuous solid web on the
normal-depth line between both circles; none passes that restriction.
It does not rule out separately sealed channels in the front and back
members across the existing hollow frame.

The next layout will evaluate those separate wall channels. Keep the first
survey and its assumptions as history. Its `single_depth_interval_mm` field
contains the minimum and maximum sampled valid depths; it does not certify
every intermediate depth across the original holes.

The All Sensors F1RD package was visually checked on page 14 of DS-0375
Rev C. In I²C mode: pin 1 supply, 2 ground, 3 analog output, 5 clock and
8 data; pins 4, 6 and 7 must remain unconnected. B is the high-pressure port,
A the low-pressure port. The manufacturer drawing specifies 3 mm port OD
and 2 mm bore. Check the PAD-27 footprint before board layout.

The FORTE hardware guide specifies Flexible 80A resin, silicone glue and
1/16-inch-ID, 1/8-inch-OD PVC tubes. Those are reference construction choices,
not a qualification of the new ENPIRE geometry, sealing or 20 N range.
The transducer range remains a candidate pending chamber/deformation work.

The earlier gas-law study uses separate gauge readings and electronic
reference subtraction. A single differential transducer connected across
two sealed channels needs its own differential/common-pressure review.
Its back channel is not automatically an unloaded reference. Mechanical
coupling, thermal gradients, leakage, tube movement and calibration remain.
