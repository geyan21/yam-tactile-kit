#!/usr/bin/python3
"""Render B1 from actual meshes, including its separate fixed sensing assembly."""

import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Circle,Polygon as PlotPolygon
import numpy as np
import trimesh
from analyze_baseline_meshes import PARTS
import draw_l1
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/b1"
COLORS={"frame":"#657c89","b1tpu":"#a8bd80","spine":"#24897f","magnet":"#cc8047",
        "plug":"#e1bf67","pcb":"#716b9b","hardware":"#555f66"}
draw_l1.COLORS.update(COLORS)


def components(plan):
    pieces=[("frame",trimesh.load_mesh(PARTS["hard_frame"],process=True))]
    for key,name in (("b1tpu","b1_magnetic_tpu_insert"),("spine","b1_fixed_sensor_spine")):
        pieces.append((key,trimesh.load_mesh(OUTPUT/f"cad/{name}.stl",process=True)))
    for magnet in plan["magnet_locations"]:
        x,y,z=magnet["native_xyz_mm"]
        mesh=trimesh.load_mesh(OUTPUT/"cad/b1_magnet_reference.stl",process=True)
        mesh.apply_translation([x-.5,y,z]);pieces.append(("magnet",mesh))
        plug=trimesh.load_mesh(OUTPUT/"cad/b1_flush_magnet_plug.stl",process=True)
        plug.apply_translation([-1.15,y,z]);pieces.append(("plug",plug))
    for sensor in plan["sensor_poses"]:
        mesh=trimesh.load_mesh(OUTPUT/"cad/b1_sensor_pcb_reference.stl",process=True)
        transform=np.eye(4)
        transform[:3,:3]=sensor["rotation_sensor_to_native"]
        transform[:3,3]=sensor["pcb_top_origin_native_mm"]
        mesh.apply_transform(transform);pieces.append(("pcb",mesh))
    for mount in plan["carrier_mounts"]:
        transform=trimesh.geometry.align_vectors([0,0,1],[1,0,0])
        transform[:3,3]=np.array(mount["reserved_head_origin_native_mm"])+[mount["reserved_head_height_mm"]/2,0,0]
        pieces.append(("hardware",trimesh.creation.cylinder(radius=mount["reserved_head_diameter_mm"]/2,
            height=mount["reserved_head_height_mm"],sections=24,transform=transform)))
    return pieces


def main():
    plan=json.loads((OUTPUT/"b1_manifest.json").read_text())
    seed=json.loads((OUTPUT/"layout_seed.json").read_text())
    config=json.loads((ROOT/"engineering/designs/b1.json").read_text())
    with execution(ROOT/"build/records","Render B1 assembly, placement and manufacturing review dimensions from checked CAD") as record:
        pieces=components(plan)
        with PdfPages(OUTPUT/"b1_review_drawings.pdf") as pdf:
            for exploded,name in ((False,"b1_assembly"),(True,"b1_exploded")):
                shown=[]
                offsets={"b1tpu":[-10,0,-8],"magnet":[2,0,-8],"plug":[6,0,-8],
                         "pcb":[16,0,0],"spine":[30,0,0],"hardware":[40,0,0]}
                for key,source in pieces:
                    mesh=source.copy()
                    if exploded:mesh.apply_translation(offsets.get(key,[0,0,0]))
                    shown.append((key,mesh))
                fig,ax=plt.subplots(figsize=(13,6))
                ax.imshow(draw_l1.depth_image(shown,width=1600,height=570));ax.set_axis_off()
                fig.suptitle("B1 · "+("separate parts" if exploded else "controlled compliance, fixed readout"),fontsize=20,color="#203f46")
                fig.text(.04,.09,"Original hard frame  ·  modified TPU  ·  four magnets and plugs  ·  five sensor heads  ·  fixed spine",fontsize=11)
                fig.text(.04,.045,"Actual meshes / unbuilt prototype. Wire routing, epoxy fillets and optional nail films are not pictured.",fontsize=10)
                fig.savefig(OUTPUT/f"{name}.png",dpi=140,bbox_inches="tight")
                pdf.savefig(fig);plt.close(fig)
            fig,ax=plt.subplots(figsize=(13,5.5),layout="constrained")
            for key,color,label in (("hard_outline_yz","#657c89","Original frame"),
                                    ("tpu_outline_yz","#739d49","TPU outer profile")):
                p=np.asarray(seed[key]);ax.plot(p[:,0],p[:,1],color=color,label=label)
            for magnet in plan["magnet_locations"]:
                _,y,z=magnet["native_xyz_mm"]
                ax.add_patch(Circle((y,z),1.5,facecolor=COLORS["magnet"]))
                ax.annotate(magnet["id"],(y,z),xytext=(0,-18),textcoords="offset points",ha="center")
            for sensor in plan["sensor_poses"]:
                ax.add_patch(PlotPolygon(sensor["footprint_yz"],facecolor=COLORS["pcb"],alpha=.18,edgecolor=COLORS["pcb"]))
                y,z=sensor["native_yz_mm"];ax.plot(y,z,"+",color=COLORS["pcb"])
                ax.text(y,z+2,sensor["id"],ha="center",fontsize=9)
            for mount in plan["carrier_mounts"]:
                ax.add_patch(Circle(mount["center_yz_mm"],3,fill=False,edgecolor="#555",linestyle=":"))
            ax.set_aspect("equal");ax.grid(alpha=.15);ax.legend(loc="upper left")
            ax.set_xlabel("Native Y (mm) · leading nail at left");ax.set_ylabel("Native Z (mm)")
            ax.set_title("Sensor placement · all electronics on the fixed side spine")
            fig.savefig(OUTPUT/"b1_layout.svg")
            pdf.savefig(fig);plt.close(fig)
            fig=plt.figure(figsize=(11.7,8.3))
            text=[
                "B1.0 manufacturing review · millimeters · do not scale this page",
                "",
                "Original TPU outer profile and attachment bores retained; hard frame unchanged.",
                f"Four side pockets: diameter {config['insert']['pocket_diameter_mm']:.2f}, depth 2.15.",
                "Magnets: N48, 3 × 1, axial north toward +native X (sensor side).",
                "Plug: 1.15 long, 3.10 stem, 3.40 bead. Groove 3.55 × 0.30.",
                "Print and gauge a pocket first. Do not force an oversize magnet into TPU.",
                "",
                "Pocket centers (X is magnet center, not side opening):",
            ]
            text += [f"  {m['id']}: ({m['native_xyz_mm'][0]:.3f}, {m['native_xyz_mm'][1]:.3f}, {m['native_xyz_mm'][2]:.3f})"
                     for m in plan["magnet_locations"]]
            text += ["","Five identical PCB heads: 8 × 6.4 × 0.8; component face points inward.",
                     f"PCB component-side plane: X={plan['sensor_pcb_top_x_mm']:.3f}.",
                     f"Outer spine: X={plan['carrier_outer_x_mm']:.3f}. Backing tape: 0.10.",
                     f"Added global width: {plan['added_global_width_excluding_fastener_heads_and_wires_mm']:.2f} without heads;",
                     f"  {plan['added_global_width_including_reserved_heads_excluding_wires_mm']:.2f} with reserved heads; wires excluded.",
                     "Reserved M3 head: diameter 6 × height 2.4. Choose actual nonmagnetic hardware.",
                     "Carrier bores: 3.4. Measure the original stack to select screw lengths.",
                     "",
                     "No unchanged-stiffness, 20 N capacity, accuracy or fatigue claim.",
                     "Use STEP/STL and the PCB fabrication archive; test one build before scaling."]
            fig.text(.07,.94,"\n".join(text),va="top",fontsize=11,family="monospace",linespacing=1.6)
            pdf.savefig(fig);plt.close(fig)
        record["rendered_components"]=len(pieces)
        print(json.dumps({"rendered_components":len(pieces),"drawings":"b1_review_drawings.pdf"}))


if __name__=="__main__":main()
