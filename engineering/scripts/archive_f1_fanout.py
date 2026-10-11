#!/usr/bin/python3
"""Create a clearly limited, downloadable F1 fanout development checkpoint."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


README = """# F1 fanout — development checkpoint

This is the connector board for the proposed 64-location resistive tactile
finger. **It is one part of an unfinished F1 assembly.** The readout board,
installed flex routes, carrier and physical tests remain in development.
It establishes no contact reliability, force accuracy or 20 N rating.

The checked layout contains 42 components, 232 pads and four copper layers.
Independent KiCad 10.0.7 checking found zero rule violations and zero missing
connections. Exact evidence and artifact hashes are in `checkpoint.json`
and `checks/summary.json`.

- `pcb/`: editable native KiCad board, embedded footprints, pin table and geometry manifest.
- `checks/`: full independent DRC report and the board with refilled copper.
- `artwork/`: development Gerbers/drills, including mask, paste and silkscreen for both populated faces.
- `visuals/`: two board faces, native assembly SVGs and a PDF.
- `components.csv`: required values/packages and connector/IC identities. Passive manufacturer part selection is still open.

## Connections

`J0R`–`J5R` accept the six row foils on the outer board face.
`J0C`–`J5C` accept the six column foils on the inner face.
Each uses Hirose FH12-6S-1SH(1)(98), six positions at 1 mm pitch.
The original thin nail and four TPU patch locations are retained in the F1 plan.

`JW` is the Hirose FH12-50S-0.5SH(55) wrist link. Its 50 pin assignments are
explicit in `pcb/f1_fanout_pins.csv`. Four rows and sixteen columns each have
separate current and sense paths. All twenty zero-ohm sense links are fitted:
`RKR0`–`RKR3` and `RKC0`–`RKC15`.

`UT`, ADG706BRUZ, can connect a 10.0 kΩ test resistor from 3.3 V to a selected
column. Its enable and address inputs have 100 kΩ pull-downs. Future firmware
must park all rows at bias before enabling this electrical check and keep its
records separate from tactile observations. This checks the cable/readout
loop at the fanout, not continuity through each flexible sensor foil.

The candidate Molex 0151660545 cable has same-side contacts. Its complete
installed geometry and conductor mapping remain to be verified. Determine
the wrist-board pinout from both connector poses, then check every conductor
with power disconnected. The cable type alone does not establish pin-1-to-pin-1 wiring.

## Recheck the supplied board

From the repository root, prepare the official isolated KiCad tool if needed:

```sh
/usr/bin/python3 engineering/scripts/prepare_b1_eda.py --extract
/usr/bin/python3 engineering/scripts/check_f1_fanout.py engineering/development/f1/fanout/pcb --export
```

Checks and fresh exports go under `build/engineering/prototypes/f1/fanout_checks/`.
The supplied checkpoint is not modified.

To regenerate the geometry and routing, prepare the CAD environment and
original source meshes using `engineering/README.md`, then run:

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/check_f1_placement.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/develop_f1_fanout.py
build/engineering/tools/cad-venv/bin/python engineering/scripts/route_f1_fanout.py ACTUAL_PLACEMENT_RUN
/usr/bin/python3 engineering/scripts/check_f1_fanout.py ACTUAL_ROUTING_RUN/board --export
```

Use the timestamped paths printed by the commands. The placement generator
also writes the reproducible alias selected by the default fanout configuration.
Each stage retains its inputs and failed attempts.

## Before an integrated prototype

The purchasing targets request 1 oz copper on all four layers. Obtain a
supplier-confirmed FR4 stack and verify the stated copper minima; default
0.5 oz inner copper is a different resistance budget. The fine features in
the screened board edge need a manufacturable contour/clearance review with
the carrier. The current drawing follows the sampled contact-access envelope.

Complete the fitted flex tails, conductor-plane unrolls, connector mating
geometry, fasteners, strain relief and actual-drive fit. Check the complete
board/cable/flex resistance network, analog stability, leakage, settling and
current/sense fault behavior. Add the wrist readout, firmware and raw acquisition.
Then fabricate specimens and perform the common contact and 20 N experiments.

The imported KiCad footprint library keeps its attribution and license in
`pcb/F1.pretty/`. Manufacturer documents are linked from the configurations;
their complete datasheets are not redistributed here.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board_directory", type=Path)
    parser.add_argument("checked_directory", type=Path)
    parser.add_argument("visual_directory", type=Path)
    parser.add_argument("--destination", type=Path, default=ROOT / "engineering/development/f1/fanout")
    args = parser.parse_args()
    board, checked, visuals, destination = (p.resolve() for p in (
        args.board_directory, args.checked_directory, args.visual_directory, args.destination))
    if not all(p.is_relative_to(ROOT) for p in (board, checked, visuals, destination)):
        parser.error("Use repository-owned source and destination paths")
    if destination.exists():
        parser.error("Preserve previous checkpoints; select a new destination for a revision")
    summary = json.loads((checked / "summary.json").read_text())
    review = json.loads((visuals / "visual_review.json").read_text())
    if not summary["passed"] or summary["violations"] or summary["unconnected"]:
        raise ValueError("Use a clean independent board check")
    if digest(board / "f1_fanout.kicad_pcb") != summary["source_pcb_sha256"]:
        raise ValueError("Board/check mismatch")
    if digest(board / "f1_fanout.json") != summary["source_manifest_sha256"]:
        raise ValueError("Geometry/check mismatch")
    if digest(checked / "summary.json") != review["independent_check_sha256"]:
        raise ValueError("Visual/check mismatch")
    for filename, expected in summary["development_exports_sha256"].items():
        if digest(checked / "development_files" / filename) != expected:
            raise ValueError(f"Changed development export: {filename}")
    for filename, expected in review["files"].items():
        if digest(visuals / filename) != expected:
            raise ValueError(f"Changed visual: {filename}")
    with execution(ROOT / "build/records", "Archive a checked F1 fanout module as explicit development work, preserving the incomplete integrated-finger status") as record:
        destination.mkdir(parents=True, exist_ok=False)
        pcb = destination / "pcb"
        pcb.mkdir()
        for name in ("f1_fanout.kicad_pcb", "f1_fanout.kicad_dru", "f1_fanout.json",
                     "f1_fanout_pins.csv", "fp-lib-table"):
            shutil.copyfile(board / name, pcb / name)
        # Include the checked copy's license and attribution with the library.
        shutil.copytree(checked / "F1.pretty", pcb / "F1.pretty")
        check_target = destination / "checks"
        check_target.mkdir()
        for name in ("summary.json", "drc.json"):
            shutil.copyfile(checked / name, check_target / name)
        shutil.copyfile(checked / "f1_fanout.kicad_pcb", check_target / "checked_f1_fanout.kicad_pcb")
        shutil.copytree(checked / "development_files", destination / "artwork")
        visual_target = destination / "visuals"
        visual_target.mkdir()
        for path in sorted(visuals.iterdir()):
            if path.is_file():
                shutil.copyfile(path, visual_target / path.name)
        for name in ("outer_assembly.svg", "inner_assembly.svg"):
            shutil.copyfile(checked / name, visual_target / name)
        data = json.loads((board / "f1_fanout.json").read_text())
        with (destination / "components.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["reference", "value_or_part", "pcb_face", "source", "selection_status"])
            for part in data["parts"]:
                writer.writerow([part["reference"], part["value"], part["side"], part.get("source", ""),
                                 "selected development connector/IC" if part.get("source") else "value/package; passive MPN pending"])
        (destination / "README.md").write_text(README)
        checkpoint = {
            "schema": "yam-f1-fanout-development-checkpoint/1",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Checked connector-board development module; integrated F1 incomplete",
            "physical_specimens_tested": 0, "integrated_f1_completed": False,
            "parts": len(data["parts"]), "pads": len(data["pads"]),
            "tracks": len(data["tracks"]), "vias": len(data["vias"]),
            "independent_check": summary,
            "source_locations": {"board": str(board.relative_to(ROOT)), "check": str(checked.relative_to(ROOT)),
                                 "visuals": str(visuals.relative_to(ROOT))},
            "archiver_sha256": digest(Path(__file__)),
            "files_sha256": {str(p.relative_to(destination)): digest(p)
                             for p in sorted(destination.rglob("*")) if p.is_file()}
        }
        (destination / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2)+"\n")
        record["checkpoint"] = {"directory": str(destination.relative_to(ROOT)),
                                "files": len(checkpoint["files_sha256"]),
                                "sha256": digest(destination / "checkpoint.json")}
        print(json.dumps(record["checkpoint"], indent=2))


if __name__ == "__main__":
    main()
