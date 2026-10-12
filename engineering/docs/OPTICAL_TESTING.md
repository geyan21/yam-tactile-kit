# O1 physical acceptance and comparison

**Physical specimens tested: 0.** O1's CAD, PCB checks, neutral ray model and synthetic software tests do not establish reliable contact, force accuracy, stiffness or durability.

Use the [common twelve-design plan](build-all.html) and [shared test protocol](testing.html). The requested force range is **up to 20 N per finger**. Use an independent force reference with documented uncertainty; the supplied fit workflow requires ≤0.05 N reference uncertainty.

## Accept the assembled sensor first

1. Check the actual drive fit, passive jaw stroke, cable slack, thin-nail access and all fasteners. Measure the added 32 mm reach and actual width/height.
2. Inspect the gel cure, thickness, flange retention, coating opacity, dot adhesion and mirror flatness. Image all 42 dots through the full working region.
3. Check each nail separately, LED current, ADC supply and raw counts. Demonstrate disconnected-lead, missing-frame, blocked-image and overexposure behavior.
4. Measure baseline drift after warm-up and under no-contact jaw/motor movement, cable movement, nearby objects and temperature changes.
5. Start at low force. Progress through 0.2, 0.5, 1, 2, 5, 10, 15 and 20 N only after the preceding assembled checks and lower-load behavior are acceptable. Preserve deformation, slippage and failed readings.

The geometry preserves the original nail and mount regions. It does not establish the extended frame's stiffness or 20 N strength. Measure tip motion and recovery at the nail and gel contacts, including loading/unloading and long holds.

## What the optical model says

![Neutral refraction screen](assets/prototypes/optical/visuals/o1_refraction.png)

The fixed assembly clears the selected 210 zero-width air-path segments. A separate undeformed-gel model uses Solaris's supplier refractive index of **1.41**. Of 105 sampled incoming rays, **three at the distal end exit a gel edge** rather than its object-facing surface. The first marker row is farther inward. These counts describe sampled model geometry; they are not contact success rates.

The model assumes an entrance-pupil position and omits finite aperture, distortion, focus, scatter, coating quality and deformation. Check the actual visible boundary and all marker rows under loading. Contacts at the frame, clips, gel border, notch or uninstrumented nail edge can bypass the sensed regions.

## Freeze training before evaluation

Use the [empty O1 trial template](assets/prototypes/optical/templates/optical_force_trials.json). It is not a dataset.

Train these six sites separately: `nail0`, `nail1`, `gel_distal`, `gel_middle_distal`, `gel_middle_proximal`, `gel_proximal`. Use all nine force levels from 0 to 20 N and at least three independent holds per level/site. A hold needs its own capture directory and a stationary window of at least ten seconds.

The four gel sites are physical probing regions, not four camera channels. The image baseline observes all 42 markers; the feature vector includes their X/Y motion and log area changes plus both nail conductances.

Record material/coating/mirror process, electronics, pose, temperature, specimen, geometry and marker-reference hashes. Declare the force axis. Negative contact presentations must have a real gap from the object; a nominal zero-force reading alone does not define free space.

```sh
/usr/bin/python3 engineering/software/optical_force.py fit \
  --trials build/o1/train_trials.json --output build/o1/model.json
/usr/bin/python3 engineering/software/optical_force.py evaluate \
  --trials build/o1/test_trials.json --model build/o1/model.json \
  --output build/o1/test_report.json
```

The force baseline is a fixed regularized linear fit, with no clipping to 0–20 N. The contact baseline uses a frozen deviation threshold. If free-space and contact training observations overlap, **no contact detector is produced**. A successful fit is not a successful held-out comparison.

Evaluation requires a new session and new captures. Test both nail prongs, nail edges/notch, distal/middle/proximal gel, and nail/nail, gel/gel and nail/gel mixtures. Changed optical settings, surface process or pose require a separately identified calibration/evaluation.

## Decide whether O1 is suitable

Report held-out force RMSE, individual errors, unavailable holds, contact misses/false positives, and actual task success. The proposed common force targets are RMSE ≤0.5 N and each error ≤max(0.5 N, 10% of reference force), including the reference bound.

For contact reliability, the tool counts any incorrect frame or unavailable presentation as a failed independent presentation and reports a one-sided 95% bound per declared condition. Use the campaign's 300 independent presentations per label/region for confirmation; adjacent video frames are not independent trials.

Repeat three separately assembled specimens, and record fabrication, assembly, rework, calibration and surface-replacement time. Compare precision tasks, tip access, gel wear, contamination and recovery with the other designs. O1's larger root, mirror/coating maintenance and processing requirements must be included in that comparison. There is no measured winner yet.
