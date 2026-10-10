#!/usr/bin/python3
"""Render the B2 assembly, sensor placement and dimensioned review from its CAD."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT/"build/engineering/tools/mpl-cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Polygon as PlotPolygon, Circle
import numpy as np
from shapely.geometry import Polygon
import trimesh

import draw_l1
from prototype_cad import yz_prism, packed
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/b2"
COLORS = {"frame":"#657c89","b1tpu":"#a8bd80","magnet":"#cc8047","plug":"#e1bf67",
          "pcb":"#48967e","backer":"#2e746e","spacer":"#78afa1","electronics":"#8374a2",
          "nail":"#d69936","hardware":"#555f66"}
EXPLOSION = {"b1tpu":(-10,0,-8),"magnet":(2,0,-8),"plug":(6,0,-8),"nail":(0,0,-10),
             "pcb":(16,0,0),"electronics":(16,0,0),"spacer":(8,0,0),"backer":(30,0,0),"hardware":(40,0,0)}


def components(plan):
    models = json.loads((ROOT/"engineering/release/b1/models.json").read_text())
    result = []
    for c in models[0]["components"]:
        if c["group"] not in ("frame","b1tpu","magnet","plug","hardware"):
            continue
        result.append((c["group"],c["name"],trimesh.Trimesh(vertices=c["vertices"],faces=c["faces"],process=True)))
    r1 = json.loads((ROOT/"engineering/release/models.json").read_text())[0]
    for c in r1["components"]:
        if c["group"]=="laminate" and c["name"].startswith(("CH0 ","CH1 ")):
            result.append(("nail",c["name"].replace("CH0","T0").replace("CH1","T1"),
                           trimesh.Trimesh(vertices=c["vertices"],faces=c["faces"],process=True)))
    for part in plan["parts"]:
        group = "pcb" if part["kind"]=="reference_only" else "backer" if part["id"]=="b2_removable_backer" else "spacer"
        result.append((group,part["id"],trimesh.load_mesh(OUTPUT/part["stl"],process=True)))
    for item in plan["components"]:
        shape = yz_prism(Polygon(item["body_yz_mm"]),plan["pcb_component_plane_x_mm"]-item["height_mm"],item["height_mm"])
        vertices,faces = shape.tessellate(.02,.1)
        mesh = trimesh.Trimesh(vertices=[v.toTuple() for v in vertices],faces=faces,process=True)
        result.append(("electronics",item["reference"]+" package envelope",mesh))
    return result


def main():
    plan = json.loads((OUTPUT/"b2_manifest.json").read_text())
    config = json.loads((ROOT/"engineering/designs/b2.json").read_text())
    basis = json.loads((ROOT/"engineering/release/b1/b1_manifest.json").read_text())
    layout = json.loads((OUTPUT/"pcb/b2_design_checks.json").read_text())
    with execution(ROOT/"build/records","Render actual B2 parts and preserved sensing locations; no physical prototype photograph or force result") as record:
        pieces = components(plan)
        draw_l1.COLORS.update(COLORS)
        with PdfPages(OUTPUT/"b2_review_drawings.pdf") as pdf:
            for exploded,name in ((False,"b2_assembly"),(True,"b2_exploded")):
                shown = []
                for group,_,source in pieces:
                    mesh = source.copy()
                    if exploded:
                        mesh.apply_translation(EXPLOSION.get(group,(0,0,0)))
                    shown.append((group,mesh))
                fig,ax = plt.subplots(figsize=(13,6))
                ax.imshow(draw_l1.depth_image(shown,width=1600,height=570));ax.set_axis_off()
                fig.suptitle("B2 · "+("exploded prototype assembly" if exploded else "one PCB and removable backer"),fontsize=20,color="#203f46")
                fig.text(.04,.085,"Original frame · B1 TPU/magnets · N0 nail pads · one PCB · two spacers · backer",fontsize=11)
                fig.text(.04,.04,"Actual CAD + component envelopes. Hardware unbuilt; cable joints and seating film are not pictured.",fontsize=10)
                fig.savefig(OUTPUT/f"{name}.png",dpi=140,bbox_inches="tight")
                pdf.savefig(fig);plt.close(fig)
            fig,ax = plt.subplots(figsize=(13,5.7),layout="constrained")
            for group,_,mesh in pieces:
                if group not in ("frame","b1tpu"):
                    continue
                triangles = mesh.triangles[:,:,[1,2]]
                from shapely.ops import unary_union
                outline = unary_union([Polygon(t) for t in triangles if Polygon(t).area>1e-8])
                items = [outline] if outline.geom_type=="Polygon" else list(outline.geoms)
                for item in items:
                    ax.add_patch(PlotPolygon(list(item.exterior.coords),facecolor=COLORS[group],edgecolor="#586f76",alpha=.25))
            ax.add_patch(PlotPolygon(layout["pcb_outline_yz_mm"],facecolor=COLORS["pcb"],edgecolor="#276954",alpha=.45))
            for hole in layout["pcb_cutouts_yz_mm"]:
                ax.add_patch(PlotPolygon(hole,facecolor="white",edgecolor="#4c8277",alpha=.6))
            for mount in plan["supports"]:
                ax.add_patch(Circle(mount["center_yz_mm"],config["mechanical"]["board_bore_mm"]/2,
                                    facecolor="white",edgecolor="#3e6a61"))
            for magnet in basis["magnet_locations"]:
                _,y,z = magnet["native_xyz_mm"]
                ax.add_patch(Circle((y,z),1.5,facecolor=COLORS["magnet"]))
                ax.annotate(magnet["id"],(y,z),xytext=(0,-17),textcoords="offset points",ha="center",fontsize=10)
            for sensor in basis["sensor_poses"]:
                y,z = sensor["native_yz_mm"]
                ax.plot(y,z,"+",color="#514076",markersize=11)
                ax.text(y,z+2,sensor["id"],color="#514076",ha="center",fontsize=11,fontweight="bold")
            ax.annotate("T0 + T1\non the two nail prongs",(-108,-3),xytext=(-105,-14),
                        arrowprops={"arrowstyle":"->"},ha="center",fontsize=11,color="#a37024")
            ax.annotate("Mux + nail ADC\nsame board",(-14,16),xytext=(-14,35),
                        arrowprops={"arrowstyle":"->"},ha="center",fontsize=10)
            ax.set_xlim(-122,0);ax.set_ylim(-19,42);ax.set_aspect("equal");ax.grid(alpha=.15)
            ax.set_xlabel("Native Y (mm) · leading nail at left");ax.set_ylabel("Native Z (mm)")
            ax.set_title("B2 sensor placement · green is one rigid board; orange magnets move with the TPU")
            fig.savefig(OUTPUT/"b2_placement.svg")
            pdf.savefig(fig);plt.close(fig)
            fig = plt.figure(figsize=(11.7,8.3))
            lines = [
                "B2.1 manufacturing review · dimensions in mm · do not scale this page",
                "",
                "Original ENPIRE hard frame, B1 TPU, magnets and sensor poses retained.",
                "New hardware: one four-layer PCB, removable backer, two locating spacers.",
                f"PCB component plane X={plan['pcb_component_plane_x_mm']:.4f}; PCB thickness 0.80.",
                f"Backer outer X={plan['backer_outer_x_mm']:.4f}; backing thickness 1.20; seating film 0.10.",
                f"Nominal minimum IC/body-to-frame gap: {plan['minimum_component_to_frame_gap_mm']:.3f}.",
                f"Added reach: {plan['added_reach_mm']:.1f}.",
                f"Added global width: {plan['added_global_width_excluding_heads_and_wires_mm']:.3f} before heads;",
                f"  {plan['added_global_width_with_reserved_heads_excluding_wires_mm']:.3f} with reserved heads; wires excluded.",
                "",
                "PCB bores: 5.00. Spacer shoulder: 4.85 OD x 0.65 long; through bore: 3.20.",
                "Spacer body: 7.00 OD. Keep PCB clamping annuli free of copper.",
            ]
            for item in plan["supports"]:
                lines.append(f"{item['part']}: body length {item['main_length_mm']:.4f}; native Y/Z {item['center_yz_mm']}.")
            lines += [
                "",
                "S0-S4: five MLX90393SLW-ABA-011 ICs; address 0x0C per isolated branch.",
                "U10: TCA9548ARGER (RGE QFN-24), 0x70. U11: ADS1115IDGSR, 0x48.",
                "J1: pin 1 3V3, 2 GND, 3 SCL/GP5, 4 SDA/GP4.",
                "J2: pin 1 T0 excitation, 2 T0 sense, 3 T1 excitation, 4 T1 sense.",
                "A 100k continuity resistor stays across each nail pad at the fingertip.",
                "",
                "Print witnesses and measure installed fit before making a batch.",
                "CAD and PCB checks do not establish force accuracy, 20 N capacity or lifetime.",
                "Use the STEP masters, checked Gerbers/drills and complete B2 build guide.",
            ]
            fig.text(.055,.95,"\n".join(lines),va="top",fontsize=10,family="monospace",linespacing=1.65)
            pdf.savefig(fig);plt.close(fig)
        models = [{
            "id":"b2_assembly","title":"B2 · consolidated magnetic PCB with two nail pads",
            "coordinates":"native_mm","assembly":True,
            "components":[packed(mesh,name,group,COLORS[group],EXPLOSION.get(group,(0,0,0)))
                          for group,name,mesh in pieces],
            "note":"Actual CAD with component envelopes. Original frame, B1 TPU/magnets and R1 N0 nail cells are retained. Cables, solder joints and seating film are omitted. Physical fit, readout and force performance remain untested.",
        }]
        for part in plan["parts"]:
            models.append({"id":part["id"],"title":part["id"].replace("_"," "),"coordinates":"native_mm",
                           "components":[packed(trimesh.load_mesh(OUTPUT/part["stl"],process=True),
                                                part["purpose"],"tool",COLORS["backer"])],
                           "note":part["purpose"]})
        (OUTPUT/"models.json").write_text(json.dumps(models,separators=(",",":"))+"\n")
        record["rendered"] = {"assembly_components":len(pieces),"models":len(models),"physical_photographs":0}
        print(json.dumps(record["rendered"],indent=2))


if __name__ == "__main__":
    main()
