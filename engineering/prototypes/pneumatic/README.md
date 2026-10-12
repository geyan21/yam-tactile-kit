# P1.0 pneumatic bench design

**Eight air channels, four remote differential transducers and two thin R1 N0 nail cells. Zero physical builds or tests.**

Start at pneumatic.html and build-pneumatic.html on the website. Exact wiring is on pneumatic-electronics.html; testing and digital reproduction have their own pages. For host scripts, shared R1 construction instructions and regeneration, use the complete repository or the complete portable kit's source directory. This prototype ZIP is the matching design/fabrication packet, not a standalone installed Python environment.

`cad/` contains 112 parts and references. Print the replacement insert, closure plugs and bench carrier as specified. Gas spaces, bond envelopes, metal tubes, electronics and nail laminates are references: do not print them as substitutes for functional materials.

`port_cut_and_hose_map.csv` is the actual selected tube table. Six standard tubes are 6 mm long, CH5 back is 8 mm, and CH4 front uses the 15 mm slim stem plus its 3 mm sleeve. Front goes to B high and back to A low of the same PS0..PS3 sensor. The first 3 mm engagement and 5 mm straight hose departure are modeled; measure and support the remaining slack hoses on the actual assembly.

`electronics/readout/p1_readout_fabrication.zip` is the checked PCB fabrication export. Use its complete components.csv as well as bom.csv. The native source, embedded footprints, pin/net list and independent DRC remain alongside it. The orientation card identifies all pressure-chip pins and both Pico socket pin-one positions. Inspect actual sensor ports and supplied headers/fasteners before assembly.

`patterns/r1_cut_sheet.*` retains the original R1 sheet; only its CH0/CH1 nail patterns are used by P1. Nominal N0 nail addition is 0.4 mm; measure the installed stack. Each nail cell needs its own 100k continuity resistor at the nail joint.

`firmware/` streams raw pressure/nail/supply data. `software/` preserves missing data, raw bytes and receipts and provides a fixed signed linear stationary-force baseline with independent physical evaluation. It supplies no measured model or qualified contact detector.

Nominal assembly, hose-clearance, cross-module and board checks pass. The ideal-gas study retains 26 out-of-range scenarios among 3,888 and an explicit common-pressure cancellation example. These are scenario inputs, not a 20 N force prediction. Actual seals, printed channels, pressure span, thermal/hose effects, loaded motion, contact reliability, force accuracy and task precision remain to be measured.

The original rigid ENPIRE frame is retained. Geometry attribution and source limitations remain in the shared geometry guide/release manifest. Earlier failed development runs remain in their original build directories; this package contains the coherent selected revision.
