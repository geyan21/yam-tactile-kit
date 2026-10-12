#!/usr/bin/python3
"""Build the P1 board carrier and retained R1 N0 nail envelopes with fit checks."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/pneumatic-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import cadquery as cq
import numpy as np
from prototype_cad import block, export_part, packed
from source_brep import load as source_solid
from build_pneumatic_ported_assembly import cyl, overlap
from screen_f1_feedback import digest
from tactile_kit.records import execution


def hexagon(center, across_flats, z, height):
    radius = across_flats/math.sqrt(3)
    points = [(center[0]+radius*math.cos(math.pi/6+i*math.pi/3),
               center[1]+radius*math.sin(math.pi/6+i*math.pi/3)) for i in range(6)]
    return cq.Workplane("XY", origin=(0, 0, z)).polyline(points).close().extrude(height).val()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, required=True)
    args = parser.parse_args()
    source = args.board.resolve()
    if not source.is_relative_to(ROOT/"build"):
        parser.error("Use a generated board from this checkout")
    board = json.loads((source/"p1_readout.json").read_text())
    check = json.loads((source/"latest_check.json").read_text())
    if check["violations"] or check["unconnected"] or check["source_sha256"] != digest(source/"p1_readout.kicad_pcb"):
        raise ValueError("Use the unchanged board with a complete passing native check")
    r1_path = ROOT/"engineering/release/r1/r1_manifest.json"
    nail_path = ROOT/"engineering/release/contact_regions/contact_report.json"
    r1, nail = json.loads(r1_path.read_text()), json.loads(nail_path.read_text())
    hard, hard_receipt = source_solid("hard_frame")
    folder = ROOT/"build/engineering/prototypes/pneumatic/bench_parts"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Build an insulated P1 bench carrier around the checked board and explicit retained R1 N0 nail envelopes; check ideal source and component intersections") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [Path(__file__), ROOT/"engineering/scripts/prototype_cad.py", ROOT/"engineering/scripts/source_brep.py",
                  source/"p1_readout.json", source/"p1_readout.kicad_pcb", source/"latest_check.json", r1_path, nail_path]
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        parts, models, solids = [], [], []
        def add(name, shape, purpose, material, kind="fabricate", group="p1_bench", color="#96a59b"):
            mesh = export_part(shape, name, folder, parts, purpose, material, kind)
            models.append(packed(mesh, name, group, color))
            solids.append((name, shape, group))
        offset = np.array([15., 3.])
        holes = [np.asarray(h["center"])+offset for h in board["holes"]]
        # Feet leave screw tips clear of the bench; nuts are reached from below.
        base = block(0, 110, 0, 92, 3, 6)
        for x, y in ((2, 2), (108, 2), (2, 90), (108, 90)):
            base = base.fuse(cyl(2, 3, [x, y, 0], [0, 0, 1]))
        for point in holes:
            base = base.fuse(cyl(3, 6, [*point, 6], [0, 0, 1]))
            base = base.cut(cyl(1.2, 12, [*point, 0], [0, 0, 1]))
            base = base.cut(hexagon(point, 4.4, 3, 1.9))
        # Loose cable-tie loops secure bundles without creating a hard hose clamp.
        for x in (6., 104.):
            for y in (12., 18., 40., 46.):
                for delta in (-2., 2.):
                    base = base.cut(block(x-.9, x+.9, y+delta-.7, y+delta+.7, 2.9, 6.1))
        add("p1_bench_carrier", base.clean(), "Printed 110x92 mm board carrier; 6 mm standoffs, nut pockets, feet and loose hose-tie slots",
            "PETG or equivalent insulating rigid print; verify actual holes and nut fit")
        pcb = block(15, 95, 3, 89, 12, 13.6)
        for pad in board["pads"]:
            if pad.get("drill"):
                center = np.asarray(pad["center"])+offset
                pcb = pcb.cut(cyl(pad["drill"]/2, 2, [*center, 11.9], [0, 0, 1]))
        for hole, point in zip(board["holes"], holes):
            pcb = pcb.cut(cyl(hole["diameter"]/2, 2, [*point, 11.9], [0, 0, 1]))
        add("p1_readout_pcb_reference", pcb.clean(), "FR4 outline and exact drilled holes from the checked readout; copper/components are separate",
            "1.6 mm four-layer FR4, nominal 35um copper", "reference_only", color="#376a5c")
        for index, point in enumerate(holes):
            washer = cyl(2.25, .5, [*point, 13.6], [0, 0, 1]).cut(cyl(1.1, .5, [*point, 13.6], [0, 0, 1]))
            screw = cyl(1, 12, [*point, 2.1], [0, 0, 1]).fuse(cyl(1.9, 2, [*point, 14.1], [0, 0, 1]))
            nut = hexagon(point, 4., 3.2, 1.6).cut(cyl(1., 1.6, [*point, 3.2], [0, 0, 1]))
            add(f"p1_board_washer_{index}", washer, "M2 washer envelope: OD4.5, ID2.2, thickness0.5 mm", "Measured M2 washer", "reference_only", color="#87969d")
            add(f"p1_board_screw_{index}", screw, "M2x12 screw, 3.8 mm head envelope; thread form not modeled", "M2x12 metal fastener", "reference_only", color="#87969d")
            add(f"p1_board_nut_{index}", nut, "M2 nut envelope: 4 mm across flats, 1.6 mm thick; thread form not modeled", "Measured M2 nut", "reference_only", color="#87969d")
        for component in board["components"]:
            if "body_mm" not in component or component["height_mm"] <= 0:
                continue
            x, y = np.asarray(component["center_mm"])+offset
            width, height = component["body_mm"]
            shape = block(-width/2, width/2, -height/2, height/2, 0, component["height_mm"])
            shape = shape.rotate((0, 0, 0), (0, 0, 1), -component["rotation_deg"]).translate((x, y, 13.6))
            add("p1_"+component["reference"]+"_body_reference", shape,
                "Nominal component body/clearance envelope: "+component["value"],
                "Purchased component reference; inspect actual body, leads and port geometry", "reference_only",
                color="#667f9a" if component["reference"].startswith("PS") else "#ad8f69")
        add("p1_pico_body_reference", block(44.5, 65.5, 7.63, 58.63, 22.1, 23.1),
            "Original Pico PCB envelope over the two 8.5 mm socket bodies; USB clearance is open at the top",
            "Original RP2040 Pico; inspect installed header height", "reference_only", color="#376a5c")
        u, v = np.asarray(nail["nail_plane_u_axis_native"]), np.asarray(nail["nail_plane_v_axis_native"])
        origin = np.asarray(nail["nail_plane_origin_native_mm"])
        normal = np.cross(u, v)
        nail_checks = []
        for cell in r1["nail_active_cells"]:
            for suffix, low, high, material in (
                    ("mount", 0., .1, "Conformal mounting adhesive envelope, nominal 0.1 mm"),
                    ("n0_laminate", .1, .4, "Retained R1 N0 insulating/foil/pressure-film laminate envelope")):
                plane = cq.Plane(origin=tuple(origin+low*normal), xDir=tuple(u), normal=tuple(normal))
                shape = cq.Workplane(plane).polyline(cell["outer"][:-1]).close().extrude(high-low).val()
                # This is the retained R1 nominal laminate/adhesive envelope
                # on the recovered planar nail. Subtracting the numerically
                # coplanar faceted frame produces degenerate sliver edges;
                # retain the envelope and measure its actual common volume.
                name = f"p1_ch{cell['id']}_"+suffix
                add(name, shape, "Retained R1 two-prong N0 construction; use the 1:1 nail cut sheet and separate continuity resistor",
                    material, "reference_only", "p1_nails", "#c39c63")
                nail_checks.append({"a": name, "b": "source_hard", "overlap_mm3": overlap(shape, hard)})
        checks = list(nail_checks)
        for index, (name, shape, group) in enumerate(solids):
            for other_name, other, other_group in solids[index+1:]:
                if group == other_group:
                    checks.append({"a": name, "b": other_name, "overlap_mm3": overlap(shape, other)})
        failures = [row for row in checks if row["overlap_mm3"] > .001]
        report = {"schema": "yam-p1-bench-and-nails/1", "parts": parts, "checks": checks, "failures": failures,
                  "passed_nominal_checks": not failures, "physical_specimens_tested": 0,
                  "board_origin_in_bench_mm": [15, 3, 12], "nail_added_nominal_mm": .4,
                  "source_hard_conversion": hard_receipt,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": ["Open bench carrier, not a qualified wrist or drive mount.",
                             "Electronic bodies are conservative references, not manufacturer STEP models or actual lead/port shapes.",
                             "N0 nominal thickness must be measured; the R1 sheet and assembly process are retained.",
                             "Actual hoses need loose strain relief and measured slack. Tie slots are not compression clamps."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "checks": len(checks), "failures": failures}
        print(json.dumps(record["result"], indent=2))
        if failures:
            raise ValueError("Resolve the bench or retained-nail nominal findings")


if __name__ == "__main__":
    main()
