#!/usr/bin/python3
"""Native writer for the F1 mating-layout revision; preserve the prior generator."""

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_native_pcb import build, pcb, vector, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specification", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--routing", type=Path)
    args = parser.parse_args()
    specification, destination = args.specification.resolve(), args.destination.resolve()
    if not all(path.is_relative_to(ROOT) for path in (specification, destination)):
        parser.error("Use repository-owned input/output paths")
    with execution(ROOT / "build/records", "Write the revised F1 connector poses with the preserved native pad-transform checks") as record:
        spec = json.loads(specification.read_text())
        route = json.loads(args.routing.read_text()) if args.routing else None
        result = build(spec, destination, route)
        path = destination / (spec["name"]+".kicad_pcb")
        board = pcb.LoadBoard(str(path))
        for item in board.GetDrawings():
            if isinstance(item, pcb.PCB_TEXT) and item.GetText() == "F1 FANOUT":
                item.SetText("F1 FA2")
                item.SetPosition(vector([44, 1.2]))
        pcb.SaveBoard(str(path), board)
        result["pcb_sha256"] = digest(path)
        result["revision_writer_sha256"] = digest(Path(__file__))
        result["status"] = "Revised mating poses; independent DRC and installed-tail checks required"
        (destination / (spec["name"]+".json")).write_text(json.dumps(result, indent=2)+"\n")
        snapshot = destination / "generation_inputs"; snapshot.mkdir()
        for source in (specification, Path(__file__), ROOT / "engineering/scripts/f1_native_pcb.py"):
            shutil.copyfile(source, snapshot / source.name)
        if args.routing:
            shutil.copyfile(args.routing, snapshot / "routing.json")
        record["result"] = {"directory": str(destination.relative_to(ROOT)), "pads": len(result["pads"]),
                            "pcb_sha256": result["pcb_sha256"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
