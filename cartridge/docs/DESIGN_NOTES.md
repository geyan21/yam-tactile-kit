# Design notes

How the v0.2 cartridge came about, and the choices behind it. The build-facing details are in [../README.md](../README.md).

## The problem

The first attempt was a CAD-to-tactile pipeline: import the gripper finger STL, select the contact regions, and unfold them into 2D to design a custom FPC. It stalled on two things. The ENPIRE-style finger (the MakerWorld design used on the YAM) has an irregular, rounded tip that is hard to unfold, and its narrow fingertip leaves little room for an FPC.

Both problems come from the finger's geometry, not from FlexiTac. Polyimide bends but does not stretch, so a flat circuit can only follow developable surfaces: planes, and cylinders or cones bent along straight fold lines. ENPIRE's two contact faces are in fact developable. The nail face is a plane, and the TPU cradle is a straight extrusion across the finger. But an unfolding tool that takes the mesh as it is meets everything on and around them: 1 mm serration teeth, far too tight a bend for polyimide; a lattice that flexes in use; and a narrow nail split by a groove.

## Turning the approach around

Instead of designing a custom FPC around the finger, the cartridge designs the finger around a standard flat pad. Its inner face is one flat bay that holds the pad flush. The nose stays a thin rigid tip, and a 1.2 mm TPU skin wraps the face, nose and sides. All the irregular shape lives in the printed core and the skin, which are cheap to change.

That also removes the narrow-tip routing problem. Every trace leaves the pad at its base and runs up a groove to the board in the cartridge, so nothing has to pass through the tip. If the very nose ever needs sensing, a pad can wrap over a cylindrical nose along a straight fold with no taxels on the bend, at the cost of a slightly blunter tip. A magnetic eFlesh insert is the other option for that spot.

The cost is width. Eight columns at 2 mm pitch plus routing margins make the tip 26 mm wide, against about 18 mm for the stock tip 5 mm from the end. Six columns would bring it to about 22 mm. Thickness stays at stock level: 3.25 mm at the centre 1.7 mm from the end, against 3.83 mm for the stock tip.

Using one standard pad for every finger also matters for a fleet. FlexiTac reports that swapping in a fresh pad does not noticeably change policy performance, so one design keeps every cartridge's data comparable.

## Keeping ENPIRE's shape

For tasks that need ENPIRE's thin nail and its cradle, the second finger, ENPIRE-T, keeps that shape and solves each problem in place instead. The teeth move into a molded skin over a smooth, rigid seat, so nothing flexes under the sensor, and the nail gets a flush 56-taxel pad around its groove. It docks on the same socket. [ENPIRE_T.md](ENPIRE_T.md) has the design and its checks.

When a task needs touch only at the nail, the cradle's compliance is worth keeping for power grasps. The third finger, ENPIRE-T Tip, senses on the nail only, with 92 taxels at 1.25 mm, and keeps ENPIRE's own TPU insert as the cradle. Its laminate wraps round the nail root and runs up the back spine behind the insert, one sheet thick, so the contact side changes only at the nail root's edge. [ENPIRE_T_TIP.md](ENPIRE_T_TIP.md) has the design and its checks.

## Sensor choice

The cartridge uses FlexiTac-style piezoresistive pads: a sealed FPC / Velostat / FPC laminate under 1 mm thick. A full unit with readout costs about $30, and the authors report that pads typically last about a year, with some teams logging thousands of demonstrations without breaking one. The dense pressure map converts directly into 3D tactile points that fuse with point-map and video streams, and a lot of compatible data already exists. Deform360, for example, holds 215.7 hours captured with FlexiTac.

Its main weakness is that it measures pressure mostly perpendicular to the surface, so shear and slip are only indirect. TacGB (TacGooseBumps) shows a way to add shear sensing to normal-only sensors like this one, and was built on FlexiTac.

For the readout, the HiPi work is the better model for a fleet than the original Arduino Nano board. Its readout board is designed for commercial fab assembly (no hand soldering) around an STM32. It reaches 220 Hz over four dense arrays in a bimanual setup, and it preserves contact shape far better than a reproducible baseline (IoU 0.43 → 0.80). The cartridge's suggested finger PCB follows that direction.

Several alternatives were considered and set aside for this finger:

- AnySkin is the easiest to swap, since its magnetic skin is separate from the electronics and trained policies keep working after a skin replacement. But it reads out through five 3-axis magnetometers, so its spatial resolution is coarse, and the board has to sit right under the skin, which is hard in a thin tip.
- eFlesh is the real CAD-to-sensor option for irregular shapes. Its tool turns simple convex STL or OBJ shapes into printable TPU sensors with embedded magnets, reaching 0.5 mm contact localisation and also estimating shear. It is worth trying for the nose.
- Both magnetic options pick up interference from nearby ferromagnetic or electromagnetic sources, so bench-test them next to the gripper motor and with metal objects first.
- Camera-based sensors such as GelSight Mini and DIGIT are too thick and too fragile for this finger.

## Designing for a fleet

The cartridge has two replacement levels. The skin is the frequent wear part, so it comes off without tools; its thickness is controlled so a swap does not shift the signal. The cartridge itself, with its core, pad and board, is swapped rarely.

The readout lives inside the finger, so the connection across the dock is five pogo pins (GND, D−, D+, VBUS, GND) instead of the pad's own 24 lines. Small FFC connectors are typically rated for only tens of mating cycles and do not survive operators swapping fingers, so the ZIFs stay inside the cartridge and are never touched in normal use. Each cartridge reports its MCU's unique ID, which gets logged with every episode, so drift can be traced to a specific pad.

The carriages move 47.5 mm each, so no flat cable crosses the moving joint. A high-flex cable with a service loop runs from each socket to the gripper body, bundled with the wrist camera cable.

Because every cartridge is the same CAD part, taxel positions come straight from CAD (`out/taxel_map.json`). That removes the per-rig pad-to-gripper calibration that 3D visuo-tactile fusion normally needs.

Some operating habits complete the design:

- Zero the pads with the gripper open at the start of every episode.
- Log the gripper motor current as a free total-force channel.
- Check each cartridge on a known-weight press jig before it goes on a robot.

## Open questions

- Whether 26 mm of fingertip width is acceptable for the target tasks, or whether a six-column pad is worth the extra layout work.
- How much the 1.2 mm skin and its durometer reduce sensitivity at light contact, and whether a softer or thinner skin wears too quickly.
- Whether the tasks need shear. If so, a TacGB-style shear layer or a magnetic sensor at the nose is the next step.
- The exact ZIF part and its FPC entry height, and the pogo-pin series for a ground-first mating order.
- Confirming on the robot that the stock tip screws go in from above, as the meshes suggest.

## Sources

- [FlexiTac project page](https://flexitac.github.io/), [paper (arXiv 2604.28156)](https://arxiv.org/abs/2604.28156), [hardware repository](https://github.com/FlexiTac/FlexiTac_Hardware_Repo)
- [Awesome FlexiTac (TacGB, Deform360 and others)](https://binghao-huang.github.io/Awesome-FlexiTac/)
- [HiPi (arXiv 2606.11372)](https://arxiv.org/abs/2606.11372)
- [AnySkin](https://any-skin.github.io/)
- [eFlesh](https://e-flesh.com)
- [i2rt YAM repository](https://github.com/i2rt-robotics/i2rt)
- [ENPIRE gripper finger on MakerWorld](https://makerworld.com/en/models/2984746-gripper-finger-for-robot-arm)
