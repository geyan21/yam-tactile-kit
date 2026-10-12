# Physical build and comparison handoff

**36 planned specimens; no physical results are entered.** The digital packages are published, but the goal is not complete until the designs are built and measured.

Operator: unassigned. Shared measurement location: unassigned.

[Download the specimen queue](specimen_queue.csv) · [Read the completion audit](completion_audit.json)

## Start the build campaign

1. Assign the student/operator and the experiment directory. Use the exact published revision below.
2. Obtain/fabricate the parts from each linked BOM and build guide. Record real material lots, electronics and build time.
3. Assemble each planned specimen separately. Check actual drive fit, leading-tip access, power, raw sensing and failure behavior before load testing.
4. Run the shared force/contact/precision protocol. Keep calibration and evaluation sessions separate, and retain failed builds, rework and unavailable readings.
5. Enter record paths and measured results in `specimen_queue.csv`. Blank metrics mean unmeasured, not zero error.

## All twelve designs

| Design | Planned specimen IDs | Build instructions |
|---|---|---|
| R1 | R1-01, R1-02, R1-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-r1.html) |
| L1 | L1-01, L1-02, L1-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-l1.html) |
| B1 | B1-01, B1-02, B1-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-b1.html) |
| B2 | B2-01, B2-02, B2-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-b2.html) |
| C1 | C1-01, C1-02, C1-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-c1.html) |
| N1 | N1-01, N1-02, N1-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-nail.html) |
| B3 | B3-01, B3-02, B3-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-recessed.html) |
| F1 | F1-01, F1-02, F1-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-f1.html) |
| K1 | K1-01, K1-02, K1-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-capacitive.html) |
| P1 | P1-01, P1-02, P1-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-pneumatic.html) |
| O1 | O1-01, O1-02, O1-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-optical.html) |
| FB1 | FB1-01, FB1-02, FB1-03 | [Build guide](https://geyan21.github.io/yam-tactile-kit/build-force-button.html) |

[Common test and comparison plan](https://geyan21.github.io/yam-tactile-kit/build-all.html)

Use 0, 0.2, 0.5, 1, 2, 5, 10, 15 and 20 N per finger with the specified independent reference. The plan also requires no-contact disturbances, nail/soft-surface edges and mixtures, tip motion, task access, wear, recovery and build practicality.

The proposed force targets are <=0.5 N held-out RMSE and the stated per-trial error rule. Contact confirmation uses 300 independent presentations per label/region with a one-sided 95% bound; adjacent frames are not independent trials. The provisional added-motion screen is 0.1 mm at 20 N.

A repeated recording or a renamed specimen is not another independent build. Follow each design's capture and validation procedure; a CAD check or synthetic fixture cannot fill a physical-results cell.

Published source revision: `7593de44878dce1305d4bcdd6dafb18d4c1c778d`.
Source archive SHA-256: `adb2cbe5cc5479083dd463e4a604375b83d13b9b38aa0591b12fb1e19d9989be`.

`completion_audit.json` records the remaining evidence for each requirement. No design is designated a physical winner.
