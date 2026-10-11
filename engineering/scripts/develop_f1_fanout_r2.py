#!/usr/bin/python3
"""Develop reversed upper connectors and check the full stiffened-tab envelopes."""

import argparse
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest
from develop_f1_fanout import transform

CONFIG = ROOT / "engineering/designs/f1_fanout_r2.json"
KICAD_PYTHON = ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/python3.11"


def map_point(point, part):
    x, y = point
    if part["side"] == "B":
        x = -x
    angle = -math.radians(part["rotation_deg"])
    return [part["center_mm"][0]+math.cos(angle)*x-math.sin(angle)*y,
            part["center_mm"][1]+math.sin(angle)*x+math.cos(angle)*y]


def revise(cfg, source, original_cfg):
    parts = copy.deepcopy(source["parts"])
    by_ref = {p["reference"]: p for p in parts}
    for ref in cfg["upper_connector_ids"]:
        by_ref[ref]["rotation_deg"] = cfg["upper_rotation_deg"]
    sensor = original_cfg["sensor_connector"]
    for part in parts:
        if not (part["reference"].startswith("J") and part["reference"].endswith("C")):
            continue
        for pin, net in part["nets"].items():
            if not net:
                continue
            link = by_ref["RK"+net[:-2]]
            local = [(int(pin)-3.5)*sensor["signal_pitch_mm"],
                     sensor["signal_pad_y_mm"]-1.85]
            link["center_mm"] = map_point(local, part)
            link["rotation_deg"] = -90+part["rotation_deg"]
    by_ref["UT"]["center_mm"] = cfg["test_mux_center_pcb_mm"]
    for index, center in enumerate(cfg["test_pull_downs"]["centers_pcb_mm"]):
        by_ref["RP"+str(index)]["center_mm"] = center
        by_ref["RP"+str(index)]["side"] = cfg["test_pull_downs"]["side"]
    old = Polygon(source["outline_xy_mm"])
    radius = cfg["contour_inward_rounding_radius_mm"]
    rounded = old.buffer(-radius, quad_segs=8).buffer(radius, quad_segs=8)
    # Clip numerical buffer approximations back to the exact accepted
    # outline; rounding must never add material in the contact envelope.
    clipped = rounded.intersection(old)
    components = [clipped] if clipped.geom_type == "Polygon" else [p for p in clipped.geoms if p.geom_type == "Polygon"]
    if not components:
        raise ValueError("Rounding removed the board")
    outline = max(components, key=lambda p: p.area)
    discarded_area = sum(p.area for p in components)-outline.area
    if not outline.is_valid or not old.buffer(1e-7).covers(outline):
        raise ValueError("Rounded board is not a single inward-contained outline")
    holes = copy.deepcopy(source["holes"][:len(cfg["mount_hole_centers_pcb_mm"])])
    for hole, center in zip(holes, cfg["mount_hole_centers_pcb_mm"]):
        hole["center_mm"] = center
    return {"schema": "yam-f1-fanout-r2-specification/1", "name": cfg["name"],
            "thickness_mm": source["thickness_mm"], "clearance_mm": source["clearance_mm"],
            "edge_mm": source["edge_mm"], "outline_xy_mm": list(outline.exterior.coords),
            "parts": parts, "holes": holes, "physical_specimens_tested": 0,
            "source_outline_area_mm2": old.area, "inward_rounded_area_mm2": outline.area,
            "discarded_rounding_components_area_mm2": discarded_area,
            "preclip_buffer_excess_area_mm2": rounded.difference(old).area}


def check(spec, data, cfg):
    failures = []
    outline = Polygon(spec["outline_xy_mm"])
    mount_checks = []
    for hole in spec["holes"]:
        center = Point(hole["center_mm"])
        keepout = center.buffer(hole["copper_keepout_diameter_mm"]/2)
        contained = outline.covers(keepout)
        mount_checks.append({
            "center_mm": hole["center_mm"],
            "keepout_diameter_mm": hole["copper_keepout_diameter_mm"],
            "contained_in_board": contained,
            "edge_distance_mm": outline.boundary.distance(center),
        })
        if not contained:
            failures.append({"kind": "mount_keepout_outside_board",
                            "center_mm": hole["center_mm"]})
    parts = {p["reference"]: p for p in spec["parts"]}
    bodies = {ref: transform(box(*part["body_envelope_mm"]), part) for ref, part in parts.items()}
    for ref, body in bodies.items():
        if not outline.covers(body):
            failures.append({"kind": "body_outside_board", "reference": ref})
        for hole in spec["holes"]:
            if body.distance(Point(hole["center_mm"])) < hole["copper_keepout_diameter_mm"]/2:
                failures.append({"kind": "body_near_mount", "reference": ref})
    refs = list(parts)
    for index, first in enumerate(refs):
        for second in refs[index+1:]:
            if parts[first]["side"] == parts[second]["side"] and bodies[first].intersection(bodies[second]).area > 1e-8:
                failures.append({"kind": "body_overlap", "a": first, "b": second})
    pad_shapes = []
    for pad in data["pads"]:
        w, h = pad["size"]
        shape = affinity.rotate(box(-w/2, -h/2, w/2, h/2), -pad["rotation"], origin=(0, 0))
        shape = affinity.translate(shape, *pad["center"])
        pad_shapes.append(shape)
        if not outline.buffer(-spec["edge_mm"]).covers(shape):
            failures.append({"kind": "pad_edge", "reference": pad["reference"], "pad": pad["pad"]})
    tree = STRtree(pad_shapes)
    for i, shape in enumerate(pad_shapes):
        for candidate in tree.query(shape.buffer(spec["clearance_mm"])):
            j = int(candidate)
            if j <= i or not set(data["pads"][i]["layers"]).intersection(data["pads"][j]["layers"]):
                continue
            a, b = data["pads"][i], data["pads"][j]
            if a["net"] and a["net"] == b["net"]:
                continue
            gap = shape.distance(pad_shapes[j])
            if gap < spec["clearance_mm"]-1e-6:
                failures.append({"kind": "pad_clearance", "a": [a["reference"], a["pad"]],
                                 "b": [b["reference"], b["pad"]], "gap_mm": gap})
    tab = cfg["tab"]
    external = box(-tab["width_mm"]/2, tab["connector_mouth_local_y_mm"]+.001,
                    tab["width_mm"]/2, tab["conservative_tip_local_y_interval_mm"][1]+tab["stiffener_length_mm"])
    tabs = {}
    for ref, part in parts.items():
        if ref.startswith("J") and ref != "JW":
            tabs[ref] = transform(external, part)
    minimum_gaps = []
    for ref, shape in tabs.items():
        other_bodies = [body for other, body in bodies.items()
                        if other != ref and parts[other]["side"] == parts[ref]["side"]]
        gap = min(shape.distance(body) for body in other_bodies)
        minimum_gaps.append({"connector": ref, "minimum_projected_other_body_gap_mm": gap})
        for other, body in bodies.items():
            if other != ref and parts[other]["side"] == parts[ref]["side"] and shape.intersection(body).area > 1e-8:
                failures.append({"kind": "external_tab_body_overlap", "connector": ref, "other": other})
        for hole in spec["holes"]:
            clearance = shape.distance(Point(hole["center_mm"]))-hole["copper_keepout_diameter_mm"]/2
            if clearance < .25:
                failures.append({"kind": "external_tab_mount_overlap", "connector": ref,
                                 "mount": hole["center_mm"], "clearance_mm": clearance})
    return {"schema": "yam-f1-fanout-r2-placement/1", "passed": not failures, "failures": failures,
            "parts": len(parts), "pads": len(data["pads"]), "tabs": minimum_gaps,
            "mounts": mount_checks,
            "physical_evidence": False,
            "limits": "Closed component bodies and conservative external tab projections. Actual contact plane, latch opening, flexible tails, carrier and robot fit remain."}, tabs


def draw(spec, tabs, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Polygon as PlotPolygon
    fig, axes = plt.subplots(1, 2, figsize=(14, 7), layout="constrained")
    for ax, side in zip(axes, ("F", "B")):
        ax.add_patch(PlotPolygon(spec["outline_xy_mm"], facecolor="#eef5ed", edgecolor="#355046"))
        for part in spec["parts"]:
            if part["side"] != side:
                continue
            shape = transform(box(*part["body_envelope_mm"]), part)
            ax.add_patch(PlotPolygon(list(shape.exterior.coords), facecolor="#bed0e1", edgecolor="#53687e"))
            ax.text(*part["center_mm"], part["reference"], ha="center", va="center", fontsize=7)
            if part["reference"] in tabs:
                ax.add_patch(PlotPolygon(list(tabs[part["reference"]].exterior.coords), facecolor="#f1c976",
                                        edgecolor="#a9751d", alpha=.65))
        for hole in spec["holes"]:
            ax.add_patch(Circle(hole["center_mm"], hole["copper_keepout_diameter_mm"]/2,
                                facecolor="none", edgecolor="#8a3956", linestyle="--"))
            ax.add_patch(Circle(hole["center_mm"], hole["diameter_mm"]/2,
                                facecolor="white", edgecolor="#8a3956"))
        ax.set(aspect="equal", xlim=(12, 77), ylim=(38, -3), xlabel="PCB x = -native Y (mm)", ylabel="PCB y = 44 -native Z (mm)")
        ax.set_title("Outer face · rows" if side == "F" else "Inner face · columns, viewed through board")
    fig.suptitle("F1 fanout revision 2 · upper connectors turn toward the back\n"
                 "Gold regions bound the external stiffened tabs; installed flexible routes remain")
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(path.with_suffix("."+suffix), dpi=170)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    config_path = args.config.resolve()
    cfg = json.loads(config_path.read_text())
    source_path = ROOT / cfg["source_board"]
    original_path = ROOT / cfg["source_configuration"]
    source, original = (json.loads(path.read_text()) for path in (source_path, original_path))
    folder = ROOT / "build/engineering/prototypes/f1/fanout_r2_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Revise F1 connector orientation and test-circuit placement to provide unobstructed stiffened-tab projections") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        paths = [config_path, source_path, original_path, Path(__file__),
                 ROOT / "engineering/scripts/write_f1_fanout_r2.py", ROOT / "engineering/scripts/f1_native_pcb.py"]
        for path in paths:
            target = inputs / path.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        spec = revise(cfg, source, original)
        spec["input_hashes"] = {str(path.relative_to(ROOT)): digest(path) for path in paths}
        spec_path = folder / "specification.json"
        spec_path.write_text(json.dumps(spec, indent=2)+"\n")
        command = [str(KICAD_PYTHON), str(ROOT / "engineering/scripts/write_f1_fanout_r2.py"),
                   str(spec_path), str(folder / "placement")]
        with (folder / "native.log").open("w") as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            record["native"] = {"command": command, "pid": process.pid}
            try:
                code = process.wait(timeout=50)
            except subprocess.TimeoutExpired:
                record["native"]["intentional_stop"] = "50 second bound on owned native writer"
                process.terminate(); process.wait(timeout=5)
                raise
        record["native"]["exit_code"] = code
        if code:
            raise RuntimeError((folder / "native.log").read_text()[-4000:])
        actual = json.loads((folder / "placement" / (cfg["name"]+".json")).read_text())
        report, tabs = check(spec, actual, cfg)
        (folder / "placement_check.json").write_text(json.dumps(report, indent=2)+"\n")
        draw(spec, tabs, folder / "tab_placement")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
