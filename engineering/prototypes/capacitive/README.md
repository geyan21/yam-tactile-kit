# K1.2 capacitive bench prototype

**Six contact cells and two protected references; 0 physical specimens tested.**

Use the separate capacitive.html page, build-capacitive.html and capacitive-testing.html for sensor placement, assembly and evaluation. Matching source documents are engineering/docs/BUILD_CAPACITIVE.md and CAPACITIVE_TESTING.md.

The tactile sensor is the custom plate/post-sheet/flex capacitor. Two TI FDC1004DGSR boards read it; an FDC1004 board alone is not a tactile sensor. CH0 and CH1 cover the two nail prongs. CH2–CH5 are curved cells on local rigid saddles over the TPU.

`cad/` and `patterns/` contain manufactured parts, tools and explicitly labeled fit references. `flex/` has seven independently checked native boards and Gerber/drill sets: order each contact shape once and REF twice. `readout/` retains the checked 23-component board used for both banks. `bom.csv` includes materials and quantities. No proprietary sensor or tool executable is represented by a printed CAD envelope.

`checks/native.json` records the native writer's pre-check stage. `checks/native_check.json` records the subsequent independent checks of all seven foils. Use the matching checked fabrication ZIPs, not an intermediate export.

The nail flex has a lifted free bend and a flat terminal. The curved terminal stiffeners have their own neutral-plane patterns and bonding forms. The seven cover molds have registration, steel-insert cavities and overflow channels. Actual fabrication, cure, demolding, ground bonds, fatigue and adhesion remain unqualified.

The two bank cases protect unloaded references and provide harness tie slots. Keep the Pico outside these cases. The actual YAM drive is unidentified: use the tabs with a measured bracket and inspect all jaw motion before installed use.

The assembly screen retains failing assumptions. Soft-post/thick-bond scenarios can bottom a nail before 20 N; high assumed post stiffness reduces the 0.2 N signal. Finite plate loading, hysteresis and no-contact bending are not solved by this model. Nominal nail addition is 0.836 mm. The 1.786 mm TPU number is above the R1 datum, not total addition to bare TPU.

Four-file raw firmware and host recording/static-calibration tools are supplied. Run host tools from the complete repository. There is no measured calibration or contact threshold. Fit and evaluate independent physical sessions; preserve all failures.

The older K1 development module is retained at engineering/development/capacitive/k1. Use this package's artwork, stops, retained plates and tooling together; do not mix revisions.
