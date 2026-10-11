#!/usr/bin/python3
"""Develop explicit F1 electrode copper, contacts and straight routing witnesses."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PlotPolygon
import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from flex_artwork import FlexArtwork
from layout_f1_cells import fan_cell
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/prototypes/f1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def x_bounds(shape, y):
    section = shape.intersection(LineString([(-100, y), (100, y)]))
    if section.is_empty or section.geom_type != "LineString":
        raise ValueError("Expected a single contact-section interval")
    return section.bounds[0], section.bounds[2]


def body_geometry(site, r1, array, routing):
    if site < 2:
        entry = r1["nail_active_cells"][site]
        outer = Polygon(entry["outer"]); active = Polygon(entry["active"])
        top = outer.bounds[3]
        y_near_root = outer.bounds[1] + .03
        lo, hi = x_bounds(outer, y_near_root)
        origin_u = (lo + hi) / 2
        transform = [1, 0, 0, -1, -origin_u, top]
        body = affinity.affine_transform(outer, transform)
        active = affinity.affine_transform(active, transform)
        return body, active, {"kind": "nail", "nail_u_origin_mm": origin_u,
                              "nail_v_at_flat_y_zero_mm": top,
                              "flat_axes": "assembly X=native U; Y points toward the root"}
    pad = r1["pads"][site - 2]
    curve = np.asarray(pad["front_curve_native_yz_mm"])
    length = float(np.linalg.norm(np.diff(curve, axis=0), axis=1).sum())
    width = pad["width_mm"]
    body = box(-width / 2, 0, width / 2, length)
    bus_width = array["rows"] * routing["nominal_short_row_feed_trace_mm"] + (array["rows"] - 1) * .225
    active = box(-width / 2 + .6, .6, width / 2 - .4 - bus_width - .3, length - .6)
    return body, active, {"kind": "tpu", "reference_surface_length_mm": length,
                          "flat_axes": "assembly X increases with native X; Y is distal-to-proximal saddle arc",
                          "note": "Reference-surface allocation only; layer-specific neutral-plane unroll remains to be integrated."}


def extended_outline(body, cfg):
    length = body.bounds[3]
    lo, hi = x_bounds(body, length - .03)
    neck = Polygon([(lo, length - .03), (hi, length - .03),
                    (cfg["tail_width_mm"] / 2, length + cfg["body_to_tail_transition_mm"]),
                    (-cfg["tail_width_mm"] / 2, length + cfg["body_to_tail_transition_mm"])])
    end = length + cfg["body_to_tail_transition_mm"] + cfg["straight_tail_length_mm"]
    wide = cfg["tail_width_mm"] / 2; tab = cfg["tab_width_mm"] / 2
    tail = Polygon([(-wide, length + cfg["body_to_tail_transition_mm"] - .02),
                    (wide, length + cfg["body_to_tail_transition_mm"] - .02),
                    (wide, end - 8), (tab, end - 4.5), (tab, end),
                    (-tab, end), (-tab, end - 4.5), (-wide, end - 8)])
    outline = unary_union((body, neck, tail))
    if outline.geom_type != "Polygon" or not outline.is_valid:
        raise ValueError("F1 contact and tail do not form one valid outline")
    return outline, length, end


def columns(active, count, gap):
    low, high = active.bounds[1] + .001, active.bounds[3] - .001
    shapes = []
    for column in range(count):
        # The fan follows the taper for nails and is rectangular for the TPU.
        shape = fan_cell(active, low, high, column, count, .1).buffer(-gap / 2)
        if shape.geom_type != "Polygon" or shape.area <= 1:
            raise ValueError("A column electrode lost its connected active area")
        shapes.append(shape)
    return shapes


def draw(art, output, title):
    fig, axes = plt.subplots(1, 2, figsize=(10, 11), layout="constrained")
    for ax, layer in zip(axes, ("F.Cu", "B.Cu")):
        ax.add_patch(PlotPolygon(list(art.outline.exterior.coords), facecolor="#e9eddf", edgecolor="#73877e"))
        for row in art.regions:
            if row["layer"] == layer:
                ax.add_patch(PlotPolygon(list(row["shape"].exterior.coords), facecolor="#b98242", alpha=.8))
        for finger in art.fingers:
            if finger["layer"] == layer:
                ax.add_patch(PlotPolygon(list(finger["shape"].exterior.coords), facecolor="#dbb753"))
        for opening in art.openings:
            if opening["layer"] == layer.replace("Cu", "Mask"):
                ax.plot(*np.asarray(opening["shape"].exterior.coords).T, color="#617fa3", lw=.7)
        for via in art.connections:
            ax.add_patch(plt.Circle(via["center"], via["drill_mm"] / 2, color="white"))
        for label in art.labels:
            if label["layer"] == layer.replace("Cu", "SilkS"):
                ax.text(*label["position_mm"], label["text"], ha="center", va="center", fontsize=6)
        ax.autoscale_view(); ax.invert_yaxis(); ax.set_aspect("equal")
        ax.set_title(layer + " · same file coordinates"); ax.set_xlabel("mm")
    fig.suptitle(title + "\nFlat development artwork · installed tail routing remains", fontsize=12)
    fig.savefig(output / (art.name + ".svg"))
    plt.close(fig)


def make_column(site, body, active, basis, array, targets, cfg):
    count = array["nail_columns_per_prong"] if site < 2 else array["tpu_columns_per_region"]
    start_column = site * 2 if site < 2 else 4 + (site - 2) * 3
    # Bottom F.Cu faces the film: mirror assembly X to give the opposite face
    # orientation from the upper row foil. Final assembly uses this mapping.
    body = affinity.scale(body, xfact=-1, yfact=1, origin=(0, 0))
    active_shapes = [affinity.scale(shape, xfact=-1, yfact=1, origin=(0, 0))
                     for shape in columns(active, count, array["electrode_gap_mm"])]
    outline, length, end = extended_outline(body, cfg)
    art = FlexArtwork(f"f1_ch{site}_columns", outline, 1, .11)
    lanes = np.linspace(-2, 2, count)
    pin_map = {}
    for order, column in enumerate(reversed(range(count))):
        net = f"C{start_column+column}"
        electrode = active_shapes[column]
        section_y = electrode.bounds[3] - .08
        lo, hi = x_bounds(electrode, section_y)
        start = ((lo + hi) / 2, section_y)
        pin = 1 + 2 * order
        contact_x = (pin - 3.5) * cfg["gold_pitch_mm"]
        contact_y = end - cfg["gold_tip_setback_mm"] - cfg["gold_length_mm"] / 2
        points = [start, (lanes[order], length + cfg["body_to_tail_transition_mm"]),
                  (lanes[order], end - cfg["stiffener_length_mm"]),
                  (contact_x, end - cfg["gold_tip_setback_mm"] - cfg["gold_length_mm"]),
                  (contact_x, contact_y)]
        widths = [1.5, 1.5, 1.5, .5, .5]
        path = art.conductor_path(net, "F.Cu", points, widths, "column current route")
        copper = unary_union((electrode, path)).simplify(.0001)
        art.region("COLUMN_" + str(column), net, "F.Cu", copper, "Continuous column electrode and current lead")
        art.finger(pin, net, (contact_x, contact_y), cfg["gold_width_mm"], cfg["gold_length_mm"])
        pin_map[str(pin)] = net
    for pin in range(1, 7):
        if str(pin) not in pin_map:
            art.finger(pin, "", ((pin - 3.5) * cfg["gold_pitch_mm"], contact_y),
                       cfg["gold_width_mm"], cfg["gold_length_mm"])
            pin_map[str(pin)] = "unused"
    active_mirror = affinity.scale(active, xfact=-1, yfact=1, origin=(0, 0))
    art.opening("F.Mask", active_mirror.buffer(.1))
    art.opening("F.Mask", box(-4, end - cfg["gold_opening_depth_mm"], 4, end + .1))
    art.stiffeners.append(box(-cfg["tab_width_mm"]/2, end-cfg["stiffener_length_mm"],
                              cfg["tab_width_mm"]/2, end))
    art.labels = [{"text": f"CH{site} COL", "position_mm": [0, end-20], "layer": "F.SilkS"},
                  {"text": "1", "position_mm": [-2.5, end-6.2], "layer": "F.SilkS"}]
    return art, {"site": f"CH{site}", "role": "columns", "pin_map": pin_map,
                 "assembly_x_from_fabrication_x": -1, "basis": basis,
                 "physical_layers": 1, "tail_geometry": "straight routing witness only"}


def make_rows(site, body, active, basis, array, targets, cfg):
    layers = 2 if site < 2 else 1
    outline, length, end = extended_outline(body, cfg)
    art = FlexArtwork(f"f1_ch{site}_rows", outline, layers, .20 if layers == 2 else .11)
    count = array["rows"]; gap = array["electrode_gap_mm"]
    low, high = active.bounds[1], active.bounds[3]
    width = targets["routing"]["nominal_short_row_feed_trace_mm"]
    pitch = width + cfg["tpu_feed_clearance_mm"]
    midpoints = [low + (row + .5) * (high - low) / count for row in range(count)]
    if layers == 2:
        # A straight corridor avoids compressing parallel trace clearances
        # around the nail's concave proximal edge.
        bounds = [x_bounds(active, y) for y in np.linspace(midpoints[0], high - .02, 80)]
        common_left = max(row[0] for row in bounds)
        common_right = min(row[1] for row in bounds)
        bus_center = (common_left + common_right) / 2
        if common_right-common_left < (count-1)*pitch+width+.6:
            raise ValueError("The tapered nail has no adequate backside feed corridor")
        lanes = [bus_center + (1.5-row)*pitch for row in range(count)]
    else:
        lanes = [body.bounds[2] - .4 - width/2 - row*pitch for row in range(count)]
    pin_map = {}
    for row in range(count):
        net = f"R{row}"
        y0 = low + row * (high-low) / count + gap/2
        y1 = low + (row+1) * (high-low) / count - gap/2
        electrode = active.intersection(box(-100, y0, 100, y1))
        if electrode.geom_type != "Polygon" or electrode.area < 1:
            raise ValueError("A row electrode lost its connected contact area")
        y = midpoints[row]
        tail_x = (1.5-row) * 1.8
        pin = 4-row
        contact_x = (pin-3.5) * cfg["gold_pitch_mm"]
        contact_y = end-cfg["gold_tip_setback_mm"]-cfg["gold_length_mm"]/2
        if layers == 1:
            start = (active.bounds[2]-.02, y)
            points = [start, (lanes[row], y), (lanes[row], length-.03),
                      (tail_x, length+cfg["body_to_tail_transition_mm"]),
                      (tail_x, length+cfg["body_to_tail_transition_mm"]+cfg["parallel_tail_widening_mm"]),
                      (tail_x, end-cfg["stiffener_length_mm"]),
                      (contact_x, end-cfg["gold_tip_setback_mm"]-cfg["gold_length_mm"]),
                      (contact_x, contact_y)]
            widths = [width, width, width, width, 1.5, 1.5, .5, .5]
            path = art.conductor_path(net, "F.Cu", points, widths, "row electrode feed and current route")
            copper = unary_union((electrode, path)).simplify(.0001)
            art.region(f"ROW_{row}", net, "F.Cu", copper, "Row electrode and insulated feed")
        else:
            via_x = bus_center - (0., .1, .55, 1.)[row]
            via_point = (via_x, y)
            pad_radius = targets["routing"]["nail_static_via_pad_mm"] / 2
            if not electrode.buffer(-pad_radius-.015).covers(Point(via_point)):
                raise ValueError("A nail interlayer pad does not fit inside its row electrode")
            art.region(f"ROW_{row}", net, "F.Cu", electrode, "Nail row electrode")
            art.interlayer(f"VBODY_{row}", net, via_point,
                           targets["routing"]["nail_static_via_pad_mm"],
                           targets["routing"]["nail_static_via_drill_mm"])
            termination = (tail_x, end-cfg["termination_via_distance_from_tip_mm"])
            points = [via_point, (lanes[row], y), (lanes[row], length-.03),
                      (tail_x, length+cfg["body_to_tail_transition_mm"]),
                      (tail_x, length+cfg["body_to_tail_transition_mm"]+cfg["parallel_tail_widening_mm"]),
                      termination]
            widths = [width, width, width, width, 1.5, 1.5]
            back = art.conductor_path(net, "B.Cu", points, widths, "Backside nail feed")
            art.region(f"BACK_{row}", net, "B.Cu", back, "Backside feed preserving the nail contact width")
            art.interlayer(f"VTAIL_{row}", net, termination,
                           targets["routing"]["nail_static_via_pad_mm"],
                           targets["routing"]["nail_static_via_drill_mm"])
            front = art.conductor_path(net, "F.Cu", [
                termination, (contact_x, end-cfg["gold_tip_setback_mm"]-cfg["gold_length_mm"]),
                (contact_x, contact_y)], [.5, .5, .5], "Stiffened termination fan-out")
            art.region(f"CONTACT_{row}", net, "F.Cu", front, "Cable contact fan-out outside free bends")
        art.finger(pin, net, (contact_x, contact_y), cfg["gold_width_mm"], cfg["gold_length_mm"])
        pin_map[str(pin)] = net
    for pin in (5, 6):
        art.finger(pin, "", ((pin-3.5)*cfg["gold_pitch_mm"], contact_y),
                   cfg["gold_width_mm"], cfg["gold_length_mm"])
        pin_map[str(pin)] = "unused"
    art.opening("F.Mask", active.buffer(.1))
    art.opening("F.Mask", box(-4, end-cfg["gold_opening_depth_mm"], 4, end+.1))
    if layers == 2:
        art.opening("B.Mask", box(-4, end-cfg["rear_copper_free_tip_length_mm"], 4, end+.1))
    art.stiffeners.append(box(-cfg["tab_width_mm"]/2, end-cfg["stiffener_length_mm"],
                              cfg["tab_width_mm"]/2, end))
    art.labels = [{"text": f"CH{site} ROW", "position_mm": [0, end-20], "layer": "F.SilkS"},
                  {"text": "1", "position_mm": [-2.5, end-6.2], "layer": "F.SilkS"}]
    return art, {"site": f"CH{site}", "role": "rows", "pin_map": pin_map,
                 "assembly_x_from_fabrication_x": 1, "basis": basis,
                 "physical_layers": layers, "tail_geometry": "straight routing witness only"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", type=int, nargs="+", default=list(range(6)))
    parser.add_argument("--roles", choices=("columns", "rows"), nargs="+", default=["columns", "rows"])
    args = parser.parse_args()
    if len(set(args.sites)) != len(args.sites) or any(site not in range(6) for site in args.sites):
        parser.error("Use distinct site indices 0..5")
    paths = [ROOT / "engineering/designs/f1.json", ROOT / "engineering/designs/f1_flex_targets.json",
             ROOT / "engineering/designs/f1_artwork_development.json",
             ROOT / "engineering/release/r1/r1_manifest.json",
             Path(__file__), ROOT / "engineering/scripts/flex_artwork.py",
             ROOT / "engineering/scripts/layout_f1_cells.py"]
    spec, targets, cfg, r1 = [json.loads(path.read_text()) for path in paths[:4]]
    run = OUTPUT / "artwork_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Develop routed F1 electrode foils and connector contacts against the source contact geometry; preserve this flat-artwork iteration") as record:
        run.mkdir(parents=True, exist_ok=False)
        inputs = run / "inputs"; inputs.mkdir()
        for path in paths:
            shutil.copyfile(path, inputs / path.name)
        results = []
        for site in args.sites:
            body, active, basis = body_geometry(site, r1, spec["array"], targets["routing"])
            for role in args.roles:
                builder = make_column if role == "columns" else make_rows
                art, metadata = builder(site, body, active, basis, spec["array"], targets, cfg)
                folder = run / art.name
                result = art.write(folder)
                draw(art, folder, art.name)
                results.append({"name": art.name, "directory": str(folder.relative_to(ROOT)),
                                "metadata": metadata, "geometry_checks": result["geometry_checks"]})
        report = {"status": "flat routing development; not the installed F1 package",
                  "source_hashes": {str(path.relative_to(ROOT)): digest(path) for path in paths},
                  "boards": results, "physical_specimens_tested": 0, "fabrication_ready": False}
        (run / "artwork.json").write_text(json.dumps(report, indent=2) + "\n")
        (OUTPUT / "latest_artwork.json").write_text(json.dumps(
            {"directory": str(run.relative_to(ROOT)), "boards": [row["name"] for row in results]}, indent=2) + "\n")
        record["artwork"] = report
        print(json.dumps({"directory": str(run.relative_to(ROOT)), "boards": [
            {"name": row["name"], **{key: row["geometry_checks"][key] for key in
                ("passed", "minimum_edge_clearance_mm", "minimum_different_net_clearance_mm",
                 "outside_outline_area_mm2")}} for row in results]}, indent=2))
        if not all(row["geometry_checks"]["passed"] for row in results):
            raise ValueError("Flat flex artwork still has geometric clearance findings")


if __name__ == "__main__":
    main()
