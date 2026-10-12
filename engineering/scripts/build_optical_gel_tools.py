#!/usr/bin/python3
"""Build two gel mold halves and a curved marker stencil from the exact O1 path."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/optical-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import cadquery as cq
import numpy as np
from shapely.geometry import Polygon
from prototype_cad import block, yz_prism, export_part, packed
from build_pneumatic_ported_assembly import cyl, overlap
from screen_f1_feedback import digest
from tactile_kit.records import execution

CONFIG = ROOT/"engineering/designs/optical_molds.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("search", type=Path)
    args = parser.parse_args()
    source = args.search.resolve()
    if not source.is_relative_to(ROOT/"build"):
        parser.error("Use the selected optical path")
    plan = json.loads((source/"report.json").read_text())
    cfg = json.loads(CONFIG.read_text())
    gel_cfg_path = ROOT/"engineering/designs/optical_gel_cartridge.json"
    gel_cfg = json.loads(gel_cfg_path.read_text())
    path_cfg = json.loads((ROOT/plan["configuration"]).read_text())
    cx = path_cfg["camera_x_mm"]
    outer = np.asarray(plan["outer_gel_profile_yz_mm"])
    inner = np.asarray(plan["inner_gel_profile_yz_mm"])
    y, z = inner[:, 0], inner[:, 1]
    profile = Polygon(np.vstack((outer, inner[::-1])))
    flange = Polygon(np.vstack((np.column_stack((y, z-gel_cfg["gel_rear_flange_vertical_thickness_mm"])), inner[::-1])))
    gel = yz_prism(profile, cx-gel_cfg["gel_main_width_mm"]/2, gel_cfg["gel_main_width_mm"]).fuse(
        yz_prism(flange, cx-gel_cfg["gel_rear_flange_width_mm"]/2, gel_cfg["gel_rear_flange_width_mm"])).clean()
    folder = ROOT/"build/engineering/prototypes/optical/gel_tools"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Build the exact O1 Solaris gel cavity, rear-face mold lid, fill/vent openings and marker stencil without assuming cure or optical performance") as record:
        folder.mkdir(parents=True)
        inputs = [CONFIG, gel_cfg_path, Path(__file__), source/"report.json", ROOT/plan["configuration"],
                  ROOT/"engineering/scripts/prototype_cad.py"]
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        yy = np.r_[y[0]-cfg["y_margin_mm"], y, y[-1]+cfg["y_margin_mm"]]
        zz = np.r_[z[0], z, z[-1]]
        z0 = float(outer[:, 1].min()-cfg["bottom_wall_mm"])
        z1 = float(z.max()+cfg["lid_wall_mm"])
        x0, x1 = cfg["x_bounds_mm"]
        lower_profile = Polygon(np.vstack((np.column_stack((yy, np.full(len(yy), z0))), np.column_stack((yy, zz))[::-1])))
        upper_profile = Polygon(np.vstack((np.column_stack((yy, zz)), np.column_stack((yy, np.full(len(yy), z1)))[::-1])))
        lower = yz_prism(lower_profile, x0, x1-x0).cut(gel).clean()
        upper = yz_prism(upper_profile, x0, x1-x0)
        for bx in cfg["bolt_x_mm"]:
            for by in (yy[0]+cfg["bolt_end_margin_mm"], yy[-1]-cfg["bolt_end_margin_mm"]):
                bore = cyl(cfg["m3_clearance_mm"]/2, z1-z0+2, [bx, by, z0-1], [0, 0, 1])
                lower = lower.cut(bore); upper = upper.cut(bore)
        ports = []
        for px, ys, diameter, role in ((cx, cfg["fill_y_mm"], cfg["fill_diameter_mm"], "fill"),):
            for py in ys:
                ports.append({"x_mm": px, "y_mm": py, "diameter_mm": diameter, "purpose": role})
        for px in cfg["vent_x_mm"]:
            for py in cfg["vent_y_mm"]:
                ports.append({"x_mm": px, "y_mm": py, "diameter_mm": cfg["vent_diameter_mm"], "purpose": "vent"})
        for port in ports:
            upper = upper.cut(cyl(port["diameter_mm"]/2, z1-z0+2, [port["x_mm"], port["y_mm"], z0-1], [0, 0, 1]))
        lower, upper = lower.clean(), upper.clean()
        # A thin, flexible stencil follows the nominal object-facing surface.
        clearance, thickness = cfg["stencil_clearance_mm"], cfg["stencil_thickness_mm"]
        stencil_profile = Polygon(np.vstack((outer-[0, clearance+thickness], (outer-[0, clearance])[::-1])))
        stencil = yz_prism(stencil_profile, cx-gel_cfg["gel_main_width_mm"]/2, gel_cfg["gel_main_width_mm"])
        slope = np.gradient(outer[:, 1], outer[:, 0])
        arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(outer, axis=0), axis=1))]
        markers = []
        for py in cfg["marker_y_mm"]:
            pz = float(np.interp(py, outer[:, 0], outer[:, 1]))
            tangent = float(np.interp(py, outer[:, 0], slope))
            normal = np.array([0., tangent, -1.]); normal /= np.linalg.norm(normal)
            for px in cfg["marker_x_mm"]:
                point = np.array([px, py, pz])
                stencil = stencil.cut(cyl(cfg["marker_diameter_mm"]/2, 2, point-normal, normal))
                markers.append({"id": len(markers), "x_mm": px, "y_mm": py, "z_mm": pz,
                                "arc_mm": float(np.interp(py, outer[:, 0], arc)), "normal": normal.tolist()})
        items = [("o1_gel_mold_contact_half", lower, "Rigid cavity half, smooth object-facing surface and flange steps", "Sealed/smoothed rigid print or machined mold; cure compatibility required", "fabricate", "#92aa9d"),
                 ("o1_gel_mold_rear_half", upper, "Matching rear-face lid with four fill and four vent holes", "Sealed/smoothed rigid mold", "fabricate", "#77979d"),
                 ("o1_gel_mold_cavity_reference", gel, "Exact clear-gel cavity; cast Solaris, do not print this as a sensing replacement", "Smooth-On Solaris", "reference_only", "#a8cdb7"),
                 ("o1_marker_stencil", stencil.clean(), "Flexible curved stencil for 42 black dots, 0.6 mm target diameter", "0.2 mm flexible stencil; qualify cut/drill and conformance", "fabricate", "#ba976c")]
        parts, models = [], []
        for name, shape, purpose, material, kind, color in items:
            mesh = export_part(shape, name, folder, parts, purpose, material, kind)
            models.append(packed(mesh, name, "o1_molds", color))
        checks = [{"a": a[0], "b": b[0], "overlap_mm3": overlap(a[1], b[1])}
                  for i, a in enumerate(items[:3]) for b in items[i+1:3]]
        failures = [row for row in checks if row["overlap_mm3"] > .001]
        # A flat 1:1 drawing uses surface arc length; it is not a camera map.
        length = float(arc[-1]); width = gel_cfg["gel_main_width_mm"]
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width+12}mm" height="{length+18}mm" viewBox="0 0 {width+12} {length+18}">',
               '<rect width="100%" height="100%" fill="white"/>',
               f'<rect x="6" y="6" width="{width}" height="{length}" fill="none" stroke="black" stroke-width=".15"/>']
        for marker in markers:
            svg.append(f'<circle cx="{marker["x_mm"]-(cx-width/2)+6:.6f}" cy="{marker["arc_mm"]+6:.6f}" r="{cfg["marker_diameter_mm"]/2}" fill="black"/>')
        svg += [f'<path d="M6 {length+10}h10" stroke="black" stroke-width=".2"/>',
                f'<text x="6" y="{length+14}" font-size="2.5">10 mm • print at 100%</text>', '</svg>']
        (folder/"o1_marker_pattern.svg").write_text("\n".join(svg)+"\n")
        (folder/"markers.json").write_text(json.dumps(markers, indent=2)+"\n")
        report = {"schema": "yam-o1-gel-tools-result/1", "parts": parts, "checks": checks, "failures": failures,
                  "passed_nominal_checks": not failures, "physical_specimens_tested": 0, "ports": ports,
                  "cavity_volume_mm3": gel.Volume(), "marker_count": len(markers), "limits": cfg["limits"],
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs}}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "cavity_volume_mm3": gel.Volume(),
                            "marker_count": len(markers), "failures": failures}
        print(json.dumps(record["result"], indent=2))
        if failures:
            raise ValueError("Resolve mold intersections")


if __name__ == "__main__":
    main()
