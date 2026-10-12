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

K1.2 is now public at commit
`a4c21794852925f8ef7c4edb58e6ffa38c4e4187`, release `kit-a4c217948529`.
Actions run 38185969621 completed successfully. All four Release archive
hashes match the local prepared distribution:
source `64e7642cbcf63876950dda54bca4407546ee8322088a216acbc418601db2fb27`,
designs `4dfa180d90d1201c90d5e04fe1c98104a8d2a485817840a2d1dc54904d53e901`,
site `ef100591d5fb0ff4e994b2883af42697a30a79212a6aab11943c9f222127650c`,
complete kit `ba449fb8ede40b73df1ab44e612afdb22782e46a4b26a9b7c0667bb4444a19b8`.
The complete kit is 1,474,099,157 bytes. The hosted distribution is
493,668,631 bytes; its 4,641 remaining local links pass verification.
Hosted browser checks pass: 53 main-page and 131 design-page checks with
all twelve design IDs covered.

Live F1, K1 and FB1 pages return HTTP 200 with the expected release.
K1 exposes the new prototype, stack, force-test guide and matching viewer.
Its live prototype snapshot matches
`5659f5e760c894a9ba158fff6e4dd520cbb1ad5f7d6b030a4b187ee2334b9413`.
The public K1 ZIP returns HTTP 200 and matches the local size of 61,701,301
bytes. This verifies delivery; physical specimens remain zero.

Work continues on `design/f1-integration-r4`. Preserve every frozen package.
F1 still needs the manufacturing/mating stack, full routed resistance and
coupled-array review, motion slack, sealing, assembly and physical comparison.
Pneumatic and optical integration also remain in scope. The full goal is
active; no measured winner is claimed.

The initial R4 terminal review is
`build/engineering/prototypes/f1/finished_tip_reviews/20261012T001811.424747Z`.
It uses the cached Hirose catalog's 1 mm terminal drawing and construction
guidance (pages 11 and 14), rendered for working review in
`mating_source_reviews/20261012T000947.685757Z`; page 8 is also available in
`mating_source_reviews/20261012T001415.801218Z`.
No complete proprietary catalog image is republished.
The selected proposal is 200 µm PI stiffener plus 50 µm bond, with 3 µm
nominal nickel and 0.2 µm gold on exposed contacts. A single-copper tongue is
0.3132 mm nominal. Retaining the rear coverlay on the two nail-row foils
would make that proposal 0.3632 mm, above the connector's 0.35 mm maximum.
The first review measured 0.525 mm to the routed back-copper regions but
omitted the separately represented plated annuli. The corrected review,
`finished_tip_reviews/20261012T005629.615428Z`, includes those pads and
finds **0.200 mm** nominal clearance for the same 6.4 mm relief. It still
passes the declared 0.15 mm geometric screen; manufacturing registration
is not established by this nominal result. The ten physical one-layer
foils need no rear mask change.

The new, separate R4 artwork run is
`artwork_runs/20261012T002149.845595Z` under the same F1 working root.
It changes only the two required rear windows and the native generator/
metadata labels; serialized outlines, copper regions, contacts, vias, paths
and stiffener footprints are exactly retained. The first attempt compared
in-memory Shapely tuples with JSON arrays and failed that identity check;
it is preserved. The successful generator compares serialized structures.
Independent checks in
`independent_checks/20261012T002212.346742Z` pass all twelve foils:
286 retained unsuppressed shared-coverlay findings, zero unreviewed
findings, and zero missing connections. These are still development
exports; no completed F1 prototype is claimed.

`f1_gold_wrist_link_r4.json` records a manufacturer-reviewed comparison
candidate, Molex 150200545 (50 conductors, 0.5 mm pitch, 152 mm Type A,
gold-finished). Its dimensional/plating limits do not establish a qualified
pair with the selected Hirose connector. The newer sales drawing permits
shorter exposed/support lengths than the initial Hirose targets; the gold
and nickel minima also differ from Hirose's construction example. Treat
those as incoming-inspection/material questions, not a completed
compatibility proof. The thicker 0.27 mm insulated section needs a new
route/bend check. No order has been placed.

Actual routed-metal models are in
`routed_network_reviews/20261012T004010.736105Z`: twenty current nets in two
temperature/copper scenarios. They use actual fanout traces, pad locations
and vias and retain the separate drive and sense-pickoff locations. Numerical
controls check one strip, duplicate-overlap removal and a single via.
Pads are idealized equipotential regions. A via star gives a full-barrel
pair resistance without counting parallel copies; actual inner-layer Z
and multi-terminal barrel fields remain approximations.

The corresponding DC matrix study,
`routed_matrix_screens/20261012T004244.848426Z`, includes the preserved
foil-path resistance estimates plus declared 50 mΩ connector and 10 mΩ
electrode-spreading allowances. All six scenarios pass the 1% electrical
interaction criterion; the maximum is 0.9253% at the 100 Ω hot/minimum-copper
case. This is an ideal-feedback, independent-resistor DC model, with no
force mapping. Film lateral conduction, offsets/leakage, gain range,
coupled transients and actual measurements remain.

The normal-browser vendor-model attempt is preserved in
`connector_browser_sources/20261012T004525.829733Z`. Both the product page
and download returned a small “Forbidden.” document from this network.
No login, challenge solving or security bypass was attempted. The real
connector cavity and contact datum remain unverified.

Corrected terminal CAD is
`finished_terminal_cad/20261012T005754.311962Z`: forty parts/references for
twelve foils. The two nail-row reinforcements are separate tip/transition
pieces so a flat PI sheet is not forced over the backing-layer step;
their terminal via annuli lie inside the static reinforcement regions.
The first attempt used a pattern name instead of the actual
`_fit_tail_reference` part ID and is preserved.
`fit_reviews/20261012T010103.492486Z` passes 704 declared source/peer/
component checks. All twelve real mating cavities remain excluded and
explicitly unqualified, rather than being replaced with invented holes.

Retained skin CAD is
`retained_skin_cad/20261012T011152.010251Z`: 58 parts/references across six
cells, including four compliant R1-derived fitting bases. All declared
base-to-source checks pass. It includes plated-stack allowances, peripheral
covers and explicit bond/foil-exit interfaces. The nominal top heights are
0.4614 mm on the nails and 0.7264 mm above the R1 TPU datum; the variable
fitting base below that datum is additional geometry.
The first cover-mold test (CH0) is running in owned session 79752.
Complete body/finish/tail envelope joining is running in owned session 71233.
Inspect those terminal results before starting the remaining mold shapes
or claiming joined-foil completion. Complete assembly checks, manufacturing
drawings, seal/strain-relief installation and physical testing remain.

At this prepublication checkpoint, K1.2 is frozen at `engineering/prototypes/capacitive` on
`design/k1-integration`, but has not been published. The public site still
has eight digital prototype packages; the local package count is now nine.
The new snapshot has 806 files and 241 CAD parts/references.
The final cell check completed successfully in owned session 47827; its run is
`cell_mechanics/20261011T222052.188577Z/assembly_reviews/20261011T222735.414702Z`
under `build/engineering/prototypes/capacitive/`. All six cells passed:
465 final comparisons and zero findings. Use its final report. Firmware,
static calibration tools and nominal geometry are still physically untested.

Current mechanical CAD is `cell_mechanics/20261011T222052.188577Z`: 114
parts across CH0–CH5 and REF. Its report SHA-256 is
`59f76ed43e016f71287a566ae54dceea297f751476b40e8392dfb571c50513f4`.
The matched review `clearance_reviews/20261011T222343.521394Z` passes all
seven lip/stop checks. Nominal bonded stop height is 0.1262 mm, travel is
0.0738 mm, and the conductive-bond envelopes remain 0.0762 mm clear at full
nominal stop. An earlier CH2 lip/stop overlap was relieved. Failed intermediate
CAD remains preserved. Sub-nanometre chart roundoff uses a bounded boundary
displacement check without moving shared outer edges.

Cover tooling is `cover_molds/20261011T222343.629473Z` for CH0 and
`cover_molds/20261011T222411.385240Z` for CH1–CH5/REF: fourteen registered
halves, steel-insert cavities and two foot-level overflow channels per shape.
Physical cure compatibility, flash control and demolding are unqualified.
`stiffener_tools/20261011T222311.691205Z` supplies seven neutral-plane cut
patterns and eight curved bonding forms. Polyimide is bonded in curvature;
no heat-setting is assumed.

The two-copy bank enclosure is `enclosure/20261011T222605.270735Z`:
44 CAD parts/references and 504 declared checks passing. It has a protected
reference support, pressure-harness ports, tie slots and mounting tabs.
Pico stays outside the cases. The actual drive bracket and full moving-harness
clearances still require measurement.

Foil geometry is `foil_runs/20261011T210432.796205Z`, native set
`foil_pcb/native-04`, checked in
`foil_pcb/native-04/independent_checks/20261011T211642.371462Z`.
All seven boards pass with zero violations/unconnected items. Native KiCad
and Gerber job files specify the 0.186 mm stack.
The full formed-foil check is `foil_fit/20261011T214927.820498Z`:
30 parts and 675 passing comparisons. Nail terminals lift 0.4 mm through a
length-preserving 4 mm free bend. Current casting CAD is
`cad_runs/20261011T212153.005385Z`; supports are
`saddle_runs/20261011T212853.113437Z`.

The complete-outline/cable/retainer study is
`assembly_screens/20261011T222925.545416Z`. Taoglas 300815C010000A is
the selected 0.81 mm coax: pressure leads at most 150 mm, references 25 mm.
Grounded-CIN planning totals are 293.30/312.81 pF nominal and 348.89/373.20 pF
with an assumed 85 µm core and permittivity 3.6. They meet the conservative
400 pF joined-shield plan; the real parasitic network remains unmeasured.
Ninety uniform material/cover cases retain 36 failures of the illustrative
five-resolution-step signal screen at 0.2 N. Four cases have early-stop
findings under thicker adhesive assumptions. These are model findings,
not measured material properties or physical qualification.

Current drawings and viewer models are
`prototype_visuals/20261011T230622.402815Z`. Earlier renderings remain.
The newest view uses explicit transparent layer order to prevent whole-mesh
painter occlusion and separates the case labels.
Build/test guides, BOM, K1.2 catalog entry and freezer are prepared.
The freezer checks native/foil/pose and assembly dependency identities.

Protocol 2 preserves boot identity, repeated startup configuration and
physical/electronics recording labels. The force fitter re-decodes raw data,
requires held-out sessions, actual >=20 N endpoints and mixed contacts, and
freezes one force axis in the source finger frame. It cannot silently sum
differently oriented local normal magnitudes as gripping force.
Seven focused force tests pass after the earlier 22 acquisition checks.
No physical calibration or contact threshold exists.

Pages staging now maps development/prototype STEP/STL links to immutable
GitHub-commit files, retaining local offline archives and hosted viewer meshes.
File/source hashes must match. The dynamic main-page CAD table receives
the same URL map as static pages. Seven distribution tests pass.
All 203 software and fresh-source package tests pass. The verified offline
browser run is `build/engineering/browser/20261011T233206.622326Z`:
52 main-page checks and 131 design-page checks, covering all twelve IDs.
K1 desktop/mobile screenshots and the stack/file views were inspected.
The single-browser all-page runs at `231945.771903Z` and `232748.518866Z`
hit their 40-second bound and were stopped as owned processes. They remain
preserved. Each design now loads only its matching model (about 0.45–3.5 MB
instead of the shared 18 MB bundle). The unchanged per-page checks run in
four batches of three, with the 40-second bound kept for each browser and
explicit complete/unique ID coverage.
Final archive sealing and hosted distribution checks remain before publication.
The local report viewer now accepts FB1/K1 static validation, retains
unavailable holds and rejects K1 files without their declared force axis.

F1's current Hirose page and PDF are reachable through the search service.
A fresh bounded STEP-cache attempt, owned session 71966, received HTTP 403
from Hirose, not an automatic-approval rejection. No access control was
bypassed. F1 mating/lamination and complete resistance/array work,
pneumatic/optical integration, and all physical builds/tests remain in scope.

The corrected FB1 publication is commit
`ed0d76dbeacf3a810aa3729a2b6bdbf1afc43726`, release
`kit-ed0d76dbeacf`. Workflow 38172826768 completed successfully; the four
Release archive checksums match the local prepared package. Live FB1,
F1 and K1 pages all contain that release. The public FB1 ZIP is 13,742,609
bytes, and its live prototype manifest matches SHA-256
`9342dd7f05d06108eb423efc129c7d5f5c3090a8c0256a158261963853c0ae2a`.
The hosted payload is 884,992,657 bytes. This verifies delivery, not hardware.

Current K1.2 integration changes are on `design/k1-integration` and are not
yet a new public K1 package. A 0.80 mm minimum active inset is now applied
in developed flex-neutral-plane coordinates and mapped back to the source
surface, so the post tooling and electrode can share a footprint. The check
in `electrode_windows/20261011T203915.094059Z` passes all six guard windows.
The old K1 module and its exact configuration remain preserved.

The shield screen now includes the reference foil and declared tail-area
allowances (20 mm² per sensor foil, 10 mm² for the reference). The previous
336/373 pF figures described only the three finger foils plus cable/board
allowances. With the reference and tails included, the 50 µm core study
`screens/20261011T204619.316859Z` gives 470.12/507.58 pF under its deliberately
pessimistic grounded-CIN assumption. A conservative 400 pF total is used for
the CAPDAC-disabled reference mode, where TI documents that the shields join;
no doubled drive capability is assumed.

The current proposal uses a 100 µm core, for a requested 0.186 mm flex
stack. `screens/20261011T204815.513859Z` gives 267.56/286.29 pF nominal and
317.32/340.66 pF in the declared 85 µm-core / relative-permittivity-3.6 case.
These are planning assumptions, not fabricator guarantees or a solved
parasitic network. The initial capacitance estimates are 4.674–15.479 pF;
the unloaded reference is 8.157 pF. All declared uniform-post range cases
pass. Nominal nail addition is now 0.836 mm; the TPU stack is 1.786 mm above
the R1 smoothed datum, with the fitting base below it. Actual copper,
tail paths, manufacturing targets and measured parasitics must still be
checked against the allowance.

Current post counts are CH0=68, CH1=64, CH2=132, CH3=176, CH4=132,
CH5=242 and REF=130. New casting/tooling must be generated for this
configuration. The latest guard check is
`electrode_windows/20261011T204815.525099Z`. Complete flex artwork, native
checks, stop/retention/vent details, plate bonds, cables, enclosure, physical
acquisition and comparison remain. No K1 physical result or integrated
prototype completion is claimed.

FB1.1 was published in commit `1a7a2a4115413f9534924990d2b3cbc1e68f5a2d`.
Workflow 38171635196 completed successfully; all four public Release archive
checksums matched the prepared files. The separate live FB1, F1 and K1 pages
served that release. The hosted payload was 884,991,448 bytes.

The subsequent host-evaluator correction closes a coverage edge case:
the general force-level tolerance must not count a measured 19.8 N hold as
the required 20 N endpoint. Twenty focused FB1 software tests now pass.
The prototype snapshot was refreshed only for the evaluator; CAD, PCB,
firmware and structural evidence are unchanged. Use the stable CAD manifest
as the recording's geometry identity. The pre-correction snapshot is retained
in `build/engineering/prototypes/force_button/software_updates/20261011T203008.252128Z`.

K1 integration has resumed on `design/k1-integration`. The first electrode
window check is
`build/engineering/prototypes/capacitive/electrode_windows/20261011T202300.332311Z`.
All six existing cell envelopes lack space for the simultaneously specified
0.30 mm edge clearance, 0.20 mm guard and 0.20 mm isolation. The protected
reference footprint fits. A proposed 0.80 mm inset retains at least 79.37%
of each original active area. This is a planning result, not fabrication
artwork: matched post tooling, capacitance/shield-load estimates, actual
copper routing, retention, stops, vents, plate bonds and physical tests remain.
The existing K1 module has not been changed by this inspection.

FB1.1 is now packaged at `engineering/prototypes/force_button/`, bringing the
digital prototype count to **eight**. Its 174-file snapshot includes 54 CAD
parts/references, the selected Honeywell FMAMSDXX025WC2C3, a two-layer sensor
PCB, four-file Pico firmware, raw recording and physical static-calibration
tools. The complete goal remains unfinished: F1, K1, pneumatic and optical
integration, fabrication and all physical comparisons remain.

The current FB1.1 uses 0.50 mm 301 spring-steel guides. CAD run
`build/engineering/prototypes/force_button/cad_runs/20261011T194618.636721Z`
passes 1,519 declared checks in `fit_checks/20261011T194806.883664Z`,
including actual sphere/plunger contact. The first sphere envelope had
accidentally used CadQuery's default upper hemisphere. That failure is
preserved; the corrected full sphere includes a documented removal of one
collapsed zero-area STL pole facet, without changing STEP geometry.

The native board is `pcb/routed-01` beneath the same prototype work root.
Its final independent check is `checks/20261011T192405.135835Z`: four
components, sixteen electrical pads, 46 tracks, three vias, zero violations
and zero missing connections. The original shared PCB checker remains
unchanged; FB1's separate wrapper exports its two designed copper layers.
Nineteen focused software checks cover raw statuses, supply/configuration
faults, timestamps, restarts, geometry/PCB correspondence and held-out
physical-trial handling. No synthetic data are presented as physical evidence.

The structural review is
`structural_reviews/20261011T200303.184054Z`. A 109,803-node fine model and
73,187-node coarse model pass the declared 1% displacement/gain comparison.
At 20 N, the fine model gives 0.0876360 mm added contact motion for an assumed
0.0001 mm/N sensor compliance and 0.0924378 mm for 0.0005 mm/N. Including
the observed mesh difference gives 0.0930659 mm against the provisional
0.1 mm screen. This is a linear model with bonded clamps and a rigid original
finger, not physical accuracy, strength or fatigue qualification.

The earlier 0.40 mm guide design is retained in `history/`. Its corresponding
models gave 0.0981779 and 0.1041905 mm; the latter lacked precision margin.
The first unbounded meshing attempt was intentionally stopped through owned
session 67979 after over eight minutes. Its inputs and stop record remain;
later jobs use a scoped parent process, saved PID/log and explicit timeout.

The separate FB1 page, build guide, test guide, CAD viewer and download links
pass local verification: 188 software/clean-reproduction tests, 5,019 local
links, 43 main-page browser checks and 110 separate-page checks. Screenshots
are retained in `build/engineering/browser/20261011T201059.509007Z`.
Publication uses the existing GitHub Actions/Pages pipeline; exact-commit
workflow, release and live-page evidence is collected by `check_publication.py`.

The paragraphs below retain earlier milestones as written.

K1 capacitive development is now at `engineering/development/capacitive/k1/`.
It contains 49 current CAD parts, seven post-sheet patterns (reference tooling
used twice), corrected conforming supports, a checked readout PCB and raw
firmware/decoder/recorder. Its 197-file checkpoint is
`424b8292b2044f82ce40f3e246782a09c70bb7bbf3ad64f6be979810610767cd`.
The earlier unpublished archive is preserved at
`build/engineering/prototypes/capacitive/k1-archive-before-capture-setup`;
the current module adds explicit isolated-recorder setup instructions.
The full K1 finger remains unfinished; the digital prototype count stays seven.

The K1 cell CAD run is
`build/engineering/prototypes/capacitive/cad_runs/20261011T165415.841509Z`.
Earlier large flat-face triangles produced invalid formed views of the
50 µm base; a source-preserving Gmsh surface mesh resolved that visualization
problem. The original failures and the direct comparison remain in
`cad_runs/20261011T164435.452494Z/forming_reviews/`. The four complete
conforming supports are in `saddle_runs/20261011T172831.557871Z`, with all
18 declared source/peer/electrode checks passing. These replace the initial
slab-only supports, which did not reach the raw TPU fitting geometry.

The K1 native board is at
`routing/20261011T172208.410587Z/native-documented-drill` below the same
capacitive development root. KiCad 10.0.7 reports zero violations and zero
missing connections for 23 components, 72 pads, 357 track segments and 34
vias. In1.Cu is reserved for driven shields. The declared native MSOP-pad
gap is 0.15 mm; routed clearances remain 0.20 mm and via drills 0.25 mm.
Earlier component/label findings, failed pin escapes and the first check
using KiCad's default 0.30 mm drill limit remain preserved.

The revised screen is `screens/20261011T163932.182186Z`. Its pressure-cell
capacitance estimates range from 6.2 to 16.8 pF before reference subtraction,
and its conservative shield scenarios are approximately 336/373 pF. Those
figures are model assumptions, not measured performance. The 0.786 mm nail
addition and 1.736 mm stack above the R1 TPU datum are precision-access
concerns; the latter is not the complete addition to bare TPU.

Eighteen focused K1 software checks pass, covering fresh transactions,
signed results, configuration changes, supply/ground/reference failures,
gaps and preserved unknown force/contact. Physical noise, timing and fault
coverage remain unverified. Still required for K1: electrode fabrication,
plate-ground joints, stops/retention, venting/sealing, guarded cables,
enclosure and complete-finger physical comparison. The pneumatic, optical,
force-button and unfinished F1 work remain in scope.

The latest separate F1 module is
`engineering/development/f1/fitted-foils-r3/`. Its twelve fitted foils pass
independent KiCad copper/connectivity checks. All 286 unsuppressed
shared-coverlay findings are retained; only the explicitly unsoldered
coverlay rule is permitted. There are zero unreviewed findings and zero
missing connections. The module has 291 files and checksum
`ab2beab85f3e87f1b3a98afc6f37d98274aed7c79745129593a6b741e328a71a`.
An unpublished archive attempt is preserved at
`build/engineering/prototypes/f1/fitted-archive-before-input-name-fix`.
Captured checkpoint inputs now use a distinct filename plus a path/hash
index, so the site does not mistake a provenance copy for a nested release.

The generator retains failures from `20261011T155317.884475Z`,
`155532.004847Z`, `155656.723105Z` and `155913.090000Z` under the same date.
Those exposed trace-clearance pinches, clipped inner offsets near the upper
connector turns and numerical polygon seams. The successful run is
`build/engineering/prototypes/f1/artwork_runs/20261011T160007.723397Z`;
its independent check is `independent_checks/20261011T160104.706906Z`.
The cut outlines use recorded 10 nm coordinate quantization; the original
R3 fit packet remains unchanged. Narrow trace sections and the staggered
pin-1 plated transition are explicit in the generated paths.

The matching `fitted_reviews/20261011T160342.338936Z` identifies all 64
row/column locations, with minimum nominal source-surface overlap
4.1243 mm². Forty one-dimensional trace estimates reach 0.1642 Ω nominal
and 0.2549 Ω in the declared 50 °C / minimum-copper / negative-width case.
Those estimates exclude electrode spreading, barrels, contacts, boards and
cable; the earlier 0.25 Ω complete-path assumptions are not qualified.
Mating/finished lamination, sealing, object/motion access, slack, full
resistance/array/reference checks and every physical experiment remain.

The latest F1 interface/fit module is `engineering/development/f1/r3/`.
Its native R3 board has 42 components, 232 pads, 959 track segments and
155 vias. Independent KiCad checking at
`build/engineering/prototypes/f1/fanout_r3_checks/20261011T152916.383909Z`
reports zero violations and zero missing connections. The same source was
rechecked after packaging. In1.Cu contains no signal tracks; its actual
filled plane was reviewed. All sixteen short sensor pickoffs, both VDD
bypass paths and nearby ground paths are preserved. Minimum nominal
via-to-paste gap is 0.115 mm, and the fifty cable pin correspondences pass.

R3 moves UT and CT1/CT2/RT together, includes actual native courtyards in
placement acceptance, cleans the inward board edge, names the mounting
footprints, and fixes the two upper labels. Explicit connector escapes,
extra planning clearance and specific verified cleanup replace the
sub-minimum necks/unused transitions in the earlier routes. No DRC rule was
suppressed. The rejected R2 study and intermediate R3 attempts are retained.

R3's matching 44 CAD solids and twelve fit patterns have 654 passing nominal
hardware-to-hardware comparisons. Their source/configuration chain is checked
against the PCB placement. At that checkpoint, twelve connector cavities/mating interfaces,
fitted electrode copper, finished stiffeners, sealing, own-layer joins,
object-approach envelopes, inextensible motion slack, full resistance/
coupled-array/reference checks and every physical experiment remain.
The current module checksum is
`4c4645a2220a3e9013aca1ca2d63e1b17e6ec1d79c4fd29eef1576f7112cfa9f`.

This completes another interface module, not the integrated F1 finger.
Seven digital prototype packages remain available; the other four unfinished
sensing designs and the common measured comparison remain in scope.

The earlier F1 mechanical checkpoint is retained at `engineering/development/f1/mechanics/`:
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
