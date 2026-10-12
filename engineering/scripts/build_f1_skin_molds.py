#!/usr/bin/python3
"""Create registered split molds for F1 retained covers and compliant fitting bases."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
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
from prototype_cad import export_part, packed, block
from check_f1_tail_fit import check_pair
from screen_f1_feedback import digest

CONFIG = ROOT / "engineering/designs/f1_skin_molds_r4.json"
SKIN = ROOT / "engineering/designs/f1_skin_r4.json"


def volume(shape):
    return 0. if shape.wrapped.IsNull() else shape.Volume()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skin_run", type=Path)
    parser.add_argument("--sites", nargs="+", type=int, default=list(range(6)))
    args = parser.parse_args()
    source = args.skin_run.resolve(); plan = json.loads((source / "report.json").read_text())
    for name, expected in plan["input_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Skin geometry inputs changed")
    if len(set(args.sites)) != len(args.sites) or set(args.sites)-set(range(6)):
        parser.error("Choose distinct sites 0..5")
    tool = json.loads(CONFIG.read_text()); skin = json.loads(SKIN.read_text())
    _, _, _, surfaces = load_surfaces(ROOT / skin["basis_stack"])
    cases_by_site = {row["site"]: row for row in plan["cases"]}
    selected = [p for p in plan["parts"] if p["id"].endswith(("_retained_cover", "_compliant_fit_base"))
                and int(p["id"].split("_")[1][2:]) in args.sites]
    folder = ROOT / "build/engineering/prototypes/f1/skin_molds" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Create split compression molds for the actual F1 cover/base CAD, including registration, fasteners, side overflow and cavity exclusions") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [CONFIG, SKIN, source / "report.json", Path(__file__)]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        parts, models, molds = [], [], []
        for part in selected:
            path = source / part["step"]
            if digest(path) != part["sha256_step"]:
                raise ValueError("Skin part changed")
            target = cq.importers.importStep(str(path)).val()
            site = int(part["id"].split("_")[1][2:]); case = cases_by_site[site]; surface = surfaces[site]
            domain = Polygon(case["cover_domain_native_us"])
            mid_s = (surface.body.bounds[1]+surface.body.bounds[3])/2
            line = domain.intersection(LineString([(-1000, mid_s), (1000, mid_s)]))
            lo_u, _, hi_u, _ = line.bounds
            is_cover = part["id"].endswith("_retained_cover")
            level = case["foot_bond_top_mm"]+.06 if is_cover else case["base_upper_datum_mm"]-.04
            _, tangent, normal = surface.frame(mid_s)
            transverse = surface.u if surface.kind == "nail" else np.array([1., 0., 0.])
            bb = target.BoundingBox(); margin = tool["blank_margin_mm"]
            x0, x1 = bb.xmin-margin, bb.xmax+margin
            y0, y1 = bb.ymin-margin, bb.ymax+margin
            z0, z1 = bb.zmin-margin, bb.zmax+margin
            split = (bb.xmin+bb.xmax)/2
            blank = block(x0, x1, y0, y1, z0, z1)
            cavity = blank.cut(target)
            gates = []
            for u, sign in ((lo_u, -1), (hi_u, 1)):
                point = surface.points(u, mid_s, level)
                direction = sign*transverse
                plane = cq.Plane(origin=tuple(point-tool["overflow_overlap_mm"]*direction),
                                 xDir=tuple(direction), normal=tuple(normal))
                gate = cq.Workplane(plane).box(x1-x0+10, tool["overflow_width_mm"], tool["overflow_height_mm"],
                                              centered=(False, True, True)).val()
                overlap = volume(gate.intersect(target))
                if not 1e-7 < overlap < .1:
                    raise ValueError(part["id"]+": side overflow does not meet a small peripheral material region")
                cavity = cavity.cut(gate)
                gates.append({"point_native_mm": point.tolist(), "direction": direction.tolist(),
                               "target_overlap_mm3": overlap})
            bolts = [(y, z) for y in (bb.ymin-tool["bolt_offset_mm"], bb.ymax+tool["bolt_offset_mm"])
                     for z in (bb.zmin-tool["bolt_offset_mm"], bb.zmax+tool["bolt_offset_mm"])]
            dowels = [(y, (bb.zmin+bb.zmax)/2) for y in
                      (bb.ymin-tool["dowel_offset_mm"], bb.ymax+tool["dowel_offset_mm"])]
            for y, z in bolts:
                cavity = cavity.cut(cq.Solid.makeCylinder(tool["bolt_diameter_mm"]/2, x1-x0+2,
                                                         cq.Vector(x0-1, y, z), cq.Vector(1, 0, 0)))
            for y, z in dowels:
                depth = tool["dowel_embed_each_half_mm"]
                cavity = cavity.cut(cq.Solid.makeCylinder(tool["dowel_diameter_mm"]/2, depth*2,
                                                         cq.Vector(split-depth, y, z), cq.Vector(1, 0, 0)))
            left = cavity.intersect(block(x0-1, split, y0-1, y1+1, z0-1, z1+1)).clean()
            right = cavity.intersect(block(split, x1+1, y0-1, y1+1, z0-1, z1+1)).clean()
            checks = [check_pair("mold_a", left, "mold_b", right),
                      check_pair("mold_a", left, part["id"], target),
                      check_pair("mold_b", right, part["id"], target)]
            if not all(row["passed"] for row in checks):
                raise ValueError("Tool cavity overlap for "+part["id"])
            for side, shape in (("a", left), ("b", right)):
                identifier = part["id"]+"_mold_"+side
                display = export_part(shape, identifier, folder, parts,
                                      "Registered split mold with two side overflow paths", tool["tool_material"], "fabricate_tool")
                models.append(packed(display, identifier, "f1_molds", "#8ca49d"))
            molds.append({"part": part["id"], "checks": checks, "split_native_x_mm": split,
                          "bolts_native_yz_mm": bolts, "dowels_native_yz_mm": dowels,
                          "suggested_m3_length_mm_min": math.ceil((x1-x0+5)/5)*5, "overflow": gates})
            (folder / "partial.json").write_text(json.dumps({"parts": parts, "molds": molds}, indent=2)+"\n")
            print(part["id"]+": two registered mold halves exported", flush=True)
        report = {"schema": "yam-f1-skin-molds/1", "physical_specimens_tested": 0, "parts": parts, "molds": molds,
                  "source_skin_sha256": digest(source / "report.json"),
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "process": tool["process"], "limits": tool["limits"]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "molds": len(molds), "halves": len(parts)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
