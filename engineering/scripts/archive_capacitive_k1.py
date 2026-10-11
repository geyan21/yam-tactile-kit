#!/usr/bin/python3
"""Archive the current K1 tooling/readout modules without claiming a completed finger."""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cells", "saddles", "board", "screen", "visuals"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / "engineering/development/capacitive/k1")
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ("cells", "saddles", "board", "screen", "visuals")}
    target = args.destination.resolve()
    if not all(p.is_relative_to(ROOT) for p in (*paths.values(), target)) or target.exists():
        parser.error("Use repository-owned inputs and a new checkpoint destination")
    cells = json.loads((paths["cells"] / "manifest.json").read_text())
    saddles = json.loads((paths["saddles"] / "manifest.json").read_text())
    board = json.loads((paths["board"] / "k1_readout.json").read_text())
    receipt = json.loads((paths["board"] / "latest_check.json").read_text())
    checked = paths["board"] / receipt["directory"]
    pcb_check = json.loads((checked / "pcb_checks.json").read_text())
    screen = json.loads((paths["screen"] / "report.json").read_text())
    visual = json.loads((paths["visuals"] / "report.json").read_text())
    if (receipt["violations"] or receipt["unconnected"] or not saddles["passed_nominal_checks"]
            or receipt["source_sha256"] != board["pcb_sha256"]
            or digest(paths["board"] / "k1_readout.kicad_pcb") != board["pcb_sha256"]):
        raise ValueError("Use the complete checked PCB and conforming saddles")
    for name, expected in visual["input_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("A visualization input changed: "+name)
    if len(cells["parts"]) != 49 or len(saddles["parts"]) != 4:
        raise ValueError("Unexpected K1 part set")
    with execution(ROOT / "build/records", "Archive the K1 cell tooling, source-fit supports, independently checked readout, raw code and stated limitations as an unfinished design module") as record:
        target.mkdir(parents=True, exist_ok=False)
        for name in ("cad", "patterns", "pcb", "artwork", "checks", "visuals", "firmware", "software", "history", "provenance"):
            (target / name).mkdir()
        selected = []
        for origin, manifest in ((paths["cells"], cells), (paths["saddles"], saddles)):
            for part in manifest["parts"]:
                historical = part["id"] in saddles["replaces"]
                for suffix in ("step", "stl"):
                    source = origin / part[suffix]
                    if digest(source) != part["sha256_"+suffix]:
                        raise ValueError("CAD identity changed: "+part["id"])
                    destination = target / ("history" if historical else "cad") / source.name
                    shutil.copyfile(source, destination)
                if not historical:
                    selected.append(part)
        for cell in cells["cells"]:
            if cell.get("formed_reference"):
                source = paths["cells"] / cell["formed_reference"]["file"]
                if digest(source) != cell["formed_reference"]["sha256"]:
                    raise ValueError("Formed reference changed")
                shutil.copyfile(source, target / "cad" / source.name)
        for source in (paths["cells"] / "patterns").iterdir():
            if source.is_file():
                shutil.copyfile(source, target / "patterns" / source.name)
        for name in ("k1_readout.kicad_pcb", "k1_readout.kicad_dru", "k1_readout.json", "k1_readout_pins.csv",
                     "fp-lib-table", "specification.json"):
            shutil.copyfile(paths["board"] / name, target / "pcb" / name)
        shutil.copytree(paths["board"] / "K1.pretty", target / "pcb/K1.pretty")
        for name, expected in pcb_check["files"].items():
            source = checked / "manufacturing" / name
            if digest(source) != expected:
                raise ValueError("Manufacturing file changed")
            shutil.copyfile(source, target / "artwork" / name)
        for source, name in ((checked / "drc.json", "pcb_drc.json"), (checked / "pcb_checks.json", "pcb_summary.json"),
                             (paths["cells"] / "manifest.json", "cell_cad.json"),
                             (paths["saddles"] / "manifest.json", "conforming_saddles.json"),
                             (paths["screen"] / "report.json", "model_screen.json"),
                             (paths["visuals"] / "report.json", "visuals.json")):
            shutil.copyfile(source, target / "checks" / name)
        for name, expected in visual["files_sha256"].items():
            source = paths["visuals"] / name
            if digest(source) != expected:
                raise ValueError("Drawing changed")
            shutil.copyfile(source, target / "visuals" / name)
        for suffix in ("png", "pdf", "svg"):
            shutil.copyfile(paths["screen"] / ("post_layout."+suffix), target / "visuals" / ("post_layout."+suffix))
        for source in (ROOT / "engineering/firmware/capacitive").iterdir():
            if source.is_file() and source.suffix in (".py", ".json"):
                shutil.copyfile(source, target / "firmware" / source.name)
        for name in ("capacitive_protocol.py", "capacitive_record.py"):
            shutil.copyfile(ROOT / "engineering/software" / name, target / "software" / name)
        shutil.copyfile(ROOT / "engineering/designs/capacitive_k1.json", target / "provenance/capacitive_k1.json")
        shutil.copyfile(paths["board"].parent / "routing.json", target / "provenance/routing.json")
        provenance = {"source_runs": {name: str(path.relative_to(ROOT)) for name, path in paths.items()},
                      "input_identities": {"cell_manifest": digest(paths["cells"] / "manifest.json"),
                                           "saddle_manifest": digest(paths["saddles"] / "manifest.json"),
                                           "pcb": board["pcb_sha256"],
                                           "native_check": digest(checked / "pcb_checks.json")}}
        (target / "provenance/source_runs.json").write_text(json.dumps(provenance, indent=2)+"\n")
        for name in ("SOURCE_ATTRIBUTION.md", "SOURCE_GEOMETRY_LICENSE"):
            shutil.copyfile(ROOT / "engineering/development/f1/r3" / name, target / name)
        with (target / "parts.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["id", "kind", "purpose", "material", "STEP", "STL"])
            for p in selected:
                writer.writerow([p["id"], p["kind"], p["purpose"], p["material"], p["step"], p["stl"]])
        with (target / "pcb_components.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["reference", "part_or_value", "footprint", "source", "quantity_per_board"])
            for part in board["parts"]:
                writer.writerow([part["reference"], part["value"], part["library"] or "K1 prototype plated wire port",
                                 part["source"], 1])
        readme = """# K1 capacitive cell tooling and readout

This is a **development module**, not a completed tactile finger or a measured
20 N result. The complete all-design campaign remains in progress.

The tactile element is a capacitor under each of the two nail prongs and
four TPU contact regions. A patterned silicone sheet separates its sensing
electrode from a grounded steel spreader. Two FDC1004DGSR boards each read
three cells against one protected, unloaded reference capacitor.
An ADS1115IDGSR on each board monitors supply and three plate-ground loops.

![Cell placement](visuals/k1_cell_placement.png)

## Current files

- 49 current checked STEP/STL parts: silicone casting masters, metal stencils,
  backing spacers, formed spreaders, conforming supports, tools and layer references.
- Six additional formed-post-sheet STL references. Flat casting masters remain
  authoritative for manufacturing; physical forming is unqualified.
- The four earlier slab-only supports in `history/`; use the conforming supports.
- One 42 × 38 mm, four-layer PCB design, used twice. It has 23 components,
  72 electrical pads, 357 routed segments, 34 vias and zero native KiCad
  violations or missing connections.
- Corresponding Gerbers/drills, embedded footprints, pins, component list,
  raw Pico firmware, decoder and USB recorder.

The layer-reference files are not functional 3D-printed capacitors.
Electrode copper, grounded plate joints, stops, retention, vent/seal details,
cable routes and the enclosure still require integration work.

![Sensor stack](visuals/k1_stack.svg)

## Mechanics and model limits

The first rigid slabs did not include the fitting base below the R1 smoothed
surface. The current supports incorporate that retained witness geometry and
reserve a 0.05 mm flex bond. Eighteen declared source/peer/flex comparisons
passed; actual printing, adhesive filling, stiffness and motion remain untested.

The nominal nail addition is 0.786 mm. The 1.736 mm TPU stack figure is above
the **R1 smoothed-saddle datum**, with the retained variable fitting geometry
below it. It is not the total addition to the bare TPU. This thickness is a
comparison concern for precision tasks.

SYLGARD 184 is the selected prototype dielectric material. The proposed sheet
has a 0.05 mm base and 0.15 mm high, 0.60 mm diameter posts. Use the material
manufacturer's 10:1 process. The 100 °C/35 minute cure is a candidate process
after the part reaches temperature; tool compatibility and actual cure need
inspection.

The saved capacitance/modulus sweep is a sensitivity study. It does not model
finite plate bending, contact-area loading, friction, viscoelasticity or measured
post compression. The revised shield estimates are about 336 and 373 pF;
the PCB and installed cable values still need measurement.

## Readout and raw code

![Readout board](visuals/k1_readout.png)

Use two identical boards on separate Pico I²C buses:

| Board | SDA / SCL | JS0 | JS1 | JS2 |
| --- | --- | --- | --- | --- |
| A | GP0 / GP1 | CH0 | CH2 | CH3 |
| B | GP2 / GP3 | CH1 | CH4 | CH5 |

Both boards use FDC1004 address 0x50 and ADS1115 address 0x48. JP pins are
3V3, GND, SDA, SCL. Each JS port is CIN, driven SHLD1, plate-ground drive,
and a separate plate-ground return. JREF is CIN4, SHLD2, GND, GND.
The driven shields are separate from ground.

The PCB uses 0.20 mm routing clearance, the native MSOP package's explicitly
declared 0.15 mm adjacent-pad clearance, and 0.25 mm via drills. Neither
copper shorts nor missing connections are waived.

Firmware reads three differences against CIN4 and then the reference itself.
It uses paired register reads, explicit single-shot triggers and configuration
checks. Timeouts require restarting the affected converter. Raw values,
timestamps and unavailable readings are retained. The coarse capacitance
plausibility checks do not guarantee detection of every cable fault.
No contact or force value is inferred.

From the complete repository, prepare an isolated recorder environment:

```sh
/usr/bin/python3 -m venv build/engineering/tools/k1-capture-venv
build/engineering/tools/k1-capture-venv/bin/python -m pip install pyserial==3.5
build/engineering/tools/k1-capture-venv/bin/python engineering/software/capacitive_record.py --port PORT --specimen ID --condition CONDITION --seconds 30 --output NEW_FILE.jsonl
```

Complete manufacturing/interfaces and physical calibration before force
feedback. Compare independent specimens for contact misses, false contacts,
force error through 20 N, hysteresis, drift, cable/temperature effects,
loaded motion, wear and precision-task access. No measured winner is claimed.
"""
        (target / "README.md").write_text(readme)
        checkpoint = {"schema": "yam-k1-development-checkpoint/1", "design_id": "CAPACITIVE",
                      "design_label": "K1 capacitive", "design_page": "capacitive.html",
                      "status": "Cell tooling and checked readout; complete finger interfaces and physical testing remain",
                      "created_utc": datetime.now(timezone.utc).isoformat(),
                      "integrated_prototype_complete": False, "physical_specimens_tested": 0,
                      "current_cad_parts": len(selected), "source_fit_pairs": len(saddles["checks"]),
                      "independent_pcb_check": {"passed": True, "violations": 0, "unconnected": 0,
                                                "receipt_sha256": digest(checked / "pcb_checks.json")},
                      "files_sha256": {str(p.relative_to(target)): digest(p) for p in sorted(target.rglob("*")) if p.is_file()}}
        (target / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2)+"\n")
        record["result"] = {"directory": str(target.relative_to(ROOT)), "current_parts": len(selected),
                            "files": len(checkpoint["files_sha256"]),
                            "checkpoint_sha256": digest(target / "checkpoint.json"),
                            "integrated_prototype_complete": False}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
