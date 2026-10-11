# Test C1 with an independent reference

C1 has no measured force calibration yet. Use this procedure to create a
specimen-specific static model and held-out evidence through the 20 N target.
Keep failures and incomplete attempts.

Use [the specimen record](../templates/c1_specimen.json), [trial manifest template](../templates/c1_force_trials.json), and [the common campaign requirements](../campaign/requirements.json).

## Before applying larger loads

1. Complete the fit, metal-part, wiring, power, clock and electrical checks in [BUILD_C1.md](BUILD_C1.md).
2. Verify that the finger loads only the floating carrier and beam. Check all clearances with the actual fasteners, coating and cable routing.
3. Use an independent force reference with at least 25 N capacity and documented uncertainty no worse than 0.05 N. The L1 design is not automatically an independent reference.
4. Progress through low loads and zero-return checks before the 10, 15 and 20 N stages. Stop a run if there is slip, permanent movement, damage, unexpected contact across the load path or a readout fault.
5. Record actual force and displacement. The CAD and ideal bonded-joint calculations are not a physical load rating.

## Calibrate with independently varied levers

First use the metal calibration arm. Its ports vary both the longitudinal and
transverse load position. Changing only force at one fixed location cannot
reliably identify two station gains.

For the initial training set, use **0, 0.2, 0.5, 1, 2, 5, 10, 15 and 20 N**,
with both left and right transverse ports and more than one longitudinal
position. Include loading and unloading and at least three independent
presentations at **every force level**. The initial training plan therefore has
at least 27 independent holds, with lever positions varied across the plan.

Hold the load stationary, record the reference immediately before and after
each approximately three-second C1 capture, and keep the original recordings.
The static tool requires at least 200 healthy frames per hold. These frames
form one hold, not 200 independent tests.

After calibration, collect new test runs at the unused intermediate lever
positions and with the real finger's nail and TPU contacts. Keep complete
sessions, contact positions and specimens out of training when testing
generalization.

## Create the trial manifests

Copy the template into the specimen directory. Fill the reference instrument,
uncertainty, specimen and geometry hash from the actual setup and recording
receipts. Set `evidence_kind` to `physical` only for actual tactile specimens
and reference-force measurements. Dummy-resistor recordings are rejected.

Each row identifies a recording, its SHA-256, the condition used in
`c1_record.py`, and the before/after reference readings. Relative recording
paths stay below that manifest's directory. Do not repeat a recording to
increase the trial count.

Create separate `train.json` and `test.json` files. The test manifest must
declare `required_condition_ids`; each declared condition needs low-force
coverage and measurements reaching the 20 N target. Each test condition needs
at least three independent holds at every listed force level. The tool rejects
a reduced force range or fewer repetitions as an incomplete static pilot.

```sh
/usr/bin/python3 engineering/software/c1_force.py fit \
  --trials results/C1-01/train.json \
  --output results/C1-01/force-model.json

/usr/bin/python3 engineering/software/c1_force.py evaluate \
  --trials results/C1-01/test.json \
  --model results/C1-01/force-model.json \
  --output results/C1-01/static-validation.json
```

The fitter rejects rank-deficient or badly conditioned data, mixed geometry,
invalid sensor frames, unstable reference holds and missing identities.
Evaluation uses the frozen coefficients and rejects re-use of training
recordings. Unavailable holds remain visible and prevent a pass.

Open `static-validation.json` in the main website's measured-report inspector
to plot reference force against predicted hold means. The preview preserves
unavailable holds and does not change the published specimen count.

## What the static result establishes

The report gives force errors for means of the declared stationary holds,
including reference uncertainty and drift between the two reference readings.
The initial screen requires RMSE at most 0.5 N and the individual error rule
`max(0.5 N, 10% of reference force)`.

That report does not establish the following:

- Dynamic force accuracy or latency. These need synchronized reference-force time series.
- Contact confidence at 0.2 N. Use independent contact/no-contact presentations and the campaign's statistical plan.
- Performance on a moving arm. Test unloaded poses and motions; account for gravity, inertia and cable loads explicitly.
- Durability, manufacturing yield or calibration transfer. Build and test independent specimens and preserve lot/process information.

For a deliberate transfer experiment, use a new specimen's recordings and set
`transfer_experiment` to `true` in the test manifest. The report keeps the
training and test specimen identities separate. A normal same-specimen
calibration must not silently become a cross-unit claim.

Compare C1 with R1/L1/B1/B2 and the other approaches under the same physical
conditions. Selection remains open until the measured evidence supports it.
