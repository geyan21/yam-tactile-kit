#!/usr/bin/python3
"""Create split K1 cover molds with steel-insert pockets, registration and overflow channels."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/capacitive-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
import numpy as np
from shapely.geometry import Polygon, box
from shapely.ops import nearest_points
from tactile_kit.records import execution
from capacitive_geometry import CONFIG, load, offsets, reference_footprints
from capacitive_cell_geometry import MECHANICS, polygons
from prototype_cad import block, export_part, packed
from check_f1_tail_fit import check_pair
from screen_f1_feedback import digest

TOOL_CONFIG = ROOT / "engineering/designs/capacitive_cover_molds.json"


def volume(shape):
    return 0. if shape.wrapped.IsNull() else shape.Volume()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cell_mechanics", type=Path)
    parser.add_argument("--sites", nargs="+", default=["CH0", "CH1", "CH2", "CH3", "CH4", "CH5", "REF"])
    args = parser.parse_args()
    source = args.cell_mechanics.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/capacitive/cell_mechanics"):
        parser.error("Use a saved K1 mechanical assembly")
    if len(set(args.sites)) != len(args.sites) or set(args.sites)-{"CH0", "CH1", "CH2", "CH3", "CH4", "CH5", "REF"}:
        parser.error("Choose distinct CH0..CH5/REF tooling")
    plan = json.loads((source / "report.json").read_text())
    for name, expected in plan["input_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Mechanical inputs have changed")
    cfg, surfaces = load()
    mech = json.loads(MECHANICS.read_text())
    tool = json.loads(TOOL_CONFIG.read_text())
    by_id = {p["id"]: p for p in plan["parts"]}
    folder = ROOT / "build/engineering/prototypes/capacitive/cover_molds" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Generate K1 split compression-mold tooling around the actual retained plate and vented cover; check connected tool solids, parting and insert/cover exclusions") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = [TOOL_CONFIG, MECHANICS, CONFIG, source / "report.json", Path(__file__)]
        for path in inputs:
            destination = folder / "inputs" / path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, destination)
        parts, models, cases = [], [], []
        record["parts"] = parts
        for cell in plan["cells"]:
            label = cell["site"]
            if label not in args.sites:
                continue
            def saved(role):
                part = by_id["k1_"+label.lower()+"_"+role]
                path = source / part["step"]
                if digest(path) != part["sha256_step"]:
                    raise ValueError("Mechanical part changed")
                return cq.importers.importStep(str(path)).val()
            cover, plate = saved("vented_cover"), saved("retained_plate")
            if label == "REF":
                body, active = reference_footprints(cfg)
                surface = SimpleNamespace(kind="nail", body=body, active=active, origin=np.array([100., 0., 0.]),
                                          u=np.array([1., 0., 0.]), t=np.array([0., -1., 0.]), n=np.array([0., 0., 1.]))
                flex_top = 2*cfg["flex"]["copper_each_mm"]+cfg["flex"]["polyimide_core_mm"]+2*cfg["flex"]["coverlay_each_mm"]
            else:
                surface = surfaces[int(label[2:])]
                body, active = surface.body, surface.active
                flex_top = offsets(surface.site, cfg)["flex_top"]
            plate_domain = Polygon(cell["plate_domain_native_us"])
            outer_foot = body.buffer(-mech["cover"]["foot_outer_inset_mm"], join_style="mitre")
            foot = outer_foot.difference(plate_domain)
            middle = [(active.bounds[i]+active.bounds[i+2])/2 for i in range(2)]
            w = mech["cover"]["vent_slot_mm"]
            cuts = box(middle[0]-w/2, -1000, middle[0]+w/2, 1000).union(box(-1000, middle[1]-w/2, 1000, middle[1]+w/2))
            foot = foot.difference(cuts)
            candidate_gates = []
            level = flex_top+mech["cover"]["foot_bond_mm"]+mech["cover"]["foot_thickness_mm"]/2
            for piece in sorted(polygons(foot), key=lambda p: -p.area):
                interior = piece.representative_point()
                boundary = nearest_points(interior, outer_foot.boundary)[1]
                uv = np.asarray(boundary.coords[0])
                uv_direction = uv-np.asarray(interior.coords[0])
                if np.linalg.norm(uv_direction) < 1e-6:
                    continue
                uv_direction /= np.linalg.norm(uv_direction)
                if surface.kind == "nail":
                    point = surface.origin+uv[0]*surface.u+uv[1]*surface.t+level*surface.n
                    tangent, normal, transverse = surface.t, surface.n, surface.u
                else:
                    base, tangent, normal = surface.frame(uv[1])
                    transverse = np.array([1., 0., 0.])
                    point = base+uv[0]*transverse+level*normal
                direction = uv_direction[0]*transverse+uv_direction[1]*tangent
                direction /= np.linalg.norm(direction)
                origin = point-tool["overflow_overlap_into_foot_mm"]*direction
                plane = cq.Plane(origin=tuple(origin), xDir=tuple(direction), normal=tuple(normal))
                gate = cq.Workplane(plane).box(2*tool["blank_margin_mm"]+10, tool["overflow_width_mm"],
                                              tool["overflow_height_mm"], centered=(False, True, True)).val()
                overlap = volume(gate.intersect(cover))
                if 1e-8 < overlap < .05 and volume(gate.intersect(plate)) < 1e-7:
                    candidate_gates.append({"shape": gate, "point": point.tolist(), "direction": direction.tolist(),
                                            "cover_overlap_mm3": overlap})
            if len(candidate_gates) < 2:
                raise ValueError(label+" needs explicit accessible overflow locations")
            # Select separated foot-level channels. Their small flash roots
            # are outside the active pressure face.
            first, second = max(((a, b) for i, a in enumerate(candidate_gates) for b in candidate_gates[i+1:]),
                                key=lambda pair: np.linalg.norm(np.asarray(pair[0]["point"])-pair[1]["point"]))
            gates = [first, second]
            bounds = cover.BoundingBox(); margin = tool["blank_margin_mm"]
            x0, x1 = bounds.xmin-margin, bounds.xmax+margin
            y0, y1 = bounds.ymin-margin, bounds.ymax+margin
            z0, z1 = bounds.zmin-margin, bounds.zmax+margin
            split = (bounds.xmin+bounds.xmax)/2
            cavity = block(x0, x1, y0, y1, z0, z1).cut(cover).cut(plate)
            for gate in gates:
                cavity = cavity.cut(gate["shape"])
            bolts = [(y, z) for y in (bounds.ymin-tool["bolt_offset_from_cavity_bounds_mm"], bounds.ymax+tool["bolt_offset_from_cavity_bounds_mm"])
                     for z in (bounds.zmin-tool["bolt_offset_from_cavity_bounds_mm"], bounds.zmax+tool["bolt_offset_from_cavity_bounds_mm"])]
            dowels = [(y, (bounds.zmin+bounds.zmax)/2) for y in
                      (bounds.ymin-tool["dowel_offset_from_cavity_bounds_mm"], bounds.ymax+tool["dowel_offset_from_cavity_bounds_mm"])]
            for y, z in bolts:
                cavity = cavity.cut(cq.Solid.makeCylinder(tool["bolt_clearance_mm"]/2, x1-x0+2,
                                                         cq.Vector(x0-1, y, z), cq.Vector(1, 0, 0)))
            for y, z in dowels:
                depth = tool["dowel_embed_each_half_mm"]
                cavity = cavity.cut(cq.Solid.makeCylinder(tool["dowel_bore_mm"]/2, 2*depth,
                                                         cq.Vector(split-depth, y, z), cq.Vector(1, 0, 0)))
            left = cavity.intersect(block(x0-1, split, y0-1, y1+1, z0-1, z1+1)).clean()
            right = cavity.intersect(block(split, x1+1, y0-1, y1+1, z0-1, z1+1)).clean()
            checks = [check_pair("left_mold", left, "right_mold", right)]
            for name, solid in (("left_mold", left), ("right_mold", right)):
                for other, part in (("cover", cover), ("steel_insert", plate)):
                    checks.append(check_pair(name, solid, other, part))
            if not all(c["passed"] for c in checks):
                raise ValueError("Mold cavity intersection at "+label)
            for suffix, shape in (("a", left), ("b", right)):
                name = "k1_"+label.lower()+"_cover_mold_"+suffix
                mesh = export_part(shape, name, folder, parts, label+" split cover mold with insert pocket and registration",
                                   tool["tool_material"], "fabricate_tool")
                models.append(packed(mesh, name, label, "#789ca2" if suffix == "a" else "#a5bcb1"))
            cases.append({"site": label, "checks": checks, "parting_native_x_mm": split,
                          "bolt_centres_native_yz_mm": bolts, "dowel_centres_native_yz_mm": dowels,
                          "suggested_m3_length_mm_min": math.ceil((x1-x0+5)/5)*5,
                          "dowels": "Two 3 mm × 8 mm smooth pins; finish and measure the bores for the actual fit",
                          "overflow_channels": [{k: v for k, v in gate.items() if k != "shape"} for gate in gates]})
            (folder / "partial.json").write_text(json.dumps({"parts": parts, "cases": cases}, indent=2)+"\n")
            print(label+": two registered mold halves exported", flush=True)
        report = {"schema": "yam-k1-cover-molds/1", "physical_specimens_tested": 0, "parts": parts, "cases": cases,
                  "source_mechanics_sha256": digest(source / "report.json"),
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "limits": tool["limits"], "process": tool["process"]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "mold_halves": len(parts), "cells": len(cases)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
