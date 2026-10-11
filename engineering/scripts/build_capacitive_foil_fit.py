#!/usr/bin/python3
"""Build K1 foil, stiffener and solder-joint envelopes and check source-finger fit."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/capacitive-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
import numpy as np
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from tactile_kit.records import execution
from capacitive_geometry import CONFIG, load, offsets
from build_f1_stack_parts import slab
from prototype_cad import export_part, packed, yz_prism
from source_brep import load as source_solid
from analyze_b1_interfaces import original_profile, extruded_profile
from check_f1_tail_fit import check_pair
from screen_f1_feedback import digest
from capacitive_tail_geometry import POSES, nail_slab, bend_parameters


def mapped_slab(surface, polygon, inner, outer, neutral, samples, poses, join):
    if surface.kind == "nail":
        return nail_slab(surface, polygon, inner, outer, neutral, poses, join)
    # The TPU body and side tab are unions of rectangles in the developed
    # chart. Partition at every U edge so no invented stretch is needed.
    levels = sorted(set(x for x, _ in polygon.exterior.coords))
    rectangles, solids = [], []
    arc = surface.offset_arc(neutral)
    for x0, x1 in zip(levels, levels[1:]):
        if x1-x0 < 1e-6:
            continue
        section = polygon.intersection(LineString([[(x0+x1)/2, -1000], [(x0+x1)/2, 1000]]))
        pieces = [section] if section.geom_type == "LineString" else list(section.geoms)
        for piece in pieces:
            if piece.length < 1e-8:
                continue
            _, lo, _, hi = piece.bounds
            rectangle = box(x0, lo, x1, hi)
            rectangles.append(rectangle)
            if lo < arc[0]-1e-6 or hi > arc[-1]+1e-6:
                raise ValueError("Side tab leaves the retained curved surface chart")
            s0, s1 = np.interp([lo, hi], arc, surface.s)
            coordinates = np.r_[s0, samples[(samples > s0+1e-5) & (samples < s1-1e-5)], s1]
            low = surface.points(np.zeros(len(coordinates)), coordinates, inner)[:, 1:]
            high = surface.points(np.zeros(len(coordinates)), coordinates, outer)[:, 1:]
            profile = Polygon(np.vstack((low, high[::-1])))
            if not profile.is_valid:
                raise ValueError("Invalid formed foil section")
            solids.append(yz_prism(profile, -7.5+x0, x1-x0))
    if polygon.symmetric_difference(unary_union(rectangles)).area > 1e-6 or not solids:
        raise ValueError("A nonrectangular curved foil needs a different forming construction")
    return solids[0].fuse(*solids[1:]).clean() if len(solids) > 1 else solids[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("foil_geometry", type=Path)
    parser.add_argument("--sites", type=int, nargs="+", default=list(range(6)))
    args = parser.parse_args()
    source = args.foil_geometry.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/capacitive/foil_runs"):
        parser.error("Use a saved K1 foil geometry run")
    if len(set(args.sites)) != len(args.sites) or any(s not in range(6) for s in args.sites):
        parser.error("Choose distinct sites 0..5")
    report_path = source / "report.json"
    geometry = json.loads(report_path.read_text())
    for name, expected in geometry["input_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Foil geometry no longer matches its inputs")
    cfg, surfaces = load()
    poses = json.loads(POSES.read_text())
    folder = ROOT / "build/engineering/prototypes/capacitive/foil_fit" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Build actual K1 source-finger foil envelopes including solder lands and stiffeners; check every source/peer/stack intersection before accepting the initial tail directions") as record:
        folder.mkdir(parents=True, exist_ok=False)
        for path in (CONFIG, POSES, Path(__file__), ROOT / "engineering/scripts/capacitive_tail_geometry.py", report_path):
            destination = folder / "inputs" / path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, destination)
        hard, hard_receipt = source_solid("hard_frame")
        soft_mesh, profile, _ = original_profile()
        soft = extruded_profile(profile)
        if abs(soft.Volume()-soft_mesh.volume) > soft_mesh.volume*1e-5:
            raise ValueError("TPU source solid differs from its mesh")
        parts, models, shapes, bindings, checks = [], [], {}, [], []
        cells = {}
        forming_checks = []
        record["parts"] = parts
        for entry in geometry["boards"]:
            if entry["site"] == "REF":
                continue
            data_path = source / entry["file"]
            if digest(data_path) != entry["sha256"]:
                raise ValueError("Foil geometry changed")
            data = json.loads(data_path.read_text())
            site = int(entry["site"][2:]); surface = surfaces[site]
            if site not in args.sites:
                continue
            positions = offsets(site, cfg); neutral = data["neutral_offset_mm"]
            domains = {"foil": Polygon(data["outline_flat_mm"]),
                       "stiffener": Polygon(data["stiffener_flat_mm"])}
            for p in data["pads"]:
                x0, y0, x1, y1 = Polygon(p["outline_mm"]).bounds
                domains["joint_"+str(p["pin"])] = box(x0-.2, y0-.2, x1+.2, y1+.2)
            extra = [y for domain in domains.values() for _, y in domain.exterior.coords]
            arc = surface.offset_arc(neutral)
            raw_samples = np.unique(np.r_[surface.s, np.interp(extra, arc, surface.s)])
            retained = [raw_samples[0]]
            for value in raw_samples[1:]:
                if value-retained[-1] > 1e-5:
                    retained.append(value)
            samples = np.asarray(retained)
            join = data["tail"]["origin_flat_mm"][1]
            if site < 2 and poses["nail_free_bend_length_mm"] > data["tail"]["length_mm"]-cfg["electrode_design"]["sensor_stiffener_length_mm"]+1e-9:
                raise ValueError("Nail bend would enter the stiffened terminal")
            roles = [
                ("foil", domains["foil"], positions["flex_bottom"], positions["flex_top"],
                 "0.186 mm PI/Cu/coverlay envelope; native artwork governs real copper and terminal openings"),
                ("stiffener", domains["stiffener"],
                 positions["flex_bottom"]-cfg["electrode_design"]["stiffener_adhesive_mm"]-cfg["electrode_design"]["stiffener_polyimide_mm"],
                 positions["flex_bottom"]-cfg["electrode_design"]["stiffener_adhesive_mm"],
                 "200 µm polyimide stiffener; separately formed cut geometry remains to be specified"),
                ("stiffener_bond", domains["stiffener"], positions["flex_bottom"]-cfg["electrode_design"]["stiffener_adhesive_mm"],
                 positions["flex_bottom"], "50 µm stiffener bond envelope")]
            for pin in (1, 2):
                roles.append(("joint_"+str(pin), domains["joint_"+str(pin)], positions["flex_top"],
                              positions["flex_top"]+.6, "Conservative solder/wire-root envelope, not a printed component"))
            for role, domain, inner, outer, purpose in roles:
                shape = mapped_slab(surface, domain, inner, outer, neutral, samples, poses, join)
                name = f"k1_ch{site}_{role}"
                if surface.kind == "nail":
                    expected = domain.area*(outer-inner)
                    difference = abs(shape.Volume()-expected)
                    if difference > expected*.0001:
                        raise ValueError("The nail forming map does not preserve material volume")
                    forming_checks.append({"id": name, "expected_volume_mm3": expected,
                                          "volume_difference_mm3": difference,
                                          "relative_to_same_flat_outline": True})
                mesh = export_part(shape, name, folder, parts, purpose, "Geometry reference; physical fit remains untested", "reference_only")
                shapes[name] = shape
                models.append(packed(mesh, name, role, {"foil": "#679b8c", "stiffener": "#8d9cba",
                                                         "stiffener_bond": "#c2b27e"}.get(role, "#ca9464")))
                bindings.append({"id": name, "site": site, "role": role, "domain": domain, "inner": inner, "outer": outer})
            if surface.kind == "tpu":
                curvature = surface.curvature()
                jacobian = min(float(np.min(1+curvature*v)) for v in (
                    positions["flex_bottom"]-.25, max(positions["flex_top"]+.6, positions["cover_top"])))
                if jacobian <= .05:
                    raise ValueError("Offset chart may fold; do not use material-coordinate separation")
            else:
                _, radius = bend_parameters(poses)
                if max(abs(positions["flex_bottom"]-.25-neutral), abs(positions["flex_top"]+.6-neutral)) >= radius:
                    raise ValueError("Nail normal-offset chart may fold")
            cells[site] = {"body": Polygon(data["body_flat_mm"]), "flex_top": positions["flex_top"],
                          "cover_top": positions["cover_top"]}
            print(f"CH{site}: foil, backing and solder envelopes generated", flush=True)
        stack_keepouts = []
        for surface in surfaces:
            positions = offsets(surface.site, cfg)
            shape = slab(surface, surface.body, positions["flex_top"]+.001, positions["cover_top"])
            stack_keepouts.append((f"CH{surface.site}_cell_stack_keepout", shape))
        for index, binding in enumerate(bindings):
            name, shape = binding["id"], shapes[binding["id"]]
            for other, solid in (("source_hard", hard), ("source_TPU", soft)):
                checks.append(check_pair(name, shape, other, solid))
            for other, solid in stack_keepouts:
                if other == f"CH{binding['site']}_cell_stack_keepout":
                    cell = cells[binding["site"]]
                    if (binding["outer"] <= cell["flex_top"]+.001 or
                            binding["domain"].intersection(cell["body"]).area < 1e-9):
                        checks.append({"a": name, "b": other, "method": "disjoint_injective_material_coordinates",
                                       "overlap_mm3": 0, "passed": True})
                        continue
                checks.append(check_pair(name, shape, other, solid))
            for second in bindings[index+1:]:
                if binding["site"] == second["site"]:
                    separate_height = binding["outer"] <= second["inner"] or second["outer"] <= binding["inner"]
                    separate_domain = binding["domain"].intersection(second["domain"]).area < 1e-9
                    if separate_height or separate_domain:
                        checks.append({"a": name, "b": second["id"], "method": "disjoint_injective_material_coordinates",
                                       "overlap_mm3": 0, "passed": True})
                        continue
                checks.append(check_pair(name, shape, second["id"], shapes[second["id"]]))
            (folder / "partial_checks.json").write_text(json.dumps(checks, indent=2)+"\n")
            print(name+f": source and peer checks complete; {sum(not c['passed'] for c in checks)} findings", flush=True)
        failures = [c for c in checks if not c["passed"]]
        report = {"schema": "yam-k1-foil-fit/1", "source_geometry_sha256": digest(report_path),
                  "sites_checked": args.sites, "pose_configuration": poses, "pose_sha256": digest(POSES),
                  "nail_volume_checks": forming_checks,
                  "parts": parts, "checks": checks, "failures": failures,
                  "passed_declared_checks": not failures, "source_hard_conversion": hard_receipt,
                  "physical_specimens_tested": 0,
                  "limits": ["Nominal shaped nail tails and conforming TPU side tabs; cable slack and moving-source behavior remain.",
                             "Known same-cell layers use disjoint material domains or thickness intervals in an injective chart; source and other-cell comparisons use native solids.",
                             "Common curve samples closer than 0.00001 mm are consolidated to avoid duplicate CAD vertices.",
                             "Solder and stiffener envelopes must clear the complete source finger and every other cell stack.",
                             "Curved stiffener fabrication and strain at the plated transition are not qualified by a geometric fit check."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "checks": len(checks),
                            "failures": failures, "passed_declared_checks": not failures}
        print(json.dumps(record["result"], indent=2))
        if failures:
            raise ValueError("Revise the K1 tail directions or envelopes before release")


if __name__ == "__main__":
    main()
