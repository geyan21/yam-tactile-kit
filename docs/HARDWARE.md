# Hardware development and assembly path

The first prototype should retain the successful thin finger and its compliance. Put calibrated normal-force sensing in a replaceable proximal adapter, and evaluate an optional pressure strip on a small local contact region.

## Record the baseline

Populate `hardware/measurements.template.json` from the actual finger and gripper. Record the CAD revision/hash, mounting-hole positions and threads, tip envelope, opening and closed gap, useful and peak per-jaw forces, finger mass, and force-displacement behavior.

Measure the constraints that made this finger more useful than the UMI gripper: access to narrow gaps, thin-object pickup, alignment, and insertion. Save baseline task results before changing geometry.

Unknown measurement fields are `null`. Do not substitute the website's illustrative values.

## Select the force element

Use the component checklist in `hardware/bom.csv`. For the first prototype, prefer a characterized commercial element if it fits the root envelope. Specify useful force range, low-force noise, overload tolerance, stiffness, off-center response, and sensitivity to shear/torsion.

A single cantilever bending signal is not automatically independent of contact location. A compensated force element, or a properly calibrated arrangement of two moment measurements, is required for moving contacts. The website's ideal moment calculation is an explanation of the principle, not a finished strain-gauge design.

The full assembled adapter needs a stiffness budget. The example 20 N / 0.05 mm gives 400 N/mm. It is not an experimentally established requirement for this YAM.

## Design the mounting adapter

Create fixed and moving halves separated by the sensing element. Provide repeatable locating faces and a tongue/shoulder or equivalent feature to carry transverse load. Captive screws or a positive latch retain the finger.

Route all normal contact load through the sensing element. A cover, fastener, taut cable, or contacting stop must not bypass it. Keep the electronics and connector at the root. Check the jaw's entire swept volume and full opening/closing motion.

Add overload stops beyond the calibrated sensing travel. Stop clearance, strength, and impact energy need design against the real actuator and load case. Use instrumented metal for the calibrated spring; a printed housing is not a substitute for a characterized sensing element.

Preserve the leading-edge profile. If the adapter changes finger position, update tool-center-point, collision, and jaw-gap models and repeat the precision-task baseline.

## Build the optional pressure coupon

Begin with a flat coupon using upstream FlexiTac hardware instructions. Establish a usable load-response range under the proposed final wear layer before ordering a narrow FPC.

Use a 1- or 2-column strip on a small planar or gently curved inner-face seat if it fits. Keep the leading edge mechanically connected to the root sensor even where an array cannot fit. Separate sensing patches can cover multiple faces without unfolding the entire STL.

Reserve borders, attachment, cable fanout, and connector space. Do not trim a finished copper pattern arbitrarily. Review the actual FPC stack and dynamic bending with the fabricator. On a compliant finger, check full bending travel for film prestrain, stiffness changes, wrinkles, and peeling.

The 2 mm grid is a published FlexiTac V2 value. The small layouts in this repository are proposed envelopes, not upstream fabrication files or verified routing.

## Electrical interface

The selected sensing element determines the amplifier, bridge excitation, ADC, and wiring. Those selections are unresolved; this release does not include a fabrication schematic or device firmware.

Keep raw analog routes short. Digitize at or beside the adapter and send digital data to a gripper-base hub. Use a protected locking connector with separate strain relief and a controlled service loop. Do not use the electrical connector as the mechanical load-bearing interface.

Prototype host transport can be a separate USB hub. A production differential bus is an option after bandwidth, power, timing, and electrical review. Do not assume the YAM motor bus accepts a new tactile device without integration work.

`hardware/data-contract.example.json` shows the intended message fields: serial, finger revision, local frame, monotonic timestamp, sequence, temperature, raw channels, normal force, and validity flags. It is a proposed interface, not an implemented YAM driver.

## Assemble and identify

1. Inspect the fixed mount and locating faces.
2. Install the characterized sensing element without adding an unintended force path.
3. Install the enclosure and noncontacting overload stops.
4. Install the finger on the repeatable moving interface.
5. Add the optional pad and wear layer only after coupon characterization.
6. Route and secure the harness through full jaw travel.
7. Associate the adapter and finger identities with the correct left/right jaw.
8. Perform an unloaded zero, reference-load check, and inspection for contact with stops or covers.

## Service

Power off for the initial service procedure. Replace the worn contact surface or inexpensive complete finger through the indexed interface. Keep the calibrated adapter where possible.

After replacement, verify seating, identity, unloaded zero, and a reference load. Replacing a pressure cassette requires its own calibration/map identity. A keyed connector alone does not establish hot-swap behavior.

## Control integration

Acquire both jaws with timestamps and validity states before closing the loop. Define normal force as positive inward on each jaw. The sum of both jaw readings differs from per-jaw force.

Develop bounded contact detection and force regulation below the policy loop. Measure actual actuator bandwidth, friction, and minimum controllable force. Define task-appropriate handling of stale data, saturation, overload, and disconnection. Retain independent actuator limits.

This repository deliberately provides no robot-motion commands. Control integration starts after the sensing assembly has been characterized.
