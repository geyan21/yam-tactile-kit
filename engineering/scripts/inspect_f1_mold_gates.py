#!/usr/bin/python3
"""Inspect peripheral gate intersections in a saved F1 skin without changing that skin."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/f1-cad-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
import numpy as np
from shapely.geometry import LineString, Polygon
from tactile_kit.records import execution
from f1_surfaces import load_surfaces
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skin", type=Path)
    parser.add_argument("--site", type=int, default=2)
    args = parser.parse_args()
    source = args.skin.resolve(); plan = json.loads((source / "report.json").read_text())
    skin_path = ROOT / "engineering/designs/f1_skin_r4.json"
    tool_path = ROOT / "engineering/designs/f1_skin_molds_r4.json"
    skin = json.loads(skin_path.read_text()); tool = json.loads(tool_path.read_text())
    _, _, _, surfaces = load_surfaces(ROOT / skin["basis_stack"])
    surface = surfaces[args.site]
    case = next(c for c in plan["cases"] if c["site"] == args.site)
    part = next(p for p in plan["parts"] if p["id"] == f"f1_ch{args.site}_retained_cover")
    shape_path = source / part["step"]
    if digest(shape_path) != part["sha256_step"]:
        raise ValueError("Saved cover changed")
    target = cq.importers.importStep(str(shape_path)).val()
    folder = source / "gate_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Read-only geometric probe of the failing F1 cover gate: compare tangent-box intersections at peripheral heights and source-arc locations") as record:
        folder.mkdir(parents=True)
        domain = Polygon(case["cover_domain_native_us"])
        bb = target.BoundingBox(); results = []
        for fraction in (.35, .5, .65):
            s = surface.body.bounds[1]+fraction*(surface.body.bounds[3]-surface.body.bounds[1])
            line = domain.intersection(LineString([(-1000, s), (1000, s)]))
            left, _, right, _ = line.bounds
            _, _, normal = surface.frame(s)
            transverse = surface.u if surface.kind == "nail" else np.array([1., 0., 0.])
            for above in (.06, .12, .20):
                level = case["foot_bond_top_mm"]+above
                for u, sign in ((left, -1), (right, 1)):
                    point = surface.points(u, s, level); direction = sign*transverse
                    plane = cq.Plane(origin=tuple(point-tool["overflow_overlap_mm"]*direction),
                                     xDir=tuple(direction), normal=tuple(normal))
                    gate = cq.Workplane(plane).box(bb.xlen+2*tool["blank_margin_mm"]+10,
                                                  tool["overflow_width_mm"], tool["overflow_height_mm"],
                                                  centered=(False, True, True)).val()
                    common = gate.intersect(target)
                    volume = 0. if common.wrapped.IsNull() else common.Volume()
                    results.append({"arc_fraction": fraction, "above_foot_mm": above, "side": sign,
                                    "point_native_mm": point.tolist(), "overlap_mm3": volume,
                                    "minimum_distance_mm": gate.distance(target)})
        inputs = [skin_path, tool_path, shape_path, source / "report.json", Path(__file__)]
        report = {"cover": part["id"], "physical_specimens_tested": 0,
                  "cover_bounds_mm": [[bb.xmin, bb.ymin, bb.zmin], [bb.xmax, bb.ymax, bb.zmax]],
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs}, "results": results}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "results": results}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
