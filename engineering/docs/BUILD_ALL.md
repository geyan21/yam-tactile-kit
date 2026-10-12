# Build all twelve designs and find which work

The goal is a measured comparison of all twelve designs for reliable contact
and grip-force feedback through **20 N per finger**, while retaining thin-tip
access for precision manipulation.

**Current evidence:** eleven digital prototype packages are available. Physical
specimens tested: **0**. No measured winner has been selected. The remaining
optical design still needs the development listed below.

## Status of every design

| Design | What can be built from current files | Work before its physical comparison |
|---|---|---|
| [R1](https://geyan21.github.io/yam-tactile-kit/r1.html) | Six local resistive cells, shaped tooling and readout | Assemble, calibrate and measure drift, edge coverage and wear |
| [L1](https://geyan21.github.io/yam-tactile-kit/l1.html) | Purchased-cell bench fixture and full-finger carriers | Confirm drive fit and cell moment response before installed tests |
| [B1](https://geyan21.github.io/yam-tactile-kit/b1.html) | Magnetic insert, five heads, side support and raw readout | Assemble, check interference, calibrate force and compare compliance |
| [B2](https://geyan21.github.io/yam-tactile-kit/b2.html) | One routed magnetic PCB, locating spacers, backer and firmware | Fit witnesses, first-board electrical checks, then matched B1/B2 tests |
| [C1](https://geyan21.github.io/yam-tactile-kit/c1.html) | Metal root beam and carriers, eight selected gauges, checked dual-bridge PCB, firmware and static calibration tools | Verify drive fit, machine and bond specimens, measure real joint motion and force response |
| [N1 rigid nail](https://geyan21.github.io/yam-tactile-kit/rigid-nail.html) | Steel sensing fork, carriers, revised frame, two shear bridges, four TPU cells and combined readout software | Fit and assemble; verify whole-finger motion, physical force calibration, mixed contacts, wear and task access |
| [B3 recessed magnetic](https://geyan21.github.io/yam-tactile-kit/recessed-magnetic.html) | Revised frame, tapered spacers, retained B2 board, gain-5 firmware and sampled field/clearance checks | Print and fit; measure frame stiffness, actual motion/headroom, then paired B2/B3 force/contact and task performance |
| [F1 flexible matrix](https://geyan21.github.io/yam-tactile-kit/flexible-matrix.html) | F1.1 R4: twelve checked flexes, 96 CAD parts/references, retained covers/molds, fanout/wrist electronics, manufacturing and static-force tools; 5,638 assembly comparisons pass | Fabricate and accept real terminals/cable, bonds, seals and slack; measure full-array behavior, contact and held-out 20 N force |
| [K1 capacitive](https://geyan21.github.io/yam-tactile-kit/capacitive.html) | Seven checked flex designs, six retained cells, protected references, cover molds, stops, terminal tools, bank cases and raw/static-force software | Fabricate and measure posts, bonds and gaps; verify installed bracket and moving harness; test early bottoming, low-force signal, contact reliability and precision |
| [P1 pneumatic](https://geyan21.github.io/yam-tactile-kit/pneumatic.html) | Eight channels, 112 CAD parts/references, four remote ELVR transducers, checked readout, two N0 nail cells, hose map, firmware and static-force tools | Fabricate and inspect seals/ports; test bending, hose/temperature effects, common-pressure cancellation, contact and held-out force through 20 N |
| [Optical](https://geyan21.github.io/yam-tactile-kit/optical.html) | Published optical approaches | Design the optical path, camera, surface, image processing and nail coverage |
| [FB1 force button](https://geyan21.github.io/yam-tactile-kit/force-button.html) | Guided root adapter, selected Honeywell FMA, checked sensor PCB, firmware, calibration tools and structural screen | Machine and assemble; measure preload, stop gaps, actual drive fit, contact reliability and held-out finger-force accuracy |

Each design keeps its separate page. New packages are added there with their
actual CAD, circuit and software checks. A coupon remains a development step
until its installed finger has been designed and evaluated.

## Common build and test procedure

1. **Identify and record the build.** Preserve material lots, printed profiles, PCB revision, component ordering codes, photos and specimen IDs. Record assembly, rework and calibration time. Begin with fit witnesses where the real drive housing is still unconfirmed.
2. **Check raw operation and faults.** Test missing sensors, disconnected leads, saturation, stale samples and configuration errors. Preserve raw data and unavailable readings. An unavailable reading cannot count as a correct contact or force prediction.
3. **Measure contact and force.** Use the same independent force reference, contact sites, loading directions and probe shapes for every design. Test both nail prongs, leading edges/notch and distal, middle and proximal soft regions. Progress from low loads to 10, 15 and 20 N using the documented fixture checks.
4. **Freeze calibration before evaluation.** Keep whole specimens and sessions out of training. Use an explicit unloaded reference. Record loaded grasps without silently taring away their force.
5. **Test the intended environment.** Include jaw opening, motor operation, no-contact motion, gravity poses, nearby steel, cable movement, temperature, loading/unloading, holds and replacement.
6. **Measure precision and durability.** Record tip movement, recovery, repeated loading, surface wear and representative manipulation tasks with a fixed task protocol.
7. **Repeat independent builds.** The initial repeatability pilot calls for three specimens per design. Keep failed builds and repair time in the comparison.

R1/L1 already have their dedicated force/contact workflows. B1/B2 have raw
magnetic acquisition and bench conditions; force/contact models for those
designs still require measured training and held-out validation data.
C1, N1, FB1, K1, F1 and P1 have separate stationary-hold fitters and evaluators; dynamic force and
contact reliability still need their own measured evidence.

## Proposed comparison targets

The user requested 20 N per finger and thin-tip precision access. The other
numbers below are engineering test targets, to be checked against actual tasks.

| Criterion | Initial target or reporting rule |
|---|---|
| Normal-force range | 0.2–20 N per finger |
| Held-out force RMSE | At most 0.5 N |
| Individual force error | At most max(0.5 N, 10% of reference force) |
| Contact at 0.2 N | Miss probability at most 1% under each declared condition |
| No-contact trials | False-contact probability at most 1% |
| Confidence | One-sided 95% bound for each separately declared condition |
| Confirmation trials | 300 independent presentations per label and region; adjacent frames are not independent trials |
| Added tip movement | Provisional 0.1 mm screen at 20 N, separately from the original finger's motion |
| Build practicality | Measured assembly, rework, calibration and replacement time; actual quotes and failed-unit counts |

Zero errors in a small pilot do not establish the 1% probability target.
Confidence statements must name their conditions and scope. Per-condition
bounds do not provide a simultaneous guarantee across the whole task set.

## How a design earns a recommendation

First identify which designs satisfy the required contact, force, access and
task tests. Then compare the successful designs on assembly effort, calibration,
repeatability, durability, repair and total cost.

Keep a visible **missing evidence** state for every unmeasured criterion.
An attractive CAD model, an IC range or a published paper result cannot fill a
physical-results cell. Failed tests should lead to an explained rejection or a
new revision and another test.

The common machine-readable plan is [campaign_requirements.json](../campaign/requirements.json).
The working source ledger is `engineering/campaign/WORK.md`. Student data
belongs in new specimen-specific recording directories, preserving prior runs.
