# k1_ch2_flex

Two-layer flexible circuit. Requested covered thickness: 0.186 mm. Core: 0.100 mm polyimide; copper: 0.018 mm each face; coverlay including adhesive: 0.025 mm each face. Confirm the supplied stack with the fabricator. F.Mask/B.Mask describe coverlay, not a substitute rigid-board solder-mask process.

F.Cu contains the sensing electrode and its driven guard. B.Cu is driven SHLD; it is not ground. Only the two top terminal lands are opened. No solder paste is generated. Hand-solder land 1 to CIN and land 2 to SHLD. The reference foil is made twice and connects its shield to SHLD2; the other foils use SHLD1.

The B.Fab outline marks a separate 0.20 mm polyimide stiffener with 0.05 mm adhesive. Its thickness is additional to the flex stack. The back stiffener covers the plated transition. Keep wire loads off the pressure area and the free bend. Label the stiffener with the cell identity during assembly.

Native DRC, board/material review, formed fit and physical bring-up remain required before use. These files are not a measured force or contact result.
