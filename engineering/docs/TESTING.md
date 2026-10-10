# Bench and task validation

The requested range is **20 N per finger**. These are proposed acceptance targets, not measured product specifications. Start at 0.2 N, check the low-load range first, and stop on visible damage, bottoming, or deformation that does not recover. This range is not a claim about the YAM actuator's rated force.

## Stage 1: dimensional and electrical fit

Use an unmodified control finger and an identified R1 specimen. Record nail thickness at three points, opening loss, cover edge position, saddle fit, cable clearance, and passive bend behavior. Test a 10 kΩ reference resistor on all six inputs, then verify actual touch and release on every zone.

Map misses explicitly: both nail leading edges, the notch, cover borders, gaps between pads, rigid side rails, and back contacts. A single-zone force fit cannot establish full-finger coverage.

## Stage 2: static normal force

Clamp only the rigid mounting region in a bench fixture. Use a 2 mm rounded probe for the initial low-force contact map. For higher loads, use a recorded representative contact fixture and first check the unmodified finger in the same setup. A 20 N broad grasp and a 20 N point load on an unsupported nail tine are different mechanical cases; document which is tested. For a scale-based reference, orient the force axis vertically and exclude fixture friction or side support from the load path.

The low-load bring-up sequence is 0, 0.2, 0.5, 1, 2, 5, 2, 1, 0.5, 0.2, 0 N. The full-range sequence adds 10, 15, 20, 15, and 10 N around the peak. Collect three complete cycles per channel and fixture. The first two are training; the third is held out. The recorder saves actual reference readings and rejects windows with faults, too few samples, or excessive change between reference readings.

A full-range report must actually reach at least 20 N in both the training and held-out data. Selecting the 20 N plan while only applying lower forces does not qualify that range.

Proposed static criteria: for the 5 N bring-up, held-out RMSE ≤0.25 N; for the full 20 N range, RMSE ≤0.5 N. Maximum absolute error must be ≤max(0.5 N, 10% of the actual force), with no held-out readings outside calibration range. Keep the separate 0.2 N contact-detection criterion. Report each channel and loading direction separately. Missing or rejected trials must be repeated; they are not removed until a passing subset remains.

The analyzer groups repeated training loads and allows a small signal guard band derived from training noise and ADC quantization, capped at 5% of the training signal span. This avoids rejecting tiny endpoint noise solely because it falls just beyond the outermost training knot. Guard-band cases are counted; their force estimates extend the endpoint slope and are not clamped to 20 N. Larger excursions remain out of range. The guard is an engineering rule to test, not a formal uncertainty interval.

Repeat center and edge loads with 6 mm rounded and flat probes after the initial fit. Keep these measurements out of training. Large errors indicate contact-area or position dependence.

## Stage 3: reliability

| Test | Measurement | Proposed decision target |
|---|---|---|
| Light contact | 20 independent 0.2 N touches per critical region, plus unloaded intervals | Detect at least 19/20; report false positives separately |
| Sustained grasp | Hold 2 N and 20 N in separate tests for 60 s, release for 60 s | Drift ≤0.25 N at 2 N and ≤1 N at 20 N; recovery within 0.1 N |
| Repeated loading | 1,000 cycles initially through the qualified task load, inspect every 100 | No short, torn cover, detached lead, or missed contact |
| Extended wear | 10,000 cycles after pilot passes | Repeat force and light-contact criteria |
| Replacement | Remove/reinstall skin five times | Measure change; require calibration if criteria no longer hold |
| Across units | Three independently built specimens | Each passes; report spread and build failures |
| Temperature | Record at least two realistic bench temperatures after equilibration | Report bias; qualify only tested range |
| Timing | Raw sequence, acquisition offsets, scan and receive times | Report achieved rate, scan span, and dropouts; no unsupported 50 Hz claim |

Static start/end reference readings do not establish dynamic accuracy. Use synchronized reference data for response-time and slip-force claims. Do not estimate latency by comparing unsynchronized clocks.

For magnetic candidates, add motor-off/motor-on, nearby steel-tool, neighboring-finger, and gripper-opening sweeps without surface contact. The desired contact signal must remain distinguishable from these disturbances. For optical candidates, inspect image visibility at the full tested bend range and after gel replacement.

## Stage 4: preserve dexterity

After the bench gates pass, compare the instrumented and original fingers on thin-card pickup, coin pickup, a small connector/peg task, and a fragile-object hold. Use the same fixtures, trajectories, object positions, and force limits. Begin with passive/manual fixture trials, then use the lab's established robot procedure.

Run at least 20 trials per condition, alternate the order, and record success, slips, object damage, completion time, and missed contacts. Preserve failed attempts. A sensing improvement does not justify a material loss in thin-tip access.

## Evidence needed to select a design

Publish the specimen manifest, raw data, calibration splits, actual task outcomes, photographs, and failure observations. Report fabrication yield, assembly time, replacement time, and consumable usage. A scale-up claim requires multiple specimens and builds; a smooth plot from one sensor is not enough.
