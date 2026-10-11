#!/usr/bin/python3
"""Report the actual nail-tail join geometry before forming it."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("foil_run", type=Path)
    args = parser.parse_args()
    source = args.foil_run.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/capacitive/foil_runs"):
        parser.error("Select an owned foil geometry run")
    folder = source / "tail_section_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Inspect only the two saved K1 nail-tail joins and their rectangle deviations; preserve original fabrication geometry") as record:
        folder.mkdir(parents=True, exist_ok=False)
        rows = []
        for site in (0, 1):
            path = source / f"k1_ch{site}_flex.json"
            data = json.loads(path.read_text())
            polygon = Polygon(data["outline_flat_mm"])
            join = data["tail"]["origin_flat_mm"][1]
            section = polygon.intersection(box(-100, join, 100, 1000))
            components = [section] if section.geom_type == "Polygon" else list(section.geoms)
            tail = unary_union([p for p in components if p.geom_type == "Polygon" and p.area > 0])
            expected = box(*tail.bounds)
            rows.append({"site": site, "geometry_sha256": digest(path), "join_mm": join,
                         "tail_bounds": list(tail.bounds), "symmetric_difference_area_mm2": tail.symmetric_difference(expected).area,
                         "tail_vertices": list(tail.exterior.coords),
                         "section_components": [{"kind": p.geom_type, "area_mm2": p.area} for p in components],
                         "rectangle_deviation_mm": tail.hausdorff_distance(expected)})
        (folder / "report.json").write_text(json.dumps(rows, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "rows": rows}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
