#!/usr/bin/python3
"""Extract actual row/column overlaps and placement from checked F1 artwork."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Polygon as PlotPolygon
import numpy as np
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def polygons(shape):
    return [shape] if shape.geom_type == "Polygon" else list(shape.geoms)


def serialized(shape):
    return [{"outer": list(poly.exterior.coords), "holes": [list(ring.coords) for ring in poly.interiors]}
            for poly in polygons(shape) if poly.area > 1e-9]


def patch(ax, shape, color, alpha=.7):
    for poly in polygons(shape):
        if poly.area <= 1e-9:
            continue
        ax.add_patch(PlotPolygon(list(poly.exterior.coords), facecolor=color, edgecolor="white", alpha=alpha))
        for ring in poly.interiors:
            ax.add_patch(PlotPolygon(list(ring.coords), facecolor="white", edgecolor="white"))


def electrode_sets(board, mirror):
    opening = next(item for item in board["coverlay_openings"] if item["layer"] == "F.Mask")
    window = Polygon(opening["outline_mm"])
    holes = unary_union([Point(row["center"]).buffer(row["drill_mm"]/2) for row in board["plated_connections"]])
    by_net = {}
    for row in board["regions"]:
        if row["layer"] != "F.Cu":
            continue
        copper = Polygon(row["outline_mm"]).intersection(window).difference(holes)
        if copper.area <= 1e-8:
            continue
        copper = affinity.scale(copper, xfact=mirror, yfact=1, origin=(0, 0))
        by_net.setdefault(row["net"], []).append(copper)
    return {net: unary_union(items) for net, items in by_net.items()}, affinity.scale(
        window, xfact=mirror, yfact=1, origin=(0, 0))


def native_point(site, point, basis, r1, contact):
    x, y = point
    if site < 2:
        u = x + basis["nail_u_origin_mm"]
        v = basis["nail_v_at_flat_y_zero_mm"] - y
        return (np.asarray(contact["nail_plane_origin_native_mm"])
                + u*np.asarray(contact["nail_plane_u_axis_native"])
                + v*np.asarray(contact["nail_plane_v_axis_native"])).tolist()
    curve = np.asarray(r1["pads"][site-2]["front_curve_native_yz_mm"])
    arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))]
    return [float(x-7.5), float(np.interp(y, arc, curve[:, 0])),
            float(np.interp(y, arc, curve[:, 1]))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artwork", type=Path)
    args = parser.parse_args()
    source = args.artwork.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/f1/artwork_runs"):
        parser.error("Select an owned F1 artwork run")
    plan = json.loads((source / "artwork.json").read_text())
    receipt = json.loads((source / "latest_independent_check.json").read_text())
    check_path = ROOT / receipt["directory"] / "summary.json"
    check = json.loads(check_path.read_text())
    if not check["all_passed"] or check["artwork_manifest_sha256"] != digest(source / "artwork.json"):
        raise ValueError("Use artwork with a matching completed independent check")
    records = {row["name"]: row for row in plan["boards"]}
    checked_boards = {row["name"]: row for row in check["boards"]}
    r1_path = ROOT / "engineering/release/r1/r1_manifest.json"
    contact_path = ROOT / "engineering/release/contact_regions/contact_report.json"
    r1 = json.loads(r1_path.read_text()); contact = json.loads(contact_path.read_text())
    output = source / "contact_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Extract contact areas from checked F1 copper and coverlay, retaining drill holes and explicit reference-surface coordinates") as record:
        output.mkdir(parents=True, exist_ok=False)
        sites = []; pixels = []
        with PdfPages(output / "f1_routed_contacts.pdf") as pdf:
            for site in range(6):
                names = [f"f1_ch{site}_{role}" for role in ("rows", "columns")]
                if any(name not in records for name in names):
                    raise ValueError("A complete contact map needs all twelve foils")
                data = [json.loads((ROOT / records[name]["directory"] / (name + ".json")).read_text()) for name in names]
                for name in names:
                    folder = ROOT / records[name]["directory"]
                    if (digest(folder / (name + ".json")) != checked_boards[name]["source_metadata_sha256"]
                            or digest(folder / (name + ".kicad_pcb")) != checked_boards[name]["source_pcb_sha256"]
                            or digest(folder / (name + ".kicad_dru")) != checked_boards[name]["source_rules_sha256"]):
                        raise ValueError("Artwork changed after its independent check")
                row_nets, row_window = electrode_sets(data[0], 1)
                col_nets, col_window = electrode_sets(data[1], -1)
                film = row_window.intersection(col_window).buffer(-.05)
                if film.geom_type != "Polygon" or film.area <= 0:
                    raise ValueError("The candidate conductive-film outline is invalid")
                site_pixels = []
                for row_net, row_shape in sorted(row_nets.items()):
                    for col_net, col_shape in sorted(col_nets.items(), key=lambda item: int(item[0][1:])):
                        overlap = row_shape.intersection(col_shape).intersection(film)
                        if overlap.is_empty or overlap.area < 1:
                            raise ValueError("A routed pixel has insufficient connected overlap")
                        x, y = overlap.centroid.coords[0]
                        pixel = {"site": f"CH{site}", "row": int(row_net[1:]), "column": int(col_net[1:]),
                                 "flat_copper_overlap_mm2": overlap.area,
                                 "center_common_flat_mm": [x, y],
                                 "center_on_reference_surface_native_mm": native_point(
                                     site, (x, y), records[names[0]]["metadata"]["basis"], r1, contact),
                                 "polygons_common_flat_mm": serialized(overlap)}
                        site_pixels.append(pixel); pixels.append(pixel)
                sites.append({"site": f"CH{site}", "pixels": site_pixels,
                              "candidate_film_outline_common_flat_mm": serialized(film),
                              "row_pin_map": records[names[0]]["metadata"]["pin_map"],
                              "column_pin_map": records[names[1]]["metadata"]["pin_map"]})
                fig, axes = plt.subplots(1, 3, figsize=(12, 5), layout="constrained")
                for net, shape in row_nets.items():
                    patch(axes[0], shape, plt.cm.Blues(.4+.13*int(net[1:])))
                for index, (net, shape) in enumerate(col_nets.items()):
                    patch(axes[1], shape, plt.cm.Oranges(.4+.15*index))
                for pixel in site_pixels:
                    shape = unary_union([Polygon(item["outer"], item["holes"])
                                         for item in pixel["polygons_common_flat_mm"]])
                    patch(axes[2], shape, plt.cm.viridis(.15+.7*(pixel["column"] % 4)/3))
                    x, y = pixel["center_common_flat_mm"]
                    axes[2].text(x, y, str(pixel["row"])+","+str(pixel["column"]), ha="center", va="center", fontsize=9)
                for ax, title in zip(axes, ("Upper rows · projected through backing",
                                          "Lower columns · assembly orientation", "Actual copper overlap · row,column")):
                    ax.set_title(title, fontsize=9)
                    ax.autoscale_view(); ax.invert_yaxis(); ax.set_aspect("equal")
                    ax.set_xlabel("Common assembly X (mm)")
                    ax.grid(alpha=.15)
                fig.suptitle(f"F1 CH{site} · routed electrode overlap\nDevelopment geometry; mounted offsets and tail routing remain", fontsize=13)
                fig.savefig(output / f"f1_ch{site}_contact.svg")
                fig.savefig(output / f"f1_ch{site}_contact.png", dpi=150)
                pdf.savefig(fig); plt.close(fig)
        if len(pixels) != 64 or len({(row["row"], row["column"]) for row in pixels}) != 64:
            raise ValueError("Routed F1 contact map is not a unique 4 × 16 allocation")
        report = {"schema": "yam-f1-routed-contact-development/1",
                  "evidence_kind": "checked_artwork_geometry", "physical_specimens_tested": 0,
                  "taxels": len(pixels), "sites": sites,
                  "minimum_flat_copper_overlap_mm2": min(row["flat_copper_overlap_mm2"] for row in pixels),
                  "artwork_manifest_sha256": digest(source / "artwork.json"),
                  "independent_check_sha256": digest(check_path),
                  "source_hashes": {str(path.relative_to(ROOT)): digest(path) for path in
                                    (Path(__file__), r1_path, contact_path)},
                  "limits": [
                      "Areas are copper overlaps in the current flat reference-surface artwork, with drill holes removed.",
                      "Coordinates lie on the original nail/R1 saddle surface; mounted layer offsets and separate neutral-plane unrolls are not yet applied.",
                      "The film outline is a development candidate, not a qualified sealing or registration process.",
                      "No physical contact threshold, crosstalk, force, wear or 20 N performance is established."
                  ]}
        (output / "routed_contacts.json").write_text(json.dumps(report, indent=2) + "\n")
        with (output / "routed_contacts.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["site", "row", "column", "overlap_mm2", "reference_x_mm", "reference_y_mm", "reference_z_mm"])
            for pixel in pixels:
                writer.writerow([pixel["site"], pixel["row"], pixel["column"],
                                 pixel["flat_copper_overlap_mm2"], *pixel["center_on_reference_surface_native_mm"]])
        record["result"] = {"directory": str(output.relative_to(ROOT)),
                            "taxels": len(pixels), "minimum_area_mm2": report["minimum_flat_copper_overlap_mm2"],
                            "physical_specimens_tested": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
