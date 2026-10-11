#!/usr/bin/python3
"""Develop K1 terminal stiffener cuts at their own neutral plane and matching bonding forms."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/capacitive-cad-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from shapely.geometry import Polygon
from tactile_kit.records import execution
from capacitive_geometry import CONFIG, load, offsets, inverse_unrolled, unrolled
from capacitive_cell_geometry import shape_for, common_samples
from build_capacitive_cell_mechanics import cut_svg
from prototype_cad import export_part, packed
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("foil_geometry", type=Path)
    args = parser.parse_args()
    source = args.foil_geometry.resolve()
    layout = json.loads((source / "report.json").read_text())
    for name, expected in layout["input_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Foil artwork inputs changed")
    cfg, surfaces = load()
    folder = ROOT / "build/engineering/prototypes/capacitive/stiffener_tools" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Generate separate K1 polyimide-stiffener neutral-plane cuts and curved adhesive-bonding forms; no thermal forming of polyimide is assumed") as record:
        folder.mkdir(parents=True)
        (folder / "patterns").mkdir()
        inputs = [CONFIG, Path(__file__), ROOT / "engineering/scripts/capacitive_cell_geometry.py",
                  ROOT / "engineering/scripts/build_capacitive_cell_mechanics.py", source / "report.json"]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        parts, models, cases = [], [], []
        for entry in layout["boards"]:
            path = source / entry["file"]
            if digest(path) != entry["sha256"]:
                raise ValueError("Foil geometry changed")
            data = json.loads(path.read_text())
            label = entry["site"]
            flat_at_foil = Polygon(data["stiffener_flat_mm"])
            if label == "REF" or int(label[2:]) < 2:
                cut = flat_at_foil
                kind = "Flat terminal: bond between smooth release-treated flat plates"
                radius = None
            else:
                surface = surfaces[int(label[2:])]
                flex_bottom = offsets(surface.site, cfg)["flex_bottom"]
                top = flex_bottom-cfg["electrode_design"]["stiffener_adhesive_mm"]
                bottom = top-cfg["electrode_design"]["stiffener_polyimide_mm"]
                neutral = (top+bottom)/2
                domain = inverse_unrolled(flat_at_foil, surface, data["neutral_offset_mm"])
                cut = unrolled(domain, surface, neutral)
                tool_domain = domain.buffer(1.0, join_style="mitre")
                if tool_domain.bounds[1] < 0 or tool_domain.bounds[3] > surface.length:
                    raise ValueError("Bonding form leaves the available curve")
                samples = common_samples(surface, [domain, tool_domain])
                # The assembled foil sits above the stiffener and its 50 µm
                # adhesive. The top tool contacts the foil's finished top.
                flex_top = offsets(surface.site, cfg)["flex_top"]
                forms = (("lower", bottom-3, bottom), ("upper", flex_top, flex_top+3))
                for side, lo, hi in forms:
                    name = "k1_"+label.lower()+"_stiffener_bond_form_"+side
                    mesh = export_part(shape_for(surface, tool_domain, lo, hi, samples), name, folder,
                                       parts, "Curved form for bonding the terminal stiffener without flattening the FPC",
                                       "Machined smooth polymer or finished precision print; verify adhesive compatibility", "fabricate_tool")
                    models.append(packed(mesh, name, label, "#889eab"))
                kind = "Elastically bend the cut stiffener on the lower form; laminate to the FPC with 50 µm adhesive and the upper form"
                radius = "Curvature follows the supplied STEP forms; qualify residual spring load and adhesion"
            cut_svg(folder / "patterns" / ("k1_"+label.lower()+"_stiffener_cut.svg"), [cut], label+" 0.20 mm PI stiffener cut at its own neutral plane")
            cases.append({"site": label, "flat_pattern_bounds_mm": list(cut.bounds), "flat_area_mm2": cut.area,
                          "material": "0.20 mm polyimide stiffener supplied by the FPC fabricator",
                          "adhesive": "0.05 mm nominal flex-compatible bonding film, selected with the FPC fabricator",
                          "process": kind, "curvature_note": radius,
                          "copies_per_finger": 2 if label == "REF" else 1})
            print(label+": separate stiffener cut"+(" and bonding forms" if label not in ("CH0", "CH1", "REF") else ""), flush=True)
        report = {"schema": "yam-k1-stiffener-tools/1", "parts": parts, "cases": cases,
                  "physical_specimens_tested": 0, "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "limits": ["The FPC fabricator must approve the PI, adhesive, copper and coverlay stack.",
                             "These forms hold the curved terminal during bonding; polyimide is not assumed to retain a heat-formed shape.",
                             "Adhesive durability, springback, soldering heat and bend-cycle life require physical tests."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "cut_patterns": len(cases), "forms": len(parts)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
