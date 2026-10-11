#!/usr/bin/python3
"""Write K1 flex fabrication geometry as editable native KiCad boards."""

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
from shapely.geometry import Point, Polygon
from tactile_kit.records import execution
from flex_artwork import number, xy, coords
from screen_f1_feedback import digest


def write(data, destination):
    name, stack = data["name"], data["stack"]
    destination.mkdir(parents=True, exist_ok=False)
    library = destination / "K1Flex.pretty"; library.mkdir()
    text = ['(kicad_pcb (version 20240108) (generator "yam_k1_flex")',
            f'(general (thickness {number(data["stack_total_mm"])})) (paper "A4")',
            '(layers (0 "F.Cu" signal) (31 "B.Cu" signal)'
            ' (34 "B.Paste" user) (35 "F.Paste" user)'
            ' (36 "B.SilkS" user) (37 "F.SilkS" user)'
            ' (38 "B.Mask" user) (39 "F.Mask" user)'
            ' (40 "Dwgs.User" user) (41 "Cmts.User" user)'
            ' (44 "Edge.Cuts" user) (46 "B.CrtYd" user) (47 "F.CrtYd" user)'
            ' (48 "B.Fab" user) (49 "F.Fab" user))',
            '(setup (pad_to_mask_clearance 0.03)',
            ' (stackup',
            '  (layer "F.SilkS" (type "Top Silk Screen"))',
            '  (layer "F.Paste" (type "Top Solder Paste"))',
            f'  (layer "F.Mask" (type "Coverlay") (thickness {number(stack["coverlay_each_mm"])}) (material "Polyimide coverlay including adhesive") (epsilon_r {number(stack["coverlay_relative_permittivity_assumed"])}))',
            f'  (layer "F.Cu" (type "copper") (thickness {number(stack["copper_each_mm"])}))',
            f'  (layer "dielectric 1" (type "core") (thickness {number(stack["polyimide_core_mm"])}) (material "Polyimide") (epsilon_r {number(stack["polyimide_relative_permittivity_assumed"])}))',
            f'  (layer "B.Cu" (type "copper") (thickness {number(stack["copper_each_mm"])}))',
            f'  (layer "B.Mask" (type "Coverlay") (thickness {number(stack["coverlay_each_mm"])}) (material "Polyimide coverlay including adhesive") (epsilon_r {number(stack["coverlay_relative_permittivity_assumed"])}))',
            '  (layer "B.Paste" (type "Bottom Solder Paste"))',
            '  (layer "B.SilkS" (type "Bottom Silk Screen"))',
            '  (copper_finish "ENIG") (dielectric_constraints no)))',
            '(net 0 "") (net 1 "CIN") (net 2 "SHLD")']
    footprint = [
        '(footprint "K1Flex:Foil" (layer "F.Cu") (at 0 0)'
        ' (attr board_only exclude_from_pos_files exclude_from_bom)',
        '(property "Reference" "FOIL" (at 0 0) (layer "F.Fab") hide'
        ' (effects (font (size 1 1) (thickness 0.15))))',
        f'(property "Value" "{name}" (at 0 0) (layer "F.Fab") hide'
        ' (effects (font (size 1 1) (thickness 0.15))))']
    nets = {"CIN": 1, "SHLD": 2}
    for item in data["regions"]:
        shape = Polygon(item["outline_mm"])
        interior = shape.buffer(-.01)
        if interior.is_empty:
            raise ValueError("No safe anchor inside custom copper")
        point = interior.representative_point()
        anchor = (point.x, point.y)
        if not shape.covers(Point(anchor).buffer(.005)):
            raise ValueError("Native custom-pad anchor would alter copper")
        footprint.append(
            f'(pad "{item["id"]}_COPPER" smd custom (at {xy(anchor)})'
            f' (size 0.01 0.01) (layers "{item["layer"]}")'
            f' (net {nets[item["net"]]} "{item["net"]}")'
            ' (options (clearance outline) (anchor circle))'
            f' (primitives (gr_poly (pts {coords(shape, anchor)}) (width 0) (fill yes))))')
    for item in data["pads"]:
        shape = Polygon(item["outline_mm"])
        x0, y0, x1, y1 = shape.bounds
        footprint.append(
            f'(pad "{item["pin"]}" smd rect (at {xy(item["center"])})'
            f' (size {xy([x1-x0, y1-y0])}) (layers "F.Cu" "F.Mask")'
            f' (net {nets[item["net"]]} "{item["net"]}"))')
    via = data["via"]
    footprint.append(
        f'(pad "SHIELD_TRANSITION" thru_hole circle (at {xy(via["center"])})'
        f' (size {number(via["pad_mm"])} {number(via["pad_mm"])})'
        f' (drill {number(via["drill_mm"])}) (layers "*.Cu") (net 2 "SHLD"))')
    footprint.append(")")
    text.extend(footprint)
    # A fabrication-layer outline marks the separate back stiffener. It is
    # not a copper, mask or routed cut feature.
    stiffener = Polygon(data["stiffener_flat_mm"])
    text.append(f'(gr_poly (pts {coords(stiffener)}) (stroke (width 0.1) (type default)) (fill none) (layer "B.Fab"))')
    outline = Polygon(data["outline_flat_mm"])
    for a, b in zip(outline.exterior.coords, list(outline.exterior.coords)[1:]):
        text.append(f'(gr_line (start {xy(a)}) (end {xy(b)}) (stroke (width 0.05) (type default)) (layer "Edge.Cuts"))')
    text.append(")")
    board = destination / (name+".kicad_pcb")
    board.write_text("\n".join(text)+"\n")
    module = "\n".join(footprint).replace('"K1Flex:Foil"', '"Foil"', 1)
    import re
    module = re.sub(r' \(net \d+ "[^"]*"\)', "", module)
    (library / "Foil.kicad_mod").write_text(module+"\n")
    (library / "ATTRIBUTION.md").write_text(
        "K1 sensing copper, driven guards, termination lands and plated transition are authored for this MIT-licensed kit. "
        "The contact outline is derived from the retained ENPIRE/R1 geometry; source attribution and hashes are in the design package.\n")
    (destination / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "K1Flex") (type "KiCad") (uri "${KIPRJMOD}/K1Flex.pretty") '
        '(options "") (descr "K1 guarded sensor foil and hand-solder lands")))\n')
    (destination / (name+".kicad_dru")).write_text(
        '(version 1)\n'
        '(rule "K1 flex copper clearance" (constraint clearance (min 0.20mm)))\n'
        '(rule "K1 flex copper to edge" (constraint edge_clearance (min 0.30mm)))\n'
        '(rule "K1 flex trace width" (constraint track_width (min 0.20mm)))\n'
        '(rule "K1 plated drill" (constraint hole_size (min 0.30mm)))\n'
        '(rule "K1 copper to drill" (constraint hole_clearance (min 0.20mm)))\n')
    shutil.copyfile(Path(__file__), destination / "writer.py")
    data = dict(data, pcb_sha256=digest(board), rules_sha256=digest(destination / (name+".kicad_dru")),
                native_check_pending=True)
    (destination / (name+".json")).write_text(json.dumps(data, indent=2)+"\n")
    (destination / "FABRICATION.md").write_text(
        f"# {name}\n\n"
        f"Two-layer flexible circuit. Requested covered thickness: {data['stack_total_mm']:.3f} mm. "
        f"Core: {stack['polyimide_core_mm']:.3f} mm polyimide; copper: {stack['copper_each_mm']:.3f} mm each face; "
        f"coverlay including adhesive: {stack['coverlay_each_mm']:.3f} mm each face. "
        "Confirm the supplied stack with the fabricator. F.Mask/B.Mask describe coverlay, not a substitute rigid-board solder-mask process.\n\n"
        "F.Cu contains the sensing electrode and its driven guard. B.Cu is driven SHLD; it is not ground. "
        "Only the two top terminal lands are opened. No solder paste is generated. Hand-solder land 1 to CIN and land 2 to SHLD. "
        "The reference foil is made twice and connects its shield to SHLD2; the other foils use SHLD1.\n\n"
        f"The B.Fab outline marks a separate {data['stiffener_polyimide_mm']:.2f} mm polyimide stiffener with "
        f"{data['stiffener_adhesive_mm']:.2f} mm adhesive. Its thickness is additional to the flex stack. "
        "The back stiffener covers the plated transition. Keep wire loads off the pressure area and the free bend. "
        "Label the stiffener with the cell identity during assembly.\n\n"
        "Native DRC, board/material review, formed fit and physical bring-up remain required before use. "
        "These files are not a measured force or contact result.\n")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("geometry", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    source, target = args.geometry.resolve(), args.destination.resolve()
    if (not source.is_relative_to(ROOT / "build/engineering/prototypes/capacitive")
            or not target.is_relative_to(ROOT / "build") or target.exists()):
        parser.error("Use a saved K1 geometry run and a fresh generated destination")
    manifest = json.loads((source / "report.json").read_text())
    with execution(ROOT / "build/records", "Write seven editable K1 native flex boards with explicit polyimide stack, sensing/guard copper, separate solder windows and one backed shield transition; no DRC waivers") as record:
        target.mkdir(parents=True, exist_ok=False)
        boards = []
        for item in manifest["boards"]:
            path = source / item["file"]
            if digest(path) != item["sha256"]:
                raise ValueError("Saved foil geometry changed")
            data = json.loads(path.read_text())
            row = write(data, target / data["name"])
            boards.append({"name": data["name"], "site": data["site"], "directory": data["name"],
                           "pcb_sha256": row["pcb_sha256"], "geometry_sha256": digest(path)})
        report = {"schema": "yam-k1-native-flex-set/1", "source_geometry_report_sha256": digest(source / "report.json"),
                  "boards": boards, "physical_specimens_tested": 0, "native_checks_pending": True}
        (target / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(target.relative_to(ROOT)), "boards": len(boards), "native_checks_pending": True}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
