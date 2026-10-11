#!/usr/bin/python3
"""Read only the native F1 wrist courtyards implicated by a saved DRC report."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_wrist_native import pcb, mm, digest


def courtyard_bounds(footprint):
    bounds = []
    for item in footprint.GraphicalItems():
        if item.GetLayer() not in (pcb.F_CrtYd, pcb.B_CrtYd):
            continue
        box = item.GetBoundingBox()
        p, size = mm(box.GetPosition()), mm(box.GetSize())
        bounds.append([p[0], p[1], p[0]+size[0], p[1]+size[1]])
    if not bounds:
        return None
    return [min(b[0] for b in bounds), min(b[1] for b in bounds),
            max(b[2] for b in bounds), max(b[3] for b in bounds)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path)
    parser.add_argument("references", nargs="+")
    args = parser.parse_args()
    source = args.board.resolve()
    if not source.is_relative_to(ROOT):
        parser.error("Use a repository-owned native board")
    folder = ROOT / "build/engineering/prototypes/f1/courtyard_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Measure the named F1 footprint courtyards to resolve saved assembly-spacing findings; no board changes") as record:
        folder.mkdir(parents=True, exist_ok=False)
        board = pcb.LoadBoard(str(source))
        rows = []
        for part in board.GetFootprints():
            if part.GetReference() not in args.references:
                continue
            rows.append({"reference": part.GetReference(), "position_mm": mm(part.GetPosition()),
                         "rotation_deg": part.GetOrientationDegrees(),
                         "courtyard_bbox_mm_including_stroke": courtyard_bounds(part)})
        if {row["reference"] for row in rows} != set(args.references):
            raise ValueError("Missing requested footprint")
        report = {"source_sha256": digest(source), "results": sorted(rows, key=lambda r: r["reference"]),
                  "note": "Axis-aligned bounds include the courtyard line stroke; use as a conservative spacing guide."}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = report
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), **report}, indent=2))


if __name__ == "__main__":
    main()
