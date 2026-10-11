# FB1 guide revision

The first checked full assembly used **0.40 mm** leaves. Its evaluated
configuration is retained as `force_button_fb1_040.json`.

- CAD: `build/engineering/prototypes/force_button/cad_runs/20261011T193546.767616Z`.
- Fit: `fit_checks/20261011T193751.012136Z` under that prototype root.
  All 1,519 declared checks passed, including actual sphere/plunger contact.
- Bonded-metal FEA: `fea/20261011T193850.271464Z`, with a 2 mm global mesh,
  0.65 mm leaf mesh and 0.0001 mm/N assumed sensor compliance.
  Maximum added contact motion at 20 N: **0.0981778752 mm**.
- Same geometric mesh, softer sensor scenario:
  `fea/20261011T194319.440476Z`, with 0.0005 mm/N assumed sensor compliance.
  Maximum added contact motion: **0.1041905238 mm**.

The latter exceeds the provisional 0.1 mm screen. The initial version is
retained as a design study, not represented as a robust pass.
No mesh convergence or physical qualification is claimed for that version.
The current FB1.1 design increases leaf thickness to 0.50 mm and requires
its own geometry and structural checks.

Original CAD, meshes, solver decks, raw outputs, failed exports and the
stopped first mesh attempt remain under `build/`. The current publication
archive includes the earlier configuration and both numerical reports
so the design change can be reviewed.
