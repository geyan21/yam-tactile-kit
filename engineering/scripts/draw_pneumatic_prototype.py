#!/usr/bin/python3
"""Render the checked P1 finger and remote bench board from their actual CAD."""

import argparse
from datetime import datetime, timezone
import csv
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT/"build/engineering/tools/pneumatic-matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/pneumatic-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as PatchPolygon, Circle
from mpl_toolkits.mplot3d import proj3d
import numpy as np
import trimesh
from analyze_baseline_meshes import PARTS
from build_b1_parts import side_outline
from prototype_cad import packed
from draw_capacitive_prototype import draw_mesh, setup_axes
from screen_f1_feedback import digest
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assembly", "bench", "board", "pairs"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ("assembly", "bench", "board", "pairs")}
    reports = {name: json.loads((path/"report.json").read_text()) for name, path in paths.items()}
    if any(not reports[name]["passed_nominal_checks"] for name in ("assembly", "bench")):
        raise ValueError("Render a passing complete mechanical selection")
    cfg_path = ROOT/"engineering/designs/pneumatic_electronics.json"
    cfg = json.loads(cfg_path.read_text())
    layout_paths = [ROOT/name for name in reports["assembly"]["input_sha256"]
                    if "/wall_pair_layouts/" in name and name.endswith("/report.json")]
    if len(layout_paths) != 1:
        raise ValueError("Missing the actual channel-section layout")
    layout = json.loads(layout_paths[0].read_text())
    frame = packed(trimesh.load_mesh(PARTS["hard_frame"], process=True), "original_hard_frame", "frame", "#9ca9a4")
    finger = [frame, *json.loads((paths["assembly"]/"models.json").read_text())]
    bench = []
    for item in json.loads((paths["bench"]/"models.json").read_text()):
        if item["name"] == "p1_pico_body_reference":
            item["color"] = "#44a68b"
        (finger if item["group"] == "p1_nails" else bench).append(item)
    for item in finger:
        group = item["group"]
        if item["name"].endswith("_local_hose"):
            item["group"], item["color"] = "p1_hoses", "#b8cad2"
        item["explosion"] = ([0, 0, -5] if group == "p1_nails" else
                             [-8, 0, 0] if group in ("p1_hardware", "p1_seals") else
                             [5, 0, 0] if group == "p1_front_air" else
                             [-5, 0, 0] if group == "p1_back_air" else [0, 0, 0])
    models = [
        {"id": "p1_assembly_reference", "title": "P1.0 · eight air channels and two thin nail cells",
         "coordinates": "native_mm", "assembly": True, "components": finger,
         "note": "Checked nominal CAD. Blue/purple are gas-space references, not solid parts to print. Only the first 8 mm of each hose is modeled. Four wrist transducers and remaining slack hoses are separate. No physical builds or 20 N qualification."},
        {"id": "p1_bench_reference", "title": "P1.0 · four remote pressure transducers and Pico carrier",
         "coordinates": "native_mm", "assembly": True, "components": bench,
         "note": "Board outline/holes match the checked PCB. Electronic shapes are nominal body envelopes; actual ports, headers and lead seating require inspection. Open bench carrier, not a qualified wrist mount."}]
    folder = ROOT/"build/engineering/prototypes/pneumatic/visuals"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Render the P1 CAD, distinguish fluid voids and purchased references, and generate the port cut/wiring table directly from selected poses") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        fig = plt.figure(figsize=(13, 7), layout="constrained")
        axis = fig.add_subplot(111, projection="3d", computed_zorder=False)
        for item in finger:
            alpha = {"frame": .10, "p1_insert": .18, "p1_seals": .28, "p1_hoses": .35}.get(item["group"], .9)
            draw_mesh(axis, item, alpha)
        points = np.vstack([item["vertices"] for item in finger])
        setup_axes(axis, points, elevation=25, azimuth=-65)
        for site in range(2, 6):
            item = next(row for row in finger if row["name"] == f"p1_ch{site}_front_air_space")
            center = np.asarray(item["vertices"]).mean(axis=0)[[1, 2, 0]]
            x, y, _ = proj3d.proj_transform(*center, axis.get_proj())
            axis.annotate(f"CH{site}", (x, y), xytext=(0, -24), textcoords="offset points",
                          fontsize=9, ha="center", zorder=1000,
                          bbox={"fc": "white", "ec": "#708f96", "alpha": .96},
                          arrowprops={"arrowstyle": "-", "color": "#53727d"})
        fig.suptitle("P1.0 · blue front / purple back air channels, orange N0 nail cells\n"
                     "Original hard frame retained · 0 physical builds · hose slack and 20 N performance unverified", fontsize=12)
        for extension in ("png", "svg", "pdf"):
            fig.savefig(folder/("p1_assembly_iso."+extension), dpi=170)
        plt.close(fig)
        fig, axis = plt.subplots(figsize=(14, 5.7), layout="constrained")
        hard_outline = side_outline(trimesh.load_mesh(PARTS["hard_frame"], process=True))
        axis.add_patch(PatchPolygon(np.asarray(hard_outline.exterior.coords), fill=False, ec="#8e9995",
                                    lw=1.3, label="Original hard-frame outline"))
        profile = layout["modified_profile"]
        axis.add_patch(PatchPolygon(np.asarray(profile["outer"]), fc="#c8d8bd", ec="#607957", lw=1))
        for ring in profile["holes"]:
            axis.add_patch(PatchPolygon(np.asarray(ring), fc="white", ec="#708763", lw=.65))
        for case in layout["cases"]:
            for role, color in (("front", "#286f91"), ("back", "#805b95")):
                _, y, z = case[role]["center_native_mm"]
                axis.add_patch(Circle((y, z), layout["channel_diameter_mm"]/2, fc=color, ec=color))
                axis.plot(y, z, "o", ms=4, color=color)
            front, back = case["front"]["center_native_mm"], case["back"]["center_native_mm"]
            middle_y = (front[1]+back[1])/2
            axis.annotate(f"CH{case['site']}\nfront / back", (back[1], back[2]), xytext=(middle_y, 37),
                          ha="center", fontsize=11, bbox={"fc": "white", "ec": "#9baea1"},
                          arrowprops={"arrowstyle": "-", "color": "#60796e"})
        # The nail prongs overlap in this side projection; the 3D view
        # separates them across X. Plot only the actual laminate meshes.
        for item in finger:
            if not item["name"].endswith("_n0_laminate"):
                continue
            vertices = np.asarray(item["vertices"])
            axis.scatter(vertices[:, 1], vertices[:, 2], s=1, color="#bd883f")
        axis.annotate("CH0 + CH1\nTwo thin nail prongs\n0.4 mm nominal addition",
                      (-110, -3.8), xytext=(-107, 24), ha="center", fontsize=11,
                      arrowprops={"arrowstyle": "-", "color": "#a47d41"})
        axis.plot([], [], "o", color="#286f91", label="Front air channel → B high")
        axis.plot([], [], "o", color="#805b95", label="Back air channel → A low")
        axis.set(xlim=(-122, 3), ylim=(-7, 44), xlabel="Native Y (mm; nail at left)", ylabel="Native Z (mm)")
        axis.set_aspect("equal")
        axis.grid(alpha=.12)
        axis.legend(loc="lower right", fontsize=9)
        fig.suptitle("P1.0 · where the sensing elements go\n"
                     "Section through the soft insert; original hard frame shown as an outline", fontsize=14)
        for extension in ("png", "svg", "pdf"):
            fig.savefig(folder/("p1_assembly."+extension), dpi=170)
        plt.close(fig)
        fig = plt.figure(figsize=(11, 8), layout="constrained")
        axis = fig.add_subplot(111, projection="3d", computed_zorder=False)
        for item in bench:
            draw_mesh(axis, item, .28 if item["name"] == "p1_bench_carrier" else .95, order=(0, 1, 2))
        setup_axes(axis, np.vstack([item["vertices"] for item in bench]), elevation=45, azimuth=-70, order=(0, 1, 2))
        axis.set(xlabel="Carrier X (mm)", ylabel="Carrier Y (mm)", zlabel="Carrier Z (mm)")
        for channel in cfg["channels"]:
            center = [channel["center_mm"][0]+15, channel["center_mm"][1]+3, 23.6]
            x, y, _ = proj3d.proj_transform(*center, axis.get_proj())
            axis.annotate(f"{channel['sensor']} → CH{channel['site']}", (x, y), xytext=(0, 10),
                          textcoords="offset points", fontsize=9, ha="center", zorder=1000,
                          bbox={"fc": "white", "ec": "#758da0", "alpha": .96})
        x, y, _ = proj3d.proj_transform(55, 31, 23.1, axis.get_proj())
        axis.annotate("Pico", (x, y), xytext=(0, 0), textcoords="offset points", ha="center",
                      fontsize=10, zorder=1000, bbox={"fc": "white", "ec": "#758da0", "alpha": .96})
        fig.suptitle("P1.0 readout · 4 × ELVR-L30D-F1RD-C-NI3H at the wrist / bench\n"
                     "80 × 86 mm PCB on an insulating carrier · 3.0 V pressure rail · electronic bodies are references", fontsize=12)
        for extension in ("png", "svg", "pdf"):
            fig.savefig(folder/("p1_readout."+extension), dpi=170)
        plt.close(fig)
        ports = []
        slim = json.loads((ROOT/"engineering/designs/pneumatic_slim_port.json").read_text())
        for row in reports["assembly"]["ports"]:
            pose = row["pose"]
            channel = next(channel for channel in cfg["channels"] if row["id"] in (channel["B_high"], channel["A_low"]))
            special = pose["kind"] == "embedded_slim"
            ports.append({"channel": row["id"], "transducer": channel["sensor"],
                          "transducer_port": "B high" if row["id"] == channel["B_high"] else "A low",
                          "route": pose["kind"], "exit_sign_x": pose["sign"],
                          "metal_tube_od_mm": slim["stem_outer_diameter_mm"] if special else 1.6,
                          "metal_tube_id_mm": slim["stem_inner_diameter_mm"] if special else 1.0,
                          "metal_cut_length_mm": slim["embedded_length_mm"]+slim["external_length_mm"] if special else pose["metal_tube_length_mm"],
                          "sleeve": "OD1.6 / ID1.3 / L3 mm" if special else "none",
                          "plug_x_faces_mm": ";".join(str(v) for v in pose["plug_faces_x_mm"]),
                          "outlet_x_mm": row["outlet_center_native_mm"][0],
                          "outlet_y_mm": row["outlet_center_native_mm"][1],
                          "outlet_z_mm": row["outlet_center_native_mm"][2],
                          "nominal_air_before_hose_sensor_mm3": row["air_volume_before_hose_sensor_mm3"]})
        with (folder/"port_cut_and_hose_map.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, list(ports[0]), lineterminator="\n")
            writer.writeheader(); writer.writerows(ports)
        for name in ("p1_pressure_sensitivity.png", "p1_pressure_sensitivity.svg", "p1_pressure_sensitivity.pdf"):
            shutil.copyfile(paths["pairs"]/name, folder/name)
        shutil.copyfile(paths["board"]/"assembly.svg", folder/"p1_pcb_assembly.svg")
        inputs = [Path(__file__), cfg_path, ROOT/"engineering/designs/pneumatic_slim_port.json",
                  ROOT/"engineering/scripts/draw_capacitive_prototype.py",
                  ROOT/"engineering/scripts/build_b1_parts.py", layout_paths[0], PARTS["hard_frame"]]
        inputs += [path/"report.json" for path in paths.values()]
        inputs += [paths[name]/"models.json" for name in ("assembly", "bench")]
        inputs += [paths["board"]/"assembly.svg"]
        report = {"schema": "yam-p1-prototype-visuals/1", "physical_specimens_tested": 0, "ports": ports,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "files_sha256": {path.name: digest(path) for path in folder.iterdir() if path.is_file()}}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "models": len(models), "port_cuts": ports}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
