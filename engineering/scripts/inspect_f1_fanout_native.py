#!/usr/bin/python3
"""Read actual native fanout courtyards and the test-mux supply interfaces."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_native_pcb import pcb, digest, mm


def courtyards(board):
    result = []
    for part in board.GetFootprints():
        boxes = []
        for item in part.GraphicalItems():
            if item.GetLayer() not in (pcb.F_CrtYd, pcb.B_CrtYd):
                continue
            bounds = item.GetBoundingBox()
            p, size = mm(bounds.GetPosition()), mm(bounds.GetSize())
            half = pcb.ToMM(item.GetWidth())/2
            boxes.append([p[0]+half, p[1]+half,
                          p[0]+size[0]-half, p[1]+size[1]-half])
        if boxes:
            result.append({"reference": part.GetReference(), "side": "B" if part.IsFlipped() else "F",
                           "bounds_mm": [min(b[0] for b in boxes), min(b[1] for b in boxes),
                                         max(b[2] for b in boxes), max(b[3] for b in boxes)],
                           "line_stroke_excluded": True})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path)
    args = parser.parse_args()
    source = args.board.resolve()
    if not source.is_relative_to(ROOT):
        parser.error("Use a repository-owned board")
    folder = ROOT / "build/engineering/prototypes/f1/native_interface_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Read native assembly envelopes and mux/capacitor pad coordinates for the rejected F1 fanout; no geometry or process state is changed") as record:
        folder.mkdir(parents=True, exist_ok=False)
        board = pcb.LoadBoard(str(source))
        courts = courtyards(board)
        pads = []
        for footprint in board.GetFootprints():
            if footprint.GetReference() not in ("UT", "CT1", "CT2", "RT"):
                continue
            for pad in footprint.Pads():
                pads.append({"reference": footprint.GetReference(), "pad": pad.GetNumber(),
                             "net": pad.GetNetname(), "center_mm": mm(pad.GetPosition()),
                             "size_mm": mm(pad.GetSize())})
        report = {"source_pcb_sha256": digest(source), "kicad": pcb.GetBuildVersion(),
                  "courtyards": courts, "interface_pads": pads}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)),
                            "critical_courtyards": [p for p in courts if p["reference"] in
                                                     ("UT", "J2R", "J3R", "J4R", "J5R", "CT1", "CT2", "RT")],
                            "supply_pads": [p for p in pads if p["reference"] != "UT" or p["net"] in ("+3V3", "GND", "TEST_D")]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
