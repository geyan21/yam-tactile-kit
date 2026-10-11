#!/usr/bin/python3
"""Build source-matched F1 layer bodies and curved forming mandrels."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/f1-cad-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
import cadquery as cq
import numpy as np
from shapely.geometry import Polygon, box
import trimesh
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_surfaces import CONFIG, load_surfaces, layer_offsets
from prototype_cad import export_part, yz_prism, packed
from screen_f1_feedback import digest


def section_profile(surface, polygon, inner, outer):
    x0, s0, x1, s1 = polygon.bounds
    if polygon.symmetric_difference(box(x0, s0, x1, s1)).area > 1e-8:
        raise ValueError("Curved slab requires a rectangular reference section")
    # Use common interior samples for every layer so contacting interfaces
    # do not acquire different polygon chord errors.
    coordinates = np.unique(np.r_[s0, surface.s[(surface.s > s0) & (surface.s < s1)], s1])
    count = len(coordinates)
    low = surface.points(np.zeros(count), coordinates, inner)[:, 1:]
    high = surface.points(np.zeros(count), coordinates, outer)[:, 1:]
    section = Polygon(np.vstack((low, high[::-1])))
    if not section.is_valid or section.area <= 0:
        raise ValueError("Offset layer section is not a simple material region")
    return section


def slab(surface, polygon, inner, outer):
    """A true nominal normal-offset layer; these are material envelopes."""
    if not outer > inner:
        raise ValueError("Layer thickness must be positive")
    if surface.kind == "nail":
        plane = cq.Plane(origin=tuple(surface.origin+surface.n*outer),
                         xDir=tuple(surface.u), normal=tuple(-surface.n))
        work = cq.Workplane(plane).polyline(list(polygon.exterior.coords)[:-1]).close()
        for ring in polygon.interiors:
            work = work.polyline(list(ring.coords)[:-1]).close()
        return work.extrude(outer-inner).val()
    section = section_profile(surface, polygon, inner, outer)
    x0, _, x1, _ = polygon.bounds
    return yz_prism(section, -7.5+x0, x1-x0)


def section_volume_checks(surface, opening, cover_domain, offsets, material, solids):
    """Exact section algebra for these parallel-extrusion constructions.

    This avoids ambiguous empty 3D booleans at shared thin-layer boundaries.
    Agreement with each exported solid's volume is checked independently.
    """
    body, active = surface.body, surface.active
    mount, col, row, outer, top = (offsets[name] for name in
                                 ("mount_outer", "column_contact", "row_contact", "row_outer", "cover_outer"))
    c = material["coverlay"]
    names = list(solids)
    volumes = {name: 0.0 for name in names}
    intersections = {a+"/"+b: 0.0 for i, a in enumerate(names) for b in names[i+1:]}
    if surface.kind == "nail":
        divisions = sorted(set((mount, col, col+c, row-c, row, outer, top)))
        def sections(value):
            result = {name: Polygon() for name in names}
            if mount < value < col:
                result["columns"] = body
            if col < value < col+c:
                result["columns"] = body.difference(opening)
            if row < value < outer:
                result["rows"] = body
            if row-c < value < row:
                result["rows"] = body.difference(opening)
            if col < value < row:
                result["film"] = active
            if outer < value < top:
                result["cover"] = cover_domain
            return result
    else:
        divisions = sorted(set(p.bounds[i] for p in (body, active, opening, cover_domain) for i in (0, 2)))
        profiles = {
            "column_base": section_profile(surface, body, mount, col),
            "column_rim": section_profile(surface, body, col, col+c),
            "column_opening": section_profile(surface, opening, col-.01, col+c+.01),
            "row_base": section_profile(surface, body, row, outer),
            "row_rim": section_profile(surface, body, row-c, row),
            "row_opening": section_profile(surface, opening, row-c-.01, row+.01),
            "film": section_profile(surface, active, col, row),
            "cover": section_profile(surface, cover_domain, outer, top),
        }
        def inside(poly, value):
            return poly.bounds[0] < value < poly.bounds[2]
        def sections(value):
            result = {name: Polygon() for name in names}
            if inside(body, value):
                col_rim, row_rim = profiles["column_rim"], profiles["row_rim"]
                if inside(opening, value):
                    col_rim = col_rim.difference(profiles["column_opening"])
                    row_rim = row_rim.difference(profiles["row_opening"])
                result["columns"] = profiles["column_base"].union(col_rim)
                result["rows"] = profiles["row_base"].union(row_rim)
            if inside(active, value):
                result["film"] = profiles["film"]
            if inside(cover_domain, value):
                result["cover"] = profiles["cover"]
            return result
    for low, high in zip(divisions, divisions[1:]):
        pieces = sections((low+high)/2)
        for name in names:
            volumes[name] += pieces[name].area*(high-low)
        for i, first in enumerate(names):
            for second in names[i+1:]:
                intersections[first+"/"+second] += pieces[first].intersection(pieces[second]).area*(high-low)
    errors = {name: abs(volumes[name]-solids[name].Volume()) for name in names}
    if any(error > max(.001, volumes[name]*.0005) for name, error in errors.items()):
        raise ValueError("CAD solid differs from its independent section construction")
    if max(intersections.values()) > .001:
        raise ValueError("Nominal material layers overlap")
    return {"site": f"CH{surface.site}", "intersections_mm3": intersections,
            "section_integral_volumes_mm3": volumes, "cad_volume_difference_mm3": errors,
            "method": "Parallel extrusion section algebra, checked against CAD volumes", "passed": True}


def mandrel(surface, cfg, offsets):
    """Rigid backing form, used away from the robot for layer assembly."""
    if surface.kind == "nail":
        outer = surface.body.buffer(3, join_style="round")
        # Flat nail layers have identical unrolled lengths, so an expanded
        # plane backing is sufficient for this initial forming tool.
        return slab(surface, outer, offsets["mount_outer"]-4, offsets["mount_outer"])
    margin = 3
    base_width = surface.width+2*margin
    s = np.linspace(0, surface.length, max(3, int(surface.length/.05)+1))
    curve = surface.points(np.zeros_like(s), s, offsets["mount_outer"])[:, 1:]
    y0, y1 = float(curve[0, 0]), float(curve[-1, 0])
    back = float(np.max(curve[:, 1]))+4
    section = Polygon([(y0-margin, curve[0, 1]), *curve.tolist(),
                       (y1+margin, curve[-1, 1]), (y1+margin, back), (y0-margin, back)])
    if not section.is_valid:
        raise ValueError("Forming-tool section intersects itself")
    return yz_prism(section, -7.5-base_width/2, base_width)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    config_path = args.config.resolve()
    if not config_path.is_relative_to(ROOT):
        parser.error("Use a repository-owned configuration")
    cfg, r1, nail, surfaces = load_surfaces(config_path)
    folder = ROOT / "build/engineering/prototypes/f1/stack_cad_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Generate and round-trip F1 contact-layer envelopes and forming tools against the retained finger surfaces; tails and physical qualification remain") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        source_paths = [config_path, Path(__file__), ROOT / "engineering/scripts/f1_surfaces.py",
                        ROOT / "engineering/scripts/prototype_cad.py",
                        ROOT / cfg["basis"]["r1_manifest"], ROOT / cfg["basis"]["nail_coordinates"]]
        for path in source_paths:
            target = inputs / path.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        parts, models, assemblies, stack_checks = [], [], [], []
        palette = {"columns": "#c1983d", "film": "#42434a", "rows": "#5d8db4", "cover": "#a2c77d"}
        m = cfg["materials_mm"]
        for surface in surfaces:
            site = surface.site
            offsets = layer_offsets(site, cfg)
            opening = surface.active.buffer(.1, join_style="mitre").intersection(surface.body)
            if not surface.body.covers(opening) or opening.area <= 0:
                raise ValueError("Active opening escaped the foil body")
            # Covered margins nominally replace the film gap; the active
            # copper envelopes face one another through the film opening.
            col_base = slab(surface, surface.body, offsets["mount_outer"], offsets["column_contact"])
            col_rim = slab(surface, surface.body, offsets["column_contact"], offsets["column_contact"]+m["coverlay"])
            col_cut = slab(surface, opening, offsets["column_contact"]-.01, offsets["column_contact"]+m["coverlay"]+.01)
            columns = col_base.fuse(col_rim.cut(col_cut))
            rows = slab(surface, surface.body, offsets["row_contact"], offsets["row_outer"])
            row_rim = slab(surface, surface.body, offsets["row_contact"]-m["coverlay"], offsets["row_contact"])
            row_cut = slab(surface, opening, offsets["row_contact"]-m["coverlay"]-.01, offsets["row_contact"]+.01)
            rows = rows.fuse(row_rim.cut(row_cut))
            film = slab(surface, surface.active, offsets["column_contact"], offsets["row_contact"])
            cover_domain = surface.body if site < 2 else box(-surface.width/2, 0, surface.width/2, surface.length)
            cover = slab(surface, cover_domain, offsets["row_outer"], offsets["cover_outer"])
            solids = {"columns": columns, "film": film, "rows": rows, "cover": cover}
            meshes = []
            for name, shape in solids.items():
                part_name = f"f1_ch{site}_{name}_body"
                material = {"columns": "PI/Cu flex envelope; active coverlay opening",
                            "rows": "PI/Cu flex envelope; active coverlay opening",
                            "film": "0.10 mm conductive pressure film",
                            "cover": "Silicone cover process target"}[name]
                mesh = export_part(shape, part_name, folder, parts,
                                   f"CH{site} {name} reference body on the actual source surface; tail not yet attached",
                                   material, kind="reference_only")
                meshes.append(mesh)
                models.append(packed(mesh, part_name, f"CH{site}", palette[name]))
            stack_checks.append(section_volume_checks(surface, opening, cover_domain, offsets, m, solids))
            form = mandrel(surface, cfg, offsets)
            export_part(form, f"f1_ch{site}_forming_mandrel", folder, parts,
                        f"CH{site} rigid backing form for separate-layer assembly away from the robot",
                        "PETG/engineering plastic tool; smooth the contact surface and use a release film",
                        kind="fabricate_tool")
            assemblies.append(trimesh.util.concatenate(meshes))
            (folder / "partial_parts.json").write_text(json.dumps(
                {"parts": parts, "stack_checks": stack_checks, "complete_f1_package": False}, indent=2)+"\n")
            print(f"Completed CH{site}: four layer bodies and one forming mandrel", flush=True)
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        fig = plt.figure(figsize=(15, 7))
        ax = fig.add_subplot(121, projection="3d")
        bx = fig.add_subplot(122, projection="3d")
        for item in models:
            points = np.asarray(item["vertices"])
            faces = np.asarray(item["faces"])
            # Y/Z/X display keeps the long finger readable; vertices remain
            # in native XYZ in all CAD and machine-readable outputs.
            poly = points[faces][:, :, [1, 2, 0]]
            (ax if item["group"] in ("CH0", "CH1") else bx).add_collection3d(
                Poly3DCollection(poly, facecolor=item["color"], edgecolor="none", alpha=.45))
        for plot, sites, title in ((ax, assemblies[:2], "Two thin nail stacks"),
                                   (bx, assemblies[2:], "Four independently developed TPU stacks")):
            bounds = trimesh.util.concatenate(sites).bounds
            lo, hi = bounds[0, [1, 2, 0]], bounds[1, [1, 2, 0]]
            plot.set(xlim=(lo[0]-1, hi[0]+1), ylim=(lo[1]-1, hi[1]+1), zlim=(lo[2]-1, hi[2]+1),
                     xlabel="Native Y (mm)", ylabel="Native Z (mm)", zlabel="Native X (mm)", title=title)
            plot.set_box_aspect(np.maximum(hi-lo, 3))
            plot.view_init(elev=28, azim=-60)
        fig.suptitle("F1 reference layer bodies · tails and complete mounted assembly pending\n"
                     "Verified STEP/STL geometry, not photographs or physical force results")
        fig.tight_layout()
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(folder / ("stack_bodies."+suffix), dpi=160, bbox_inches="tight")
        plt.close(fig)
        report = {"schema": "yam-f1-stack-cad/1", "physical_specimens_tested": 0, "complete_f1_package": False,
                  "input_hashes": {str(path.relative_to(ROOT)): digest(path) for path in source_paths},
                  "parts": parts, "stack_checks": stack_checks,
                  "limits": [
                      "Foil solids are conservative material envelopes; they are not copper Gerbers or printer-ready sensor foils.",
                      "Tail geometry, connector mating, mounted-frame collisions, retention and sealing remain to be completed.",
                      "The tools establish nominal forming surfaces. Actual material thickness, preload, bonding and release process require trial assemblies.",
                      "No contact, force, durability or 20 N qualification follows from these geometric checks."
                  ]}
        (folder / "stack_manifest.json").write_text(json.dumps(report, indent=2)+"\n")
        record["summary"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts),
                            "reference_bodies": 24, "forming_tools": 6, "nominal_stack_checks_passed": True}
        print(json.dumps(record["summary"], indent=2))


if __name__ == "__main__":
    main()
