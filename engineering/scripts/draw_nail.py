#!/usr/bin/python3
"""Render the separate nail, gauge envelopes and retained four-cell TPU skin."""

import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"]=str(ROOT/"build/engineering/tools/cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import cadquery as cq
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle
import numpy as np
import trimesh

from analyze_baseline_meshes import PARTS
from nail_geometry import basis,native,local_x
from prototype_cad import packed,digest
import draw_l1
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/prototypes/nail"
COLORS={"frame":"#657c89","tpu":"#a8bd80","nailbody":"#8c9ca4",
        "nailleft":"#397d76","nailright":"#65a294","nailgauges":"#d7aa47",
        "saddles":"#bd8856","laminate":"#dba968","hardware":"#525f66","tool":"#c79758"}
EXPLODE={"frame":(0,0,10),"tpu":(0,0,-5),"nailbody":(0,-18,0),
         "nailleft":(-10,0,0),"nailright":(10,0,0),"saddles":(0,0,-12),"laminate":(0,0,-18)}


def mesh_of(shape):
    vertices,faces=shape.tessellate(.03,.1)
    return trimesh.Trimesh(vertices=[value.toTuple() for value in vertices],faces=faces,process=True)


def components(plan,cfg):
    rows=[]
    groups={"nail_bare_sensing_fork":"nailbody","nail_left_fixed_carrier":"nailleft",
            "nail_right_fixed_carrier":"nailright","nail_revised_hard_frame":"frame"}
    for part in plan["parts"]:
        rows.append((groups[part["id"]],part["purpose"],trimesh.load_mesh(OUTPUT/part["stl"],process=True),None))
    rows.append(("tpu","Original TPU insert",trimesh.load_mesh(PARTS["soft_insert"],process=True),None))
    r1=json.loads((ROOT/"engineering/release/models.json").read_text())[0]["components"]
    reused=[]
    for part in r1:
        if part["group"] in ("saddles","laminate") and part["name"].startswith(("CH2 ","CH3 ","CH4 ","CH5 ")):
            mesh=trimesh.Trimesh(vertices=part["vertices"],faces=part["faces"],process=True)
            rows.append((part["group"],"Retained R1 "+part["name"],mesh,None))
            reused.append(part["name"])
    if len(reused)!=8:
        raise ValueError("Expected exactly four retained TPU saddles and four laminate envelopes")
    plane,_,_=basis()
    for gauge in plan["gauges"]:
        x=gauge["outer_face_native_x_mm"]
        side=-1 if gauge["bridge"]==0 else 1
        # A visible 0.05 mm marker locates the purchased carrier's footprint.
        # It is not a claim about the actual bonded gauge thickness.
        marker=trimesh.creation.box([.05,*gauge["carrier_size_yz_mm"]])
        transform=np.eye(4);transform[:3,:3]=np.asarray(plan["nail_plane_axes_native"]).T
        transform[:3,3]=plane.toWorldCoords((local_x(x,plane)+side*.04,*gauge["center_nail_yz_mm"])).toTuple()
        marker.apply_transform(transform)
        rows.append(("nailgauges",gauge["id"]+" foil carrier location",marker,(side*14,-18,0)))
    # Flush flat-head references and the free end of each proposed M3x40
    # side-mount screw. Threaded engagement is shown in the drawings, not
    # replaced by solid shafts through the CAD's tap-drill holes.
    for hole in plan["clamp_holes"]:
        x=hole["outer_x_mm"];y,z=hole["center_native_yz_mm"]
        direction=1 if hole["carrier"]==0 else -1
        head=cq.Solid.makeCone(3,1.7,1.3,cq.Vector(x,y,z),cq.Vector(direction,0,0))
        rows.append(("hardware",hole["screw"]+" head reference",mesh_of(head),(direction*-12,0,0)))
    right=[row for row in plan["mounts"] if row["carrier"]==1]
    left=[row for row in plan["mounts"] if row["carrier"]==0]
    for a,b in zip(right,left):
        x=a["outer_x_mm"];y,z=a["center_native_yz_mm"]
        head=cq.Solid.makeCone(3,1.7,1.3,cq.Vector(x,y,z),cq.Vector(-1,0,0))
        rows.append(("hardware","M3x40 side-mount flat head",mesh_of(head),(12,0,0)))
        end=x-40
        if end<b["outer_x_mm"]:
            free=cq.Solid.makeCylinder(1.5,b["outer_x_mm"]-end,cq.Vector(end,y,z),cq.Vector(1,0,0))
            rows.append(("hardware","M3x40 free thread envelope",mesh_of(free),(-12,0,0)))
    return rows,reused


def gauge_figure(plan,cfg):
    fig,axes=plt.subplots(1,2,figsize=(13,5),layout="constrained")
    n=cfg["nail"];g=cfg["gauges"]
    for ax,row in zip(axes,plan["gauges"]):
        free,fixed=n["web_free_end_local_y_mm"],n["web_fixed_boundary_local_y_mm"]
        z=n["web_lower_local_z_mm"];height=n["web_height_mm"]
        ax.add_patch(Rectangle((free,z),fixed-free,height,facecolor="#dce6e8",edgecolor="#758b97"))
        ax.add_patch(Rectangle((fixed,z),n["clamp_end_length_mm"],height,facecolor="#a6b8bb",edgecolor="#758b97"))
        cy,cz=row["center_nail_yz_mm"];w,h=row["carrier_size_yz_mm"]
        ax.add_patch(Rectangle((cy-w/2,cz-h/2),w,h,facecolor="#dfbb65",edgecolor="#8c652e"))
        ax.plot([cy-2,cy+2],[cz-2,cz+2],color="#816135")
        ax.plot([cy-2,cy+2],[cz+2,cz-2],color="#816135")
        ax.text(cy,cz+5.2,"+Exc toward +Z",ha="center",fontsize=9)
        ax.text(cy,cz-5.3,"Purchased full bridge\n7.6 × 8.9 mm carrier",ha="center",va="top",fontsize=9)
        ax.annotate("",xy=(fixed,z-2),xytext=(cy,z-2),arrowprops={"arrowstyle":"<->","color":"#536b71"})
        ax.text((fixed+cy)/2,z-3.3,f"{fixed-cy:g} mm to clamp boundary",ha="center",fontsize=8)
        ax.set_xlim(free-2,fixed+n["clamp_end_length_mm"]+2)
        ax.set_ylim(z-5,z+height+4);ax.set_aspect("equal");ax.grid(alpha=.15)
        ax.set_xlabel("Nail-plane Y toward root (mm)");ax.set_ylabel("Nail-plane Z into finger (mm)")
        ax.set_title(f'{row["id"]} · outer native X = {row["outer_face_native_x_mm"]:.2f} mm',fontsize=12)
    fig.suptitle("N1 gauge placement · OMEGA SGT-2DD/350-SY41 on each outer web face\nDiagonal symbol indicates shear sensing; internal grid centers are not fabrication dimensions.",fontsize=12)
    return fig


def main():
    cfg=json.loads((ROOT/"engineering/designs/nail.json").read_text())
    plan=json.loads((OUTPUT/"nail_manifest.json").read_text())
    for name,expected in plan["source_hashes"].items():
        if digest(ROOT/name)!=expected:
            raise ValueError("Nail CAD is stale: "+name)
    with execution(ROOT/"build/records","Render actual new nail/frame CAD, both foil locations and all four TPU cells; no physical specimen is pictured") as record:
        rows,reused=components(plan,cfg)
        draw_l1.COLORS.update(COLORS)
        with PdfPages(OUTPUT/"nail_review_drawings.pdf") as pdf:
            for exploded in (False,True):
                pieces=[]
                for group,name,mesh,offset in rows:
                    copy=mesh.copy()
                    if exploded:
                        copy.apply_translation(offset or EXPLODE.get(group,(0,0,0)))
                    pieces.append((group,copy))
                fig=plt.figure(figsize=(13,6.8))
                ax=fig.add_axes((.02,.19,.96,.66))
                ax.imshow(draw_l1.depth_image(pieces,width=1700,height=730));ax.set_axis_off()
                fig.suptitle("N1 · "+("separate assembly components" if exploded else "bare sensing nail with four TPU contact cells"),
                             fontsize=18,color="#203f46")
                fig.text(.04,.115,"Steel fork + two shear webs · fixed side carriers · revised PETG frame · original TPU + four R1 cells",fontsize=10)
                fig.text(.04,.075,"CAD rendering. Gold rectangles locate purchased foil carriers; wiring, adhesive and protective coatings are not modeled.",fontsize=9)
                fig.text(.04,.04,"Experimental prototype · physical assembly, calibration and qualification pending",fontsize=9,color="#755846")
                fig.savefig(OUTPUT/("nail_exploded.png" if exploded else "nail_assembly.png"),dpi=150)
                pdf.savefig(fig);plt.close(fig)
            fig=gauge_figure(plan,cfg)
            fig.savefig(OUTPUT/"nail_gauge_placement.svg");fig.savefig(OUTPUT/"nail_gauge_placement.png",dpi=150)
            pdf.savefig(fig);plt.close(fig)
            fig,axes=plt.subplots(1,2,figsize=(13,7),layout="constrained")
            pieces=[(group,mesh) for group,_,mesh,_ in rows]
            draw_l1.projected(axes[0],pieces,1,2,.3);draw_l1.projected(axes[1],pieces,0,1,.3)
            axes[0].set_title("Side placement · both foil carriers project to this location")
            axes[1].set_title("Top placement · separate NL / NR outer faces")
            for index,gauge in enumerate(plan["gauges"]):
                x,y,z=gauge["center_native_xyz_mm"]
                axes[1].scatter([x],[y],color="#9b6d2c",s=35,zorder=20)
                axes[1].annotate(gauge["id"],xy=(x,y),xytext=(x+(-7 if index==0 else 5),y-8),
                                 arrowprops={"arrowstyle":"->"},fontsize=10)
            _,y,z=plan["gauges"][0]["center_native_xyz_mm"]
            axes[0].annotate("NL / NR\nfoil on outer webs",xy=(y,z),xytext=(y-24,z+14),
                             arrowprops={"arrowstyle":"->"},fontsize=10)
            r1_plan=json.loads((ROOT/"engineering/release/r1/r1_manifest.json").read_text())
            for pad in r1_plan["pads"]:
                front=np.asarray(pad["front_curve_native_yz_mm"]);center=front.mean(axis=0)
                axes[0].annotate(f'CH{pad["id"]}',xy=center,xytext=(center[0],center[1]-8),
                                 ha="center",arrowprops={"arrowstyle":"->"},fontsize=9)
            fig.suptitle("N1 sensing locations · two nail bridges and four retained R1 TPU cells",fontsize=14)
            fig.savefig(OUTPUT/"nail_placement.svg");pdf.savefig(fig);plt.close(fig)
            for part in plan["parts"]:
                mesh=trimesh.load_mesh(OUTPUT/part["stl"],process=True)
                fig,axes=plt.subplots(1,3,figsize=(13,5),layout="constrained")
                for ax,(a,b) in zip(axes,((1,2),(0,1),(0,2))):
                    draw_l1.projected(ax,[("tool",mesh)],a,b,.85)
                fig.suptitle(part["id"]+"\n"+part["purpose"],fontsize=11)
                pdf.savefig(fig);plt.close(fig)
            fig=plt.figure(figsize=(8.27,11.69));plt.axis("off")
            lines=[
                "N1.1 prototype review · millimeters · use STEP masters",
                "",
                "Nail: wrought 17-4PH, H900 candidate; certify the actual material.",
                "Leading contact-plane footprint retained; leading thickness 1.35 mm.",
                "Two webs: 1.5 mm thick × 14 mm tall; active length 14 mm.",
                "Each foil carrier center: nail-plane Y=15.5, Z=17 mm.",
                "Full shear bridge: OMEGA SGT-2DD/350-SY41, 350 ohm.",
                "",
                "Front clamps: two M3x8 flat heads left; two M3x6 right.",
                "Side mounting: M3x40 flat heads from right into tapped left carrier.",
                "Inspect actual screw engagement, source posts and clearances.",
                "Tap-drill CAD contains 2.5 mm bores; cut M3 threads as specified.",
                "",
                "Four TPU cells use R1 CH2–CH5 tooling and material instructions.",
                "Their 0.30 mm laminate envelopes are displayed; covers are not.",
                "Use the complete six-file N1 firmware and its raw recorder.",
                "",
                "The frame cut's small distal crescent is intentionally removed.",
                "The three attachment regions and central frame are checked.",
                "Clearance pockets are in the new frame; original files are retained.",
                "",
                "No physical build, force calibration, contact reliability or",
                "robot-task performance has been measured for this design.",
            ]
            fig.text(.05,.96,"\n".join(lines),va="top",fontsize=9.5,linespacing=1.5,family="monospace")
            pdf.savefig(fig);plt.close(fig)
        model={"id":"nail_assembly","title":"N1 · bare nail with two shear bridges and four TPU cells",
               "coordinates":"native_mm","assembly":True,
               "components":[packed(mesh,name,group,COLORS[group],offset or EXPLODE.get(group,(0,0,0)))
                             for group,name,mesh,offset in rows],
               "note":"Checked nail/frame CAD, foil-carrier location markers, reserved fasteners and retained R1 TPU interfaces. Coatings and wiring are omitted. Physical validation is pending."}
        models=[model]
        for part in plan["parts"]:
            models.append({"id":part["id"],"title":part["id"].replace("_"," "),"coordinates":"native_mm",
                           "components":[packed(trimesh.load_mesh(OUTPUT/part["stl"],process=True),part["purpose"],"tool",COLORS["tool"])],
                           "note":part["purpose"]+" "+part["material"]})
        (OUTPUT/"models.json").write_text(json.dumps(models,separators=(",",":"))+"\n")
        record["rendered"]={"assembly_components":len(rows),"models":len(models),"reused_r1_interfaces":reused,
                            "physical_photographs":0}
        print(json.dumps(record["rendered"],indent=2))


if __name__=="__main__":
    main()
