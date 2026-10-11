#!/usr/bin/python3
"""Route electrodes on the twelve preserved R3 fit outlines."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PlotPolygon
import numpy as np
from shapely import affinity, set_precision
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from tactile_kit.records import execution
from flex_artwork import FlexArtwork
from f1_surfaces import load_surfaces
from develop_f1_artwork import columns, x_bounds
from screen_f1_feedback import digest

CONFIG = ROOT / "engineering/designs/f1_fitted_artwork_r3.json"


class FittedArtwork(FlexArtwork):
    """Quantize the complete union; retain unresolved topology findings."""

    def conductor_path(self, net, layer, points, widths, role):
        if len(points) != len(widths) or min(widths) < .125:
            raise ValueError("Fitted copper must retain the minimum nominal line width")
        pieces = [Point(point).buffer(width/2, quad_segs=12) for point, width in zip(points, widths)]
        for a, b, wa, wb in zip(points, points[1:], widths, widths[1:]):
            dx, dy = b[0]-a[0], b[1]-a[1]
            distance = math.hypot(dx, dy)
            if distance < 1e-10:
                continue
            nx, ny = -dy/distance, dx/distance
            pieces.append(Polygon([(a[0]+nx*wa/2, a[1]+ny*wa/2),
                                   (b[0]+nx*wb/2, b[1]+ny*wb/2),
                                   (b[0]-nx*wb/2, b[1]-ny*wb/2),
                                   (a[0]-nx*wa/2, a[1]-ny*wa/2)]))
        raw = unary_union(pieces)
        shape = set_precision(raw, self.copper_grid)
        difference = raw.symmetric_difference(shape).area
        entry = {"net": net, "layer": layer, "points_mm": points, "widths_mm": widths, "role": role,
                 "numeric_join": {"precision_grid_mm": self.copper_grid,
                                  "raw_type": raw.geom_type,
                                  "raw_hole_areas_mm2": [Polygon(r).area for r in getattr(raw, "interiors", [])],
                                  "quantized_type": shape.geom_type,
                                  "quantized_hole_areas_mm2": [Polygon(r).area for r in getattr(shape, "interiors", [])],
                                  "symmetric_difference_mm2": difference}}
        self.paths.append(entry)
        if (shape.geom_type != "Polygon" or not shape.is_valid or shape.interiors
                or difference > self.copper_grid*raw.length*2):
            error = ValueError("The conductor union has an unresolved topology or displacement finding")
            error.failed_path = entry
            raise error
        return shape


def fabrication(shape, pattern):
    return affinity.rotate(
        affinity.scale(shape, xfact=pattern["fabrication_x_mirror"], yfact=1, origin=(0, 0)),
        pattern["fabrication_rotation_deg"], origin=(0, 0))


def point_transform(point, pattern):
    return list(fabrication(Point(point), pattern).coords)[0]


def unroll(shape, surface, offset):
    arc = surface.offset_arc(offset)
    def ring(points):
        return [(x, float(np.interp(y, surface.s, arc))) for x, y in points]
    return Polygon(ring(shape.exterior.coords), [ring(r.coords) for r in shape.interiors])


def pin_mapping(board, connector):
    pads = [p for p in board["pads"] if p["reference"] == connector and p["pad"].isdigit()]
    if {int(p["pad"]) for p in pads} != set(range(1, 7)):
        raise ValueError("Expected the exact six electrical connector lands")
    result = {}
    for pad in pads:
        net = pad["net"]
        if net and not re.fullmatch(r"[RC]\d+_I", net):
            raise ValueError("Unexpected fanout connector net")
        result[int(pad["pad"])] = {"fanout_net": net, "foil_net": net.removesuffix("_I")}
    return result


def offset_lane(points, offset, widening_run):
    line = LineString(points)
    shifted = line.offset_curve(offset, quad_segs=32, join_style="round") if offset else line
    if shifted.geom_type != "LineString" or shifted.is_empty:
        raise ValueError("A parallel tail lane split or disappeared")
    result = list(shifted.coords)
    expected = np.asarray(points[0])+[0, offset]
    if math.dist(result[0], expected) > 1e-5:
        raise ValueError("Tail offset lost its intended connection at the bend")
    if (abs(result[1][1]-result[0][1]) > 1e-5
            or result[1][0]-result[0][0] <= widening_run):
        raise ValueError("No straight wide section for the conductor-width transition")
    return [result[0], (result[0][0]+widening_run, result[0][1]), *result[1:]]


def draw(art, metadata, folder):
    fig, axes = plt.subplots(1, 2, figsize=(13, 8), layout="constrained")
    for ax, layer in zip(axes, ("F.Cu", "B.Cu")):
        ax.add_patch(PlotPolygon(art.outline.exterior.coords, fc="#eef1e7", ec="#557067"))
        for ring in art.outline.interiors:
            ax.add_patch(PlotPolygon(ring.coords, fc="white", ec="#557067"))
        for item in art.regions:
            if item["layer"] == layer:
                ax.add_patch(PlotPolygon(item["shape"].exterior.coords, fc="#bd8549", ec="none"))
        for item in art.fingers:
            if item["layer"] == layer:
                ax.add_patch(PlotPolygon(item["shape"].exterior.coords, fc="#d7b65a", ec="none"))
                x, y = item["center"]
                ax.text(x, y+4, str(item["pin"]), ha="center", fontsize=6)
        for item in art.connections:
            ax.add_patch(plt.Circle(item["center"], item["pad_mm"]/2, color="#bd8549"))
            ax.add_patch(plt.Circle(item["center"], item["drill_mm"]/2, color="white"))
        ax.autoscale_view()
        ax.invert_yaxis()
        ax.set(aspect="equal", xlabel="Fabrication X (mm)", ylabel="Fabrication Y (mm)",
               title=layer+" · same file coordinates")
    fig.suptitle(
        f'{art.name} · R3 fit outline → {metadata["connector"]}\n'
        'Routing development · connector datum, motion and physical behavior unqualified', fontsize=12)
    for extension in ("png", "pdf", "svg"):
        fig.savefig(folder / (art.name+"."+extension), dpi=150)
    plt.close(fig)


def build(pattern, route, surface, stack, cfg, board):
    site, role = pattern["site"], pattern["role"]
    tail = stack["tails"]
    body = unroll(surface.body, surface, pattern["conductor_offset_mm"])
    active = unroll(surface.active, surface, pattern["conductor_offset_mm"])
    original_outline = Polygon(pattern["outline_flat_mm"], pattern["inner_cuts_flat_mm"])
    grid = cfg["outline_precision_grid_mm"]
    outline = set_precision(original_outline, grid)
    cleanup_area = original_outline.symmetric_difference(outline).area
    if (outline.geom_type != "Polygon" or not outline.is_valid or cleanup_area > .005
            or not original_outline.buffer(2*grid).covers(outline)
            or not outline.buffer(2*grid).covers(original_outline)):
        raise ValueError("Outline quantization exceeds the numerical-seam repair bound")
    original_holes = [Polygon(ring).area for ring in original_outline.interiors]
    if len(outline.interiors) < sum(area > 1e-6 for area in original_holes):
        raise ValueError("A genuine internal cut would be lost")
    layers = 2 if role == "rows" and site < 2 else 1
    art = FittedArtwork(f"f1_ch{site}_{role}", outline, layers,
                       pattern["covered_tail_thickness_mm"],
                       clearance=tail["trace_clearance_mm"], edge=tail["edge_clearance_mm"])
    art.copper_grid = cfg["copper_precision_grid_mm"]
    mapping = pin_mapping(board, pattern["connector"])
    y_exit = pattern["flat_exit_y_before_fabrication_transform_mm"]
    origin_x = pattern["body_origin_native_mm"][0]
    u_widen0, u_widen1 = 7.2-origin_x, 8.35-origin_x
    affine = pattern["native_yz_to_unfolded_tail_affine"]
    long_path = list(affinity.affine_transform(LineString(route["path_yz_mm"]), affine).coords)
    end = point_transform(long_path[-1], pattern)
    tip = np.asarray(pattern["connector_tip_flat_mm_assumed"])
    if abs(end[0]-tip[0]) > 1e-5 or end[1] >= tip[1]-tail["stiffener_length_mm"]:
        raise ValueError("The unfolded taper does not enter the connector along +Y")
    # Extend the centreline into the wide taper. Otherwise the short final
    # mechanical lead truncates the inside offset curves at the last corner.
    direction = np.asarray(long_path[-1])-long_path[-2]
    direction /= np.linalg.norm(direction)
    extension = tip[1]-tail["stiffener_length_mm"]-end[1]
    long_path.append(tuple(np.asarray(long_path[-1])+extension*direction))
    centerline = [(u_widen1, y_exit), *long_path]
    if math.dist(centerline[0], centerline[1]) < 1e-7:
        centerline.pop(0)
    if abs(centerline[1][1]-y_exit) > 1e-5 or centerline[1][0] <= centerline[0][0]:
        raise ValueError("The unfolded formed bend must begin along +U")
    width = cfg["neck_trace_width_mm"]
    long_width = cfg["long_trace_width_mm"]
    neck_pitch = cfg["neck_lane_pitch_mm"]
    long_pitch = cfg["long_lane_pitch_mm"]
    body_width, pitch = cfg["body_feed_width_mm"], cfg["body_feed_pitch_mm"]
    spatial = []
    conductor_items = []
    if role == "rows":
        low, high = active.bounds[1], active.bounds[3]
        midpoints = [low+(row+.5)*(high-low)/4 for row in range(4)]
        if layers == 2:
            limits = [x_bounds(active, y) for y in np.linspace(midpoints[0], high-.02, 80)]
            left, right = max(p[0] for p in limits), min(p[1] for p in limits)
            bus_center = (left+right)/2
            lanes = [bus_center+(1.5-row)*pitch for row in range(4)]
        else:
            order = list(range(4)) if pattern["source_edge"] == "proximal" else list(reversed(range(4)))
            lanes = [body.bounds[2]-.4-body_width/2-order[row]*pitch for row in range(4)]
        for row in range(4):
            net, pin = f"R{row}", 4-row
            if mapping[pin]["foil_net"] != net:
                raise ValueError("R3 row pin contract changed")
            gap = cfg["electrode_gap_mm"]/2
            electrode = active.intersection(box(-100, low+row*(high-low)/4+gap,
                                                100, low+(row+1)*(high-low)/4-gap))
            mid = midpoints[row]
            if layers == 2:
                start = (bus_center-(0., .1, .55, 1.)[row], mid)
                if not electrode.buffer(-cfg["nail_via_pad_mm"]/2-.015).covers(Point(start)):
                    raise ValueError("Nail electrode cannot contain its static interlayer pad")
                art.region(f"ROW_{row}", net, "F.Cu", fabrication(electrode, pattern), "Nail row electrode")
                art.interlayer(f"VBODY_{row}", net, point_transform(start, pattern),
                               cfg["nail_via_pad_mm"], cfg["nail_via_drill_mm"])
            else:
                start = (active.bounds[2]-.02, mid)
            neck_offset = (row-1.5)*neck_pitch
            points = [start, (lanes[row], mid), (lanes[row], y_exit+neck_offset),
                      (u_widen0-cfg["neck_relief_length_mm"], y_exit+neck_offset),
                      (u_widen0, y_exit+neck_offset), (u_widen1, y_exit+(row-1.5)*long_pitch)]
            conductor_items.append((net, pin, electrode, points,
                                    [body_width, body_width, body_width, width, cfg["widening_corner_trace_mm"], width],
                                    (row-1.5)*long_pitch, "B.Cu" if layers == 2 else "F.Cu"))
            spatial.append({"row": row, "foil_net": net, "connector_pin": pin})
    else:
        count = 2 if site < 2 else 3
        electrodes = columns(active, count, cfg["electrode_gap_mm"])
        pins = [1+2*i for i in range(count)]
        if pattern["source_edge"] == "proximal":
            pins.reverse()
        for index, (pin, electrode) in enumerate(zip(pins, electrodes)):
            net = mapping[pin]["foil_net"]
            if not net.startswith("C"):
                raise ValueError("Unexpected column pin allocation")
            sign = -1 if pattern["source_edge"] == "proximal" else 1
            lane_index = sign*(index-(count-1)/2)
            section_y = electrode.bounds[3]-.08 if sign == -1 else electrode.bounds[1]+.08
            left, right = x_bounds(electrode, section_y)
            start = ((left+right)/2, section_y)
            points = [start, (start[0], y_exit+lane_index*neck_pitch),
                      (u_widen0-cfg["neck_relief_length_mm"], y_exit+lane_index*neck_pitch),
                      (u_widen0, y_exit+lane_index*neck_pitch),
                      (u_widen1, y_exit+lane_index*long_pitch)]
            conductor_items.append((net, pin, electrode, points,
                                    [width, width, width, cfg["widening_corner_trace_mm"], width],
                                    lane_index*long_pitch, "F.Cu"))
            spatial.append({"column_in_increasing_source_u": index, "foil_net": net, "connector_pin": pin})
    for net, pin, electrode, points, widths, offset, layer in conductor_items:
        lane = offset_lane(centerline, offset, cfg["constant_width_widening_run_mm"])
        if math.dist(points[-1], lane[0]) > 1e-5:
            raise ValueError("Neck and planar tail do not join")
        points += lane[1:]
        widths += [long_width]*(len(lane)-1)
        widths[-1] = cfg["termination_trace_width_mm"]
        transformed = [point_transform(point, pattern) for point in points]
        contact = [float(tip[0]+pin-3.5), float(tip[1]-tail["gold_contact_tip_setback_mm"]-
                                              tail["gold_contact_length_mm"]/2)]
        if layer == "B.Cu":
            stagger = cfg["outer_termination_via_stagger_mm"] if pin == 1 else 0.
            termination = [contact[0], float(tip[1]-tail["termination_via_distance_from_tip_mm"]-stagger)]
            transformed.append(termination)
            widths.append(cfg["termination_trace_width_mm"])
            path = art.conductor_path(net, layer, transformed, widths, "Fitted nail row feed and formed tail")
            art.region("BACK_"+net, net, layer, path, "Backside feed outside nail contact area")
            art.interlayer("VTAIL_"+net, net, termination, cfg["nail_via_pad_mm"], cfg["nail_via_drill_mm"])
            front = art.conductor_path(net, "F.Cu", [termination, contact], [.5, .5], "Stiffened contact link")
            art.region("CONTACT_"+net, net, "F.Cu", front, "Front contact after static plated transition")
        else:
            transformed += [[contact[0], float(tip[1]-tail["gold_contact_tip_setback_mm"]-
                                                tail["gold_contact_length_mm"])], contact]
            widths += [cfg["termination_trace_width_mm"], .5]
            path = art.conductor_path(net, layer, transformed, widths, "Fitted electrode feed and formed tail")
            copper = unary_union((fabrication(electrode, pattern), path)).simplify(.0001)
            art.region("ELECTRODE_"+net, net, layer, copper, "Continuous sensing electrode and installed-shape lead")
    for pin, item in mapping.items():
        art.finger(pin, item["foil_net"],
                   (float(tip[0]+pin-3.5), float(tip[1]-tail["gold_contact_tip_setback_mm"]-
                                                tail["gold_contact_length_mm"]/2)),
                   cfg["contact_width_mm"], tail["gold_contact_length_mm"])
    art.opening("F.Mask", fabrication(active.buffer(.1), pattern))
    art.opening("F.Mask", box(tip[0]-4, tip[1]-tail["gold_opening_depth_mm"], tip[0]+4, tip[1]+.1))
    if layers == 2:
        art.opening("B.Mask", box(tip[0]-4, tip[1]-tail["rear_copper_free_tip_length_mm"], tip[0]+4, tip[1]+.1))
    art.stiffeners.append(box(tip[0]-tail["tab_width_mm"]/2, tip[1]-tail["stiffener_length_mm"],
                              tip[0]+tail["tab_width_mm"]/2, tip[1]))
    metadata = {"site": f"CH{site}", "role": role, "connector": pattern["connector"],
                "interface_revision": "R3", "pin_map": {str(p): value["foil_net"] or "unused" for p, value in mapping.items()},
                "fanout_pin_map": {str(p): value["fanout_net"] for p, value in mapping.items()},
                "spatial_electrodes": spatial, "source_edge": pattern["source_edge"],
                "physical_layers": layers, "basis": pattern,
                "outline_cleanup": {"precision_grid_mm": grid, "symmetric_difference_mm2": cleanup_area,
                                    "original_hole_areas_mm2": original_holes,
                                    "retained_holes": len(outline.interiors),
                                    "generated_inner_cuts_mm": [list(ring.coords) for ring in art.outline.interiors]},
                "physical_specimens_tested": 0, "installed_finger_qualified": False}
    return art, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", type=int, nargs="+", default=list(range(6)))
    parser.add_argument("--roles", choices=("columns", "rows"), nargs="+", default=["columns", "rows"])
    args = parser.parse_args()
    if len(set(args.sites)) != len(args.sites) or any(site not in range(6) for site in args.sites):
        parser.error("Use distinct sites 0..5")
    cfg = json.loads(CONFIG.read_text())
    checkpoint = ROOT / cfg["checkpoint"]
    files = ("checks/fit_patterns.json", "checks/tail_routes.json", "pcb/f1_fanout_r3.json",
             "configuration/f1_formed_stack.json")
    saved = json.loads((checkpoint / "checkpoint.json").read_text())
    for name in files:
        if digest(checkpoint / name) != saved["files_sha256"][name]:
            raise ValueError("The published R3 input changed: "+name)
    fit, routes, board = [json.loads((checkpoint / name).read_text()) for name in files[:3]]
    stack, _, _, surfaces = load_surfaces(checkpoint / files[3])
    selected = [p for p in fit["patterns"] if p["site"] in args.sites and p["role"] in args.roles]
    paths = [CONFIG, Path(__file__), checkpoint / "checkpoint.json", *[checkpoint / p for p in files],
             ROOT / stack["basis"]["r1_manifest"], ROOT / stack["basis"]["nail_coordinates"],
             ROOT / "engineering/scripts/flex_artwork.py", ROOT / "engineering/scripts/f1_surfaces.py",
             ROOT / "engineering/scripts/develop_f1_artwork.py", ROOT / "engineering/scripts/layout_f1_cells.py"]
    folder = ROOT / "build/engineering/prototypes/f1/artwork_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Generate F1 fitted electrode copper on the preserved R3 nominal outlines; retain failures and require independent native checks before fabrication exports") as record:
        folder.mkdir(parents=True, exist_ok=False)
        source_hashes = {str(path.relative_to(ROOT)): digest(path) for path in paths}
        for path in paths:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        results, failures = [], []
        for pattern in selected:
            try:
                route = next(r for r in routes["routes"] if r["site"] == pattern["site"] and r["role"] == pattern["role"])
                art, metadata = build(pattern, route, surfaces[pattern["site"]], stack, cfg, board)
                target = folder / art.name
                data = art.write(target)
                draw(art, metadata, target)
                item = {"name": art.name, "directory": str(target.relative_to(ROOT)),
                        "metadata": metadata, "geometry_checks": data["geometry_checks"]}
                results.append(item)
                print(json.dumps({"name": art.name, **data["geometry_checks"]}), flush=True)
            except (ValueError, TypeError, KeyError) as error:
                failure = {"site": pattern["site"], "role": pattern["role"], "error": str(error)}
                if hasattr(error, "failed_path"):
                    failure["failed_path"] = error.failed_path
                failures.append(failure)
                print(json.dumps({k: v for k, v in failure.items() if k != "failed_path"}), flush=True)
        report = {"schema": "yam-f1-fitted-artwork/1", "status": "R3 fit-shaped routing development; independent checks and integrated qualification remain",
                  "source_hashes": source_hashes,
                  "boards": results, "failed_boards": failures,
                  "requested_boards": [f'f1_ch{p["site"]}_{p["role"]}' for p in selected],
                  "physical_specimens_tested": 0,
                  "fabrication_ready": False}
        (folder / "artwork.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "boards": len(results),
                            "geometric_passes": sum(r["geometry_checks"]["passed"] for r in results),
                            "failed_boards": [{k: v for k, v in f.items() if k != "failed_path"} for f in failures],
                            "physical_specimens_tested": 0}
        print(json.dumps(record["result"], indent=2))
        if any(digest(ROOT / name) != expected for name, expected in source_hashes.items()):
            raise ValueError("An input changed during the run; preserve it and regenerate")
        if failures or not results or not all(r["geometry_checks"]["passed"] for r in results):
            raise ValueError("Fitted electrode copper still has unresolved geometry")


if __name__ == "__main__":
    main()
