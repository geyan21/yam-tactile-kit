# F1.1 R4 bench design

**Six pressure-film islands, twelve custom flexes and 64 proposed electrical locations; 0 physical specimens tested.**

Use flexible-matrix.html, f1-manufacturing.html, f1-capture.html and f1-testing.html on the kit website, or the corresponding files in docs/. Run host software from the complete repository.

`cad/` contains the current retained covers/bases, complete foil envelopes, segmented terminal pieces, assembly forms, carrier and molds. `parts.csv` distinguishes fabrication, tooling and reference envelopes. Never print an electrode or purchased-component envelope and call it a working sensor. `patterns/` supplies the six developed film cuts and PI/adhesive pieces.

`flex/` holds twelve distinct R4 native designs with full independent checks and their original development Gerber/drill exports. Use the proposed manufacturing contract and inspect terminal coupons before a larger order. The original warnings remain; material/finish tolerances and actual connector seating require physical acceptance. `electronics/fanout/` is the matching checked R3 board; `electronics/wrist/` retains the complete checked wrist module. Use both complete component CSVs in addition to bom.csv. Use package-level docs/ for current integration; the retained wrist module also includes its original historical instructions.

Nominal nail addition is 0.4614 mm. The 0.7264 mm TPU figure is above the R1 fitting datum; the variable base below it is additional. TPU covers and bases are 14 mm wide around 13 mm foils. Earlier 13 mm covers lacked side skirts and remain historical only.

The complete static overlap screen keeps twelve manufacturer mating cavities unqualified. Actual seals, strain relief, installed drive, loaded motion and tail slack require physical inspection. The Molex gold cable is an incoming-inspection candidate with documented dimensional/plating questions, not a guaranteed qualified connector pair.

Raw firmware and version-2 host recordings preserve timestamps, faulty/incomplete frames and the fixed gain map. The stationary-force tool uses independent physical sessions and retains unavailable holds. There is no supplied measured force model or qualified contact detector. The routed ideal-feedback DC study does not include continuous-film lateral conduction or full coupled dynamics.

All earlier F1 modules remain in engineering/development/f1. Use this revision's parts together, then compare independent physical specimens with the simpler designs through 20 N per finger.
