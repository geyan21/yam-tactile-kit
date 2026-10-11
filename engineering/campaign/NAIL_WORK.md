# Separate rigid-nail development

The NAIL candidate now has a separate N1.1 digital build package alongside
R1/L1/B1/B2/C1. No physical N1 specimen or measured force result is reported.

## Current mechanism

A bare metal fork follows the original nail's contact-plane footprint. Its
leading thickness is 1.35 mm in the first geometry. Two narrow vertical metal
webs connect the fork to thicker inactive clamp ends. Fixed side carriers use
the original middle and proximal attachment axes.

The selected gauge candidate is two OMEGA SGT-2DD/350-SY41 full shear-bridge
patterns, one on each web's outer face. The 7.6 × 8.9 mm carrier fits the
modeled side surfaces. Catalog illustrations do not supply a metrology record
of every internal grid center; numerical accuracy must not assume that they do.

The earlier flat bending-strip layout would need wider supports for its
13.8 × 6.8 mm gauge carrier. Development moved to vertical shear webs to keep
the support narrower. No performance ranking comes from that layout choice.

## Frame evidence so far

`prepare_source_brep.py` recovered a valid faceted solid from the pinned
9,748-triangle hard frame. Source and recovered volume differ by about
9 × 10⁻¹¹ mm³; bounds and STEP round trip passed. This is a faceted derivative,
not the original author's analytic CAD.

A cut at native Y = −96 mm left a loose 28.1 mm³ distal crescent. Both Boolean
methods agreed. Its bounds and both raw/fixed variants are preserved under
`build/engineering/prototypes/nail/frame_review/`. The generator discards only
fragments within an explicit distal strip and checks all three attachment
regions separately.

The first nail arrangement intersected the original hard side walls, while
clearing the TPU. The current separate frame has 0.6 mm clearance pockets for
the metal webs. The protected central frame and all three attachment regions
remain unchanged. Four exported parts now pass solid, STEP and STL checks,
with no rigid overlaps in the checked assembly.

The initial metal structural runs gave about 0.0101 mm maximum tip motion at
20 N. A finer mesh at 1.25/0.5 mm aborted inside the direct high-order mesher
before the structural solve; its copied inputs remain preserved. The observed
error was `Failed to reach critical value ... ScaledJac`, with tool exit code
134. Later runs use an isolated mesh worker, saved mesh stages and an elastic
smoothing pass before direct optimization.

The 1.35/0.5 mm mesh completed with 124,898 nodes and positive Jacobians.
Visual inspection then prompted an explicit fastener-rim check. That check
found missing carrier material around all four front countersinks. The
pre-revision CAD, code and drawings were archived under
`iterations/20261011T014049.329375Z_before_complete_clamp_pads/`.
The current revision adds complete clamp pads with a 1.1 mm vertical border.
Its geometry and structural checks must be rerun before publication; the
earlier motion numbers do not qualify the revised parts.

The corrected front pads passed the four front-clamp checks. Extending the
same review to the side mounts found incomplete rims at the two right-side
countersinks. That geometry was preserved under
`iterations/20261011T021443.892752Z_before_complete_side_mount_rims/`.
The locating bosses now continue through the outer carrier plate, supplying
the full required surround. All eight fastener checks and the structural
comparison remain required on this final geometry.

N1-specific firmware, the pressure scanner, raw recorder and static force
baseline are now written. Fifteen software tests cover acquisition faults,
sample age/identity, dummy-data rejection and calibration math. These are
software checks; physical sensor and force performance remain unmeasured.

## Completed digital package and remaining physical work

The final geometry passes all eight fastener checks. The two final structural
meshes differ by less than 0.34% on the declared motion comparisons, and the
model predicts 0.0093646 mm maximum leading-tip normal motion at 20 N. The
printed frame and real joints remain outside that model.

The complete packet includes CAD, drawings, sensor locations, wiring, a BOM,
combined Pico acquisition, raw recording and static force calibration tools.
The release labels were finalized only after proving unchanged physical
parameters and geometry files. Its original development runs remain intact.

Build independent specimens and measure fit, actual joint/whole-finger motion,
contact, force, drift, precision and durability. The all-design campaign
continues with the recessed magnetic frame and the five other approaches.

The soft region uses the four retained R1 TPU cells. Sensing the nail alone
does not meet the all-region comparison. No physical N1 specimen is reported.

Primary component references are in `designs/nail.json` and
`designs/nail_electronics.json`; editable geometry is in
`scripts/nail_geometry.py` and `scripts/build_nail_parts.py`.
