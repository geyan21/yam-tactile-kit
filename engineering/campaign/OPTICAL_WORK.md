# O1 optical development

The active goal remains to build and compare all twelve designs. No physical
builds or measurements exist. The user already confirmed common materials
can be obtained and a student can assemble/test; do not ask again.

Worktree: `build/optical-worktree`, branch `design/optical-o1`. It shares only
the pinned `sources` and `source_brep` caches with the canonical checkout.
Use the canonical `build/repo/build/engineering/tools/cad-venv/bin/python`.
New results remain in this worktree's `build/`.

P1 is digitally complete and being published separately. Its first public
commit `85b34c4e95dc4eec37a452fa483852002627f13b` failed CI because an
unanchored `build/` Git ignore omitted seven frozen provenance files.
Follow-up `2ebb6df24ae8cc1a346f03823d544522f46c0d15` restores them, limits the
ignore to `/build/`, and adds a Git-inclusion/hash check before CI tests.
A fresh Git worktree passed all 4,411 expected frozen/source paths.
P1's 112-part, 414-file snapshot remains unchanged:
`68aa9caa300bee7cf82fb73cb3e32a1d44e7107f4208bb24aa212d1ba20331fb`.
P1 is published and verified live at
https://geyan21.github.io/yam-tactile-kit/pneumatic.html from `2ebb6df`.
Workflow 38214213124 passed. The parent worktree's publication check
`20261012T071112.099676Z` verifies all five pages, release assets, and every
member of the P1 ZIP. Eleven digital designs are published; none is
physically qualified. Do not repeat the completed P1 publication work.

## Current O1 checkpoint, 2026-10-12

The refined path `path_searches/20261012T065149.643835Z` is now the basis:
gel Y = -94…-23, camera (-7.5, 0, 22), mirror Z = 0.55Y + 60,
16.539° camera pitch, 63.892 mm mirror, 210 nominal ray segments.
`core_witnesses/20261012T071941.242797Z` passes frame/gel checks with the
window X = -13…-2, Y = -85…1. Wider earlier windows disconnected the nail.
`camera_space_screens/20261012T074327.049703Z` reserves the official
Camera Module 3 Wide envelope, rotated 180°, and a 32 mm root extension.
`root_bays/20261012T080302.568971Z` passes 595 nominal material comparisons,
ray-centre checks, and nail/drive/both mount-region preservation.

Solaris gel, Psycho Paint / Silc Pig coatings, and four Kingbright
APT2012QBC/D LEDs with individual 220 ohm resistors are selected in
`optical_materials.json`. Supplier facts and hashes are retained in
`material_sources/20261012T080411.702240Z`. The selected prototype uses
blue illumination and marker tracking, without the paper's fluorescent
paints or yellow filter. It is not a calibrated photometric normal map.

The first retained cartridge at `gel_cartridges/20261012T081832.857213Z`
had a valid single STEP solid but two microscopic nonmanifold STL edges.
The unchanged STEP was reviewed at `mesh_export_reviews/20261012T082559.487955Z`;
finer tessellation does not cure it. The seat edges were adjusted 0.05 mm
into the adjoining walls to avoid a coincident edge; recheck before use.
The failed CAD and all diagnostic results are preserved.

Remaining: pass the retained cartridge, gel molds/patterns, light board
and retention, N0 nail integration, local image acquisition and measured
analysis, final checks, separate O1 pages, frozen packet and publication.
No optical force/contact model or physical comparison result exists.
The older search notes below are history, not instructions to restart.

## Verified primary sources

The Baby Fin Ray v1 paper was fetched to
`reference_sources/20261012T054402.830874Z` beneath
`build/engineering/prototypes/optical/`. It describes a hollow TPU 95A
structure, a 2.5 × 18 mm gel section, a 0.2 mm reflective PET sheet and a
small 120-degree spy camera at the base. Its different geometry/results
do not establish O1 or 20 N performance.

Official Camera Module 3 Wide mechanical/product documents and the
Picamera2 manual are in `camera_sources/20261012T055639.449081Z`.
The product HTML returned 403; the three official PDFs succeeded.
Hashes and factual review are in `research/optical_source_review.json`.
The proposed O1 device is **Raspberry Pi Camera Module 3 Wide, standard
visible-light IR-cut variant**, Sony IMX708. It is a different camera from
the paper's spy module. No SKU code was verified or invented.

The drawing was visually reviewed at
`source_page_reviews/20261012T060143.935050Z`. PCB dimensions are
25 × 23.862 × 1.12 mm; product overall height is 12.4 mm for Wide.
Horizontal/vertical nominal FOV: 102/67 degrees. From the drawing's
top-left board datum, Ø2.2 holes are at X = 2/23 and Y = 9.362/21.862;
the lens axis is X = 12.5, Y = 9.462. These holes are not symmetric
about the lens axis. The entrance pupil is unspecified. Do not treat a
mechanical lens outline as a calibrated ray origin or focus guarantee.
Picamera2 `RGB888` memory is **B,G,R**, suitable for OpenCV.

The paper's gel/paint mixture is a reference, not a selected current
manufacturer-qualified O1 material recipe. Actual materials, coating,
illumination and capture code still need completion.

## Current geometric evidence

`path_searches/20261012T061315.432063Z` contains 378 bounded neutral ray
cases. Five pass the declared gel-visibility/cone screen. It uses a
smoothed source front profile, 13 mm-wide / 2.5 mm-thick candidate gel,
and a flat neutral mirror plane. It does **not** clear the original ribs
or frame, include refraction/distortion/focus, or infer force.

The height-first selection is case 34:
camera ray origin X = -7.5, Y = 0, Z = 18 mm; mirror Z = 0.55 Y + 60;
mirror extent Y = -84.327 to -26.205 mm. Mirror length is 66.334 mm;
maximum Z = 45.587 mm. Camera pitch is 20.460 degrees above native
distal direction. Vertical ray span is 45.483 degrees; path lengths are
68.67–101.08 mm. The camera-leg clearance is 1.818 mm in the simplified
gel-only screen. Case 76 (same slope/intercept, camera Y = 0, Z = 22)
is also viable and may offer a better root aperture/clearance tradeoff.
Neither is a final camera mount.

The first run failed only while plotting a Shapely ring; that source is
preserved in commit `6656173`. The corrected script uses `ring.coords`
and saves `geometry_result.json` before plotting.

Actual-source mesh intersections are in
`obstruction_reviews/20261012T062657.300078Z`. Across the five passing
layouts, 195–223 of 228 centre-line segments hit the original hard frame,
and 147–162 hit TPU. Case 76 has 216 frame-blocked segments, including
141 surface hits in the reporting zone Y ≥ -15. The hits do not touch
the nail zone Y ≤ -96. These are zero-width ray checks, not aperture or
manufacturing-clearance qualification.

The retained interface report places the two mount bores along Y at
X ≈ -20.7108 and 0.2892, Z ≈ 14.2832 mm, with 21 mm pitch.
Their measured section radii are roughly 2.3 mm (one counterbore larger).
Any new frame must preserve the attachment regions and bores explicitly,
not merely remain one connected solid.

## Next implementation

Use a **fixed camera and rigidly supported mirror** for O1, with a compliant
gel/front carrier. This is a deliberate precision-oriented alternative to
the paper's freely bending mirror. Existing B1/P1 and all other designs stay
unchanged. No physical accuracy or stiffness improvement is claimed.

Before frame CAD, refine the optical field to end near Y = -23 mm, matching
the proximal R1 contact region and leaving room for the source insert's
root retention. Keep the previous full-length search as history.
Require a root optical aperture above the protected mount-bore region,
then determine the actual material to remove from the frame and TPU.
Minimize added rear height; the current neutral mirror is substantially
higher than the original frame and that footprint penalty must be visible.

Build the revised frame/optical backing, hollow front carrier, retained gel
and molds, camera/LED mounting and two thin R1 N0 nail interfaces. Verify
source attachment preservation, material intersections, optical aperture
clearance and controlled displacement cases. Camera pupil/focus and actual
drive/hose/cable fit remain physical acceptance items.

Then finish exact illumination/material procurement, acquisition and image
quality handling, physical force/contact analysis, separate O1 pages and a
coherent frozen packet. No O1 fabricated package, force model or contact
detector exists yet. Do not mark the overall goal complete.
