# Sensor and mechanical comparison

[Open the design directory for a separate page on every design and alternative](https://geyan21.github.io/yam-tactile-kit/designs.html). Each page states the exact sensor choice, placement, available files and build status.

The decision is driven by reliable contact and grip-force feedback with a thin, precise leading tip. R1, L1 and B1 have separate digital build packages; none has been selected as a physically validated winner.

**Read [the newer architecture and scalability study](ARCHITECTURE.md)** for the assessment of magnetic sensing, the consolidated B2 board concept, the C1 strain-force coupon, quantitative limitations, and the batch-cost/validation plan. The review below preserves the modality-specific context.

| Candidate | Useful signal | Fit to this finger | Main experiment | Current state |
|---|---|---|---|---|
| R1 independent resistive cells | Local contact and calibrated local normal-force proxy | Two custom nail cells; four conformal saddle cells | Drift, edge coverage, hysteresis, cover and cable wear | Tooling and readout supplied; unbuilt |
| FlexiTac / HiPi-style matrix | Denser pressure distribution | Requires custom fork-shaped flex layout and curved pad treatment | Crosstalk, bending life, sealing, channel rate | Research comparison; no released routed ENPIRE FPC |
| AnySkin / ReSkin magnetic skin | Magnetic changes from skin deformation | Stock board is wider than the 15 mm insert; requires another mount | Field interference, replacement variation, force calibration | Primary PCB and firmware audited |
| eFlesh-style printed magnetic structure | Deformation coupled to permanent magnets | Promising for an internal or redesigned compliant section; hard nail remains separate | TPU creep, magnet retention, field bias, contact coverage | Primary process and dimensions reviewed |
| Baby Fin Ray optical | Dense contact shape and texture | Requires hollow optical path, illumination, and a changed compliant structure | Occlusion under bend, gel wear, camera timing, nail coverage | Primary fabrication method reviewed |
| L1 root normal-force cell | Aggregate normal load including hard-frame contacts | Leaves contact surfaces intact; adds 20 mm reach and a larger root | Off-axis load, moments, stiffness, housing fit, cable route | Aluminum carriers, purchased-cell readout and test fixtures supplied; unbuilt |
| B1 magnetic insert | Local deformation/field observations; optional nail pressure pads | Original contact envelope, added side spine | Magnetic interference, calibration transfer, TPU mechanics and retention | CAD, PCB and raw readout supplied; unbuilt |
| B2 consolidated magnetic PCB | Same intended measurements as B1 | One rigid board at the same head poses | Fewer manual connections without sacrificing registration or serviceability | Outline and allocation study; no routed PCB |
| C1 differential strain | Aggregate normal force inferred from two calibrated bending measurements | Requires a new controlled root load path | Gain matching, drift, stiffness, cross-axis response | Analytical screen and metal bench coupon; no adapter |

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

Use B1 as the current magnetic pilot and test the actual motor/jaw/steel conditions. Finish the B2 packaging design if that modality passes; evaluate the C1 coupon if aggregate force stability is the main problem. Advance a dense matrix only after the laminate and sealing process survive the material tests. Advance optical sensing when dense contact geometry justifies the redesign. Choose from physical contact coverage, held-out force error, tip access, replacement and wear results across multiple builds.

Apply the same [contact criteria](CONTACT.md) to the two supplied readouts. Report both observed event rates and their uncertainty, and retain failures in leading-edge and gap cases. The supplied contact parser supports R1 and L1; magnetic, matrix and optical readouts need their own verified data adapters before they can enter this executable comparison.
