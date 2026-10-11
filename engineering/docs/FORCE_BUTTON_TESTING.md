# FB1: measure whether the force button works

FB1 must pass the same **0.2–20 N finger-force** and thin-tip task tests as
the other designs. Its catalog force range, digital self-checks and CAD
clearances are not physical performance results. No measured FB1 winner
or calibration is included.

## Before the full-finger experiment

Use the [build guide](BUILD_FORCE_BUTTON.md), a rigid test stand and an
independent force reference with documented total uncertainty no worse than
0.05 N. A Mark-10 M5-5 is one reference-gauge example: the manufacturer's
sheet lists 25 N capacity, 0.005 N resolution and ±0.1% full-scale accuracy.
Its calibration certificate and the fixture/alignment uncertainty still
need review; display resolution alone is not measurement uncertainty.

Record the PCB revision, FMA ordering code/lot, metal and leaf material,
leaf thicknesses, fasteners, preload, stop gaps, raw zero, temperature and
assembly time. Keep a specimen ID and a new bench-session ID for every
independent session.

Before fitting the floating carriage, approach the FMA with a flat probe
through the fixed stop frame's center bore. Check its direct-load response
and return to zero. Keep the board/backing assembly unchanged when completing
the mechanism. This check helps set preload; it does not calibrate finger
force through the assembled guide and backing.

## Electrical and coupling faults

Record every fault condition, including:

- Missing FMA, missing ADC, stale status, diagnostic status and out-of-span counts.
- Each of the six cable wires disconnected separately.
- Cable movement, probe removal and service-loop repositioning.
- Plunger backed off from the sphere, then restored to the recorded preload.
- Clamp looseness or contact between the floating carrier and surrounding parts.
- A stop deliberately reached in a controlled low-force setup, then reset
  and checked before normal tests.

The live program reports raw availability, not mechanical correctness.
An open plunger or a parallel force path may leave perfectly plausible
I²C readings. Such events need independent physical checks.

The bare FMA's absolute overforce specification is not an operating range.
Do not use it as the assembled finger's strength rating. During staged tests,
stop for unexpected motion, rubbing, permanent zero shift, loss of preload,
early stop contact or unavailable readings.

## Static force calibration

Use the
[unmeasured trial template](../templates/force_button_force_trials.json).
Record independent stationary holds at **0, 0.2, 0.5, 1, 2, 5, 10, 15 and
20 N**, with at least three separate holds per level. Approach the high
levels only after the lower stages and the mechanism checks pass.
The high-level holds must have an actual reference mean of **at least 20 N**;
a nominal target label or the general force-level tolerance cannot qualify
a lower measured load.

Hold the force steady before recording. Capture 15 seconds and use the
declared 2–12 second interval as the initial stationary window. Record the
independent reference immediately before and after that window. Loading and
unloading are different conditions; do not silently combine them.

The manifest must identify actual physical evidence, specimen, bench
session, geometry/checkpoint hash, force-reference identity/uncertainty,
region and the hash of every raw recording. Keep recordings beneath the
manifest directory. Do not change `unmeasured_template` to `physical` until
the corresponding measurements actually exist.

```bash
/usr/bin/python3 engineering/software/force_button_force.py fit \
  --trials measurements/fb1-a/train.json \
  --output measurements/fb1-a/model.json
```

This fits a linear relation from raw FMA counts to external finger force.
It learns the installed zero and sensitivity rather than silently treating
the sensor's factory nominal newtons as finger newtons.

The fitter re-decodes raw packets, ignores cached predictions, rejects
incomplete or unavailable holds and counts independent holds rather than
adjacent frames. Retain failed attempts and their causes when revising a
trial plan.

## Held-out validation

Freeze the model, then collect new recordings in a **different bench
session**. The test plan must cover all six regions:

| Region | Required contact examples |
|---|---|
| Left nail | Small and broad contacts on the left prong |
| Right nail | Matching contacts on the right prong |
| Nail edges / notch | Leading edge and notch-adjacent contact with a documented probe |
| Distal TPU | Soft contact near the tip |
| Middle TPU | Mid-length contact |
| Proximal TPU | Soft contact near the root |

Use all nine force levels and three independent holds per level for every
declared condition. Add separate condition IDs for loading/unloading,
probe area and any environmental challenge. The initial six-condition
plan therefore needs at least 162 held-out holds per specimen. Frames
inside a hold are not independent repetitions.

```bash
/usr/bin/python3 engineering/software/force_button_force.py evaluate \
  --trials measurements/fb1-a/test.json \
  --model measurements/fb1-a/model.json \
  --output measurements/fb1-a/static-validation.json
```

The static screen requires complete planned coverage, no unavailable holds,
force RMSE at most 0.5 N and each error plus the declared reference bound at
most `max(0.5 N, 0.1 × reference force)`. It rejects reusing training
recordings or training-session identities. Cross-specimen transfer must be
declared explicitly.

A passing stationary-hold result does not establish dynamic accuracy,
contact reliability or moving-robot compensation.

## Contact, motion and durability

Use [the common contact protocol](CONTACT.md) and
[all-design campaign](BUILD_ALL.md). Freeze a contact rule using training
sessions; do not select its threshold on the test set. Count an unavailable
prediction as a failed presentation, and keep no-contact trials separate
from 0.2 N contacts.

The confirmation target is a one-sided 95% upper bound of at most 1% on
misses and false contacts under **each separately declared condition**.
The initial plan uses 300 independent presentations per label and region.
This does not give a simultaneous guarantee over every possible condition.

Measure added contact-point motion at 20 N relative to the unmodified
finger in the same fixture. The provisional screen is 0.1 mm of adapter
addition; the original TPU may intentionally bend much more. Check both
nail prongs and the soft regions, return to zero, all stop gaps and the
plunger alignment under load.

Then test no-contact jaw motion, motor operation, gravity poses, nearby
steel, temperature changes, long holds, repeated loading, wear and
replacement. Root sensors also respond to loads from finger inertia,
gravity and cable forces. This kit does not supply a qualified dynamic
compensation or gripper-control system.

## How to judge FB1

Its potential advantage is a purchased digital sensor with a thin original
contact tip and no magnets or bonded strain gauges. Its disadvantages are
the 50 mm root extension, the alignment/preload/stop setup and the fact that
its published factory error does not guarantee our low-force targets.

The FMA sheet lists a maximum total-error figure of ±8% of full scale under
its stated 5 V and 20–80% full-scale conditions. For 25 N, that figure
corresponds to ±2 N; it is not a verified 3.3 V or 0.2 N result. This makes
FB1 a **candidate to test**, not an established precision-force choice.
Compare it directly with L1 and C1 using the same reference, contact sites,
assembly-time accounting and held-out protocol.

The [Honeywell data sheet](https://prod-edam.honeywell.com/content/dam/honeywell-edam/sps/siot/fr-ca/products/sensors/force-sensors/microforce-fma-series/documents/hon-ia-hss-force-fma-series-datasheet-32347833-ciid-181799.pdf)
and [Mark-10 reference-gauge sheet](https://www.mark-10.com/downloads/product-downloads/DataSheetSeries5.pdf)
are the primary component references. Our assembled-finger results must
come from the experiment above.
