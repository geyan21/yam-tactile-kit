# Concept design files

These files are the editable design starting point supplied with YAM Tactile Kit. They are **component envelopes for visualization and discussion, not fabrication-ready parts**.

The generic wedge-shaped finger is not a copy of the user's MakerWorld model. The original finger's dimensioned CAD and measured mounting geometry remain unavailable.

| File | Use |
| --- | --- |
| `assembly-envelopes.scad` | Editable OpenSCAD assembly of the conceptual envelopes |
| `assembly-envelopes.json` | Component vertices, triangles, coordinate frame, and explicit assumptions |
| `mount-envelope.stl` | Generic fixed-mount packaging volume |
| `sensor-envelope.stl` | Generic force-module packaging volume |
| `finger-envelope.stl` | Thin tapered finger envelope |
| `pad-envelope.stl` | Laminate allowance, when a nonzero-thickness pad fits the grid budget |
| `finger-concept.svg` | Dimension-labeled schematic generated from the build inputs |
| `original-architecture.svg` | Original force-path and service-interface drawing |
| `design-inputs.json` | Exact example inputs used to generate this package |
| `design-summary.json` | Calculated pad, opening, force, and stiffness budgets |
| `bom.csv` | Component-selection checklist; unresolved part numbers are explicit |
| `measurements.template.json` | Actual assembly measurements still required |
| `data-contract.example.json` | Proposed sensor message format |

Lengths are in millimeters. The assembly coordinate frame is X inward normal, Y finger width, and Z distal. STL does not store units; select millimeters when importing it.

The mount and force-module dimensions are illustrative packaging assumptions recorded in the JSON. No fastener pattern, calibrated spring, selected force transducer, PCB, protective stop, or manufacturing tolerance is modeled. The laminate's overlap with the finger illustrates a recess allowance; it is not a finished pocket.

Each exported component STL is a closed mesh. The parts remain separate and can overlap in the conceptual assembly. The meshes do not constitute a printable, load-qualified gripper.

Edit the source design JSON and run `scripts/reproduce.py` from the source repository to regenerate every design output. The OpenSCAD file can also be opened and edited directly; [OpenSCAD](https://openscad.org/) is optional and is not needed by the Python builder or web viewer.

The release checks mesh closure, orientation, and agreement between the browser and Python geometry. OpenSCAD itself is not a required tool in the verified build, and no structural or manufacturing validation is implied.

Before designing production parts, record the actual mounting geometry and operating loads, select a characterized force element, develop its real load path and overload protection, and follow the hardware/validation guide.
