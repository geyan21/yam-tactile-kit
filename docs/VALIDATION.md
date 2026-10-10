# Physical validation plan

All hardware tests below are outstanding. Passing the repository's software tests demonstrates reproducible calculations and website behavior, not gripper robustness.

## Establish task requirements

Choose the actual object set, useful per-jaw force range, smallest detectable contact, allowed tip deflection, narrow-access geometry, acceptable object damage, and service interval. Record the baseline with the current finger.

The values below are initial proposed development gates from the design review. Adjust them to the real tasks before qualification.

| Area | Proposed experiment | Evidence to save |
| --- | --- | --- |
| Geometry and dexterity | Compare thin-object pickup, narrow access, alignment, and insertion with the original finger | CAD revision, gap/TCP measurements, task results |
| Normal force | Loads at nose, middle, edges, and varied orientations; initial error target greater of 0.2 N or 5% of reading | Reference instrument calibration, raw data, residual plots |
| Cross-axis behavior | Shear, torque, and off-center normal loading | Interference matrices and worst-case errors |
| Drift | Warm-up, temperature sweep, loading/unloading cycles, ten-minute holds and recovery | Time series and hysteresis/creep measurements |
| Replacement | At least ten units across build batches; repeated removal and refitting; proposed service target under two minutes | Serial numbers, seating/zero/reference checks, service timings |
| Pressure-map fidelity | Point, line, broad and separated contacts under the final cover | Reference contact masks, crosstalk and saturation results |
| Wear and fatigue | Initial 10,000-cycle development test, then a distinct 100,000-cycle stage at representative loads | Cycle/load history, inspections, drift and failures |
| Timing and control | Initial force-channel target at least 200 Hz and under 10 ms measured sensor-to-controller latency | Timestamp jitter, missed frames, step response and overshoot |
| Failure behavior | Sensor disconnect, stale data, saturation and overload | Controller state traces and observed response |
| Manufacturing | Controlled assembly, materials, cure/adhesive process and end-of-line checks | Build records, rejects, calibration yield and cost |

Cycle counts do not translate directly into years of service. A small pilot does not establish fleet reliability. The final qualification sample size and acceptance criteria must match the intended usage and reliability claim.

## Keep evidence attributable

Save each test in a separate dated directory with the adapter/finger revisions, serial numbers, fixture configuration, commands, operator, raw data, and calibration identity. Do not overwrite the original runs when changing processing.

Report measurement uncertainty and exclusions. Distinguish a prototype that passes a particular task from a product that is qualified across its intended envelope.

## Release gates

The hardware can progress from concept to a bench prototype after exact geometry, load range, and components are selected. Robot integration requires a characterized assembly and a bounded control strategy. A production release additionally requires manufacturing, service, reliability, and task evidence.

The software release in this repository does not advance those hardware gates automatically.
