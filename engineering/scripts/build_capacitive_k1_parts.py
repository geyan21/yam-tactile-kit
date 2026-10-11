#!/usr/bin/python3
"""Build K1 molding sheets, formed cell references and source-matched tools."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/capacitive-cad-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
import matplotlib
matplotlib.use("Agg")
import numpy as np
from shapely.geometry import Polygon, box
import trimesh

from tactile_kit.records import execution
from capacitive_geometry import CONFIG, load, posts, offsets, unrolled, formed_vertices, reference_footprints
from build_f1_stack_parts import slab, mandrel
from prototype_cad import export_part, packed
from screen_f1_feedback import digest


def planar(polygon, height):
    work = cq.Workplane("XY").polyline(list(polygon.exterior.coords)[:-1]).close()
    for ring in polygon.interiors:
        work = work.polyline(list(ring.coords)[:-1]).close()
    return work.extrude(height).val()


def draw_pattern(name, body, active, centers, cfg, target):
    """Machine-scale SVG and an A4 inspection drawing."""
    from matplotlib import pyplot as plt
    x0, y0, x1, y1 = body.bounds
    width, height = x1-x0+8, y1-y0+8
    def points(polygon):
        return " ".join(f"{x-x0+4:.5f},{y-y0+4:.5f}" for x, y in polygon.exterior.coords)
    radius = cfg["dielectric"]["post_diameter_mm"]/2
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.5f}mm" height="{height:.5f}mm" viewBox="0 0 {width:.5f} {height:.5f}">',
           f'<title>{escape(name)}: post holes and sheet outline in millimetres</title>',
           f'<polygon points="{points(body)}" stroke="#223e46" fill="none" stroke-width=".05"/>',
           f'<polygon points="{points(active)}" stroke="#568471" fill="none" stroke-width=".05"/>']
    svg += [f'<circle cx="{x-x0+4:.5f}" cy="{y-y0+4:.5f}" r="{radius:.5f}" stroke="#222" fill="none" stroke-width=".03"/>'
            for x, y in centers]
    svg.append("</svg>")
    (target / (name+"_layout.svg")).write_text("\n".join(svg)+"\n")
    fig = plt.figure(figsize=(210/25.4, 297/25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set(xlim=(0, 210), ylim=(297, 0), aspect="equal")
    ax.axis("off")
    shift = np.array([30-x0, 50-y0])
    ax.text(15, 15, name, fontsize=14)
    ax.text(15, 25, "K1 DEVELOPMENT · PRINT AT 100% · MILLIMETRES", fontsize=9)
    for poly, color in ((body, "#223e46"), (active, "#568471")):
        values = np.asarray(poly.exterior.coords)+shift
        ax.plot(*values.T, color=color, lw=.6)
    for point in centers:
        ax.add_patch(plt.Circle(np.asarray(point)+shift, radius, fill=False, color="#333", lw=.35))
    ax.text(15, 140, f'{len(centers)} complete holes · diameter {2*radius:.2f} mm', fontsize=10)
    ax.text(15, 150, "0.15 mm metal stencil; 0.05 mm backing cavity above it.", fontsize=9)
    ax.text(15, 160, "Green: silicone base. Black outer line: contact-cell body.", fontsize=9)
    ax.text(15, 170, "Use the separate full stencil CAD for its border and clamping.", fontsize=9)
    ax.text(15, 182, "Formed dimensions, shrinkage, post compression and force response are unmeasured.", fontsize=8)
    ax.plot([15, 15, 65, 65], [249, 250, 250, 249], color="#223e46", lw=.8)
    ax.text(15, 258, "50.00 mm — verify with a ruler", fontsize=9)
    fig.savefig(target / (name+"_inspection.pdf"))
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", type=int, nargs="+", default=list(range(6)))
    parser.add_argument("--reference", action="store_true", help="Also create the shared flat reference-cell tooling")
    parser.add_argument("--forming-mesh-mm", type=float, default=.15)
    args = parser.parse_args()
    if (len(set(args.sites)) != len(args.sites) or any(site not in range(6) for site in args.sites)
            or not .05 <= args.forming_mesh_mm <= .5):
        parser.error("Select distinct sites 0..5")
    cfg, surfaces = load()
    folder = ROOT / "build/engineering/prototypes/capacitive/cad_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Generate K1 flat casting masters, stencil tooling and nominal installed cell references on the preserved finger; explicitly retain unqualified mechanics and integration status") as record:
        folder.mkdir(parents=True, exist_ok=False)
        patterns = folder / "patterns"; patterns.mkdir()
        inputs = [CONFIG, Path(__file__), ROOT / "engineering/scripts/capacitive_geometry.py",
                  ROOT / "engineering/scripts/f1_surfaces.py", ROOT / "engineering/scripts/build_f1_stack_parts.py",
                  ROOT / "engineering/scripts/prototype_cad.py",
                  ROOT / "engineering/scripts/mesh_capacitive_cast.py",
                  *[ROOT / cfg["basis"][key] for key in ("r1_manifest", "nail_coordinates")]]
        hashes = {str(path.relative_to(ROOT)): digest(path) for path in inputs}
        for path in inputs:
            destination = folder / "inputs" / path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        parts, models, cells = [], [], []
        record["run_directory"] = str(folder.relative_to(ROOT))
        record["generated_parts"] = parts
        d, f, b = cfg["dielectric"], cfg["flex"], cfg["body"]
        jobs = [(f"CH{site}", surfaces[site]) for site in args.sites]
        if args.reference:
            jobs.append(("REF", None))
        for label, surface in jobs:
            name = "k1_"+label.lower()
            if surface is None:
                body, active = reference_footprints(cfg)
                native_offsets = None
            else:
                native_offsets = offsets(surface.site, cfg)
                body = unrolled(surface.body, surface, native_offsets["post_base_middle"])
                active = unrolled(surface.active, surface, native_offsets["post_base_middle"])
            centers = posts(active, cfg)
            base = planar(active, d["base_mm"])
            bosses = [cq.Solid.makeCylinder(d["post_diameter_mm"]/2, d["post_height_mm"]+.005,
                                             cq.Vector(x, y, d["base_mm"]-.005)) for x, y in centers]
            sheet = base.fuse(*bosses).clean()
            sheet_mesh = export_part(sheet, name+"_post_sheet_flat", folder, parts,
                                     f"{label} flat molded silicone master; form before installed use",
                                     "SYLGARD 184, 10:1; process and compression unqualified", "cast")
            low_x, low_y, high_x, high_y = body.bounds
            tool_body = box(low_x-4, low_y-4, high_x+4, high_y+4)
            stencil_blank = planar(tool_body, d["post_height_mm"])
            holes = [cq.Solid.makeCylinder(d["post_diameter_mm"]/2, d["post_height_mm"]+.02,
                                          cq.Vector(x, y, -.01)) for x, y in centers]
            stencil = stencil_blank.cut(*holes).clean()
            export_part(stencil, name+"_post_stencil", folder, parts,
                        f"{label} through-hole stencil for the separate silicone post sheet",
                        "0.15 mm laser-cut stainless shim; use flat release plates", "fabricate_tool")
            backing = planar(tool_body.difference(active), d["base_mm"])
            export_part(backing, name+"_backing_spacer", folder, parts,
                        f"{label} spacer defining the thin silicone base above the post stencil",
                        "0.05 mm metal/polyimide shim; verify thickness and cure compatibility", "fabricate_tool")
            draw_pattern(name, body, active, centers, cfg, patterns)
            cell = {"site": label, "post_count": len(centers), "post_centers_flat_mm": centers,
                    "flat_body_mm": list(body.exterior.coords), "flat_active_mm": list(active.exterior.coords),
                    "reference_copies_required": 2 if surface is None else 1,
                    "offsets_native_normal_mm": native_offsets}
            if surface is not None:
                if surface.kind == "tpu":
                    # Large flat-face triangles can cut through a curved
                    # 50 µm base after mapping. Remesh the saved STEP surface
                    # in a separate process, preserving a conforming boundary.
                    mesh_dir = folder / "surface_meshes" / name
                    mesh_dir.parent.mkdir(exist_ok=True)
                    command = [sys.executable, str(ROOT / "engineering/scripts/mesh_capacitive_cast.py"),
                               str(folder / "cad" / (name+"_post_sheet_flat.step")), str(mesh_dir),
                               "--size-mm", str(args.forming_mesh_mm)]
                    with (folder / (name+"_surface_mesh.log")).open("w") as stream:
                        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
                        entry = {"command": command, "pid": process.pid}
                        record.setdefault("surface_mesh_runs", []).append(entry)
                        started = time.monotonic()
                        while True:
                            try:
                                code = process.wait(timeout=20)
                                break
                            except subprocess.TimeoutExpired:
                                if time.monotonic()-started < 180:
                                    continue
                                record["intentional_stop_requests"].append(
                                    f"Stop owned Gmsh surface process {process.pid}: 180 second bound")
                                process.kill(); process.wait()
                                raise RuntimeError("Surface meshing exceeded its bound")
                        entry["exit_code"] = code
                        if code:
                            raise RuntimeError((folder / (name+"_surface_mesh.log")).read_text()[-3000:])
                    sheet_mesh = trimesh.load_mesh(mesh_dir / "flat_refined.stl", process=True)
                formed = sheet_mesh.copy()
                formed.vertices = formed_vertices(formed.vertices, surface, native_offsets["flex_top"],
                                                   native_offsets["post_base_middle"])
                _, tangent, normal = surface.frame(surface.length/2)
                direction = surface.u if surface.kind == "nail" else np.array([1., 0., 0.])
                handedness = float(np.dot(np.cross(direction, tangent), normal))
                if abs(handedness+1) > 1e-6:
                    raise ValueError("Review the source surface chart orientation")
                # Source U / distal-to-proximal arc / outward normal form a
                # left-handed chart. Reverse face winding once, explicitly.
                formed.invert()
                if not formed.is_watertight or formed.volume <= 0:
                    raise ValueError("The nominal forming map folded or opened the post sheet")
                formed_path = folder / "cad" / (name+"_post_sheet_formed_reference.stl")
                formed.export(formed_path)
                cell["formed_reference"] = {"file": str(formed_path.relative_to(folder)),
                                           "sha256": digest(formed_path), "watertight": True,
                                           "surface_chart_handedness": handedness,
                                           "method": "Same casting mesh, mapped onto the nominal base mid-plane; no physical forming prediction"}
                models.append(packed(formed, name+"_post_sheet_formed_reference", "k1_posts", "#bc995f"))
                objects = [
                    ("flex_reference", slab(surface, surface.body, native_offsets["flex_bottom"], native_offsets["flex_top"]),
                     "Requested two-layer flexible electrode/guard stack; copper artwork is separate", "reference_only", "#587c89"),
                    ("ground_spreader", slab(surface, surface.body, native_offsets["plate_bottom"], native_offsets["plate_top"]),
                     b["spreader_material"], "form_sheet", "#9aa5ac"),
                    ("cover_reference", slab(surface, surface.body, native_offsets["plate_top"], native_offsets["cover_top"]),
                     "Silicone cover envelope; retention and vent details remain", "reference_only", "#92bda0"),
                ]
                if surface.site >= 2:
                    objects.append(("rigid_saddle", slab(surface, surface.body, native_offsets["mount"], native_offsets["flex_bottom"]),
                                    "PETG local rigid saddle; source fit and added stiffness require physical checks",
                                    "fabricate", "#b9c5d0"))
                for role, shape, material, kind, color in objects:
                    mesh = export_part(shape, name+"_"+role, folder, parts,
                                       f"{label} {role.replace('_', ' ')} on the source contact surface", material, kind)
                    models.append(packed(mesh, name+"_"+role, "k1_"+role, color))
                form = mandrel(surface, {}, {"mount_outer": native_offsets["plate_bottom"]})
                export_part(form, name+"_spreader_form", folder, parts,
                            f"{label} separate matched form for the metal spreader; springback is not compensated",
                            "Rigid forming tool; verify formed curvature before assembly", "fabricate_tool")
                cell["spreader_flat_cut_mm"] = list(unrolled(surface.body, surface,
                                                            (native_offsets["plate_bottom"]+native_offsets["plate_top"])/2).exterior.coords)
            cells.append(cell)
            (folder / "partial.json").write_text(json.dumps({"parts": parts, "cells": cells}, indent=2)+"\n")
            print(f"{label}: casting master, stencil, backing spacer and {len(centers)} posts exported", flush=True)
        report = {"schema": "yam-k1-cell-cad/1", "physical_specimens_tested": 0,
                  "integrated_prototype_complete": False, "input_sha256": hashes,
                  "parts": parts, "cells": cells,
                  "remaining": ["Stops, vents and retention details", "Electrode artwork and plate ground contacts",
                                "Cable routes, readout PCB and enclosure", "Loaded deformation, calibration and physical comparison"]}
        (folder / "manifest.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts),
                            "cells": len(cells), "physical_specimens_tested": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
