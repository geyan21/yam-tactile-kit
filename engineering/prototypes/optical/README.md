# O1.0 fixed-optics tactile finger

Camera Module 3 Wide, rigid PET mirror backing, clear Solaris gel with 42 markers, four blue LEDs and two thin R1 N0 nail cells. The camera bay adds 32 mm reach. Zero physical builds or tests; 20 N is a target, not a rating.

Start at optical.html and build-optical.html. Separate wiring, physical-testing and reproduction pages accompany this packet. Use the complete repository/source packet to run Python tools and obtain shared setup dependencies; this ZIP is not a standalone installed environment.

`cad/` and `parts.csv` distinguish fabricated parts from gel, bond, camera/electronic and hardware references. Cast the gel with the supplied molds; do not substitute a rigid printed gel. `patterns/` contains 1:1 mirror and marker sheets plus the retained R1 nail sheet. Use only CH0/CH1 from that R1 sheet.

`electronics/led/o1_blue_ring_fabrication.zip` is the independently checked two-layer board export. Native PCB, embedded footprints, pin/net CSV and complete component positions are included. Use optical-electronics.html for Pi/ADS1115 wiring and the two separate nail nodes.

`software/` provides lossless capture, marker-reference creation, raw replay and physical force/contact fitting/evaluation. No coefficients, measured images or force/contact results are supplied. `templates/` contains empty setup/trial files.

The undeformed-gel refraction screen retains three distal edge-exit rays out of 105 sampled rays. Pupil, focus, distorted/deformed visibility, actual drive/harness fit, stiffness, surface wear and force/contact performance need physical acceptance. The preserved CAD/PCB checks are limited to their declared nominal properties.
