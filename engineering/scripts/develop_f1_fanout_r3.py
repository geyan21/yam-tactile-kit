#!/usr/bin/python3
"""Develop R3 while checking full assembly envelopes and a manufacturable edge."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

from shapely.geometry import Polygon, box

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from develop_f1_fanout_r2 import revise, check as prior_check
from develop_f1_fanout import transform
from screen_f1_feedback import digest

CONFIG = ROOT / "engineering/designs/f1_fanout_r3.json"
KICAD_PYTHON = ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/python3.11"


def clean_outline(spec, source, cfg):
    old = Polygon(source["outline_xy_mm"])
    before = Polygon(spec["outline_xy_mm"])
    rules = cfg["outline_cleanup"]
    clean = before.buffer(-rules["additional_inset_mm"]).simplify(rules["simplification_mm"], preserve_topology=True)
    if clean.geom_type != "Polygon":
        raise ValueError("Cleanup disconnected the board")
    coordinates = list(clean.exterior.coords)[:-1]
    removed = 0
    while True:
        short = next((i for i in range(len(coordinates))
                      if math.dist(coordinates[i], coordinates[(i+1) % len(coordinates)])
                      < rules["minimum_segment_mm"]), None)
        if short is None:
            break
        del coordinates[(short+1) % len(coordinates)]
        removed += 1
    clean = Polygon(coordinates)
    if not clean.is_valid or not old.buffer(1e-8).covers(clean):
        raise ValueError("Cleaned outline escaped the accepted contact envelope")
    lengths = [math.dist(a, b) for a, b in zip(clean.exterior.coords, list(clean.exterior.coords)[1:])]
    spec["outline_xy_mm"] = list(clean.exterior.coords)
    spec["outline_cleanup"] = {"short_vertices_removed": removed,
                               "minimum_segment_mm": min(lengths),
                               "maximum_deviation_from_r2_mm": before.hausdorff_distance(clean),
                               "outside_original_area_mm2": clean.difference(old).area,
                               "original_envelope_containment": True}


def validate(spec, data, cfg):
    report, tabs = prior_check(spec, data, cfg)
    failures = report["failures"]
    courts = data.get("courtyards", [])
    if len(courts) != len(spec["parts"]):
        failures.append({"kind": "missing_native_courtyard"})
    for index, a in enumerate(courts):
        for b in courts[index+1:]:
            if a["side"] == b["side"] and box(*a["bounds_mm"]).intersection(box(*b["bounds_mm"])).area > 1e-8:
                failures.append({"kind": "native_courtyard_overlap", "a": a["reference"], "b": b["reference"]})
    by_pad = {(p["reference"], p["pad"]): p for p in data["pads"]}
    supply = by_pad[("UT", "1")]
    bypass = []
    for ref in ("CT1", "CT2"):
        cap = by_pad[(ref, "1")]
        distance = math.dist(supply["center"], cap["center"])
        bypass.append({"capacitor": ref, "supply_land_distance_mm": distance})
        if cap["net"] != "+3V3" or distance > cfg["maximum_bypass_pad_distance_mm"]:
            failures.append({"kind": "bypass_placement", "capacitor": ref, "distance_mm": distance})
    report.update({"schema": "yam-f1-fanout-r3-placement/1", "passed": not failures,
                   "courtyards_checked": len(courts), "bypass": bypass,
                   "outline_cleanup": spec["outline_cleanup"],
                   "limits": "Nominal bodies, true courtyard boundaries, pad spacing, external tab projections and bypass proximity. Complete copper, routed bypass loop, mating, fitted tails and physical behavior remain."})
    return report, tabs


def draw(spec, data, tabs, folder):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Polygon as DrawPolygon, Rectangle
    fig, axes = plt.subplots(1, 2, figsize=(15, 7), layout="constrained")
    for ax, side in zip(axes, ("F", "B")):
        ax.add_patch(DrawPolygon(spec["outline_xy_mm"], facecolor="#eef5ed", edgecolor="#355046"))
        for item in data["courtyards"]:
            if item["side"] == side:
                x0, y0, x1, y1 = item["bounds_mm"]
                ax.add_patch(Rectangle((x0, y0), x1-x0, y1-y0, facecolor="none",
                                       edgecolor="#a45c82", linestyle="--", linewidth=.65))
        for part in spec["parts"]:
            if part["side"] != side:
                continue
            shape = transform(box(*part["body_envelope_mm"]), part)
            ax.add_patch(DrawPolygon(list(shape.exterior.coords), facecolor="#bed0e1", edgecolor="#53687e"))
            ax.text(*part["center_mm"], part["reference"], ha="center", va="center", fontsize=7)
            if part["reference"] in tabs:
                ax.add_patch(DrawPolygon(list(tabs[part["reference"]].exterior.coords),
                                         facecolor="#f1c976", edgecolor="#a9751d", alpha=.55))
        for hole in spec["holes"]:
            ax.add_patch(Circle(hole["center_mm"], hole["copper_keepout_diameter_mm"]/2,
                                facecolor="none", edgecolor="#8a3956", linestyle="--"))
            ax.add_patch(Circle(hole["center_mm"], hole["diameter_mm"]/2, facecolor="white", edgecolor="#8a3956"))
        ax.set(xlim=(12, 77), ylim=(38, -3), aspect="equal",
               xlabel="PCB x = -native Y (mm)", ylabel="PCB y = 44 -native Z (mm)")
        ax.set_title("Outer face — row connectors and test circuit" if side == "F" else "Inner face — column connectors")
    fig.suptitle("F1 fanout R3 · native assembly courtyards included\n"
                 "Gold: external stiffened tabs · dashed: actual courtyard boundaries · no physical qualification")
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(folder / ("placement."+suffix), dpi=165)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    config_path = args.config.resolve()
    cfg = json.loads(config_path.read_text())
    source_path, original_path = (ROOT / cfg[key] for key in ("source_board", "source_configuration"))
    source, original = (json.loads(p.read_text()) for p in (source_path, original_path))
    folder = ROOT / "build/engineering/prototypes/f1/fanout_r3_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Develop a separate R3 with supported courtyard spacing, cleaned inward outline and relocated supply/test parts; preserve all R2 evidence") as record:
        folder.mkdir(parents=True, exist_ok=False)
        paths = [config_path, source_path, original_path, Path(__file__),
                 ROOT / "engineering/scripts/develop_f1_fanout_r2.py",
                 ROOT / "engineering/scripts/write_f1_fanout_r3.py",
                 ROOT / "engineering/scripts/inspect_f1_fanout_native.py",
                 ROOT / "engineering/scripts/f1_native_pcb.py"]
        for path in paths:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        spec = revise(cfg, source, original)
        spec["schema"] = "yam-f1-fanout-r3-specification/1"
        by_ref = {p["reference"]: p for p in spec["parts"]}
        for ref, values in cfg["part_overrides"].items():
            by_ref[ref].update(values)
        spec["reference_positions_pcb_mm"] = cfg["reference_positions_pcb_mm"]
        spec["via_to_paste_clearance_mm"] = cfg["via_to_paste_clearance_mm"]
        clean_outline(spec, source, cfg)
        spec["input_hashes"] = {str(path.relative_to(ROOT)): digest(path) for path in paths}
        specification = folder / "specification.json"
        specification.write_text(json.dumps(spec, indent=2)+"\n")
        command = [str(KICAD_PYTHON), str(ROOT / "engineering/scripts/write_f1_fanout_r3.py"),
                   str(specification), str(folder / "placement")]
        with (folder / "native.log").open("w") as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            record["native"] = {"argv": command, "pid": process.pid}
            try:
                code = process.wait(timeout=50)
            except subprocess.TimeoutExpired:
                record["native"]["intentional_stop"] = "50 second bound on owned native writer"
                process.terminate()
                process.wait(timeout=5)
                raise
        record["native"]["exit_code"] = code
        if code:
            raise RuntimeError((folder / "native.log").read_text()[-4000:])
        data = json.loads((folder / "placement/f1_fanout_r3.json").read_text())
        report, tabs = validate(spec, data, cfg)
        (folder / "placement_check.json").write_text(json.dumps(report, indent=2)+"\n")
        draw(spec, data, tabs, folder)
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
