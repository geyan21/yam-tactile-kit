# C1.1 prototype scope

The original ENPIRE frame/contact geometry is attributed to Wenli Xiao / NVIDIA. The unchanged source geometry and provenance remain in engineering/docs/GEOMETRY.md.

C1.1 adds a transverse metal strain beam, two carriers, clamp caps, alignment and bench fixtures, dual-bridge readout, raw acquisition and static calibration tools. The earlier longitudinal C1 coupon remains in engineering/concepts.

CAD, PCB DRC and structural/numerical checks are digital evidence. No physical C1 assembly, calibrated accuracy, lifetime or robot qualification is reported. Structural calculations use ideal bonded clamps and a rigid finger; real joints, wires, gauge bonding, temperature and motion require measurements.

Structural mesh generation uses Gmsh 4.15.2 (Geuzaine and Remacle); structural solution uses CalculiX 2.23 (Dhondt). Official download provenance is retained in the structural reports. The tools themselves are not redistributed in this package.
