# P1 pneumatic development

Work is isolated in `build/pneumatic-worktree`, branch `design/pneumatic-p1`.
The checkout shares only the pinned public source-geometry cache via
`build/engineering/sources`; generated results stay in this checkout's build
directory. The explicit CAD interpreter is the canonical kit's
`build/repo/build/engineering/tools/cad-venv/bin/python`.

The P1 nominal bench assembly and readout are complete locally. No P1
physical specimen or force calibration exists.
The user confirmed that no new builds or measurements are available yet.

The P1.0 package is frozen at `engineering/prototypes/pneumatic/`: 414 files
plus its snapshot, 112 CAD parts/references, 40 PCB components and 3,514
declared nominal geometry comparisons. Snapshot SHA256:
`68aa9caa300bee7cf82fb73cb3e32a1d44e7107f4208bb24aa212d1ba20331fb`.
The final wiring/card review is
`diagram_reviews/20261012T053300.700772Z`, with both canvas checks passing.
P1's own assembly, electrical, test and reproduction pages are integrated;
complete website, clean-source and publication validation follow this freeze.

The current selected runs are:

- Channel layout: `wall_pair_layouts/20261012T033428.385609Z`.
- Final guarded poses: `port_pose_searches/20261012T045018.079417Z`.
- Slim CH4 front: `slim_port_probes/20261012T042933.871931Z`.
- Complete insert: `ported_assemblies/20261012T045727.167175Z`, 55 parts,
  1,540 material/source/air checks, 366 hose-guard checks, eight isolated
  capped cavities and no nominal findings.
- Routed board: `boards/20261012T044642.938727Z`, 40 components, 412 tracks,
  63 vias, native KiCad 10.0.7 DRC with zero violations/unconnected items.
- Carrier and N0 nail references: `bench_parts/20261012T050454.589293Z`,
  57 parts, 1,388 checks.
- Cross-module/pin review: `integration_reviews/20261012T051804.471388Z`,
  220 additional nail/air-module comparisons and passing pin/land checks.
- Paired gas model: `pair_screens/20261012T050406.520333Z`, 3,888 scenarios;
  26 are outside the nominal ±30 inH2O range. Common-pressure cancellation
  and thermal false signals remain modeled limitations.
- Final side/3D drawings: `visuals/20261012T052214.617429Z`.

Paths above are beneath this worktree's
`build/engineering/prototypes/pneumatic/`. The current source includes
raw firmware, recorder/receipt handling, a signed linear stationary-force
baseline and 23 passing synthetic protocol/hold tests. No physical
contact detector or measured force model is supplied.

Six standard tubes are OD1.6/ID1.0/L6 mm; CH5 back is L8. CH4 front uses
OD1.2/ID0.8/L15 mm and an OD1.6/ID1.3/L3 sleeve at its outer end.
The local hose model covers 3 mm engagement and 5 mm straight departure.
All eight actual slack routes and transducer-port mates still need inspection.
The selected pressure device is ELVR-L30D-F1RD-C-NI3H. The board has a
3.0 V LP5907 rail for the ELVRs and TCA9548A; Pico/nail ADS1115 use 3.3 V.

Preserve the earlier failures below. The first end-plug/branch overlap
was corrected with a plug guard in the pose search. Including the actual
hose envelope required revised CH2 back orientation and the longer CH5
back tube. The initial carrier run at `bench_parts/20261012T050212.470819Z`
hit a CAD-kernel error subtracting a nearly planar frame from an adhesive
envelope. The current run retains the R1 nominal envelope and independently
checks its common volume instead.

## Published basis and earlier development

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

Next routing work is not implemented yet: retain the straight front ports
where they pass, and search rear branch bores from a point inside each rear
channel toward an existing hollow region. Test outlet directions toward
either X side with a downward Z component and modest Y offsets. Reserve
enough distance from the flush end plugs. Require the full fitting envelope
to clear the source hard frame, the free metal tube to clear the insert,
and a material wall around the branch bore/embedded holder.
Do not waive the 9.811 mm³ frame collision or count a reference cavity as
clearance. A later assembled-air-volume/closure check must distinguish the
intended open tube outlets from unintended leaks or merged channels.

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

The first bounded port-pose search is
`build/engineering/prototypes/pneumatic/port_pose_searches/20261012T041355.514427Z`.
It finds seven frame-clear candidates: five straight and two angled.
CH4 front remains unresolved; its full holder intersects the hard frame by
3.5808 mm³ on either straight side. The angled candidates in the first grid
do not solve that interface.

The narrower direct-stem probe,
`build/engineering/prototypes/pneumatic/slim_port_probes/20261012T042430.369886Z`,
shows that a 1.2 mm OD metal stem clears the insert/frame with the declared
0.15 mm radial guard on both sides. The standard hose sleeve is still too
close to the frame: its guard overlaps by about 1.58 mm³ when placed over
the last 3 mm of an 8 mm external stem. Move only that sleeve farther out
and recheck; do not waive the hose collision. The prototype retains the
original rigid frame. Loaded motion and bond performance remain untested.
