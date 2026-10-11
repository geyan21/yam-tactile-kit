# FB1.1 force-button root prototype

**54 CAD parts/references, checked sensor PCB, raw firmware and physical calibration tools. Physical specimens tested: 0.**

Sensor: Honeywell FMAMSDXX025WC2C3, 25 N, 3.3 V, I2C 0x28. It sits at the root, with its sphere facing a flat adjustable plunger. Four 0.50 mm steel guides locate the floating carrier. The original nail and TPU retain their contact geometry; root reach increases 50 mm.

Use the separate force-button.html page, build-force-button.html and force-button-testing.html on the published site. In the complete source repository, the matching documents are engineering/docs/BUILD_FORCE_BUTTON.md and FORCE_BUTTON_TESTING.md.

CAD-stage readiness in force_button_manifest.json describes mechanical generation alone. The final package checks are recorded in prototype_snapshot.json. Hardware envelopes are references, not printable functional sensors or screws. Helical threads are manufacturing callouts.

The earlier 0.40 mm guide study is retained in history/; its softer-sensor scenario exceeded the provisional 0.1 mm motion target. Current structural results are in checks/structure.json and visuals/fb1_structural_screen.png. Their scope is a bonded, linear model, not real-joint or physical force qualification.

Firmware ZIP: four files for one Pico. Software scripts preserve raw data, failures and held-out sessions. Run host capture/calibration commands from the complete repository, which supplies src/tactile_kit/records.py. No physical force model or contact rule is bundled.

Set preload and all three overload gaps by independent measurement. Verify the actual drive interface, bolt lengths, cable loops, clamp slip, loaded clearances and tip motion. Factory nominal sensor newtons do not equal calibrated finger force.
