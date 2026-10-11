# Test N1 with the same physical targets

N1 has no measured force calibration yet. Build the complete sensing assembly,
retain an original control, and use the [common campaign](BUILD_ALL.md) to
compare contact, force, precision, effort and wear through 20 N per finger.

Use [the specimen record](../templates/nail_specimen.json) and
[trial-manifest template](../templates/nail_force_trials.json). Keep original
raw files, recording receipts, failed trials and photographs.

## Before the force pilot

1. Complete [BUILD_NAIL.md](BUILD_NAIL.md), including fit, real fastener engagement, gauge wiring, TPU cells and electrical checks.
2. Verify both bridge currents and shunt responses, both grounded pressure inputs, both reference dividers and all four cell responses. Test disconnected leads, shorts, stale conversions and wrong settings.
3. Use an independent reference with at least 25 N capacity and documented uncertainty no worse than 0.05 N.
4. Begin at low loads and inspect return position and clearance. Progress through 5, 10, 15 and 20 N only while the assembly remains stable.
5. Measure the complete finger's tip movement and compare it with the original control. The metal-only finite-element result excludes real joints and printed-frame compliance.

## Train one region at a time

The supplied static baseline has a two-bridge linear model for the nail and
four individual monotonic curves for CH2–CH5. It adds their predicted normal
forces. This is a testable baseline; mechanical crosstalk, creep or inactive
channel bias can make it fail.

Use **0, 0.2, 0.5, 1, 2, 5, 10, 15 and 20 N**, with at least three independent
holds at every level for each of the five training groups:

- `nail`: vary the loaded prong and lever position, including left and right contacts.
- `CH2`, `CH3`, `CH4`, `CH5`: load the named TPU region while the other surfaces remain clear.

The minimum training set has 135 independent holds. Vary nail lever positions
so the two bridge features are identifiable. A single fixed lever gives a
rank-deficient or poorly conditioned calibration.

Align reference loads with **+native Z**, the same declared jaw-force axis as
the other root-force experiments. Record actual probe geometry and position.
Hold the load steady and note the reference immediately before and after each
approximately three-second capture.

The analyzer requires at least 200 healthy nail frames and 50 distinct pressure
samples per cell in each hold. Cached pressure values are counted once using
their conversion-start identities. Data acquired before the recording window
are excluded. Many frames from one hold remain **one independent hold**.

## Freeze the model and collect new validation runs

Create separate `train.json` and `test.json` manifests from the template. Set
`evidence_kind` to `physical` only for real tactile specimens and force-reference
measurements. Dummy recordings are rejected.

Each row names its recording, SHA-256, condition, active region or regions,
and the two observed reference readings. Keep the companion recording receipt.
Each independent hold needs a different recording.

```sh
/usr/bin/python3 engineering/software/nail_force.py fit \
  --trials results/N1-01/train.json \
  --output results/N1-01/force-model.json

/usr/bin/python3 engineering/software/nail_force.py evaluate \
  --trials results/N1-01/test.json \
  --model results/N1-01/force-model.json \
  --output results/N1-01/static-validation.json
```

The test manifest declares `required_condition_ids`. Every declared condition
needs all force levels and repetitions, with a consistent region combination.
Include complete single-region tests for the nail and all four TPU cells,
plus complete **mixed-contact** conditions. Test unused nail locations,
leading rims, TPU edges, pad gaps and wider objects that might touch a carrier.

The analyzer rejects reuse of training recordings, mixed geometry/resistor
settings and interrupted captures. Unavailable predictions remain in the
report and prevent a pass. Small negative zero errors are retained; values
outside the calibrated signal guard are unavailable.

For an explicit transfer experiment, set `transfer_experiment` to `true` in
the new specimen's test manifest. The training and test identities remain
separate. A same-unit calibration does not demonstrate interchangeability.

## Interpret the static result

The screen requires held-out RMSE at most **0.5 N**, plus the individual error
rule **max(0.5 N, 10% of reference force)** including the recorded reference
uncertainty and end-to-end hold drift.

It evaluates means of stationary holds. It does not establish dynamic force
accuracy, a 0.2 N contact-confidence bound, pose compensation, fatigue life or
robot-task success.

For contact qualification, use independent loaded and clear presentations
under the campaign's per-condition statistical plan. Include unloaded jaw
motion, changed gravity poses, cable motion, temperature and proximity cases.
The steel nail has weight and inertia; a fixed bench offset does not remove
those loads during arm motion.

Build at least three independently assembled specimens for the initial
repeatability pilot. Record machining, assembly, rework, calibration and
replacement time. Compare the complete N1 system with the other designs;
report missing evidence and failed conditions explicitly.
