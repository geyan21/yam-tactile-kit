# F1 stationary-force and contact experiments

**No F1 calibration or measured performance is supplied.** The firmware
records raw 64-location matrix observations. The new force tool fits six
experimental site curves from physical stationary holds and tests them in
a different session. It does not calibrate a 64-taxel pressure map.

## Before tactile calibration

Use `F1_MANUFACTURING.md` and `F1_WRIST_CAPTURE.md` to check construction,
wiring, continuity, supplies and the actual film/connector stack. Keep the
finger stationary until physical tail slack and retention have been checked.

Start with gain 0 at all positions. Record known resistor/load-box tests
using `--source-kind electrical_dummy`. Inspect baseline and active phases,
column tests, settling, noise and headroom. Then use incremental physical
loads to choose one fixed gain per position over its complete required
range. Repeat after changing the settling time or gain map. Keep the final
configuration fixed for both training and evaluation.

The firmware does not implement automatic ranging. A high gain that resolves
light touch may saturate at higher force; a low gain may miss small contacts.
The experiment must expose that tradeoff. Nominal electrical simulations
cannot choose a validated force range without the actual film.

## Recording one hold

Use a calibrated reference that measures force along **one declared axis in
the source finger's native frame**. Keep that axis unchanged through all
single-site and mixed-site tests. Local normal magnitudes from different
curved surfaces cannot simply be added and called grip-axis force.

```sh
/usr/bin/python3 engineering/software/f1_record.py \
  --port ACTUAL_SENSOR_PORT \
  --specimen ACTUAL_SPECIMEN_ID \
  --session-id ACTUAL_SESSION_ID \
  --condition ACTUAL_CONTACT_CONDITION \
  --geometry ACTUAL_ASSEMBLY_MANIFEST.json \
  --seconds 30 \
  --output results/f1/session/NEW_HOLD.jsonl
```

Use a separate file for each independent hold and retain its
`.receipt.json`. The recorder does not command a robot. Record the reference
before and after the declared stationary window. A useful starting window
is 5–25 seconds in a 30-second recording.

Copy `engineering/templates/f1_force_trials.json` beside the recordings.
Replace its placeholders with actual specimen, session, geometry, reference
and file hashes. Reference uncertainty must be documented and no worse than
0.05 N for this screen. Do not replace missing measurements with planned loads.
The recorder's version-2 header supplies session identity and relative host
time; older records remain historical and are not silently converted.

## Train, then evaluate

For training, load each of CH0–CH5 separately at **0, 0.2, 0.5, 1, 2, 5, 10,
15 and at least 20 N**, with at least three independent holds at every level.
Release and reposition between holds. Record the indenter, actual contact
position and loading direction. If a component fails or the required range
cannot be reached, retain the failed attempt; that design has not passed.

```sh
/usr/bin/python3 engineering/software/f1_force.py fit \
  --trials results/f1/train/trials.json \
  --output results/f1/train/model.json
```

The tool independently decodes every raw frame; it does not trust the saved
validator's verdict. It requires all 64 pixels and sixteen electrical column
checks, rejects saturated/faulty frames, changed configurations and incomplete
receipts, and keeps missing holds unavailable. Each accepted window needs
at least ten complete frames and ten seconds of stationary observations.
Frame timing remains in the report; passing a stationary test says nothing
about rapid contact detection.

For evaluation, make a **new session with new recording files**. Use new
contact positions and shapes within the regions below. Require single-site
coverage for all six sites, the two nail edges/notch neighborhood, all TPU
regions, both nails together, two TPU regions together, and a nail/TPU mixture.
Each required condition needs the same full force-level/repetition plan.
For mixed contact, the reference measures the total force along the common
axis; it is not the sum of independently assumed local loads.

```sh
/usr/bin/python3 engineering/software/f1_force.py evaluate \
  --trials results/f1/test/trials.json \
  --model results/f1/train/model.json \
  --output results/f1/test/validation.json
```

The provisional static screen requires held-out RMSE ≤0.5 N, each hold's
absolute error plus its reference bound ≤max(0.5 N, 10% of reference force),
inactive-site estimated force within ±0.2 N, and no site estimate below
−0.2 N. Every required hold must be available. The 20 N endpoint is literal:
19.8 N does not qualify it. Estimates are not clipped to 0 or 20 N.

The six curves use sums of baseline-minus-active signals divided by nominal
feedback resistance. These are sequential apparent-current proxies. They
do not prove independent pixel currents, eliminate lateral film conduction,
or make the measured response independent of contact shape.

## Decide whether F1 is useful

Preserve the 64-location raw map during localized contact tests. Test central
contacts, edges, simultaneous contacts and neighboring unloaded locations.
Measure false contacts during no-contact TPU bending and changes caused by
tail movement. A broad false map or a force curve that changes strongly with
contact shape is a real failure for this application.

Then run the common campaign's low-force contact, timing, drift, hysteresis,
repeated bending, wear and precision-object tasks. Include the original thin
finger as the access/precision baseline. Compare assembly time, replacement
effort and build yield as well as electrical error.

The existing common R1/L1 contact parser does not accept F1 raw frames.
Do not feed it converted dummy records. F1 dynamic contact qualification
still needs the actual time-aligned reference observations and a reviewed
detector; the static tool deliberately leaves contact and robot qualification
false. Use the raw records and common experimental conditions to collect
that evidence before declaring a winner.
