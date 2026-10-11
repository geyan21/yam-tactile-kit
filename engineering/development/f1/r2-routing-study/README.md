# R2 routing study — rejected, do not fabricate or power

The board has 0 missing connections, but independent KiCad checking reports **95 violations**. No Gerbers were exported.

This is failure evidence for continued layout work, not a usable F1 electronics release.

Findings by type:

- shorting_items: 1
- hole_clearance: 1
- courtyards_overlap: 3
- invalid_outline: 1
- track_width: 87
- silk_edge_clearance: 2

The route includes an R3_I-to-GND short and 0.1124 mm neck-down tracks below the declared 0.15 mm minimum. Courtyard, outline and silkscreen findings also remain. The full report is in `checks/drc.json`; every finding must be resolved before export.

The official bundled-Java Freerouting 2.5.0 tool produced the stored session. Its own near-1000 score did not establish compliance with this board's native rules. The import restores a missing empty mounting-package string and records a 0.1 µm placement-grid allowance; the final board is regenerated from its original placement, with no generated pad-net changes.

Keep this study separate from the original checked fanout, the checked wrist module, and the mechanical fit packet. None supplies a physically qualified F1 finger. Fitted flex, reference/coupled-array checks and all contact/20 N tests remain.
