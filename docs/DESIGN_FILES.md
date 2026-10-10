# Get and use the design files

The landing page's **Get the complete kit** section provides the whole handoff in one download. It contains the source repository, an offline copy of the website, the documentation, and the design package.

Separate downloads are also provided for source code, design files, documentation, and the offline website. The complete instructions and all visualization panels are available on the landing page itself; the separate guide page is a convenient reading/printing view.

## What the design package contains

The package includes editable OpenSCAD source, a JSON triangle model, separate STL component envelopes, both SVG design drawings, exact input parameters, calculated budgets, the component checklist, the measurement template, and the proposed sensor data contract.

The 3D assembly illustrates component placement and a thin tapered finger. It is generic packaging geometry. It is not the user's exact finger, a selected commercial force sensor, or manufacturing-ready CAD.

The mount and sensor envelopes use recorded illustrative dimensions. Their shape does not specify a calibrated spring. Mounting holes, cable channels, overload stops, tolerances, and the actual compliant finger structure still need design work.

## Reproduce or modify the geometry

Edit a copy of `examples/design.example.json` or export settings from the web lab, then run:

```sh
/usr/bin/python3 scripts/reproduce.py --design examples/my-design.json
```

Generated geometry appears in `build/design/`. The downloadable design ZIP is in `build/site/downloads/yam-tactile-designs.zip`.

The browser's 3D view uses the same parameter rules as the Python geometry generator. Drag to rotate, use arrow keys when the view has focus, or use the reset/explode controls. The parameters modify envelopes; they do not perform FEA or validate a real sensor.

An individual STL mesh can be imported into a CAD program using millimeter units. The separate components are closed meshes, but overlaps in the assembly are intentional packaging allowances. Do not print or mount them as qualified working parts.

The generated `.scad` file is editable in OpenSCAD without external libraries. The Python build and website do not require OpenSCAD to be installed. Mesh validation does not establish that a completed mechanical design is safe or manufacturable.

## Reproduction and hardware readiness

The digital outputs, source code, synthetic calibration exercise, and website can be reproduced now. Physical replication still requires the actual finger CAD and measurements, part selection, detailed mechanical/electrical design, assembly, calibration, and qualification.

The exact missing inputs and the bench-to-robot procedure are listed in the hardware and validation chapters. Keep the concept/measurement status attached to files when sharing them.
