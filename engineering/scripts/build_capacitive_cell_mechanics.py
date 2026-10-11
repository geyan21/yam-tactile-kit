#!/usr/bin/python3
"""Build K1 vented stop pieces, retained plates and silicone-cover geometry."""

from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/capacitive-cad-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
import numpy as np
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from tactile_kit.records import execution
from capacitive_geometry import CONFIG, load, offsets, unrolled, inverse_unrolled, reference_footprints
from capacitive_cell_geometry import MECHANICS, polygons, common_samples, shape_for, remove_duplicate_vertices
from prototype_cad import export_part, packed
from screen_f1_feedback import digest


def cut_svg(path, pieces, caption):
    bounds = unary_union(pieces).bounds
    x0, y0, x1, y1 = bounds
    width, height = x1-x0+6, y1-y0+6
    from xml.sax.saxutils import escape
    text = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.3f}mm" height="{height:.3f}mm" viewBox="0 0 {width:.3f} {height:.3f}">',
            f'<title>{escape(caption)}</title><g fill="none" stroke="#000" stroke-width=".025">']
    for piece in pieces:
        for ring in (piece.exterior, *piece.interiors):
            points = " ".join(f"{x-x0+3:.6f},{y-y0+3:.6f}" for x, y in ring.coords)
            text.append(f'<polygon points="{points}"/>')
    text.append("</g></svg>")
    path.write_text("\n".join(text)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", nargs="+", help="Build only named cells (CH0..CH5 or REF).")
    args = parser.parse_args()
    cfg, surfaces = load()
    mechanics = json.loads(MECHANICS.read_text())
    stop, cover, plate_cfg, bond = (mechanics[key] for key in ("stop", "cover", "plate", "plate_ground_bonds"))
    folder = ROOT / "build/engineering/prototypes/capacitive/cell_mechanics" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Build K1 bonded stop quadrants, plate-retaining silicone covers with open vents and two separate ground-bond access ports; preserve geometry as an unqualified assembly proposal") as record:
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "patterns").mkdir()
        inputs = [CONFIG, MECHANICS, Path(__file__), ROOT / "engineering/scripts/capacitive_geometry.py",
                  ROOT / "engineering/scripts/capacitive_cell_geometry.py",
                  ROOT / "engineering/scripts/f1_surfaces.py", ROOT / "engineering/scripts/prototype_cad.py"]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        parts, models, cells = [], [], []
        record["parts"] = parts
        ref_body, ref_active = reference_footprints(cfg)
        reference = SimpleNamespace(kind="nail", site=6, body=ref_body, active=ref_active, length=ref_body.bounds[3],
                                    s=np.linspace(0, ref_body.bounds[3], 100),
                                    origin=np.array([100., 0., 0.]), u=np.array([1., 0., 0.]),
                                    t=np.array([0., -1., 0.]), n=np.array([0., 0., 1.]))
        jobs = [(f"CH{s.site}", s, False) for s in surfaces]+[("REF", reference, True)]
        if args.sites:
            if set(args.sites)-{label for label, _, _ in jobs}:
                raise ValueError("Unknown cell in --sites")
            jobs = [job for job in jobs if job[0] in args.sites]
        for label, surface, is_reference in jobs:
            if is_reference:
                flex_top = 2*cfg["flex"]["copper_each_mm"]+cfg["flex"]["polyimide_core_mm"]+2*cfg["flex"]["coverlay_each_mm"]
                plate_bottom = flex_top+cfg["dielectric"]["base_mm"]+cfg["dielectric"]["post_height_mm"]
                plate_top = plate_bottom+cfg["body"]["spreader_thickness_mm"]
                cover_top = plate_top+cfg["body"]["nail_cover_mm"]
            else:
                pos = offsets(surface.site, cfg)
                flex_top, plate_bottom, plate_top, cover_top = [pos[k] for k in ("flex_top", "plate_bottom", "plate_top", "cover_top")]
            stop_top = flex_top+stop["adhesive_nominal_mm"]+stop["film_nominal_mm"]
            stop_neutral = flex_top+stop["adhesive_nominal_mm"]+stop["film_nominal_mm"]/2
            body, active = surface.body, surface.active
            plate = body.buffer(-plate_cfg["edge_inset_mm"], join_style="mitre")
            if not is_reference and surface.kind == "nail":
                tip = body.intersection(box(-1000, body.bounds[1]-.1, 1000,
                                            body.bounds[1]+plate_cfg["nail_leading_strip_preserved_mm"]))
                plate = plate.union(tip)
            if plate.geom_type != "Polygon" or not plate.is_valid:
                raise ValueError("Invalid retained metal plate")
            body_flat = body if is_reference else unrolled(body, surface, stop_neutral)
            active_flat = active if is_reference else unrolled(active, surface, stop_neutral)
            stop_ring_flat = body_flat.buffer(-stop["outer_inset_mm"], join_style="mitre").difference(
                active_flat.buffer(stop["active_clearance_mm"], join_style="mitre"))
            stop_ring = stop_ring_flat if is_reference else inverse_unrolled(stop_ring_flat, surface, stop_neutral)
            mid_u = (active.bounds[0]+active.bounds[2])/2
            mid_s = (active.bounds[1]+active.bounds[3])/2
            def cross(width):
                return box(mid_u-width/2, -1000, mid_u+width/2, 1000).union(
                    box(-1000, mid_s-width/2, 1000, mid_s+width/2))
            stop_pieces = polygons(stop_ring.difference(cross(stop["vent_slot_mm"])))
            if len(stop_pieces) != 4 or min(p.area for p in stop_pieces) < stop["minimum_piece_area_mm2"]:
                raise ValueError(label+" stop quadrants are missing or too small")
            if any(piece.difference(plate).area > 1e-6 for piece in stop_pieces):
                raise ValueError(label+" stop not fully under the metal plate")
            outer = plate.buffer(cover["wall_mm"], join_style="mitre").intersection(body)
            wall = outer.difference(plate)
            original_lip = plate.difference(plate.buffer(-cover["under_plate_lip_mm"], join_style="mitre"))
            forbidden_lip = unary_union(stop_pieces).buffer(cover["lip_stop_clearance_mm"], join_style="mitre")
            raw_lip = original_lip.difference(forbidden_lip) if original_lip.intersection(forbidden_lip).area > 1e-8 else original_lip
            lip = remove_duplicate_vertices(raw_lip)
            lip_cleanup_area = raw_lip.symmetric_difference(lip).area
            if lip_cleanup_area > 1e-6*raw_lip.length:
                raise ValueError("Lip cleanup exceeds the numerical seam bound")
            if lip.area/original_lip.area < cover["minimum_retained_lip_area_fraction"]:
                raise ValueError(label+" lip relief removes too much retaining material")
            foot = body.buffer(-cover["foot_outer_inset_mm"], join_style="mitre").difference(plate)
            vent = cross(cover["vent_slot_mm"]).intersection(body)
            ports = []
            if surface.kind == "tpu":
                edge = plate.bounds[0]
                for delta in (-bond["centre_spacing_mm"]/2, bond["centre_spacing_mm"]/2):
                    domain = box(edge-bond["outside_edge_mm"], mid_s+delta-bond["edge_length_mm"]/2,
                                 edge, mid_s+delta+bond["edge_length_mm"]/2)
                    port = domain.buffer(bond["port_margin_mm"], join_style="mitre").intersection(body)
                    ports.append({"bond_domain": domain, "port_domain": port,
                                  "contact_uv": [edge, mid_s+delta], "edge_axis_uv": [0, 1]})
            else:
                edge = plate.bounds[3]
                horizontal = plate.intersection(box(-1000, edge-.001, 1000, edge+.001))
                centre = (horizontal.bounds[0]+horizontal.bounds[2])/2
                for delta in (-bond["centre_spacing_mm"]/2, bond["centre_spacing_mm"]/2):
                    domain = box(centre+delta-bond["edge_length_mm"]/2, edge,
                                 centre+delta+bond["edge_length_mm"]/2, edge+bond["outside_edge_mm"])
                    port = domain.buffer(bond["port_margin_mm"], join_style="mitre").intersection(body)
                    ports.append({"bond_domain": domain, "port_domain": port,
                                  "contact_uv": [centre+delta, edge], "edge_axis_uv": [1, 0]})
            # Include every material/cut endpoint in one source-curve sample
            # set, avoiding differing chord approximations at shared faces.
            domains = [body, active, plate, outer, *polygons(wall), *polygons(lip), *polygons(foot),
                       *stop_pieces, *polygons(vent)]
            domains += [p for port in ports for p in polygons(port["port_domain"])]
            domains += [port["bond_domain"] for port in ports if surface.kind == "tpu"]
            samples = common_samples(surface, domains)
            def solid(domain, inner, outer_offset):
                return shape_for(surface, domain, inner, outer_offset, samples)
            def output(shape, role, purpose, material, kind, color):
                name = "k1_"+label.lower()+"_"+role
                mesh = export_part(shape, name, folder, parts, purpose, material, kind)
                if not is_reference:
                    models.append(packed(mesh, name, role, color))
                return name
            plate_shape = solid(plate, plate_bottom, plate_top)
            output(plate_shape, "retained_plate", "Metal pressure spreader with room for the vented retainer; nail leading edge preserved",
                   plate_cfg["material"], "form_sheet", "#9ca9b0")
            for index, piece in enumerate(stop_pieces):
                output(solid(piece, flex_top, flex_top+stop["adhesive_nominal_mm"]),
                       f"stop_{index}_bond", "Stop adhesive; nominal thickness is included in the stop stack",
                       stop["adhesive"], "reference_only", "#d5bb73")
                output(solid(piece, flex_top+stop["adhesive_nominal_mm"], stop_top),
                       f"stop_{index}", "Polyimide overload-stop quadrant; keep the vent gaps open",
                       stop["film"], "cut_film", "#caad63")
            top = solid(outer, plate_top, cover_top)
            wall_shape = solid(wall, flex_top+cover["foot_bond_mm"], cover_top)
            lip_shape = solid(lip, plate_bottom-cover["under_plate_lip_thickness_mm"], plate_bottom)
            foot_shape = solid(foot, flex_top+cover["foot_bond_mm"],
                               flex_top+cover["foot_bond_mm"]+cover["foot_thickness_mm"])
            cap = top.fuse(wall_shape, lip_shape, foot_shape).clean()
            vent_cut = solid(vent, flex_top-.01, flex_top+cover["vent_top_above_flex_mm"])
            cap = cap.cut(vent_cut)
            for port in ports:
                cut = solid(port["port_domain"], plate_bottom-bond["normal_margin_mm"],
                            plate_top+bond["normal_margin_mm"]+.01)
                cap = cap.cut(cut)
            cap = cap.clean()
            output(cap, "vented_cover", "Soft retainer and wear cover; four lower vents and two separate plate-bond access ports",
                   cover["material"], "cast", "#8db79f")
            # Bond film is split by the open vent slots; export connected
            # pieces individually rather than claiming a disconnected part.
            foot_bond_pieces = polygons(foot.difference(vent))
            for index, piece in enumerate(foot_bond_pieces):
                output(solid(piece, flex_top, flex_top+cover["foot_bond_mm"]),
                       f"cover_bond_{index}", "Local retainer-foot bond; do not bridge the vent channels",
                       cover["foot_bond_material"], "reference_only", "#bcab80")
            for index, port in enumerate(ports):
                output(solid(port["bond_domain"], plate_bottom-bond["normal_margin_mm"],
                             plate_top+bond["normal_margin_mm"]),
                       f"ground_bond_{index}", "Separate conductive plate-bond envelope; no connection to the driven shield",
                       bond["adhesive"], "reference_only", "#ac8d6c")
            flat_plate = plate if is_reference else unrolled(plate, surface, (plate_bottom+plate_top)/2)
            flat_stops = stop_pieces if is_reference else [unrolled(p, surface, stop_neutral) for p in stop_pieces]
            cut_svg(folder / "patterns" / ("k1_"+label.lower()+"_plate_cut.svg"), [flat_plate], label+" metal plate cut, millimetres")
            cut_svg(folder / "patterns" / ("k1_"+label.lower()+"_stop_cut.svg"), flat_stops, label+" bonded stop quadrants, millimetres")
            cells.append({"site": label, "reference_copies": 2 if is_reference else 1,
                          "plate_domain_native_us": list(plate.exterior.coords),
                          "stop_domains_native_us": [list(p.exterior.coords) for p in stop_pieces],
                          "lip_domains_native_us": [{"outer": list(p.exterior.coords),
                                                     "holes": [list(r.coords) for r in p.interiors]} for p in polygons(lip)],
                          "retained_lip_area_fraction": lip.area/original_lip.area,
                          "lip_cleanup_area_mm2": lip_cleanup_area,
                          "stop_total_height_mm": stop_top-flex_top,
                          "nominal_normal_travel_to_stop_mm": plate_bottom-stop_top,
                          "nominal_remaining_post_height_mm": stop_top-flex_top-cfg["dielectric"]["base_mm"],
                          "cover_top_normal_offset_mm": cover_top,
                          "ground_bonds": [{"contact_uv": p["contact_uv"], "edge_axis_uv": p["edge_axis_uv"],
                                           "normal_interval_mm": [plate_bottom, plate_top]} for p in ports]})
            (folder / "partial.json").write_text(json.dumps({"parts": parts, "cells": cells}, indent=2)+"\n")
            print(label+": stop quadrants, retained plate and vented cover generated", flush=True)
        report = {"schema": "yam-k1-cell-mechanics/1", "parts": parts, "cells": cells,
                  "physical_specimens_tested": 0, "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "status": "Mechanical geometry proposal; source/peer checks, cover molds, assembly and physical tests remain",
                  "limits": ["The adhesive-backed stop height and cover stiffness are not measured.",
                             "The retainer is a parallel mechanical path; its contribution requires calibration and a separate model sensitivity check.",
                             "The plates and cover replace earlier full-outline plate/cover references. Preserve the earlier files as history.",
                             "Ground-bond envelopes specify access, not proven adhesion, electrical resistance or strain relief."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "cells": len(cells)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
