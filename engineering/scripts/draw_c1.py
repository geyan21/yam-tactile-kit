#!/usr/bin/python3
"""Render C1's checked parts, gauge positions and manufacturing review drawings."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"] = str(ROOT/"build/engineering/tools/cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import cadquery as cq
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle,Circle
import numpy as np
import trimesh

from analyze_baseline_meshes import PARTS
from prototype_cad import packed
import draw_l1
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/c1"
COLORS = {"frame":"#657c89","tpu":"#a8bd80","c1fixed":"#31847c",
          "c1floating":"#cb8542","c1beam":"#8296a3","c1clamp":"#506977",
          "c1gauge":"#d8a648","hardware":"#555f66","tool":"#d4aa72"}
EXPLODE = {"frame":(0,-15,-10),"tpu":(-10,-15,-10),"c1fixed":(0,15,-8),
           "c1floating":(0,0,-5),"c1beam":(0,0,8),"c1clamp":(0,0,17),
           "c1gauge":(0,0,8),"hardware":(0,0,25)}


def mesh_of(shape):
    vertices,faces = shape.tessellate(.025,.1)
    return trimesh.Trimesh(vertices=[v.toTuple() for v in vertices],faces=faces,process=True)


def components(plan,cfg):
    result = []
    for group,path in (("frame",PARTS["hard_frame"]),("tpu",PARTS["soft_insert"])):
        mesh = trimesh.load_mesh(path,process=True)
        mesh.apply_translation(plan["finger_translation_native_mm"])
        result.append((group,"Original "+group,mesh))
    for name in plan["assembly_part_ids"]:
        group = "c1beam" if name=="c1_strain_beam" else "c1clamp" if name.endswith("_clamp") else "c1floating" if "floating" in name else "c1fixed"
        result.append((group,name,trimesh.load_mesh(OUTPUT/"cad"/f"{name}.stl",process=True)))
    g = cfg["gauges"]
    for row in plan["gauges"]:
        x,y,z = row["center_native_mm"]
        direction = 1 if row["face"]=="top" else -1
        grid = trimesh.creation.box([g["grid_length_mm"],g["grid_width_mm"],.025])
        grid.apply_translation([x,y,z+direction*.025])
        result.append(("c1gauge",row["id"]+" active-grid location",grid))
    m = cfg["mount"];b = cfg["beam"]
    top = b["bottom_native_z_mm"]+b["thickness_mm"]+m["clamp_cap_thickness_mm"]
    for x,y in plan["clamp_holes_native_xy_mm"]:
        washer = trimesh.creation.cylinder(radius=m["m4_head_washer_diameter_mm"]/2,height=m["m4_washer_thickness_mm"],sections=24)
        washer.apply_translation([x,y,top+m["m4_washer_thickness_mm"]/2])
        head = trimesh.creation.cylinder(radius=3.5,height=m["m4_head_height_mm"],sections=24)
        head.apply_translation([x,y,top+m["m4_washer_thickness_mm"]+m["m4_head_height_mm"]/2])
        result += [("hardware","M4 washer-stack envelope",washer),("hardware","M4 socket-head envelope",head)]
    interface = json.loads((ROOT/"engineering/release/l1/root_interface.json").read_text())
    for x,z in interface["bolt_centers_native_xz_mm"]:
        fixed_front = plan["fixed_mount_plane_y_mm"]-m["fixed_root_plate_thickness_mm"]
        head = cq.Solid.makeCone(3,1.7,1.3,cq.Vector(x,fixed_front+.05,z),cq.Vector(0,1,0))
        result.append(("hardware","Flush M3 fixed-head reference",mesh_of(head)))
        transform = trimesh.geometry.align_vectors([0,0,1],[0,1,0])
        transform[:3,3] = [x,plan["floating_mount_plane_y_mm"]+m["floating_root_plate_thickness_mm"]+m["m3_rear_hardware_projection_mm"]/2,z]
        reference = trimesh.creation.cylinder(radius=m["m3_rear_hardware_diameter_mm"]/2,
                                              height=m["m3_rear_hardware_projection_mm"],sections=24,transform=transform)
        result.append(("hardware","Floating M3 rear hardware envelope",reference))
    return result


def main():
    plan = json.loads((OUTPUT/"c1_manifest.json").read_text())
    cfg = json.loads((ROOT/"engineering/designs/c1.json").read_text())
    with execution(ROOT/"build/records","Render C1 physical part geometry and labeled gauge-grid positions; no fabricated specimen is pictured") as record:
        parts = components(plan,cfg)
        draw_l1.COLORS.update(COLORS)
        with PdfPages(OUTPUT/"c1_review_drawings.pdf") as pdf:
            for exploded,name in ((False,"c1_assembly"),(True,"c1_exploded")):
                shown = []
                for group,_,source in parts:
                    mesh = source.copy()
                    if exploded:
                        mesh.apply_translation(EXPLODE.get(group,(0,0,0)))
                    shown.append((group,mesh))
                fig,ax = plt.subplots(figsize=(13,6))
                ax.imshow(draw_l1.depth_image(shown,width=1600,height=570));ax.set_axis_off()
                fig.suptitle("C1 · "+("exploded root-force assembly" if exploded else "bare original finger with a strain-sensing root"),fontsize=19,color="#203f46")
                fig.text(.035,.085,"Original frame + TPU · fixed carrier · floating carrier · metal strain beam · two end clamps",fontsize=11)
                fig.text(.035,.04,"CAD rendering. Gold markers locate active gauge grids; full gauge backings, leads and wrist electronics are not shown.",fontsize=10)
                fig.savefig(OUTPUT/f"{name}.png",dpi=140,bbox_inches="tight")
                pdf.savefig(fig);plt.close(fig)
            b = cfg["beam"];g = cfg["gauges"]
            x0 = b["fixed_boundary_native_x_mm"];x1 = x0+b["active_length_mm"]
            y0,y1 = plan["beam_y_bounds_mm"]
            fig,axes = plt.subplots(1,2,figsize=(13,5),layout="constrained")
            for ax,face in zip(axes,("top","bottom")):
                ax.add_patch(Rectangle((x0,y0),b["active_length_mm"],b["width_mm"],facecolor="#e0e8e9",edgecolor="#677d85"))
                for a in (x0-b["end_clamp_length_mm"],x1):
                    ax.add_patch(Rectangle((a,y0),b["end_clamp_length_mm"],b["width_mm"],facecolor="#a9b9be",edgecolor="#677d85"))
                for x,y in plan["clamp_holes_native_xy_mm"]:
                    ax.add_patch(Circle((x,y),b["end_hole_diameter_mm"]/2,facecolor="white",edgecolor="#677d85"))
                for row in plan["gauges"]:
                    if row["face"]!=face:
                        continue
                    x,y,z = row["center_native_mm"]
                    ax.add_patch(Rectangle((x-g["grid_length_mm"]/2,y-g["grid_width_mm"]/2),
                                           g["grid_length_mm"],g["grid_width_mm"],facecolor="#c6923d"))
                    ax.text(x,y+2.5,row["id"],ha="center",fontsize=11,fontweight="bold",color="#775125")
                    ax.annotate("",xy=(x+3*row["tabs_toward_native_x"],y),xytext=(x,y),
                                arrowprops={"arrowstyle":"->","color":"#775125"})
                ax.set_xlim(x0-11,x1+11);ax.set_ylim(y0-3,y1+6);ax.set_aspect("equal")
                ax.set_xlabel("Native X (mm) · fixed end left")
                ax.set_ylabel("Native Y (mm)")
                ax.set_title(face.capitalize()+" face · grid positions\nArrows indicate lead-tab direction")
                ax.grid(alpha=.15)
            fig.suptitle("Eight CEA-13-062UWA-350 gauges · four per bridge · align the active grid, not the backing center")
            fig.savefig(OUTPUT/"c1_gauge_placement.svg")
            pdf.savefig(fig);plt.close(fig)
            fig = plt.figure(figsize=(11.7,8.3))
            lines = [
                "C1.1 manufacturing review · dimensions in millimeters · use STEP masters",
                "",
                f"Metal beam: {b['active_length_mm']} active + two {b['end_clamp_length_mm']} end clamps;",
                f"  width {b['width_mm']}, thickness {b['thickness_mm']}, 6061-T6 aluminum.",
                "All load-path parts must be metal. Printed copies are fit witnesses.",
                "",
                f"Added reach {plan['added_reach_mm']:.1f}; global width addition {plan['added_global_width_mm']:.2f}.",
                f"Added back height with reserved hardware: {plan['added_back_height_with_reserved_hardware_mm']:.2f}.",
                "Original nail and TPU retained; no contact film is needed on the nail.",
                "",
                "Gauge grid centers (X, Y, Z), with grid axes parallel to native X:",
            ]
            lines += [f"  {r['id']}: ({r['center_native_mm'][0]:.3f}, {r['center_native_mm'][1]:.3f}, {r['center_native_mm'][2]:.3f})"
                      for r in plan["gauges"]]
            lines += [
                "",
                "Grid: 1.57 x 3.05. Actual backing: 7.9 x 4.8; backing is asymmetric.",
                "The larger keepout allows backing placement without guessing its grid offset.",
                "Use the marking stencil and manufacturer bonding instructions.",
                "",
                "Beam end through bores: 4.5. Carrier pilot bores: 3.3; tap M4 x 0.7.",
                "Four M4 x 25 screws. Two 0.5 mm small-OD washers per screw; total stack 1.0.",
                "Fixed clearance mount: M3 90-degree flat heads <=6.0 OD seated flush.",
                "Alternative fixed carrier has 2.5 bores for M3 threads.",
                "Floating rear hardware <=7 OD and <=4.5 projection; verify actual lengths.",
                "",
                "Force range, drift, joint slip, endurance and robot tasks require physical tests.",
                "Finite-element calculations use ideal bonded joints and do not qualify hardware.",
            ]
            fig.text(.05,.95,"\n".join(lines),va="top",fontsize=9.5,family="monospace",linespacing=1.45)
            pdf.savefig(fig);plt.close(fig)
        model = {
            "id":"c1_assembly","title":"C1 · transverse strain beam at the finger root","coordinates":"native_mm","assembly":True,
            "components":[packed(mesh,name,group,COLORS[group],EXPLODE.get(group,(0,0,0))) for group,name,mesh in parts],
            "note":"Actual checked CAD with hardware envelopes and active-grid location markers. Gauge backing, coating, leads and wrist electronics are omitted. No C1 hardware has been tested.",
        }
        models = [model]
        for part in plan["parts"]:
            models.append({"id":part["id"],"title":part["id"].replace("_"," "),"coordinates":"native_mm",
                           "components":[packed(trimesh.load_mesh(OUTPUT/part["stl"],process=True),part["purpose"],"tool",COLORS["tool"])],
                           "note":part["purpose"]+" "+part["material"]})
        (OUTPUT/"models.json").write_text(json.dumps(models,separators=(",",":"))+"\n")
        record["rendered"] = {"assembly_components":len(parts),"models":len(models),"physical_photographs":0}
        print(json.dumps(record["rendered"],indent=2))


if __name__=="__main__":
    main()
