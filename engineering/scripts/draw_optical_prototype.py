#!/usr/bin/python3
"""Render O1's checked CAD, optical path, molds and actual LED board placement."""

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT/"build/engineering/tools/optical-matplotlib"))
sys.path.insert(0, str(ROOT/"src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Polygon as PatchPolygon
from mpl_toolkits.mplot3d import proj3d
import numpy as np
from shapely.geometry import MultiPoint
import trimesh
from draw_capacitive_prototype import draw_mesh, setup_axes
from inspect_optical_obstructions import segments
from screen_f1_feedback import digest
from tactile_kit.records import execution


def style(item):
    name = item["name"]
    group = ("o1_nails" if name.startswith("o1_ch") else
             "o1_camera" if name.startswith("o1_camera_") and name.endswith("_reference") else
             "o1_mirror" if "mirror" in name else "o1_gel" if "gel_blank" in name or "coating" in name else
             "o1_lighting" if name.startswith(("o1_D", "o1_R", "o1_J", "o1_led", "o1_light_mount")) else
             "o1_clips" if "retaining_clip" in name else "o1_frame" if name in ("o1_retained_gel_frame", "o1_camera_bay_lid") else "o1_hardware")
    item["group"] = group
    item["color"] = {"o1_nails": "#c9994f", "o1_camera": "#846e9d", "o1_mirror": "#5988a3",
                     "o1_gel": "#a3cdb1", "o1_lighting": "#477bbe", "o1_clips": "#968963",
                     "o1_frame": "#a3b1a5", "o1_hardware": "#8e969b"}[group]
    item["explosion"] = [0, 0, {"o1_gel": -8, "o1_mirror": 6, "o1_camera": 8, "o1_lighting": 12,
                               "o1_clips": -5, "o1_nails": -5}.get(group, 0)]
    return item


def board_svg(board, destination):
    scale, ox, oy = 25, 48, 115
    result = ['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="640" viewBox="0 0 1100 640">',
              '<rect width="1100" height="640" fill="#f5f8f4"/>',
              '<g font-family="sans-serif" fill="#203f46">',
              '<text x="32" y="42" font-size="27" font-weight="bold">O1 blue LED ring • actual component-side placement</text>',
              '<text x="32" y="76" font-size="18">16 × 16 × 0.8 mm · 2 copper layers · Ø8 mm nonplated lens aperture</text>',
              f'<rect x="{ox}" y="{oy}" width="400" height="400" fill="#d5e8d8" stroke="#55776a"/>']
    for track in board["tracks"]:
        a, b = track["start"], track["end"]
        result.append(f'<path d="M{ox+a[0]*scale} {oy+a[1]*scale}L{ox+b[0]*scale} {oy+b[1]*scale}" fill="none" stroke="{("#c87d59" if track["layer"]=="F.Cu" else "#5e87aa")}" stroke-width="{track["width"]*scale}" opacity=".35"/>')
    result.append(f'<circle cx="{ox+200}" cy="{oy+200}" r="100" fill="#f5f8f4" stroke="#657f7e"/>')
    for part in board["parts"]:
        x, y = [value*scale for value in part["center_mm"]]
        width, height, _ = part["body_mm"]
        color = "#75a4d5" if part["reference"].startswith("D") else "#dcc198"
        result.append(f'<rect x="{ox+x-width*scale/2}" y="{oy+y-height*scale/2}" width="{width*scale}" height="{height*scale}" fill="{color}" stroke="#526971" transform="rotate({-part["rotation_deg"]} {ox+x} {oy+y})"/>')
        label_x, label_y = ox+x, oy+y-25
        if part["reference"] == "R2":
            label_x, label_y = ox+418, oy+205
        elif part["reference"] == "R4":
            label_x, label_y = ox-19, oy+205
        elif part["reference"] == "D1":
            label_x, label_y = ox+x+45, oy+y-20
        result.append(f'<text x="{label_x}" y="{label_y}" text-anchor="middle" font-size="16" font-weight="bold">{part["reference"]}</text>')
    for pad in board["pads"]:
        x, y = pad["center"]; width, height = pad["size"]
        color = "#c4754d" if pad["net"] == "LED_5V" else "#466b81" if pad["net"] == "GND" else "#d6b34b"
        result.append(f'<rect x="{ox+(x-width/2)*scale}" y="{oy+(y-height/2)*scale}" width="{width*scale}" height="{height*scale}" fill="{color}" stroke="white" stroke-width=".7" transform="rotate({-pad["rotation"]} {ox+x*scale} {oy+y*scale})"/>')
        result.append(f'<text x="{ox+x*scale}" y="{oy+y*scale+5}" text-anchor="middle" font-size="13" fill="white">{html.escape(pad["pad"])}</text>')
    notes = [
        ("J1 power leads", "Pin 1 (left, square land): +5 V", "Pin 2 (right): GND"),
        ("D1–D4: APT2012QBC/D", "Pin 1 / cathode is LEFT on all four.", "Pin 2 / anode is RIGHT on all four."),
        ("R1–R4: 220 Ω each", "Use 1206, 1%, at least 0.25 W.", "R1/R3 left and R2/R4 lower pad = +5 V."),
        ("Assembly", "Use the carrier's four short edge lips.", "Keep the lens hole and moving barrel clear."),
    ]
    for i, (heading, first, second) in enumerate(notes):
        y = 140+i*100
        result += [f'<text x="506" y="{y}" font-size="22" font-weight="bold">{heading}</text>',
                   f'<text x="506" y="{y+30}" font-size="18">{first}</text>',
                   f'<text x="506" y="{y+57}" font-size="18">{second}</text>']
    result += ['<text x="32" y="571" font-size="18">Land geometry and wiring follow the native KiCad board; use its Gerbers/drills for fabrication.</text>',
               '<text x="32" y="604" font-size="17">CAD mapping: u = KiCad x − 8; v = 8 − KiCad y; component face n = 5.6 mm.</text></g></svg>']
    destination.write_text("\n".join(result)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("assembly", "tools", "board", "refraction"):
        parser.add_argument("--"+key, type=Path, required=True)
    args = parser.parse_args()
    paths = {key: getattr(args, key).resolve() for key in ("assembly", "tools", "board", "refraction")}
    reports = {key: json.loads((paths[key]/"report.json").read_text()) for key in ("assembly", "tools", "refraction")}
    if any(not reports[key]["passed_nominal_checks"] for key in ("assembly", "tools")):
        raise ValueError("Render a passing assembly and mold selection")
    for report in reports.values():
        for name, expected in report["input_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError("A visual input changed: "+name)
    board_path = paths["board"]/"o1_blue_ring.json"
    board = json.loads(board_path.read_text())
    search_path = ROOT/next(name for name in reports["assembly"]["input_sha256"] if "/path_searches/" in name and name.endswith("report.json"))
    plan = json.loads(search_path.read_text()); cfg = json.loads((ROOT/plan["configuration"]).read_text())
    reach = reports["assembly"]["added_reach_mm"]
    finger = [style(item) for item in json.loads((paths["assembly"]/"models.json").read_text())]
    molds = json.loads((paths["tools"]/"models.json").read_text())
    for item in molds:
        role = ("rear" if "rear_half" in item["name"] else "stencil" if "stencil" in item["name"]
                else "cast" if "cavity_reference" in item["name"] else "contact")
        item["group"] = "o1_mold_"+role
        item["explosion"] = [0, 0, {"rear": 12, "stencil": -8, "cast": 4, "contact": 0}[role]]
    models = [{"id": "o1_assembly_reference", "title": "O1.0 · fixed optics, removable gel and two thin nail cells",
               "coordinates": "native_mm", "assembly": True, "components": finger,
               "note": "Actual nominal CAD; electronic bodies are dimensional references. 32 mm added reach. Gel/coating/optics and 20 N performance are unbuilt and unqualified."},
              {"id": "o1_tools_reference", "title": "O1.0 · gel molds and marker stencil",
               "coordinates": "native_mm", "assembly": True, "components": molds,
               "note": "Tooling in original sensing-core coordinates. Cast the clear gel; do not print a rigid replacement for it. Physical curing, coating and demolding are unqualified."}]
    folder = ROOT/"build/engineering/prototypes/optical/visuals"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Render O1's checked actual CAD, fixed camera rays, casting tools and native LED placement; preserve the neutral-refraction edge exits and physical limits") as record:
        folder.mkdir(parents=True)
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        fig, ax = plt.subplots(figsize=(14, 6.5), layout="constrained")
        for item in finger:
            vertices = np.asarray(item["vertices"])
            name = item["name"]
            if name == "o1_retained_gel_frame":
                mesh = trimesh.Trimesh(vertices=vertices, faces=item["faces"], process=False)
                lines = trimesh.intersections.mesh_plane(mesh, [1, 0, 0], [cfg["camera_x_mm"], 0, 0])
                ax.add_collection(LineCollection(lines[:, :, 1:], colors="#6f8278", linewidths=.7))
            elif name in ("o1_mirror_sheet_witness", "o1_camera_pcb_reference", "o1_camera_focus_housing_reference",
                          "o1_camera_lens_reference", "o1_led_pcb_reference") or name.endswith("_n0_laminate"):
                hull = MultiPoint(vertices[:, 1:]).convex_hull
                ax.add_patch(PatchPolygon(np.asarray(hull.exterior.coords), facecolor=item["color"], edgecolor="#617975",
                                         alpha=.55 if item["group"] == "o1_gel" else .85, linewidth=.7))
        # Use the exact curved gel profile, rather than its convex projection.
        outer, inner = np.asarray(plan["outer_gel_profile_yz_mm"]), np.asarray(plan["inner_gel_profile_yz_mm"])
        profile = np.vstack((outer, inner[::-1])); profile[:, 0] -= reach
        ax.add_patch(PatchPolygon(profile, fc="#b1d6ba", ec="#558970", lw=1.2))
        rays = segments(plan["selected"], np.asarray(plan["optical_targets_inner_yz_mm"]), cfg["active_half_width_mm"], cfg["camera_x_mm"])
        for ray in rays:
            if ray["x_offset_mm"] == 0 and ray["station"] % 5 == 1:
                a, b = ray["start"], ray["end"]
                ax.plot([a[1]-reach, b[1]-reach], [a[2], b[2]], color="#477fa9", lw=1, alpha=.65)
        marker_data = json.loads((paths["tools"]/"markers.json").read_text())
        for marker in marker_data:
            if marker["x_mm"] == cfg["camera_x_mm"]:
                ax.plot(marker["y_mm"]-reach, marker["z_mm"], "o", ms=3, color="#263e43")
        center = lambda name: np.asarray(next(item for item in finger if item["name"] == name)["vertices"]).mean(axis=0)[1:]
        gel_point = outer[len(outer)//2]-[reach, 0]
        labels = [
            ("Two N0 nail cells\n0.4 mm nominal addition", center("o1_ch0_n0_laminate"), (-139, 31)),
            ("Fixed PET mirror\n14 × 63.9 × 0.2 mm", center("o1_mirror_sheet_witness"), (-111, 60)),
            ("Clear Solaris gel + markers\n2.5 mm gel; white outer coating", gel_point, (-90, -16)),
            ("Camera + blue LED ring\ninside added root bay", center("o1_led_pcb_reference"), (-30, 53)),
            ("Original drive interface\n32 mm added finger reach", (-6, 13), (-8, -16)),
        ]
        for text, point, location in labels:
            ax.annotate(text, point, xytext=location, ha="center", fontsize=10,
                        bbox={"fc": "white", "ec": "#a2b3aa", "alpha": .96},
                        arrowprops={"arrowstyle": "-", "color": "#5d7b79"})
        ax.set(xlim=(-156, 12), ylim=(-24, 69), xlabel="Drive-referenced Y (mm)", ylabel="Z (mm)")
        ax.set_aspect("equal"); ax.grid(alpha=.12)
        fig.suptitle("O1.0 • sensor placement and folded camera view\nNominal CAD section; blue lines are viewing rays. No physical force or optical qualification.", fontsize=13)
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(folder/("o1_sensor_placement."+suffix), dpi=170)
        plt.close(fig)
        for title, values, stem, tool_view in (
            ("O1.0 • fixed optics and removable gel cartridge", finger, "o1_assembly", False),
            ("O1.0 • two mold halves, gel cavity and flexible dot stencil", molds, "o1_molds", True)):
            fig = plt.figure(figsize=(13, 7), layout="constrained")
            ax = fig.add_subplot(111, projection="3d", computed_zorder=False)
            plotted = []
            for item in values:
                shift = (0, 0, 12 if "rear_half" in item["name"] else -8 if "stencil" in item["name"] else 4 if "cavity_reference" in item["name"] else 0) if tool_view else (0, 0, 0)
                alpha = .18 if item["group"] == "o1_frame" else .45 if item["group"] == "o1_gel" else .9
                if tool_view:
                    alpha = .3 if "half" in item["name"] else .85
                draw_mesh(ax, item, alpha, shift=shift)
                plotted.append(np.asarray(item["vertices"])+shift)
            setup_axes(ax, np.vstack(plotted), elevation=28, azimuth=-58)
            fig.suptitle(title+"\nCAD only • casting, mating, optics, precision and 20 N response require physical tests", fontsize=13)
            for suffix in ("png", "svg", "pdf"):
                fig.savefig(folder/(stem+"."+suffix), dpi=170)
            plt.close(fig)
        board_svg(board, folder/"o1_led_assembly.svg")
        shutil.copyfile(ROOT/"engineering/web/o1_wiring.svg", folder/"o1_wiring.svg")
        shutil.copyfile(paths["tools"]/"o1_marker_pattern.svg", folder/"o1_marker_pattern.svg")
        for suffix in ("png", "svg", "pdf"):
            shutil.copyfile(paths["refraction"]/("o1_refraction."+suffix), folder/("o1_refraction."+suffix))
        length = plan["selected"]["mirror_length_mm"]
        (folder/"o1_mirror_cut.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="{length+24}mm" viewBox="0 0 40 {length+24}">'
            '<rect width="100%" height="100%" fill="white"/>'
            f'<rect x="13" y="6" width="14" height="{length}" fill="none" stroke="black" stroke-width=".15"/>'
            f'<path d="M13 {length+12}h10" stroke="black" stroke-width=".2"/>'
            f'<text x="4" y="{length+19}" font-family="sans-serif" font-size="2.3">10 mm scale • print at 100%</text></svg>\n')
        inputs = [Path(__file__), ROOT/"engineering/scripts/draw_capacitive_prototype.py", ROOT/"engineering/web/o1_wiring.svg",
                  search_path, ROOT/plan["configuration"], board_path, paths["tools"]/"markers.json"]
        inputs += [paths[key]/"report.json" for key in reports]
        inputs += [paths[key]/"models.json" for key in ("assembly", "tools")]
        report = {"schema": "yam-o1-prototype-visuals/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "files_sha256": {p.name: digest(p) for p in folder.iterdir() if p.is_file()},
                  "limits": "Nominal CAD and declared neutral optics model; no fabricated photographs or measured force data."}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "models": len(models), "files": len(report["files_sha256"])}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
