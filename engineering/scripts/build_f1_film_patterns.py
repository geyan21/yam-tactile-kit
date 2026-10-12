#!/usr/bin/python3
"""Develop the six F1 pressure-film islands at their current material mid-surfaces."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
from shapely.geometry import Polygon
from tactile_kit.records import execution
from f1_surfaces import load_surfaces
from screen_f1_feedback import digest

CONFIG = ROOT / "engineering/designs/f1_skin_r4.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skin_run", type=Path)
    args = parser.parse_args()
    source = args.skin_run.resolve()
    plan = json.loads((source / "report.json").read_text())
    for name, expected in plan["input_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Skin source changed")
    config = json.loads(CONFIG.read_text())
    _, _, _, surfaces = load_surfaces(ROOT / config["basis_stack"])
    folder = ROOT / "build/engineering/prototypes/f1/film_patterns" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Develop six actual F1 pressure-film cut outlines at their plated-stack mid-surfaces; export 1:1 patterns with scale bars and preserve physical-forming limits") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        (folder / "patterns").mkdir()
        inputs = [Path(__file__), CONFIG, ROOT / config["basis_stack"],
                  ROOT / "engineering/scripts/f1_surfaces.py", source / "report.json"]
        patterns = []
        for case, surface in zip(plan["cases"], surfaces):
            site = case["site"]
            if site != surface.site:
                raise ValueError("Site ordering changed")
            level = (case["column_contact_mm"]+case["row_contact_mm"])/2
            arc = surface.offset_arc(level)
            domain = surface.active
            def ring(values):
                return [(float(u), float(np.interp(s, surface.s, arc))) for u, s in values]
            flat = Polygon(ring(domain.exterior.coords), [ring(r.coords) for r in domain.interiors])
            if not flat.is_valid or flat.is_empty:
                raise ValueError("Invalid developed film")
            part = next(p for p in plan["parts"] if p["id"] == f"f1_ch{site}_pressure_film")
            volume = flat.area*case["film_thickness_mm"]
            error = abs(volume-part["volume_mm3"])
            if error > max(.002, .01*part["volume_mm3"]):
                raise ValueError("Developed material volume differs by more than the declared 1%/0.002 mm3 screen")
            x0, y0, x1, y1 = flat.bounds
            width, length = x1-x0, y1-y0
            if width > 170 or length > 180:
                raise ValueError("Pattern exceeds the unscaled A4 area")
            def path_data(values):
                points = [(u-x0+25, s-y0+55) for u, s in values]
                return "M "+" L ".join(f"{x:.8f},{y:.8f}" for x, y in points)+" Z"
            d = path_data(flat.exterior.coords)+" "+" ".join(path_data(r.coords) for r in flat.interiors)
            name = f"f1_ch{site}_pressure_film_cut.svg"
            text = f'''<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" viewBox="0 0 210 297">
<rect width="210" height="297" fill="white"/>
<g font-family="sans-serif" fill="#16232b">
<text x="20" y="18" font-size="6">F1 R4 · CH{site} conductive film</text>
<text x="20" y="28" font-size="3.8">Cut one; 0.100 mm nominal identified pressure film.</text>
<text x="20" y="35" font-size="3.8">Print 100%; no page fitting. Outside outline is the cut.</text>
<text x="20" y="42" font-size="3.8">Width {width:.3f} mm · developed length {length:.3f} mm</text>
<path d="{d}" fill="#eeeeee" fill-rule="evenodd" stroke="#111111" stroke-width=".08"/>
<text x="25" y="50" font-size="3.5">Distal edge</text>
<text x="25" y="{65+length:.3f}" font-size="3.5">Toward root (increasing source S)</text>
<path d="M20 250H70 M20 247V253 M70 247V253" stroke="#111111" fill="none" stroke-width=".25"/>
<text x="20" y="260" font-size="4">50.000 mm scale bar</text>
<text x="20" y="273" font-size="3.5">Mid-surface reference; actual forming and thickness unmeasured.</text>
<text x="20" y="280" font-size="3.5">Keep adhesive out of the active film-to-metal contacts.</text>
</g></svg>
'''
            (folder / "patterns" / name).write_text(text)
            patterns.append({"site": site, "file": "patterns/"+name, "sha256": digest(folder / "patterns" / name),
                             "flat_outline_mm": list(flat.exterior.coords), "flat_holes_mm": [list(r.coords) for r in flat.interiors],
                             "width_mm": width, "developed_length_mm": length, "area_mm2": flat.area,
                             "mid_surface_offset_mm": level, "thickness_mm": case["film_thickness_mm"],
                             "developed_volume_mm3": volume, "volume_error_mm3": error, "volume_screen_passed": True})
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        report = {"schema": "yam-f1-film-cut-patterns/1", "physical_specimens_tested": 0, "patterns": patterns,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": ["Nominal mid-surface cuts, not a measured mechanical neutral surface.",
                             "Check the printed scale bar, film lot/thickness, fitted registration and physical response."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "patterns": len(patterns)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
