#!/usr/bin/python3
"""Build F1 plated-stack references, compliant fitting bases and peripheral covers."""

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
from shapely.geometry import Polygon, box
from tactile_kit.records import execution
from f1_surfaces import load_surfaces, layer_offsets
from build_f1_stack_parts import slab, mandrel
from capacitive_cell_geometry import polygons, common_samples, shape_for
from prototype_cad import export_part, packed, block
from source_brep import load as source_solid
from analyze_b1_interfaces import original_profile, extruded_profile
from check_f1_tail_fit import check_pair
from screen_f1_feedback import digest

CONFIG = ROOT / "engineering/designs/f1_skin_r4.json"
EXITS = ROOT / "engineering/designs/f1_exit_spaced_candidate.json"


def main():
    config = json.loads(CONFIG.read_text())
    stack_path = ROOT / config["basis_stack"]
    cfg, r1, nail, surfaces = load_surfaces(stack_path)
    exits = json.loads(EXITS.read_text())
    finish = config["finish_nominal_mm_each_contact_face"]
    folder = ROOT / "build/engineering/prototypes/f1/retained_skin_cad" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Build complete F1 compliant fit bases and cast-cover retention around the plated layer stack, keeping source-datum and physical-evidence limits explicit") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        paths = [CONFIG, EXITS, stack_path, Path(__file__), ROOT / "engineering/scripts/f1_surfaces.py",
                 ROOT / "engineering/scripts/build_f1_stack_parts.py",
                 ROOT / "engineering/scripts/capacitive_cell_geometry.py",
                 ROOT / cfg["basis"]["r1_manifest"], ROOT / cfg["basis"]["nail_coordinates"]]
        hard, hard_receipt = source_solid("hard_frame")
        mesh, profile, _ = original_profile(); soft = extruded_profile(profile)
        if abs(soft.Volume()-mesh.volume) > mesh.volume*1e-5:
            raise ValueError("Source TPU conversion changed")
        parts, models, cases, base_checks, bases = [], [], [], [], []
        for surface in surfaces:
            site = surface.site; positions = layer_offsets(site, cfg)
            mount = positions["mount_outer"]; cc = positions["column_contact"]
            rc = positions["row_contact"]+2*finish; ro = positions["row_outer"]+2*finish
            top = positions["cover_outer"]+2*finish
            body, active = surface.body, surface.active
            opening = active.buffer(.1, join_style="mitre").intersection(body)
            if site < 2:
                delta = surface.origin-np.asarray(nail["nail_plane_origin_native_mm"])
                center_u = float(delta @ np.asarray(nail["nail_plane_u_axis_native"]))
                top_v = float(delta @ np.asarray(nail["nail_plane_v_axis_native"]))
                footprint = Polygon(nail["nail_footprint"]["outer"], nail["nail_footprint"]["holes"])
                available = affinity.affine_transform(footprint, [1, 0, 0, -1, -center_u, top_v])
                cover_domain = body.buffer(config["nail_cover_expand_mm"], join_style="mitre").intersection(
                    available.buffer(-config["nail_available_face_edge_margin_mm"], join_style="mitre"))
                if body.difference(cover_domain).area > 1e-6:
                    raise ValueError(f"CH{site}: the cover cannot enclose the foil within the available nail face")
                frame_top = 0.
            else:
                cover_domain = box(-surface.width/2, 0, surface.width/2, surface.length)
                frame_top = mount-config["foil_mount_bond_nominal_mm"]
                witness = next(p for p in r1["parts"] if p["id"] == f"pad_{site}_saddle_witness")
                path = ROOT / "engineering/release/r1" / witness["step"]
                if digest(path) != witness["sha256_step"]:
                    raise ValueError("R1 fitting witness changed")
                paths.append(path)
                base = cq.importers.importStep(str(path)).val()
                x0 = r1["pads"][site-2]["assembly_native_x_limits_mm"][0]
                base = base.rotate((0, 0, 0), (1, 1, 1), 120).translate((x0, 0, 0))
                a, _, _ = surface.frame(0); b, _, _ = surface.frame(surface.length)
                bb = base.BoundingBox()
                base = base.intersect(block(bb.xmin-1, bb.xmax+1, a[1], b[1], bb.zmin-2, bb.zmax+2))
                base = base.fuse(slab(surface, cover_domain, -.03, frame_top)).clean()
                identifier = f"f1_ch{site}_compliant_fit_base"
                display = export_part(base, identifier, folder, parts,
                                      "Variable-thickness compliant fitting base from the source TPU to the FPC mount",
                                      config["material"], "cast")
                models.append(packed(display, identifier, "f1_fit_bases", "#8da18c"))
                for other_name, other in (("source_hard", hard), ("source_TPU", soft), *bases):
                    base_checks.append(check_pair(identifier, base, other_name, other))
                bases.append((identifier, base))
            wall = cover_domain.difference(body.buffer(config["side_clearance_to_foil_mm"], join_style="mitre"))
            foot_height = frame_top+config["frame_bond_nominal_mm"]
            edge = exits["edge_by_site"][site]
            if edge == "distal":
                port = box(-1000, -1000, 1000, body.bounds[1]+config["exit_port_inside_body_length_mm"])
            else:
                port = box(-1000, body.bounds[3]-config["exit_port_inside_body_length_mm"], 1000, 1000)
            port = port.intersection(cover_domain)
            domains = [body, active, opening, cover_domain, *polygons(wall), *polygons(port)]
            samples = common_samples(surface, domains)
            def shaped(domain, low, high):
                return shape_for(surface, domain, low, high, samples)
            def output(shape, role, purpose, material, kind="reference_only"):
                identifier = f"f1_ch{site}_"+role
                display = export_part(shape, identifier, folder, parts, purpose, material, kind)
                models.append(packed(display, identifier, {
                    "retained_cover": "f1_covers", "columns_body": "f1_stacks", "rows_body": "f1_stacks",
                    "pressure_film": "f1_stacks"}.get(role, "f1_stack_bonds"),
                    {"retained_cover": "#b3cba7", "pressure_film": "#686777"}.get(role, "#8cabb2")))
            columns = shaped(body, mount, cc).fuse(shaped(body, cc, cc+.05).cut(shaped(opening, cc-.01, cc+.06))).clean()
            rows = shaped(body, rc, ro).fuse(shaped(body, rc-.05, rc).cut(shaped(opening, rc-.06, rc+.01))).clean()
            output(columns, "columns_body", "Lower FPC body envelope with its active coverlay opening", "PI/Cu/coverlay envelope")
            output(rows, "rows_body", "Upper FPC body envelope with the plated-stack allowance", "PI/Cu/coverlay envelope")
            output(shaped(active, cc, cc+finish), "column_finish_envelope", "Maximum-height envelope over active exposed copper; real plated area follows artwork", "Nominal Ni/Au finish envelope")
            output(shaped(active, rc-finish, rc), "row_finish_envelope", "Maximum-height envelope over active exposed copper; real plated area follows artwork", "Nominal Ni/Au finish envelope")
            output(shaped(active, cc+finish, rc-finish), "pressure_film", "Measured conductive-film island; register to the row/column contact map", "0.10 mm pressure-sensitive conductive film", "cut_film")
            cap = shaped(cover_domain, ro, top).fuse(shaped(wall, foot_height, top)).clean()
            cap = cap.cut(shaped(port, foot_height-.01, ro+config["exit_port_above_row_mm"])).clean()
            output(cap, "retained_cover", "Cast wear cover and peripheral skirt with a shared end port for both foil necks",
                   config["material"], "cast")
            output(shaped(body, frame_top, mount), "foil_mount_bond", "Lower-foil mounting bond; keep adhesive out of the active conductive film",
                   "50 µm insulating adhesive envelope")
            for index, piece in enumerate(polygons(wall.difference(port))):
                if piece.area < config["minimum_foot_piece_area_mm2"]:
                    raise ValueError("A peripheral cover foot is too small")
                output(shaped(piece, frame_top, foot_height), "cover_foot_bond_"+str(index),
                       "Peripheral flexible bond to the nail face or compliant fitting base",
                       config["frame_bond_material"])
            form = mandrel(surface, cfg, positions)
            identifier = f"f1_ch{site}_layer_assembly_form"
            export_part(form, identifier, folder, parts, "Backing form for registering layers away from the robot",
                        "Smooth finished tool with compatible release agent", "fabricate_tool")
            cases.append({"site": site, "foil_body_native_us": list(body.exterior.coords),
                          "cover_domain_native_us": list(cover_domain.exterior.coords),
                          "tail_exit": edge, "cover_top_above_source_datum_mm": top,
                          "column_contact_mm": cc+finish, "row_contact_mm": rc-finish,
                          "film_thickness_mm": rc-cc-2*finish, "base_upper_datum_mm": frame_top,
                          "foot_bond_top_mm": foot_height, "row_outer_mm": ro,
                          "minimum_skirt_foot_area_mm2": min(p.area for p in polygons(wall.difference(port)))})
            (folder / "partial.json").write_text(json.dumps({"parts": parts, "cases": cases, "base_checks": base_checks}, indent=2)+"\n")
            print(f"CH{site}: plated layers, retained cover and mounting interfaces generated", flush=True)
        for path in paths:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        report = {"schema": "yam-f1-retained-skin-cad/1", "physical_specimens_tested": 0,
                  "parts": parts, "cases": cases, "base_checks": base_checks,
                  "base_source_checks_pass": all(c["passed"] for c in base_checks),
                  "source_hard_conversion": hard_receipt,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in paths},
                  "limits": config["limits"]+["Cover/base molds, complete source/peer checks and the foil-neck joins remain."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "cells": len(cases),
                            "base_source_checks_pass": report["base_source_checks_pass"]}
        print(json.dumps(record["result"], indent=2))
        if not report["base_source_checks_pass"]:
            raise ValueError("Resolve the fitting-base source checks")


if __name__ == "__main__":
    main()
