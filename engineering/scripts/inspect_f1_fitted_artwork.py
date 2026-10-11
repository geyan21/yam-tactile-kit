#!/usr/bin/python3
"""Locate fitted-foil clearance findings in the saved fabrication coordinates."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from shapely.geometry import Polygon
from shapely.ops import nearest_points

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def location(a, b):
    return {"distance_mm": a.distance(b),
            "points_mm": [list(p.coords)[0] for p in nearest_points(a, b)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artwork", type=Path)
    args = parser.parse_args()
    source = args.artwork.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/f1/artwork_runs"):
        parser.error("Use a preserved fitted-artwork run")
    plan_path = source / "artwork.json"
    plan = json.loads(plan_path.read_text())
    output = source / "geometry_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Locate copper-to-cut and between-net findings in saved F1 foil geometry without changing its source") as record:
        output.mkdir(parents=True, exist_ok=False)
        results = []
        for entry in plan["boards"]:
            data = json.loads((ROOT / entry["directory"] / (entry["name"]+".json")).read_text())
            basis = entry["metadata"]["basis"]
            cuts = entry["metadata"].get("outline_cleanup", {}).get("generated_inner_cuts_mm",
                                                                   basis["inner_cuts_flat_mm"])
            outline = Polygon(data["outline_mm"], cuts)
            regions = {r["name"]: Polygon(r["outline_mm"]) for r in data["regions"]}
            edges = [{"name": name, **location(shape, outline.boundary)}
                     for name, shape in regions.items()]
            close = []
            for item in data["geometry_checks"]["closest_pairs"]:
                if item["a"] in regions and item["b"] in regions:
                    close.append({"a": item["a"], "b": item["b"],
                                  **location(regions[item["a"]], regions[item["b"]])})
            result = {"name": entry["name"],
                      "edges": sorted(edges, key=lambda r: r["distance_mm"])[:4],
                      "between_nets": close[:4]}
            results.append(result)
        report = {"artwork_sha256": digest(plan_path), "boards": results}
        (output / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(output.relative_to(ROOT)), "boards": len(results)}
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
