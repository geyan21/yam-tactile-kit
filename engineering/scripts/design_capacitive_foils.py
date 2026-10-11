#!/usr/bin/python3
"""Design K1 sensing electrodes, driven guards and two-land flex terminations."""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PlotPolygon, Circle
import numpy as np
from shapely import affinity, set_precision
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from tactile_kit.records import execution
from capacitive_geometry import CONFIG, load, offsets, unrolled, reference_footprints
from screen_f1_feedback import digest


GRID = 1e-5


def clean(shape, name):
    result = set_precision(shape, GRID)
    if result.geom_type != "Polygon" or result.is_empty or not result.is_valid or result.interiors:
        raise ValueError(name+" must be one simply connected polygon")
    if shape.symmetric_difference(result).area > GRID*shape.length*2:
        raise ValueError("Numerical cleanup moved "+name+" too far")
    return result


def coordinates(shape):
    return [list(point) for point in shape.exterior.coords]


def build(label, surface, cfg):
    f, e = cfg["flex"], cfg["electrode_design"]
    if surface is None:
        body, active = reference_footprints(cfg)
        neutral = None
    else:
        neutral = offsets(surface.site, cfg)["flex_bottom"]+f["coverlay_each_mm"]+f["copper_each_mm"]+f["polyimide_core_mm"]/2
        body = unrolled(surface.body, surface, neutral)
        active = unrolled(surface.active, surface, neutral)
    body, active = clean(body, "body"), clean(active, "active electrode")
    width = e["tail_width_mm"]
    length = e["reference_tail_length_mm"] if surface is None else e["sensor_tail_length_mm"]
    if surface is not None and surface.kind == "tpu":
        origin = np.array([body.bounds[0], (body.bounds[1]+body.bounds[3])/2])
        along, across = np.array([-1., 0.]), np.array([0., 1.])
        exit_name = "negative_U"
    else:
        # Place the terminal centre on a real width of the proximal edge.
        cross = body.intersection(LineString([[-100, body.bounds[3]-.05], [100, body.bounds[3]-.05]]))
        if cross.is_empty or cross.bounds[2]-cross.bounds[0] < width:
            raise ValueError(label+" has insufficient proximal width for its terminal")
        origin = np.array([(cross.bounds[0]+cross.bounds[2])/2, body.bounds[3]])
        along, across = np.array([0., 1.]), np.array([1., 0.])
        exit_name = "proximal"
    def local(point):
        return origin+point[0]*across+point[1]*along
    def rectangle(x0, x1, y0, y1):
        return Polygon([local(p) for p in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))])
    tail = rectangle(-width/2, width/2, -.4, length)
    source_outline = clean(body.union(tail), "source foil outline")
    outline = clean(source_outline.simplify(.002, preserve_topology=True), "foil outline")
    outline_deviation = source_outline.hausdorff_distance(outline)
    segment_lengths = [math.dist(a, b) for a, b in zip(outline.exterior.coords, list(outline.exterior.coords)[1:])]
    if outline_deviation > .00201 or min(segment_lengths) < .001:
        raise ValueError("Outline cleanup moved the edge too far or left microscopic segments")
    added_tail_area = outline.difference(body).area
    allowance = cfg["readout"]["reference_foil_tail_area_allowance_mm2"] if surface is None else cfg["readout"]["sensor_foil_tail_area_allowance_mm2"]
    if added_tail_area > allowance+1e-6:
        raise ValueError(label+" exceeds the shield-load tail-area allowance")
    pad_w, pad_l = e["terminal_pad_mm"]
    pad_s = length-e["terminal_end_inset_mm"]
    pads = []
    for pin, net, x in ((1, "CIN", -e["terminal_pitch_mm"]/2), (2, "SHLD", e["terminal_pitch_mm"]/2)):
        shape = rectangle(x-pad_w/2, x+pad_w/2, pad_s-pad_l/2, pad_s+pad_l/2)
        pads.append({"pin": pin, "net": net, "shape": shape, "center": local([x, pad_s]).tolist()})
    signal_pad = pads[0]
    # Extend a straight probe line inward from the CIN land. The first
    # intersection determines a source-matched feed without guessing a slope.
    end = np.asarray(signal_pad["center"])
    probe = LineString([end, end-along*200])
    intersection = probe.intersection(active)
    if intersection.is_empty or intersection.geom_type not in ("LineString", "MultiLineString"):
        raise ValueError("No direct electrode escape at "+label)
    segments = [intersection] if intersection.geom_type == "LineString" else list(intersection.geoms)
    endpoint = min((np.array(p) for segment in segments for p in segment.coords), key=lambda p: np.linalg.norm(end-p))
    start = endpoint-along*.1
    if not active.covers(Point(start)):
        raise ValueError("CIN escape does not enter the electrode")
    feed = LineString([start, end]).buffer(f["trace_mm"]/2+.01, cap_style="round")
    signal = clean(unary_union([active, feed, signal_pad["shape"]]), "CIN copper")
    copper_inside = outline.buffer(-(f["edge_clearance_mm"]+.02), join_style="mitre")
    # One opening through the guard provides the insulated CIN exit.
    guard = clean(copper_inside.difference(signal.buffer(f["clearance_mm"]+.02)),
                      "top driven guard")
    shield_back = clean(copper_inside, "back driven shield")
    if not guard.buffer(1e-6).covers(pads[1]["shape"]):
        raise ValueError("The SHLD terminal is not connected to the top guard")
    via = Point(pads[1]["center"]).buffer(e["shield_via_pad_mm"]/2)
    if not guard.covers(via) or not shield_back.covers(via):
        raise ValueError("The plated SHLD transition must be fully supported on both faces")
    edges = {name: outline.boundary.distance(shape) for name, shape in
             (("CIN", signal), ("front_SHLD", guard), ("back_SHLD", shield_back))}
    gap = signal.distance(guard)
    if min(edges.values()) < f["edge_clearance_mm"]-1e-7 or gap < f["clearance_mm"]-1e-7:
        raise ValueError("Copper clearance failed before native export")
    stiffener_length = min(length, e["sensor_stiffener_length_mm"])
    stiffener = rectangle(-width/2, width/2, length-stiffener_length, length)
    for pad in pads:
        if not stiffener.covers(pad["shape"]):
            raise ValueError("Solder land outside its mechanical stiffener")
    return {
        "name": "k1_"+label.lower()+"_flex", "site": label, "physical_layers": 2,
        "stack_total_mm": 2*f["copper_each_mm"]+f["polyimide_core_mm"]+2*f["coverlay_each_mm"],
        "body": body, "active": active, "outline": outline,
        "regions": [("CIN", "CIN", "F.Cu", signal), ("GUARD", "SHLD", "F.Cu", guard),
                    ("BACK_SHIELD", "SHLD", "B.Cu", shield_back)],
        "pads": pads, "via": {"center": pads[1]["center"], "pad_mm": e["shield_via_pad_mm"],
                               "drill_mm": e["shield_via_drill_mm"], "net": "SHLD"},
        "stiffener": stiffener, "stiffener_polyimide_mm": e["stiffener_polyimide_mm"],
        "stiffener_adhesive_mm": e["stiffener_adhesive_mm"],
        "tail": {"exit": exit_name, "origin_flat_mm": origin.tolist(), "along_flat": along.tolist(),
                 "across_flat": across.tolist(), "length_mm": length, "width_mm": width,
                 "added_area_mm2": added_tail_area, "reserved_area_mm2": allowance},
        "neutral_offset_mm": neutral, "CIN_feed_points_mm": [start.tolist(), end.tolist()],
        "outline_cleanup": {"maximum_deviation_mm": outline_deviation, "minimum_segment_mm": min(segment_lengths),
                            "symmetric_difference_mm2": source_outline.symmetric_difference(outline).area,
                            "method": "Topology-preserving 0.002 mm simplification, then 0.00001 mm coordinate grid"},
        "checks": {"minimum_copper_edge_mm": min(edges.values()), "CIN_SHLD_clearance_mm": gap,
                   "tail_within_area_allowance": True, "pads_and_via_on_stiffener": True},
        "physical_specimens_tested": 0,
    }


def payload(foil, cfg):
    result = {k: v for k, v in foil.items() if k not in ("body", "active", "outline", "regions", "pads", "stiffener")}
    result.update({"schema": "yam-k1-flex-artwork/1", "body_flat_mm": coordinates(foil["body"]),
                   "active_flat_mm": coordinates(foil["active"]), "outline_flat_mm": coordinates(foil["outline"]),
                   "regions": [{"id": name, "net": net, "layer": layer, "outline_mm": coordinates(shape)}
                               for name, net, layer, shape in foil["regions"]],
                   "pads": [{k: v for k, v in p.items() if k != "shape"} | {"outline_mm": coordinates(p["shape"])}
                            for p in foil["pads"]],
                   "stiffener_flat_mm": coordinates(foil["stiffener"]), "stack": cfg["flex"],
                   "status": "Fabrication geometry development; native DRC, formed fit and physical checks remain",
                   "terminal_intent": "Hand-solder only on lands 1/CIN and 2/SHLD. Two plate-ground leads remain separate.",
                   "limits": ["No physical fit, capacitance or force result is implied.",
                              "The initial tail path is a fabrication proposal; actual formed clearance must pass before release.",
                              "The reference is made twice. Its SHLD connects to SHLD2; finger-cell shields connect to SHLD1."]})
    return result


def main():
    cfg, surfaces = load()
    folder = ROOT / "build/engineering/prototypes/capacitive/foil_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Design seven K1 flex shapes with actual sensing copper, continuous driven guards, two exposed solder lands and backed shield transitions; retain all previous tooling and require independent native/formed checks") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = [CONFIG, Path(__file__), ROOT / "engineering/scripts/capacitive_geometry.py",
                  ROOT / "engineering/scripts/f1_surfaces.py"]
        for source in inputs:
            target = folder / "inputs" / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
        foils = []
        for surface in [*surfaces, None]:
            label = "REF" if surface is None else "CH"+str(surface.site)
            foil = build(label, surface, cfg)
            data = payload(foil, cfg)
            (folder / (foil["name"]+".json")).write_text(json.dumps(data, indent=2)+"\n")
            fig, axes = plt.subplots(1, 2, figsize=(10, 6), layout="constrained")
            for ax, layer in zip(axes, ("F.Cu", "B.Cu")):
                ax.add_patch(PlotPolygon(foil["outline"].exterior.coords, fc="#f0f3e8", ec="#526b6c"))
                for _, net, region_layer, shape in foil["regions"]:
                    if layer == region_layer:
                        ax.add_patch(PlotPolygon(shape.exterior.coords, fc="#b57745" if net == "CIN" else "#80a69a"))
                if layer == "F.Cu":
                    for pad in foil["pads"]:
                        ax.add_patch(PlotPolygon(pad["shape"].exterior.coords, fc="#d3bb68", ec="#867648"))
                        ax.text(*pad["center"], str(pad["pin"]), fontsize=8, ha="center", va="center")
                ax.add_patch(Circle(foil["via"]["center"], foil["via"]["drill_mm"]/2, fc="white", ec="#555"))
                ax.add_patch(PlotPolygon(foil["stiffener"].exterior.coords, fill=False, ec="#59728a", ls="--"))
                ax.autoscale_view(); ax.invert_yaxis(); ax.set(aspect="equal", xlabel="Developed U (mm)", ylabel="Developed arc (mm)", title=layer)
            fig.suptitle(label+" · K1 sensing electrode + driven guard\n1 = CIN · 2 = SHLD · blue outline = back stiffener · physical fit unqualified", fontsize=12)
            for suffix in ("png", "pdf", "svg"):
                fig.savefig(folder / (foil["name"]+"."+suffix), dpi=150)
            plt.close(fig)
            foils.append({"name": foil["name"], "file": foil["name"]+".json", "sha256": digest(folder / (foil["name"]+".json")),
                          "site": label, **foil["checks"], "tail_area_mm2": foil["tail"]["added_area_mm2"]})
            (folder / "partial.json").write_text(json.dumps(foils, indent=2)+"\n")
            print(label+": two conductors and backed terminations generated", flush=True)
        report = {"schema": "yam-k1-flex-layout/1", "physical_specimens_tested": 0, "boards": foils,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "status": "Geometry ready for native PCB and formed-assembly checks"}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "foils": len(foils), "physical_specimens_tested": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
