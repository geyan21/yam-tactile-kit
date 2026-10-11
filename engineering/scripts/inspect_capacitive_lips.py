#!/usr/bin/python3
"""Review K1 lip domains and rectangular-strip approximation before CAD export."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/capacitive-cad-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))

from shapely.geometry import box
from shapely.ops import unary_union
from tactile_kit.records import execution
from capacitive_geometry import load, offsets, unrolled, inverse_unrolled
from capacitive_cell_geometry import MECHANICS, polygons, rectangular_strips, remove_duplicate_vertices


def main():
    cfg, surfaces = load()
    mechanics = json.loads(MECHANICS.read_text())
    stop, cover, plate_cfg = (mechanics[key] for key in ("stop", "cover", "plate"))
    folder = ROOT / "build/engineering/prototypes/capacitive/lip_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Read-only K1 lip chart review: measure strip reconstruction error to locate the CAD failure") as record:
        folder.mkdir(parents=True)
        rows = []
        for surface in surfaces:
            if surface.kind == "nail":
                continue
            body, active = surface.body, surface.active
            neutral = offsets(surface.site, cfg)["flex_top"]+stop["adhesive_nominal_mm"]+stop["film_nominal_mm"]/2
            ring = unrolled(body, surface, neutral).buffer(-stop["outer_inset_mm"], join_style="mitre").difference(
                unrolled(active, surface, neutral).buffer(stop["active_clearance_mm"], join_style="mitre"))
            ring = inverse_unrolled(ring, surface, neutral)
            u, s = active.centroid.coords[0]
            half = stop["vent_slot_mm"]/2
            cross = box(u-half, -1000, u+half, 1000).union(box(-1000, s-half, 1000, s+half))
            pieces = polygons(ring.difference(cross))
            plate = body.buffer(-plate_cfg["edge_inset_mm"], join_style="mitre")
            original = plate.difference(plate.buffer(-cover["under_plate_lip_mm"], join_style="mitre"))
            forbidden = unary_union(pieces).buffer(cover["lip_stop_clearance_mm"], join_style="mitre")
            raw = original.difference(forbidden) if original.intersection(forbidden).area > 1e-8 else original
            cleaned = remove_duplicate_vertices(raw)
            for index, polygon in enumerate(polygons(cleaned)):
                rectangles = rectangular_strips(polygon)
                error = polygon.symmetric_difference(unary_union(rectangles))
                rows.append({"site": surface.site, "piece": index, "area_mm2": polygon.area,
                             "reconstruction_error_mm2": error.area, "error_wkt": error.wkt,
                             "domain_wkt": polygon.wkt})
        (folder / "report.json").write_text(json.dumps(rows, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)),
                            "reviews": [{k: v for k, v in row.items() if not k.endswith("wkt")} for row in rows]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
