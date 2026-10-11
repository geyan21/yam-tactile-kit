#!/usr/bin/python3
"""Build a K1 bank case around the checked PCB and the actual protected reference cell."""

import argparse
from datetime import datetime, timezone
import json
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
from tactile_kit.records import execution
from capacitive_geometry import CONFIG, load, reference_footprints
from prototype_cad import block, export_part, packed
from build_f1_stack_parts import slab
from check_f1_tail_fit import check_pair
from screen_f1_feedback import digest

CASE = ROOT / "engineering/designs/capacitive_enclosure.json"
BOARD = ROOT / "engineering/development/capacitive/k1/pcb/k1_readout.json"


def cylinder(x, y, z, radius, height):
    return cq.Solid.makeCylinder(radius, height, cq.Vector(x, y, z), cq.Vector(0, 0, 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mechanics", type=Path)
    parser.add_argument("foils", type=Path)
    args = parser.parse_args()
    mechanics = args.mechanics.resolve(); foils = args.foils.resolve()
    mech = json.loads((mechanics / "report.json").read_text())
    layouts = json.loads((foils / "report.json").read_text())
    for report in (mech, layouts):
        for name, expected in report["input_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError("K1 input changed: "+name)
    ref_entry = next(b for b in layouts["boards"] if b["site"] == "REF")
    ref_path = foils / ref_entry["file"]
    if digest(ref_path) != ref_entry["sha256"]:
        raise ValueError("Reference foil changed")
    ref = json.loads(ref_path.read_text())
    cfg, _ = load(); case = json.loads(CASE.read_text()); board = json.loads(BOARD.read_text())
    folder = ROOT / "build/engineering/prototypes/capacitive/enclosure" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Build the K1 bank enclosure and protected-reference support against the checked PCB holes and actual reference CAD; retain a separate measured drive-bracket requirement") as record:
        folder.mkdir(parents=True)
        inputs = [CASE, BOARD, CONFIG, Path(__file__), mechanics / "report.json", foils / "report.json", ref_path]
        for path in inputs:
            destination = folder / "inputs" / path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, destination)
        sx, sy = case["outer_xy_mm"]; wall, base = case["wall_mm"], case["base_mm"]
        rim = base+case["inside_height_mm"]
        px, py, pz = case["pcb_origin_xyz_mm"]; ptop = pz+case["pcb_thickness_mm"]
        body = block(0, sx, 0, sy, 0, rim).cut(block(wall, sx-wall, wall, sy-wall, base, rim+1))
        board_shape = block(px, px+42, py, py+38, pz, ptop)
        pcb_holes = []
        for hole in board["holes"]:
            x, y = np.asarray(hole["center_mm"])+[px, py]
            pcb_holes.append([x, y])
            body = body.fuse(cylinder(x, y, base-.1, case["pcb_post_diameter_mm"]/2, pz-base+.1))
            body = body.cut(cylinder(x, y, .8, case["pcb_post_pilot_mm"]/2, pz+.2))
            board_shape = board_shape.cut(cylinder(x, y, pz-.1, hole["diameter_mm"]/2, case["pcb_thickness_mm"]+.2))
        lid = block(0, sx, 0, sy, rim, rim+case["lid_mm"])
        for x, y in case["lid_screws_xy_mm"]:
            body = body.fuse(cylinder(x, y, base-.1, case["lid_boss_diameter_mm"]/2, rim-base+.1))
            body = body.cut(cylinder(x, y, rim-6, case["lid_pilot_mm"]/2, 7))
            lid = lid.cut(cylinder(x, y, rim-.1, case["lid_clearance_mm"]/2, case["lid_mm"]+.2))
        for y in case["cable_port_centres_y_mm"]:
            w = case["cable_port_width_y_mm"]/2
            lo, hi = case["cable_port_z_mm"]
            body = body.cut(block(-.1, wall+.1, y-w, y+w, lo, hi))
            # Separate slots route a tie through the wall and around only
            # the insulated harness jackets outside the electrical joints.
            tw = case["tie_slot_width_y_mm"]/2
            lo, hi = case["tie_slot_z_mm"]
            for offset in (-2.25, 2.25):
                body = body.cut(block(-.1, wall+.1, y+offset-tw, y+offset+tw, lo, hi))
        # JP is a four-wire solder port near the opposite edge.
        body = body.cut(block(px+29, px+39, sy-wall-.1, sy+.1, 7, 12))
        for x in (px+29.5, px+37.5):
            body = body.cut(block(x-1.5, x+1.5, sy-wall-.1, sy+.1, 4, 5.5))
        tab_holes = []
        for x0, x1, cx in ((-8, .2, -4), (sx-.2, sx+8, sx+4)):
            tab = block(x0, x1, sy/2-6, sy/2+6, 0, base)
            tab = tab.cut(cylinder(cx, sy/2, -.1, case["mount_tab_hole_mm"]/2, base+.2))
            body = body.fuse(tab); tab_holes.append([cx, sy/2])
        body, lid = body.clean(), lid.clean()
        ref_bottom = ptop+case["reference_mount_mm"]+case["reference_bond_mm"]
        support = block(px+24.5, px+38.5, py+5.7, py+17.7, ptop, ptop+case["reference_mount_mm"])
        bond = block(px+24.5, px+38.5, py+5.7, py+17.7,
                     ptop+case["reference_mount_mm"], ref_bottom)
        # Source REF coordinates are (100+u, -s, n). Rotate about Z
        # so the short foil tail faces the JREF solder lands.
        def place_reference(shape):
            return shape.rotate((0, 0, 0), (0, 0, 1), 180).translate((px+131.5, py+5.7, ref_bottom))
        ref_body, ref_active = reference_footprints(cfg)
        surface = SimpleNamespace(kind="nail", origin=np.array([100., 0., 0.]),
                                  u=np.array([1., 0., 0.]), t=np.array([0., -1., 0.]), n=np.array([0., 0., 1.]))
        flex_total = 2*cfg["flex"]["copper_each_mm"]+cfg["flex"]["polyimide_core_mm"]+2*cfg["flex"]["coverlay_each_mm"]
        reference_parts = []
        for role, domain, lo, hi in (
                ("foil", Polygon(ref["outline_flat_mm"]), 0, flex_total),
                ("stiffener", Polygon(ref["stiffener_flat_mm"]), -.25, -.05),
                ("stiffener_bond", Polygon(ref["stiffener_flat_mm"]), -.05, 0)):
            reference_parts.append(("reference_"+role, place_reference(slab(surface, domain, lo, hi))))
        for part in mech["parts"]:
            if not part["id"].startswith("k1_ref_"):
                continue
            path = mechanics / part["step"]
            if digest(path) != part["sha256_step"]:
                raise ValueError("Reference CAD changed")
            reference_parts.append(("reference_"+part["id"][7:], place_reference(cq.importers.importStep(str(path)).val())))
        for pad in ref["pads"]:
            x0, y0, x1, y1 = Polygon(pad["outline_mm"]).bounds
            reference_parts.append(("reference_joint_"+str(pad["pin"]),
                                    place_reference(slab(surface, box(x0-.2, y0-.2, x1+.2, y1+.2), flex_total, flex_total+.6))))
        # Fixed conservative envelopes leave the actual component/lead
        # tolerances to an assembled-board fit witness.
        components = []
        for part in board["parts"]:
            if part["reference"].startswith("J"):
                continue
            x, y = np.asarray(part["center_mm"])+[px, py]
            dx, dy, dz = (5.2, 3.3, 1.2) if part["reference"].startswith("U") else (2.2, 1.3, 1.1)
            components.append((part["reference"], block(x-dx/2, x+dx/2, y-dy/2, y+dy/2, ptop, ptop+dz)))
        checks = [check_pair("case", body, "lid", lid), check_pair("case", body, "pcb", board_shape),
                  check_pair("lid", lid, "pcb", board_shape)]
        for name, shape in [("reference_support", support), ("reference_mount_bond", bond), *reference_parts, *components]:
            for other_name, other in (("case", body), ("lid", lid), ("pcb", board_shape)):
                checks.append(check_pair(name, shape, other_name, other))
        for name, shape in reference_parts:
            for other_name, other in components:
                checks.append(check_pair(name, shape, other_name, other))
        if not all(row["passed"] for row in checks):
            (folder / "failed_checks.json").write_text(json.dumps(checks, indent=2)+"\n")
            raise ValueError("Enclosure/reference interference; see retained findings")
        parts, models = [], []
        physical = [("bank_case", body, "print", case["material"]),
                    ("bank_lid", lid, "print", case["material"]),
                    ("reference_support", support, "print", case["material"]),
                    ("reference_mount_bond", bond, "reference_only", "50 µm insulating adhesive; qualify adhesion"),
                    ("pcb_envelope", board_shape, "reference_only", "1 mm checked PCB reference")]
        physical += [(name, shape, "reference_only", "Placed source reference CAD") for name, shape in reference_parts]
        physical += [("component_"+name, shape, "reference_only", "Conservative component clearance envelope") for name, shape in components]
        for name, shape, kind, material in physical:
            mesh = export_part(shape, "k1_"+name, folder, parts, name.replace("_", " "), material, kind)
            models.append(packed(mesh, "k1_"+name, name, "#639b8b" if kind == "print" else "#adbaa3"))
        report = {"schema": "yam-k1-enclosure/1", "parts": parts, "checks": checks, "passed": True,
                  "quantity_per_finger": 2, "physical_specimens_tested": 0,
                  "pcb_mount_xy_mm": pcb_holes, "case_mount_xy_mm": tab_holes,
                  "pcb_top_z_mm": ptop, "reference_foil_bottom_z_mm": ref_bottom,
                  "minimum_reference_to_lid_clearance_mm": min(lid.distance(shape) for _, shape in reference_parts),
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "hardware": case["hardware"], "limits": case["limits"]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "checks": len(checks)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
