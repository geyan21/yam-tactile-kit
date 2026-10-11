#!/usr/bin/python3
"""Create twelve developed fit patterns and nominal 3D F1 tail references."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/f1-cad-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
import cadquery as cq
import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
import trimesh
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_surfaces import load_surfaces, layer_offsets
from prototype_cad import export_part, packed, yz_prism
from screen_f1_feedback import digest


def material_offsets(site, role):
    # Coordinates relative to the active conductor's centre, along source N.
    # After the quarter bend source N becomes native +X for both foils.
    if role == "columns":
        return (-.0425, .0675)
    return (-.0675, .1275 if site < 2 else .0425)


def profile_solid(polygon, origin, normal, outer, inner):
    plane = cq.Plane(origin=tuple(origin+outer*normal),
                     xDir=(1, 0, 0), normal=tuple(-normal))
    work = cq.Workplane(plane).polyline(list(polygon.exterior.coords)[:-1]).close()
    for ring in polygon.interiors:
        work = work.polyline(list(ring.coords)[:-1]).close()
    return work.extrude(outer-inner).val()


def bent_strip(start, tangent, normal, radius, width, inner, outer):
    plane = cq.Plane(origin=tuple(start-width/2*tangent),
                     xDir=(1, 0, 0), normal=tuple(tangent))
    # The plane's Y axis is source N. The circle centre is at N=-radius.
    ro, ri = radius+outer, radius+inner
    q = math.sqrt(.5)
    return (cq.Workplane(plane).moveTo(0, outer)
            .threePointArc((ro*q, -radius+ro*q), (ro, -radius))
            .lineTo(ri, -radius)
            .threePointArc((ri*q, -radius+ri*q), (0, inner))
            .close().extrude(width).val())


def svg_polygon(polygon, fill, stroke="#29464d"):
    rings = [polygon.exterior, *polygon.interiors]
    d = " ".join("M"+" L".join(f"{x:.5f},{y:.5f}" for x, y in ring.coords)+" Z" for ring in rings)
    return f'<path d="{d}" fill="{fill}" fill-rule="evenodd" stroke="{stroke}" stroke-width=".15"/>'


def draw_pattern(name, geometry, body, bends, tip, role, site, connector, target):
    """A4 in millimetres; no scaling of the pattern itself."""
    x0, y0, x1, y1 = geometry.bounds
    if x1-x0 > 180 or y1-y0 > 230:
        raise ValueError("Fit pattern needs a larger page; never silently scale it")
    dx, dy = 15-x0, 34-y0
    view = affinity.translate(geometry, dx, dy)
    body_view = affinity.translate(body, dx, dy)
    content = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" viewBox="0 0 210 297">',
        '<rect width="210" height="297" fill="white"/>',
        f'<text x="15" y="12" font-family="sans-serif" font-size="5">{escape(name)}</text>',
        '<text x="15" y="20" font-family="sans-serif" font-size="3.4">FIT PATTERN ONLY · NO COPPER ARTWORK · PRINT AT 100%</text>',
        f'<text x="15" y="26" font-family="sans-serif" font-size="3.3">CH{site} {role} → {connector} · view from F.Cu side</text>',
        svg_polygon(view, "#eef3e9"),
        svg_polygon(body_view, "#d6e5bd", "#5c7754"),
    ]
    for line in bends:
        points = [(x+dx, y+dy) for x, y in line.coords]
        content.append('<polyline points="'+" ".join(f"{x:.5f},{y:.5f}" for x, y in points)+
                       '" fill="none" stroke="#ac6436" stroke-width=".2" stroke-dasharray="1 .7"/>')
    tip = np.asarray(tip)+[dx, dy]
    # Pin rectangles are orientation marks, deliberately gray rather than
    # Gerber-like copper fills. They do not define electrode routing.
    for pin in range(1, 7):
        x = tip[0]+pin-3.5
        content.append(f'<rect x="{x-.325:.5f}" y="{tip[1]-6.3:.5f}" width=".65" height="6" '
                       'fill="none" stroke="#8a9296" stroke-width=".1"/>')
        content.append(f'<text x="{x:.5f}" y="{tip[1]+2.2:.5f}" text-anchor="middle" '
                       f'font-family="sans-serif" font-size="1.7">{pin}</text>')
    content += [
        '<path d="M15 271v-2M15 270h50M65 271v-2" fill="none" stroke="#223b43" stroke-width=".25"/>',
        '<text x="15" y="277" font-family="sans-serif" font-size="3.2">50 mm scale bar · verify with a ruler</text>',
        '<text x="15" y="284" font-family="sans-serif" font-size="3.1">Dashed lines bound the 90° bend. Form around the radius; do not crease.</text>',
        '<text x="15" y="290" font-family="sans-serif" font-size="3.1">Connector datum, source join, bending slack and physical fit remain unverified.</text>',
        '</svg>',
    ]
    svg = target / (name+".svg")
    svg.write_text("\n".join(content)+"\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    fig = plt.figure(figsize=(210/25.4, 297/25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set(xlim=(0, 210), ylim=(297, 0), aspect="equal")
    ax.axis("off")
    ax.fill(*np.asarray(body_view.exterior.coords).T, color="#d6e5bd")
    for ring in (view.exterior, *view.interiors):
        ax.plot(*np.asarray(ring.coords).T, color="#29464d", lw=.45)
    for line in bends:
        xy = np.asarray(line.coords)+[dx, dy]
        ax.plot(*xy.T, color="#ac6436", lw=.6, linestyle="--")
    for pin in range(1, 7):
        x = tip[0]+pin-3.5
        ax.add_patch(Rectangle((x-.325, tip[1]-6.3), .65, 6,
                               facecolor="none", edgecolor="#8a9296", linewidth=.3))
        ax.text(x, tip[1]+2.2, str(pin), ha="center", fontsize=5)
    ax.text(15, 12, name, fontsize=14)
    ax.text(15, 20, "FIT PATTERN ONLY · NO COPPER ARTWORK · PRINT AT 100%", fontsize=9)
    ax.text(15, 26, f"CH{site} {role} → {connector} · view from F.Cu side", fontsize=9)
    ax.plot([15, 15, 65, 65], [269, 270, 270, 269], color="#223b43", lw=.7)
    for y, text in (
            (277, "50 mm scale bar · verify with a ruler"),
            (284, "Dashed lines bound the 90° bend. Form around the radius; do not crease."),
            (290, "Connector datum, source join, bending slack and physical fit remain unverified.")):
        ax.text(15, y, text, fontsize=8)
    # Do not use a tight bounding box: the PDF must retain its exact A4 scale.
    fig.savefig(target / (name+".pdf"))
    plt.close(fig)


def make_pattern(surface, route, cfg, exits, stack):
    site, role = route["site"], route["role"]
    offsets = layer_offsets(site, stack)
    offset = offsets["row_conductor_center" if role == "rows" else "column_conductor_center"]
    edge = exits["edge_by_site"][site]
    s_end = surface.body.bounds[1 if edge == "distal" else 3]
    p, tangent, normal = surface.frame(s_end)
    cu_origin = p+offset*normal
    arc = surface.offset_arc(offset)
    def flat_ring(ring):
        return [(x, float(np.interp(y, surface.s, arc))) for x, y in ring.coords]
    body = Polygon(flat_ring(surface.body.exterior),
                   [flat_ring(ring) for ring in surface.body.interiors])
    end_flat = float(np.interp(s_end, surface.s, arc))
    advance = (exits["exit_native_y_mm_by_site"][site]-cu_origin[1])/tangent[1]
    y_exit = end_flat+advance
    section_s = s_end+(.03 if edge == "distal" else -.03)
    section = surface.body.intersection(LineString([(-100, section_s), (100, section_s)]))
    lo, hi = section.bounds[0], section.bounds[2]
    narrow, wide = stack["tails"]["row_neck_width_mm"], stack["tails"]["long_tail_width_mm"]
    bend_x = cfg["lateral_bend_start_x_mm"][role]
    bend_u = bend_x-p[0]
    widen_u0, widen_u1 = 7.2-p[0], 8.35-p[0]
    if widen_u1 > bend_u+1e-8:
        raise ValueError("Widening extends into the formed bend")
    # This full-width end extension is explicit in the fit pattern; source
    # intersections are not inferred from the earlier lateral-only screen.
    join = box(lo+.3, min(end_flat, y_exit-narrow/2)-.03,
               hi, max(end_flat, y_exit+narrow/2)+.03)
    lateral = box(hi-.1, y_exit-narrow/2, widen_u0, y_exit+narrow/2)
    widen = Polygon([(widen_u0, y_exit-narrow/2), (widen_u1, y_exit-wide/2),
                     (bend_u, y_exit-wide/2), (bend_u, y_exit+wide/2),
                     (widen_u1, y_exit+wide/2), (widen_u0, y_exit+narrow/2)])
    neck = unary_union((join, lateral, widen))
    radius = route["nominal_form_radius_mm"]
    bend_length = radius*math.pi/2
    unfolded_bend = box(bend_u, y_exit-wide/2, bend_u+bend_length, y_exit+wide/2)
    bend_end = np.asarray(route["bend_native_mm"][-1])
    direction = -normal
    # YZ plane coordinates become the continued U/T plane after unfolding.
    shift = np.array([bend_u+bend_length, y_exit])
    matrix = np.array([direction[1:], tangent[1:]])
    translation = shift-matrix @ bend_end[1:]
    affine = [matrix[0, 0], matrix[0, 1], matrix[1, 0], matrix[1, 1], *translation]
    flat_tail = affinity.affine_transform(Polygon(route["tail_envelope_yz_mm"]), affine)
    forbidden_flat_overlap = body.intersection(flat_tail).area
    flat = unary_union((body, neck, unfolded_bend, flat_tail))
    if flat.geom_type != "Polygon" or not flat.is_valid:
        raise ValueError("Unfolding does not make one connected fit outline")
    inner, outer = material_offsets(site, role)
    neck_local = affinity.translate(neck, yoff=-end_flat)
    neck_shape = profile_solid(neck_local, cu_origin, normal, outer, inner)
    bend_start = cu_origin+advance*tangent
    bend_start[0] = bend_x
    curve_shape = bent_strip(bend_start, tangent, normal, radius, wide, inner, outer)
    planar = yz_prism(Polygon(route["tail_envelope_yz_mm"]),
                      route["nominal_plane_native_x_mm"]+inner, outer-inner)
    tail_shape = neck_shape.fuse(curve_shape, planar)
    # Coordinates on the finished pattern are rotated so the connector
    # insertion direction points along page +Y. Mirroring columns makes F.Cu
    # face the film when the two foils are assembled.
    mirror = 1 if role == "rows" else -1
    end_direction = np.asarray(route["tip_yz_mm_assumed"])-np.asarray(route["goal_yz_mm"])
    mapped = np.array([mirror, 1])*(matrix @ end_direction)
    rotation = 90-math.degrees(math.atan2(mapped[1], mapped[0]))
    def fabrication(shape):
        return affinity.rotate(affinity.scale(shape, xfact=mirror, yfact=1, origin=(0, 0)),
                               rotation, origin=(0, 0))
    tip_flat = matrix @ np.asarray(route["tip_yz_mm_assumed"])+translation
    tip_shape = fabrication(LineString([tip_flat, tip_flat+[0, .0001]]))
    tip = list(tip_shape.coords)[0]
    bends = [fabrication(LineString([(u, y_exit-wide/2), (u, y_exit+wide/2)]))
             for u in (bend_u, bend_u+bend_length)]
    basis = {
        "site": site, "role": role, "connector": route["connector"],
        "source_edge": edge, "conductor_offset_mm": offset,
        "unrolled_body_end_mm": end_flat, "tangent_extension_mm": advance,
        "flat_exit_y_before_fabrication_transform_mm": y_exit,
        "body_origin_native_mm": p.tolist(),
        "fabrication_x_mirror": mirror, "fabrication_rotation_deg": rotation,
        "native_yz_to_unfolded_tail_affine": affine,
        "connector_tip_flat_mm_assumed": list(tip),
        "nominal_conductor_bend_radius_mm": radius,
        "minimum_material_bend_radius_mm": radius+inner,
        "covered_tail_thickness_mm": outer-inner,
        "nonlocal_body_tail_flat_overlap_mm2": forbidden_flat_overlap,
        "unrolled_outline_holes": len(flat.interiors),
        "physical_evidence": False,
        "limits": [
            "No routed electrode copper or connector stiffener is included in this fit-only CAD.",
            "The body-end extension is new geometry and requires its own full source/stack collision checks.",
            "The unfolded surface follows a conductor reference, not a measured mechanical neutral axis.",
            "Nominal connector midpoints are assumptions; actual mating, inextensible slack and motion remain."
        ],
    }
    return fabrication(flat), fabrication(body), bends, tip, tail_shape, basis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tail_run", type=Path)
    args = parser.parse_args()
    source = args.tail_run.resolve()
    if not source.is_relative_to(ROOT):
        parser.error("Use a repository-owned route run")
    report_path = source / "report.json"
    report = json.loads(report_path.read_text())
    if report["nominal_lanes_passed"] != 12:
        raise ValueError("Use a study with twelve nominal lanes")
    route_path = source / "inputs/engineering/designs/f1_tail_route_development.json"
    cfg = json.loads(route_path.read_text())
    exits_path = source / "inputs" / cfg["exit_configuration"]
    exits = json.loads(exits_path.read_text())
    stack_path = source / "inputs/engineering/designs/f1_formed_stack.json"
    stack, r1, nail, surfaces = load_surfaces(stack_path)
    folder = ROOT / "build/engineering/prototypes/f1/tail_fit_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Create developed paper/polyester fit patterns and reference tail CAD from the twelve nominal F1 lanes; do not imply copper or physical qualification") as record:
        folder.mkdir(parents=True, exist_ok=False)
        patterns = folder / "patterns"; patterns.mkdir()
        paths = [report_path, route_path, exits_path, stack_path, Path(__file__),
                 ROOT / "engineering/scripts/f1_surfaces.py", ROOT / "engineering/scripts/prototype_cad.py"]
        for path in paths:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        parts, results, models = [], [], []
        for row in sorted(report["routes"], key=lambda p: (p["site"], p["role"])):
            site, role = row["site"], row["role"]
            name = f"f1_ch{site}_{role}_fit"
            flat, body, bends, tip, tail, result = make_pattern(surfaces[site], row, cfg, exits, stack)
            result["name"] = name
            result["outline_flat_mm"] = list(flat.exterior.coords)
            result["inner_cuts_flat_mm"] = [list(ring.coords) for ring in flat.interiors]
            draw_pattern(name, flat, body, bends, tip, role, site, row["connector"], patterns)
            mesh = export_part(tail, name+"_tail_reference", folder, parts,
                               f"CH{site} {role} covered-tail fit reference; electrode body and stiffener are separate",
                               "Nominal PI/Cu/coverlay envelope, not a 3D-printable functional sensor",
                               "reference_only")
            models.append(packed(mesh, name, "tails", "#bf9758" if role == "columns" else "#548db0"))
            results.append(result)
            (folder / "partial.json").write_text(json.dumps({"parts": parts, "patterns": results}, indent=2)+"\n")
            print(name+": fit pattern and round-tripped tail reference", flush=True)
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        manifest = {
            "schema": "yam-f1-tail-fit/1", "physical_specimens_tested": 0, "complete_f1_assembly": False,
            "parts": parts, "patterns": results,
            "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in paths},
            "nonlocal_unfolded_overlap_maximum_mm2": max(p["nonlocal_body_tail_flat_overlap_mm2"] for p in results),
            "instruction": "Print at 100%, check the 50 mm scale bar, cut paper or approximately 0.1 mm polyester, mark the F.Cu face and connector, and form the quarter bend without a sharp crease. This is a fit study, not sensor fabrication."
        }
        (folder / "fit_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "fit_patterns": len(results),
                            "reference_tail_solids": len(parts),
                            "nonlocal_flat_overlap_maximum_mm2": manifest["nonlocal_unfolded_overlap_maximum_mm2"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
