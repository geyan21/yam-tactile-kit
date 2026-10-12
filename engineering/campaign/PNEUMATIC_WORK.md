# P1 pneumatic development

Work is isolated in `build/pneumatic-worktree`, branch `design/pneumatic-p1`.
The checkout shares only the pinned public source-geometry cache via
`build/engineering/sources`; generated results stay in this checkout's build
directory. The explicit CAD interpreter is the canonical kit's
`build/repo/build/engineering/tools/cad-venv/bin/python`.

No P1 physical specimen, completed assembly or force calibration exists.

F1 was published and verified at commit
`e8f794c3d4b0af61a1cb4bcfeb16a2d3b2357d4e`, release `kit-e8f794c3d4b0`.
Actions run 38199610904 succeeded. The canonical checkout's
`build/engineering/publication_checks/20261012T034634.437400Z/report.json`
verifies all four release hashes, the live F1 pages and source/snapshot
files, and every nested file in the 71,529,705-byte F1 prototype ZIP.
There are ten published digital packages and zero reported physical specimens.

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

The revised separate-member layout is
`build/engineering/prototypes/pneumatic/wall_pair_layouts/20261012T033428.385609Z`.
It places four pairs of 1.5 mm channels, with local support circles reserving
0.6 mm walls. Only 1.9505 mm³ of material is added inside the original exterior
outline. The source frame's existing open regions remain between front and
back members; a continuous straight material web between the channels is
not required in this revision.

The corresponding 3D witness is
`build/engineering/prototypes/pneumatic/insert_witnesses/20261012T034054.152615Z`.
It contains the soft-body witness and eight gas-volume references. Original,
modified and added-material intersections with the actual hard frame are
all zero. The nominal round gas references overlap the faceted body holes
by 0.002661 mm³ each; this small polygon/circle difference is explicitly
reported rather than hidden. Actual ports and seals were absent from this
witness. The next generator adds external reinforced tube sockets and
flush plugs, with its own material/frame/peer checks.

The first port attempt,
`build/engineering/prototypes/pneumatic/ported_insert/20261012T035338.282864Z`,
generates CH2 front successfully but rejects CH2 back. A straight fitting
intersects the original hard frame on either X side, approximately 9.811 mm³
per candidate. Preserve the partial parts and failed-port report.
The next search will test angled exits from the rear channel into the
existing open rib space, with explicit checks for the frame and free metal
tube. No port route or complete P1 assembly is claimed yet.

The next layout will evaluate those separate wall channels. Keep the first
survey and its assumptions as history. Its `single_depth_interval_mm` field
contains the minimum and maximum sampled valid depths; it does not certify
every intermediate depth across the original holes.

The All Sensors F1RD package was visually checked on page 14 of DS-0375
Rev C. In I²C mode: pin 1 supply, 2 ground, 3 analog output, 5 clock and
8 data; pins 4, 6 and 7 must remain unconnected. B is the high-pressure port,
A the low-pressure port. PAD-27 specifies 2.54 mm pin pitch, 16.26 mm row
separation and 0.89–1.00 mm finished holes. The package's 3 mm and 2 mm
diameter callouts are retained without treating the smaller dimension as
a verified internal bore. Use a conservative outside envelope and inspect
the actual tube interface; internal transducer dead volume remains unknown.

The FORTE hardware guide specifies Flexible 80A resin, silicone glue and
1/16-inch-ID, 1/8-inch-OD PVC tubes. Those are reference construction choices,
not a qualification of the new ENPIRE geometry, sealing or 20 N range.
The transducer range remains a candidate pending chamber/deformation work.

The earlier gas-law study uses separate gauge readings and electronic
reference subtraction. A single differential transducer connected across
two sealed channels needs its own differential/common-pressure review.
Its back channel is not automatically an unloaded reference. Mechanical
coupling, thermal gradients, leakage, tube movement and calibration remain.
