#!/usr/bin/python3
"""Extract the fitted 64-taxel map and a declared foil-conductor resistance screen."""

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PlotPolygon
import numpy as np
from shapely import affinity, segmentize
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from tactile_kit.records import execution
from f1_surfaces import load_surfaces, layer_offsets
from develop_f1_fitted_artwork import fabrication, unroll
from screen_f1_feedback import digest


def pieces(shape):
    if shape.geom_type == "Polygon":
        return [shape]
    return [p for part in getattr(shape, "geoms", []) for p in pieces(part)]


def reference_shape(shape, surface, basis):
    unrotated = affinity.rotate(shape, -basis["fabrication_rotation_deg"], origin=(0, 0))
    flat = affinity.scale(unrotated, xfact=basis["fabrication_x_mirror"], yfact=1, origin=(0, 0))
    flat = segmentize(flat, .1)
    arc = surface.offset_arc(basis["conductor_offset_mm"])
    def ring(coordinates):
        values = np.asarray(coordinates)
        return list(zip(values[:, 0], np.interp(values[:, 1], arc, surface.s)))
    return unary_union([Polygon(ring(p.exterior.coords), [ring(r.coords) for r in p.interiors])
                        for p in pieces(flat)])


def electrodes(data, entry, surface):
    basis = entry["metadata"]["basis"]
    film_flat = fabrication(unroll(surface.active, surface, basis["conductor_offset_mm"]), basis)
    window = unary_union([Polygon(p["outline_mm"]) for p in data["coverlay_openings"] if p["layer"] == "F.Mask"])
    holes = unary_union([Point(via["center"]).buffer(via["drill_mm"]/2, quad_segs=32)
                         for via in data["plated_connections"]])
    nets = {}
    for region in data["regions"]:
        if region["layer"] != "F.Cu":
            continue
        exposed = Polygon(region["outline_mm"]).intersection(window).intersection(film_flat).difference(holes)
        if exposed.area > 1e-6:
            nets.setdefault(region["net"], []).append(reference_shape(exposed, surface, basis))
    return {net: unary_union(shapes) for net, shapes in nets.items()}


def path_squares(path):
    result = 0.
    length = 0.
    for a, b, wa, wb in zip(path["points_mm"], path["points_mm"][1:],
                             path["widths_mm"], path["widths_mm"][1:]):
        segment = math.dist(a, b)
        if min(wa, wb) <= 0:
            raise ValueError("Nonpositive conductor width")
        length += segment
        result += segment/wa if abs(wa-wb) < 1e-12 else segment*math.log(wb/wa)/(wb-wa)
    return result, length


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artwork", type=Path)
    args = parser.parse_args()
    source = args.artwork.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/f1/artwork_runs"):
        parser.error("Use one preserved fitted-artwork run")
    plan_path = source / "artwork.json"
    plan = json.loads(plan_path.read_text())
    receipt = json.loads((source / "latest_independent_check.json").read_text())
    check_path = ROOT / receipt["directory"] / "summary.json"
    check = json.loads(check_path.read_text())
    if (not check["all_passed"] or check["artwork_manifest_sha256"] != digest(plan_path)
            or plan.get("failed_boards") or len(plan["boards"]) != 12):
        raise ValueError("Use all twelve independently checked, unchanged fitted foils")
    stack_path = ROOT / "engineering/development/f1/r3/configuration/f1_formed_stack.json"
    targets_path = ROOT / "engineering/designs/f1_flex_targets.json"
    conductor_path = ROOT / "engineering/designs/f1_fanout_manufacturing_targets.json"
    stack, _, _, surfaces = load_surfaces(stack_path)
    targets = json.loads(targets_path.read_text())
    screen = json.loads(conductor_path.read_text())["resistance_screen"]
    rho = screen["copper_resistivity_ohm_mm_at_20c"]
    copper = targets["materials"]["copper_nominal_mm_per_layer"]
    minimum_copper = targets["materials"]["copper_minimum_mm_required_for_resistance_budget"]
    minimum_width_fraction = 1-targets["routing"]["trace_width_relative_tolerance_from_fabricator"]
    heat = 1+screen["copper_temperature_coefficient_per_c"]*(screen["temperature_c_assumed"]-20)
    entries = {row["name"]: row for row in plan["boards"]}
    verified = {row["name"]: row for row in check["boards"]}
    output = source / "fitted_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Map checked F1 fitted copper onto individual source surfaces and calculate a stated one-dimensional foil resistance scenario; preserve unknown force and whole-system status") as record:
        output.mkdir(parents=True, exist_ok=False)
        inputs = [plan_path, check_path, stack_path, targets_path, conductor_path, Path(__file__),
                  ROOT / "engineering/scripts/develop_f1_fitted_artwork.py", ROOT / "engineering/scripts/f1_surfaces.py"]
        input_hashes = {str(path.relative_to(ROOT)): digest(path) for path in inputs}
        row_paths, contact_sites, pixels = [], [], []
        fig, axes = plt.subplots(2, 3, figsize=(13, 10), layout="constrained")
        for site, surface in enumerate(surfaces):
            sets = {}
            for role in ("rows", "columns"):
                name = f"f1_ch{site}_{role}"
                entry, identity = entries[name], verified[name]
                folder = ROOT / entry["directory"]
                data_path = folder / (name+".json")
                if (digest(data_path) != identity["source_metadata_sha256"]
                        or digest(folder / (name+".kicad_pcb")) != identity["source_pcb_sha256"]
                        or digest(folder / (name+".kicad_dru")) != identity["source_rules_sha256"]):
                    raise ValueError("Fitted artwork changed after native checking")
                data = json.loads(data_path.read_text())
                sets[role] = electrodes(data, entry, surface)
                expected_nets = {n for n in entry["metadata"]["pin_map"].values() if n != "unused"}
                if set(sets[role]) != expected_nets:
                    raise ValueError("An expected electrode does not reach the pressure-film region")
                by_net = {}
                for path in data["paths"]:
                    squares, length = path_squares(path)
                    value = by_net.setdefault(path["net"], {"squares": 0., "length_mm": 0., "minimum_nominal_width_mm": 1e6})
                    value["squares"] += squares
                    value["length_mm"] += length
                    value["minimum_nominal_width_mm"] = min(value["minimum_nominal_width_mm"], min(path["widths_mm"]))
                for net, value in by_net.items():
                    nominal = rho*value["squares"]/copper
                    scenario = rho*heat*value["squares"]/(minimum_copper*minimum_width_fraction)
                    row_paths.append({"site": f"CH{site}", "role": role, "net": net, **value,
                                      "nominal_20c_trace_ohm": nominal,
                                      "screen_50c_minimum_copper_width_trace_ohm": scenario,
                                      "plated_transitions": sum(v["net"] == net for v in data["plated_connections"])})
            ax = axes.flat[site]
            ax.add_patch(PlotPolygon(surface.body.exterior.coords, fc="#f0f2e8", ec="#647969"))
            site_pixels = []
            for row, row_shape in sorted(sets["rows"].items()):
                for column, column_shape in sorted(sets["columns"].items(), key=lambda p: int(p[0][1:])):
                    area = row_shape.intersection(column_shape).intersection(surface.active)
                    if area.area < 1 or len(pieces(area)) != 1:
                        raise ValueError("A nominal taxel lacks one substantial connected overlap")
                    u, s = area.centroid.coords[0]
                    pixel = {"site": f"CH{site}", "row": int(row[1:]), "column": int(column[1:]),
                             "source_surface_area_mm2": area.area, "source_u_s_mm": [u, s],
                             "center_native_mm": surface.points(u, s, layer_offsets(site, stack)["film_center"]).tolist(),
                             "reference_outline_mm": list(area.exterior.coords),
                             "reference_holes_mm": [list(r.coords) for r in area.interiors],
                             "force_calibration": None}
                    pixels.append(pixel)
                    site_pixels.append(pixel)
                    ax.add_patch(PlotPolygon(area.exterior.coords, fc=plt.get_cmap("tab20")(int(column[1:])%20),
                                            ec="white", linewidth=.5, alpha=.85))
                    for ring in area.interiors:
                        ax.add_patch(PlotPolygon(ring.coords, fc="white"))
                    ax.text(u, s, f"{row}\n{column}", ha="center", va="center", fontsize=7)
            contact_sites.append({"site": f"CH{site}", "source_edge": entries[f"f1_ch{site}_rows"]["metadata"]["source_edge"],
                                  "taxels": len(site_pixels),
                                  "minimum_source_overlap_mm2": min(p["source_surface_area_mm2"] for p in site_pixels),
                                  "column_order_in_increasing_source_u": entries[f"f1_ch{site}_columns"]["metadata"]["spatial_electrodes"]})
            ax.autoscale_view()
            ax.invert_yaxis()
            ax.set(aspect="equal", xlabel="Source U (mm)", ylabel="Distal → proximal arc (mm)",
                   title=f'CH{site} · {"nail" if site < 2 else "TPU"} · {len(site_pixels)} electrical locations')
        if {(p["row"], p["column"]) for p in pixels} != {(r, c) for r in range(4) for c in range(16)} or len(pixels) != 64:
            raise ValueError("The fitted contact map is not exactly one 4 × 16 allocation")
        fig.suptitle("F1 R3 fitted copper · common source-surface contact map\n"
                     "Nominal registered layers; no physical pressure or force measurements", fontsize=14)
        for suffix in ("png", "pdf", "svg"):
            fig.savefig(output / ("fitted_contact_map."+suffix), dpi=160)
        plt.close(fig)
        numerical = np.trapezoid(1/np.linspace(.15, .44, 10001), dx=10/10000)
        analytical = 10*math.log(.44/.15)/(.44-.15)
        relative_error = abs(numerical-analytical)/analytical
        if relative_error > 1e-8:
            raise ValueError("The tapered trace integral failed its independent numerical check")
        report = {"schema": "yam-f1-fitted-review/1", "physical_specimens_tested": 0,
                  "complete_f1_assembly": False, "input_sha256": input_hashes,
                  "checked_foils": 12, "taxels": pixels, "sites": contact_sites, "foil_paths": row_paths,
                  "path_integral_numerical_relative_error": relative_error,
                  "resistance_assumptions": {"rho_ohm_mm_at_20c": rho, "nominal_copper_mm": copper,
                                             "minimum_copper_mm": minimum_copper, "width_fraction": minimum_width_fraction,
                                             "screen_temperature_c": screen["temperature_c_assumed"],
                                             "temperature_multiplier": heat},
                  "limits": [
                      "Contact areas are nominal overlaps after separate layer unrolling and inverse mapping; registration, deformation, film spreading and crosstalk are not measured.",
                      "Resistance is a one-dimensional linearly tapered trace estimate, not an upper bound or a complete electrical path.",
                      "Electrode spreading, plated barrels, pad current crowding, finish, connector contacts, PCB, cable and strain-induced resistance changes are excluded.",
                      "31.5 µm minimum copper and 20% negative width tolerance are declared procurement/screen conditions, not measurements of delivered foils.",
                      "Connector mating, finished stiffeners, sealing, object access, loaded motion, fatigue, full-array/reference behavior and 20 N force/contact validation remain."
                  ]}
        (output / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        with (output / "taxels.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["site", "row", "column", "source_area_mm2", "native_x_mm", "native_y_mm", "native_z_mm"])
            for p in pixels:
                writer.writerow([p["site"], p["row"], p["column"], p["source_surface_area_mm2"], *p["center_native_mm"]])
        with (output / "foil_resistance.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row_paths[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(row_paths)
        record["result"] = {"directory": str(output.relative_to(ROOT)), "checked_foils": 12,
                            "taxels": len(pixels), "foil_paths": len(row_paths),
                            "minimum_overlap_mm2": min(p["source_surface_area_mm2"] for p in pixels),
                            "maximum_nominal_trace_ohm": max(p["nominal_20c_trace_ohm"] for p in row_paths),
                            "maximum_screen_trace_ohm": max(p["screen_50c_minimum_copper_width_trace_ohm"] for p in row_paths),
                            "physical_specimens_tested": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
