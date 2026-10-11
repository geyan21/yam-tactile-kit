# Sensor and mechanical comparison

[Open the design directory for a separate page on every design and alternative](https://geyan21.github.io/yam-tactile-kit/designs.html). Each page states the exact sensor choice, placement, available files and build status.

The decision is driven by reliable contact and grip-force feedback through
20 N per finger with a thin, precise leading tip. Nine digital prototype
packages are available. F1, pneumatic and optical integration remain in
development. **Physical specimens tested: 0; no measured winner.**

The root-sensing designs preserve the bare contact surfaces and measure an
aggregate load. The local-cell designs also provide location information,
with additional material on or inside the finger. Those are design differences;
their practical value must be measured on the same precision tasks.

**Read [the architecture and scalability study](ARCHITECTURE.md)** for the assessment of magnetic sensing, the earlier B2/C1 concepts, quantitative limitations, and the batch-cost/validation plan. Use the separate B2 and C1 build pages for their current parts. The review below preserves the modality-specific context.

| Candidate | Useful signal | Fit to this finger | Main experiment | Current state |
|---|---|---|---|---|
| R1 independent resistive cells | Local contact and calibrated local force proxies | Two custom nail cells; four conformal saddle cells | Drift, edge coverage, hysteresis, cover and cable wear | Tooling and readout supplied; unbuilt |
| L1 root normal-force cell | Aggregate normal load including hard-frame contacts | Leaves contact surfaces intact; adds 20 mm reach and a larger root | Off-axis load, moments, stiffness, housing fit, cable route | Aluminum carriers, purchased-cell readout and test fixtures supplied; unbuilt |
| B1 magnetic insert | Local deformation/field observations; optional nail pressure pads | Original contact envelope, added side spine | Magnetic interference, calibration transfer, TPU mechanics and retention | CAD, PCB and raw readout supplied; unbuilt |
| B2 consolidated magnetic PCB | Magnetic observations and nail conductance; force calibration pending | One rigid board at the same head poses, with two locating spacers and a backer | Compare assembly, consistency and whole-board repair against B1 | B2.1 checked PCB, CAD and readout package; physically untested |
| C1 differential strain | Aggregate normal force from two calibrated strain bridges | Transverse metal root adapter; bare nail retained, larger root | Real clamp motion, gauge placement, thermal drift, cross-axis and lever response | C1.1 checked CAD/PCB and acquisition; numerical screen passed, physical tests pending |
| N1 bare sensing nail | Calibrated nail normal force and four local TPU force proxies | Steel fork with two shear webs, revised frame and side carriers | Whole-finger motion, frame-contact bypass, force calibration, mixed contacts and wear | Four checked CAD parts, selected gauges and combined readout; physical tests pending |
| B3 recessed magnetic | Magnetic deformation observations and separate nail signals | Recesses the B2 electronics into a revised frame | Frame stiffness, real magnetic headroom, bending, contact and paired B2/B3 performance | B3.1 build package and field/clearance screens; unbuilt |
| F1 flexible matrix | 64 proposed contact locations from routed row/column electrodes | Twelve shaped foils, fixed fanout and wrist electronics | Mating/lamination, resistance budget, full-array crosstalk, slack, wear and force calibration | Checked modules; complete integrated build remains |
| K1 capacitive | Six local capacitance signals for physical contact/force calibration | Two nail cells and four curved cells; nominal 0.836 mm nail addition | Stop height, low-force signal, finite plate loading, cable/bending artifacts and wear | K1.2 bench build package; model findings retained; unbuilt |
| Pneumatic | Pressure response to compliant chamber deformation | Needs ENPIRE chambers, tube paths and nail coverage | Leakage, temperature, pressure/force range, hysteresis and loading rate | Published references; ENPIRE integration remains |
| Optical | Dense surface deformation or texture images | Needs a camera, illumination and clear optical path within a redesigned finger | Occlusion, depth/force calibration, timing, gel wear and nail coverage | Published references; ENPIRE integration remains |
| FB1 packaged force button | Aggregate normal-force signal through a guided root adapter | Bare original nail/TPU; 50 mm added reach | Preload, stop gaps, real-joint motion, calibrated accuracy and contact reliability | FB1.1 CAD/PCB, code and structural screen; unbuilt |

K1 illustrates why a passed design check is only one filter. Its complete-foil/
cable planning case fits the converter's shield limit, and its nominal
geometry checks pass. Its separate material sweep still exposes early
bottoming with thick stop adhesive and low 0.2 N signals with high assumed
post stiffness. Those findings remain visible in the
[K1 test guide](CAPACITIVE_TESTING.md).

The [common build campaign](BUILD_ALL.md) records missing physical evidence
instead of assigning an invented score. A design earns a recommendation only
after contact reliability, force, access and task criteria are met; assembly
effort, repeatability, wear, replacement and cost then distinguish the survivors.

## Resistive: manufacturability versus force stability

[FlexiTac's primary hardware repository](https://github.com/FlexiTac/FlexiTac_Hardware_Repo) supplies a multiplexed readout and points to a separate fabrication tutorial. Its fast example streams 16 × 32 eight-bit values. A stock rectangle does not follow this nail's narrow fork. The hardware repository states CC BY-NC 4.0; do not infer commercial hardware permission from another package's software license.

[HiPi](https://arxiv.org/abs/2606.11372) is relevant to reducing readout crosstalk. Availability of production fabrication files must be verified before treating it as a ready-to-order module. R1 deliberately uses independent film islands and dividers to separate material behavior from matrix electronics.

R1's disadvantages are not hidden by a smooth calibration curve: contact-area dependence, creep, hysteresis, temperature sensitivity, conductor fatigue, and cover delamination all need testing. If these defeat the force requirement, it can still be evaluated as a contact-location layer.

## Magnetic: preserve compliance, measure interference

[AnySkin](https://any-skin.github.io/) uses a replaceable magnetic skin with a multi-magnetometer board. Its documented skin fabrication includes magnetic powder and a magnetization process. A premade skin is a sensible benchmark when that process is not available.

[ReSkin's fabrication files](https://github.com/raunaqbhirangi/reskin_sensor/tree/b82de2a9e9300af3062b3d635a85a2365af14a98/circuits) specify a 20 × 29 mm board. Its BOM and placement comments are not fully consistent about magnetometer variants and resistor values. Confirm the assembled board revision and I²C address map; do not submit a blind assembly order from mismatched files.

[eFlesh](https://arxiv.org/html/2506.09994v1) combines printed TPU structures, magnet pockets, and this family of magnetometer boards. Its repository identifies TPU 95A and 4.7625 mm diameter × 1.5875 mm thick N52 magnets for fingertip examples. This avoids fabricating a powder-loaded magnetic silicone.

The eFlesh paper's main normal-force characterization uses a 40 × 40 mm instance and reports 0.27 N RMSE over its experiment. That result does not transfer to a narrow ENPIRE insert. Its convex CAD-to-lattice input also cannot be applied unquestioningly to the current concave, hollow TPU skeleton.

## Optical: a relevant redesign path

[GelSight Baby Fin Ray](https://arxiv.org/html/2303.14883v1) is directly relevant to compliant fingers. It moves rigid electronics toward the base and uses flexible optical elements. Its hardware description includes an 18 mm-wide gel section, modified TPU struts, and dedicated optical casting and painting. It is a substantial finger redesign, not a film to paste onto the current insert.

[Simulation-guided compliant tactile design](https://arxiv.org/abs/2403.04638) offers a process for exploring compliance and optical visibility together. For this project, the hard leading nail must still be sensed or its blind region explicitly accepted.

## Selection rule

Build the thin R1 nail experiment and [L1's independent force fixture](L1_TESTING.md) first. Keep all off-center L1 loads out of training; its cell's scalar capacity does not establish the required moment behavior. Fit the L1 carrier to the actual housing before machining it. A successful cell test still needs the separate integrated-finger validation.

Use B1 as the magnetic pilot and compare the supplied B2 package under the same motor/jaw/steel conditions. Compare C1's whole-finger force path with N1's separate sensing nail and local TPU cells. The remaining approaches need their own material, integration and readout development. The active campaign covers all twelve designs; choose from physical contact coverage, held-out force error, tip access, replacement and wear results across multiple builds.

Apply the same [contact criteria](CONTACT.md) to the two supplied readouts. Report both observed event rates and their uncertainty, and retain failures in leading-edge and gap cases. The supplied contact parser supports R1 and L1; magnetic, matrix and optical readouts need their own verified data adapters before they can enter this executable comparison.
