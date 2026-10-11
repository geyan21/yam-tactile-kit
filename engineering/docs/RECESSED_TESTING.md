# B3 physical tests and comparison

Build three independent B3 specimens and matched B2 controls before drawing
a repeatability conclusion. Keep an original unsensored finger as the
precision/stiffness control. Record print process, magnet lot, nail-pad
construction, assembly time, failed parts and rework.

No B3 specimen has been physically tested in this workspace. This plan
specifies work to do; the downloadable records contain no measured result.

## Fit, retention and low-force checks

1. Follow the measured seating and PCB checks in the build guide. Photograph both mounted spacer feet, board annuli, recess, solder joints and cable exits.
2. Identify the actual drive variant. With force removed, check both fingers through the entire jaw range and intended precision approaches. Observe the housing, other finger, nail pads, screws and cable loops.
3. Verify power, bus levels, five magnetic channels and both nail channels. Unplug one sensor branch, open each nail lead and use controlled electrical faults to verify that faults remain unavailable readings.
4. Measure unloaded field, noise and configuration stability with the motor off, motor active without contact, several gravity poses and the intended steel tools nearby. Keep each condition separate.
5. Apply low reference forces first. Measure TPU side movement, package clearance, board movement, spacer seating, source-frame bending and zero return. Stop the physical run if parts crack, shift, rub or fail to return; retain the failure record.

The **+2 mm native-X motion assumption is not allowable travel**. The
clearance calculation uses that hypothetical pointwise bound and a 0.05 mm
model allowance to obtain 1.95 mm separation from the checked electronic
supports. It excludes the source attachments, drive and cable loops. Measure
the real deformation and check the real geometry before proceeding upward.

## Force, contact and precision

Use an independent force reference with at least 25 N capacity and documented
uncertainty no greater than 0.05 N. Neither an uncalibrated B3 field nor an
unqualified L1 cell supplies the ground truth.

Progress through 0, 0.2, 0.5, 1, 2, 5, 10, 15 and 20 N only after the
preceding physical checks pass. Test the two nail prongs, nail edges/notch,
and distal, middle and proximal TPU. Include loading/unloading, different
probe areas, holds, mixed nail/TPU contact and full release.

Synchronize the force reference with each raw capture. Preserve the original
force timestamps and uncertainty, actual contact position/area, specimen ID,
temperature, jaw/motor condition and hardware configuration. Keep training
and validation sessions separate. A calibration from B1 or B2 cannot be
assigned to the recessed frame.

Measure leading-tip motion relative to the jaw and the matched original
finger at 20 N. The campaign's provisional limit is 0.1 mm **added motion**;
it is not a demonstrated B3 result. Measure frame motion and TPU deformation
separately where possible so the source of an error can be identified.

The common targets are held-out force RMSE ≤0.5 N and per-trial absolute error
≤max(0.5 N, 10% of reference force). For 0.2 N contact detection, test miss and
false-contact probability ≤1% with a one-sided 95% bound per declared
condition. The confirmation plan uses 300 independent presentations of each
label per region; adjacent sensor frames are not independent presentations.
Use [campaign requirements](../campaign/requirements.json) and the existing
[contact protocol](CONTACT.md).

## Decide whether the recess helps

| Question | Required evidence |
|---|---|
| Does it improve precision access? | Actual width/cable measurements and the same fixed task protocol for B2/B3 |
| Does the frame remain suitable? | Matched tip-motion, zero-return, load, fatigue and crack/retention records |
| Does the closer board improve the signal? | Noise, drift, field headroom and held-out force/contact results |
| Does it tolerate the real robot? | No-contact motion, gravity, motor, steel, cable and temperature trials |
| Can students reproduce it? | Independent assembly, rework, calibration, repair time and failed-build records |

B3's current digital benefit is the 2.439 mm inward board shift. The
remaining decision is whether that width reduction is worth a revised frame,
smaller spacer feet and a new calibration. Missing physical results cannot
be scored as successful tests.
