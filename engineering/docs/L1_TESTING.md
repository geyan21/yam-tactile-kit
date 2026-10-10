# L1: test the cell, then the complete finger

**A center-loaded calibration is not enough.** L1 places the finger beside the cell and extends its reach. The test must reveal errors from longitudinal and transverse lever arms, then check the assembled finger with an unchanged force sensitivity.

Use an independent reference with at least 25 N capacity and stated uncertainty ≤0.05 N over the tested range. Use a fixed stand and a translation stage or screw press. Align the applied reference force with W, the cell's measured axis. For integrated tests W is native +Z into the finger's contact side. Record force-axis alignment and probe geometry; a scalar gauge pointed along a different direction is not a normal-force reference.

![Cell plate and integrated finger contact locations](../release/l1/l1_test_map.svg)

## Prepare the fixture and specimen

Complete the [L1 specimen sheet](../templates/l1_specimen.json), [assembly](BUILD_L1.md) and [electrical checks](L1_ELECTRONICS.md). Record actual cell dimensions, hardware, material, assembly photographs, source hashes, reference calibration and pose.

Clamp only the two solid 13 mm ends of the cell. The bench fixed shoe leaves 3 mm clearance beneath its middle; the live spacer leaves 3 mm above it. Attach the combined load plate to the live end with its M5 screw. The center cap gives the probe a surface over the screw head. The plate's smaller holes locate the off-center load positions; they are not attachment points to the fixed stand.

Keep the cell's wire end fixed and the opposite end live in both fixtures. Orient the bench so the positive reference force follows the same W direction as the later finger test. For gravity loading, W must point down; include the fixture's own weight and the force-conversion method in the record.

Use a dial indicator to record unloaded and loaded movement of the carrier, cell and fingertip. Begin at 0.2, 0.5, 1, 2 and 5 N. Stop for a slipping seat, contact across a clearance, a loose bolt, visible damage or zero shift that does not recover after unloading. A low-load pass is not the requested 20 N qualification.

## Stage A: cell and moment plate

The supplied `l1_bench_plan.json` contains **147 trials**: three center loading/unloading cycles and staged displaced loads with a release after each. The first two center cycles train one force sensitivity; the third center cycle and every displaced position are held out.

The required plate ports enclose the modeled finger's projected lever envelope. At U = 70 mm, V = −45 mm, 20 N produces 1.66 N·m about the live-end screw axis. This is a proposed test condition. The cell supplier does not publish the moment capacity needed to certify it.

The optional ±130 mm bar creates 2.60 N·m at the cell and exceeds this required cell envelope. Use it only for a separate characterization study; it is not necessary to pass Stage A. The robot-mount moment and cell live-end moment have different origins.

```sh
build/l1-host/bin/python engineering/software/l1_bench.py \
  --plan engineering/release/l1/l1_bench_plan.json \
  --port /dev/ttyACM0 --output results/L1-001/cell-plate-01 \
  --specimen L1-001 --operator student \
  --reference-id REF-001 --reference-uncertainty-n 0.02 \
  --pose-id bench-W-up \
  --mounting-notes "Replace with actual fastener lengths, engagement, torque, fixture and cable route"
```

Replace the example reference uncertainty with its documented value. For each trial the program asks for the actual stable reading before and after capture. It saves raw frames, timestamps, plan, metadata, hashes and the accepted analysis window. The target is an instruction, not ground truth. Type `q` or interrupt to stop; completed records remain intact.

Complete the physical loading steps carefully. The recorder rejects readout faults, excessive reference change and too few samples. The analyzer also rejects a missing force level, incomplete plan, mixed configuration or missing 20 N coverage. Preserve a rejected session and create a new named run after correction.

```sh
/usr/bin/python3 engineering/software/l1_calibrate.py \
  results/L1-001/cell-plate-01 \
  --output results/L1-001/cell-report.json
```

The analyzer verifies raw-file hashes and recomputes means, fits the two center cycles, then predicts all held-out forces. It never uses location to correct a reading. Proposed static screening criteria are RMSE ≤0.25 N and maximum absolute error ≤0.50 N across all held-out trials.

These error criteria use each trial's two-second mean. Inspect the preserved raw noise, sample timing and transient response separately; averaging can hide an unstable instantaneous signal.

If displaced loads fail, inspect the fixture and repeat after a documented correction. Persistent location dependence rejects this cell/adapter approach for reliable aggregate force. Do not fit a separate gain for every position and then describe the result as location-independent.

## Stage B: assembled finger

Install the aluminum carriers and original finger. The `l1_finger_plan.json` contains **131 trials**: three explicit unloaded zero readings, then eight force levels at eight contact sites with an unload after each. The four nail sites and four TPU sites are intersections with the actual source meshes; the [contact coordinate file](../release/l1/contact_sites.json) gives their locations.

Keep the same cell, electronics and gain. Pose may change from Stage A, but all of Stage B must use one recorded stationary pose. Remove external contact for the first three readings. Their mean sets only the integrated assembly's unloaded offset. The cell sensitivity is copied from Stage A and stays fixed.

```sh
build/l1-host/bin/python engineering/software/l1_bench.py \
  --plan engineering/release/l1/l1_finger_plan.json \
  --port /dev/ttyACM0 --output results/L1-001/finger-01 \
  --specimen L1-001 --operator student \
  --reference-id REF-001 --reference-uncertainty-n 0.02 \
  --pose-id finger-W-up \
  --mounting-notes "Replace with actual carrier material, fasteners, torque, gaps and cable route"

/usr/bin/python3 engineering/software/l1_validate_finger.py \
  results/L1-001/finger-01 \
  --cell-calibration results/L1-001/cell-report.json \
  --output results/L1-001/finger-report.json
```

Stage B uses the same error criteria plus ≤0.20 N maximum zero-return error and ≤0.10 N spread among the initial unloaded readings. The report separates results by contact site and retains the original model. It is evidence for the tested stationary assembly only.

## Before selecting a scalable design

| Experiment | What to record | Proposed decision |
|---|---|---|
| 0.2 N contact / no-contact repetitions | At least 100 loaded and 100 unloaded events at each nail/TPU family; locked threshold and a separate evaluation set | ≥99% detection and ≤1% false events on evaluation data; report counts and uncertainty |
| Pose sweep with no contact | Same fixed model at multiple gravity directions, then documented explicit unloaded zeros | Determine whether pose bias defeats the force criterion; no hidden re-tare |
| Static creep | Hold 5 and 20 N for 60 s, unload, repeat after recovery | Record peak drift, reference drift and zero recovery; compare to the 0.5 N error budget |
| Stiffness and clearance | Indicator readings and minimum gap at 0, 5, 10 and 20 N | No bypass contact; task-relevant tip deflection must be agreed from the actual precision task |
| Shear and torque cross-sensitivity | Independently referenced non-normal loads with normal force held constant | Quantify coupling before using the reading during sliding or twisting |
| Fault matrix | Both excitation leads, both signal leads, signal short, reset and USB loss | Document detection and missed faults; runtime signal short is a known gap |
| Reassembly and replication | At least three independent cells/builds and five removal/reinstallation cycles | Repeat the held-out force tests; compare manufacturing and mounting variation |
| Wear and task trials | 10,000 representative load cycles, post-test calibration, thin-edge insertion and precision pickup against an unmodified control | Measure degradation and actual task success; this cycle count is a proposed test, not an attained lifetime |

The supplied static scripts do not automate this later qualification matrix. Save these raw logs and observations with explicit experiment IDs. Dynamic latency needs a synchronized physical reference; USB arrival rate alone is not sensor response bandwidth.

## Return the evidence

Return the completed specimen sheet, actual CAD hashes, photos of both mount directions, measured gaps, fastener records, Stage A and B session directories, both reports, indicator readings and fault logs. Keep all raw JSONL files and failures.

Load a measured report into the website's result inspector to view held-out reference versus predicted force. The file stays local to that browser. Uploading or inspecting it does not change the published specimen count.

No physical L1 specimen has been assembled or tested in this release. CAD checks, register tests and synthetic software fixtures cannot establish 20 N accuracy, a safe moment rating or robust robot grasping.
