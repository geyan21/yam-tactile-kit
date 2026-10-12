#!/usr/bin/python3
"""Build actual F1 terminal backing pieces and corrected connector-end envelopes."""

import argparse
import copy
from datetime import datetime, timezone
import json
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
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union
from tactile_kit.records import execution
from prototype_cad import yz_prism, export_part, packed
from screen_f1_feedback import digest

MECHANICS = ROOT / "engineering/designs/f1_terminal_mechanics_r4.json"
SOURCE = ROOT / "engineering/development/f1/r3"


def native_polygon(shape, basis):
    shape = affinity.rotate(shape, -basis["fabrication_rotation_deg"], origin=(0, 0))
    shape = affinity.scale(shape, xfact=basis["fabrication_x_mirror"], yfact=1, origin=(0, 0))
    a, b, c, d, tx, ty = basis["native_yz_to_unfolded_tail_affine"]
    inverse = np.linalg.inv(np.array([[a, b], [c, d]]))
    shift = -inverse @ np.array([tx, ty])
    return affinity.affine_transform(shape, [*inverse[0], *inverse[1], *shift])


def write_cut(path, polygons):
    x0 = min(p.bounds[0] for p in polygons); y0 = min(p.bounds[1] for p in polygons)
    x1 = max(p.bounds[2] for p in polygons); y1 = max(p.bounds[3] for p in polygons)
    text = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{x1-x0+4:.5f}mm" height="{y1-y0+4:.5f}mm" viewBox="0 0 {x1-x0+4:.5f} {y1-y0+4:.5f}">',
            '<title>F1 terminal reinforcement cutting pattern, millimetres</title><g fill="none" stroke="black" stroke-width=".025">']
    for polygon in polygons:
        points = " ".join(f"{x-x0+2:.8f},{y-y0+2:.8f}" for x, y in polygon.exterior.coords)
        text.append(f'<polygon points="{points}"/>')
    text.append("</g></svg>")
    path.write_text("\n".join(text)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artwork", type=Path)
    parser.add_argument("tip_review", type=Path)
    args = parser.parse_args()
    artwork = args.artwork.resolve(); reviews = args.tip_review.resolve()
    plan = json.loads((artwork / "artwork.json").read_text())
    tip_review = json.loads((reviews / "report.json").read_text())
    config = json.loads(MECHANICS.read_text())
    tip_path = ROOT / config["tip_plan"]; tip = json.loads(tip_path.read_text())
    if not tip_review["proposed_contract_checks_pass"]:
        raise ValueError("Unresolved terminal proposal")
    for name, expected in plan["source_hashes"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Artwork inputs changed")
    receipt = json.loads((artwork / "latest_independent_check.json").read_text())
    if not receipt["all_passed"]:
        raise ValueError("Use checked R4 artwork")
    fit = json.loads((SOURCE / "checks/fit_patterns.json").read_text())
    routes = json.loads((SOURCE / "checks/tail_routes.json").read_text())["routes"]
    by_part = {p["id"]: p for p in fit["parts"]}
    by_route = {(row["site"], row["role"]): row for row in routes}
    by_contract = {row["foil"]: row for row in tip_review["cases"]}
    folder = ROOT / "build/engineering/prototypes/f1/finished_terminal_cad" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Build nominal F1 plated-contact envelopes, real PI/adhesive pieces and cutting patterns; keep the undimensioned connector cavity outside the claimed checks") as record:
        folder.mkdir(parents=True); (folder / "patterns").mkdir()
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [MECHANICS, tip_path, artwork / "artwork.json", reviews / "report.json",
                  SOURCE / "checks/fit_patterns.json", SOURCE / "checks/tail_routes.json", Path(__file__)]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        parts, models, cases = [], [], []
        for entry in plan["boards"]:
            name = entry["name"]; meta = entry["metadata"]; basis = meta["basis"]
            site = int(meta["site"][2:]); role = meta["role"]; contract = by_contract[name]
            route = by_route[(site, role)]
            old_part = by_part[name+"_fit_tail_reference"]
            old_path = SOURCE / old_part["step"]
            if digest(old_path) != old_part["sha256_step"]:
                raise ValueError("R3 tail reference changed")
            shape = cq.importers.importStep(str(old_path)).val()
            data_path = artwork / name / (name+".json"); data = json.loads(data_path.read_text())
            x0, y0, x1, y1 = contract["stiffener_bounds_mm"]
            tip_y = contract["terminal_tip_flat_mm"][1]; direction = contract["tip_inward_y_sign"]
            plane_x = route["nominal_plane_native_x_mm"]
            def region(start, end):
                a, b = tip_y+direction*start, tip_y+direction*end
                return box(x0, min(a, b), x1, max(a, b))
            def slab(polygon, low, high):
                return yz_prism(native_polygon(polygon, basis), plane_x+low, high-low)
            # The existing tail reference is uniformly covered. Remove that
            # conservative cover envelope only at the actual contact face,
            # leaving room for the explicit nickel/gold finish.
            finish = tip["nickel_nominal_mm"]+tip["gold_minimum_mm"]
            front = region(0, 6.5)
            row = role == "rows"
            if row:
                shape = shape.cut(slab(front, -.2, -.0175-finish))
            else:
                shape = shape.cut(slab(front, .0175+finish, .2))
            two_layer = data["physical_layers"] == 2
            relief = region(0, tip["back_coverlay_relief_from_tip_mm"])
            if two_layer:
                shape = shape.cut(slab(relief, .0425, .3))
            mesh = export_part(shape.clean(), name+"_finished_tail", folder, parts,
                               "Nominal connector-end material envelope, corrected for exposed contacts and rear relief",
                               "Layer envelope only; order the matching physical FPC", "reference_only")
            models.append(packed(mesh, name+"_finished_tail", "f1_tails", "#7194a6"))
            if two_layer:
                cut_regions = [
                    ("tip", relief, .0425),
                    ("transition", region(tip["back_coverlay_relief_from_tip_mm"]+config["nail_reinforcement_gap_mm"], 8), .1275)]
            else:
                cut_regions = [("full", region(0, 8), .0425 if row else -.0425)]
            support = unary_union([piece[1] for piece in cut_regions])
            via_support = []
            for via in data["plated_connections"]:
                if not via["name"].startswith("VTAIL"):
                    continue
                copper = Point(via["center"]).buffer(via["pad_mm"]/2, quad_segs=64)
                if copper.difference(support).area > 1e-7:
                    raise ValueError(name+": a terminal via leaves its static reinforcement")
                via_support.append({"via": via["name"], "copper_edge_to_support_edge_mm": support.boundary.distance(copper)})
            for label, domain, base in cut_regions:
                sign = 1 if row else -1
                adhesive_end = base+sign*config["adhesive_nominal_mm"]
                outer = adhesive_end+sign*config["stiffener_nominal_mm"]
                for suffix, a, b, kind, material in (
                        ("bond", base, adhesive_end, "reference_only", "50 µm qualified FPC stiffener bond"),
                        ("pi", adhesive_end, outer, "cut_film", "0.20 mm polyimide reinforcement")):
                    identifier = name+"_"+label+"_stiffener_"+suffix
                    mesh = export_part(slab(domain, min(a, b), max(a, b)), identifier, folder, parts,
                                       "Static terminal reinforcement; keep the transition region strain-relieved",
                                       material, kind)
                    models.append(packed(mesh, identifier, "f1_stiffeners", "#bfa777" if suffix == "bond" else "#817d9e"))
            write_cut(folder / "patterns" / (name+"_stiffener_cut.svg"), [piece[1] for piece in cut_regions])
            cases.append({"foil": name, "connector": meta["connector"], "site": site, "role": role,
                          "nominal_conductor_plane_native_x_mm": plane_x,
                          "nominal_contact_tongue_thickness_mm": contract["proposed_tip_nominal_mm"],
                          "reinforcement_piece_count": len(cut_regions),
                          "terminal_via_support": via_support,
                          "nominal_supported_region_length_mm": 8.,
                          "connector_cavity_qualified": False})
            (folder / "partial.json").write_text(json.dumps({"parts": parts, "cases": cases}, indent=2)+"\n")
            print(name+": corrected material envelope and "+str(len(cut_regions))+" PI pieces", flush=True)
        report = {"schema": "yam-f1-finished-terminals/1", "physical_specimens_tested": 0,
                  "parts": parts, "cases": cases, "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "limits": config["limits"]+["These parts still require source/peer and complete entry-lane checks.",
                                           "Active sensing-body plating, sealing and dynamic slack are separate integration work."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "foils": len(cases)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
