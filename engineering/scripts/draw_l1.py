#!/usr/bin/python3
"""Render actual L1 CAD, a contact test map, and review drawings from frozen dimensions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"]=str(ROOT/"build/engineering/tools/cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.collections import PolyCollection
from matplotlib.colors import to_rgb
from matplotlib.patches import Circle,Rectangle
import numpy as np
import trimesh

from analyze_baseline_meshes import PARTS
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/l1"
COLORS={"frame":"#657c89","tpu":"#a8bd80","fixed":"#31847c","floating":"#cb8542","cell":"#8b7eb0","hardware":"#555f66"}


def components(plan):
    pieces=[]
    for key,source in (("frame","hard_frame"),("tpu","soft_insert")):
        mesh=trimesh.load_mesh(PARTS[source],process=True)
        mesh.apply_translation(plan["finger_translation_native_mm"])
        pieces.append((key,mesh))
    for key,name in (
        ("fixed","l1_fixed_carrier_m3_clearance"),
        ("floating","l1_floating_finger_carrier"),("cell","tal220b_reference"),
    ):
        pieces.append((key,trimesh.load_mesh(OUTPUT/f"cad/{name}.stl",process=True)))
    for part in plan["hardware_envelopes"]:
        axis=np.asarray(part["axis"],dtype=float)
        transform=trimesh.geometry.align_vectors([0,0,1],axis)
        transform[:3,3]=np.asarray(part["origin_mm"])+axis*part["height_mm"]/2
        mesh=trimesh.creation.cylinder(radius=part["diameter_mm"]/2,height=part["height_mm"],sections=24,transform=transform)
        pieces.append(("hardware",mesh))
    return pieces


def projected(ax,pieces,a,b,alpha=.7):
    all_points=[]
    for key,mesh in pieces:
        all_points.append(mesh.vertices)
        ax.add_collection(PolyCollection(mesh.triangles[:,:,[a,b]],facecolor=COLORS[key],edgecolor="none",alpha=alpha))
    all_points=np.vstack(all_points)
    ax.set_xlim(all_points[:,a].min()-5,all_points[:,a].max()+5)
    ax.set_ylim(all_points[:,b].min()-5,all_points[:,b].max()+5)
    ax.set_aspect("equal");ax.grid(alpha=.17)
    ax.set_xlabel(f"Native {'XYZ'[a]} (mm)");ax.set_ylabel(f"Native {'XYZ'[b]} (mm)")


def save(fig,name):
    fig.savefig(OUTPUT/f"{name}.svg",bbox_inches="tight")
    fig.savefig(OUTPUT/f"{name}.png",dpi=150,bbox_inches="tight")
    plt.close(fig)


def depth_image(pieces,width=1600,height=630):
    """Orthographic CPU rasterization avoids whole-part painter-order artifacts."""
    triangles=np.concatenate([mesh.triangles for _,mesh in pieces])[:,:,[1,2,0]]
    base_colors=np.concatenate([np.tile(to_rgb(COLORS[key]),(len(mesh.faces),1)) for key,mesh in pieces])
    triangles-=triangles.reshape(-1,3).mean(axis=0)
    yaw=.3;pitch=-.55
    cy,sy=np.cos(yaw),np.sin(yaw);cp,sp=np.cos(pitch),np.sin(pitch)
    rotation=np.array([[cy,0,sy],[sy*sp,cp,-cy*sp],[-sy*cp,sp,cy*cp]])
    triangles=triangles@rotation.T
    normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-10)
    light=.55+.45*np.abs(normals@np.array([.25,.4,.85]))
    colors=np.clip(base_colors*light[:,None]*255,0,255).astype(np.uint8)
    low=triangles.reshape(-1,3).min(axis=0);high=triangles.reshape(-1,3).max(axis=0)
    scale=min((width-50)/(high[0]-low[0]),(height-50)/(high[1]-low[1]))
    center=(low+high)/2
    triangles[:,:,0]=(triangles[:,:,0]-center[0])*scale+width/2
    triangles[:,:,1]=height/2-(triangles[:,:,1]-center[1])*scale
    image=np.full((height,width,3),255,dtype=np.uint8)
    depth=np.full((height,width),-np.inf)
    for triangle,color in zip(triangles,colors):
        a,b,c=triangle
        denominator=(c[1]-b[1])*(a[0]-b[0])+(b[0]-c[0])*(a[1]-b[1])
        if abs(denominator)<1e-6:continue
        left=max(0,int(np.floor(triangle[:,0].min())));right=min(width-1,int(np.ceil(triangle[:,0].max())))
        top=max(0,int(np.floor(triangle[:,1].min())));bottom=min(height-1,int(np.ceil(triangle[:,1].max())))
        if right<left or bottom<top:continue
        yy,xx=np.mgrid[top:bottom+1,left:right+1];xx=xx+.5;yy=yy+.5
        u=((c[1]-b[1])*(xx-b[0])+(b[0]-c[0])*(yy-b[1]))/denominator
        v=((a[1]-c[1])*(xx-c[0])+(c[0]-a[0])*(yy-c[1]))/denominator
        w=1-u-v;z=u*a[2]+v*b[2]+w*c[2]
        area=depth[top:bottom+1,left:right+1]
        mask=(u>=-1e-7)&(v>=-1e-7)&(w>=-1e-7)&(z>area+1e-5)
        area[mask]=z[mask];image[top:bottom+1,left:right+1][mask]=color
    return image


def contact_sites(config,plan):
    hard=trimesh.load_mesh(PARTS["hard_frame"],process=True)
    soft=trimesh.load_mesh(PARTS["soft_insert"],process=True)
    contact=json.loads((ROOT/"engineering/release/contact_regions/contact_report.json").read_text())
    r1=json.loads((ROOT/"engineering/release/r1/r1_manifest.json").read_text())
    candidates=[]
    origin=np.asarray(contact["nail_plane_origin_native_mm"])
    u=np.asarray(contact["nail_plane_u_axis_native"]);v=np.asarray(contact["nail_plane_v_axis_native"])
    for number,(a,b) in enumerate(((-3.5,9.5),(3.5,9.5),(-7,0),(7,0))):
        p=origin+a*u+b*v
        candidates.append((f"nail_{number+1}","hard_frame",hard,p[0],p[1]))
    for pad in r1["pads"]:
        candidates.append((f"tpu_{pad['id']-1}","soft_insert",soft,-7.5,sum(pad["native_y_limits_mm"])/2))
    cell_center=np.asarray(plan["cell_mount_centers_native_xyz_mm"][1])
    shift=np.asarray(plan["finger_translation_native_mm"])
    sites=[]
    for name,material,mesh,x,y in candidates:
        hits,_,_=mesh.ray.intersects_location([[x,y,-30]],[[0,0,1]],multiple_hits=True)
        if not len(hits):raise ValueError(f"Contact site misses the real {material}: {name}")
        point=hits[np.argmin(hits[:,2])]+shift
        relative=point-cell_center
        sites.append({
            "id":name,"surface":material,"native_xyz_mm":np.round(point,6).tolist(),
            "u_mm":round(float(-relative[1]),6),"v_mm":round(float(relative[0]),6),
            "force_direction_native":[0,0,1],
            "note":"Mesh ray intersection; align force with +native Z. Record actual probe contact and alignment.",
        })
    result={"revision":config["revision"],"physical_contacts_tested":0,"sites":sites}
    (OUTPUT/"contact_sites.json").write_text(json.dumps(result,indent=2)+"\n")
    return sites


def main():
    config=json.loads((ROOT/"engineering/designs/l1.json").read_text())
    plan=json.loads((OUTPUT/"l1_manifest.json").read_text())
    with execution(ROOT/"build/records","Render actual root-force geometry, test locations and dimensioned review drawings; no physical performance data") as record:
        pieces=components(plan);sites=contact_sites(config,plan)
        fig=plt.figure(figsize=(13,6))
        ax=fig.add_axes((.025,.18,.95,.65))
        ax.imshow(depth_image(pieces))
        ax.set_axis_off()
        fig.suptitle("L1 · complete finger load path",x=.06,ha="left",fontsize=21,color="#203f46")
        labels=[("frame","Original PETG"),("tpu","Original TPU"),("fixed","Fixed carrier"),
                ("floating","Floating carrier"),("cell","Purchased cell"),("hardware","Reserved fastener space")]
        fig.legend([Rectangle((0,0),1,1,color=COLORS[key]) for key,_ in labels],
                   [label for _,label in labels],loc="lower center",ncol=3,frameon=False)
        fig.text(.06,.91,"Actual meshes and new CAD. Unbuilt prototype; screws shown as clearance envelopes.",fontsize=11,color="#526770")
        save(fig,"l1_assembly")

        fig,axes=plt.subplots(1,2,figsize=(14,6),gridspec_kw={"width_ratios":[2.3,1]},constrained_layout=True)
        projected(axes[0],pieces,1,2,.55)
        projected(axes[1],pieces,0,2,.55)
        axes[0].set_title("Side view · full assembly")
        axes[1].set_title("Root envelope")
        mount=json.loads((OUTPUT/"root_interface.json").read_text())["mount_plane"]["native_y_mm"]
        shifted_mount=mount+plan["finger_translation_native_mm"][1]
        axes[0].axvline(mount,color="#203f46",linestyle=":",linewidth=1)
        axes[0].axvline(shifted_mount,color="#cb8542",linestyle=":",linewidth=1)
        axes[0].annotate("",xy=(mount,50),xytext=(shifted_mount,50),arrowprops={"arrowstyle":"<->","color":"#203f46"})
        axes[0].text((mount+shifted_mount)/2,52,f"{plan['reach_extension_mm']:g} mm",ha="center")
        axes[0].set_ylim(-10,60)
        axes[0].annotate("Original finger → floating carrier → cell → fixed carrier",
                         xy=(-80,44),xytext=(-140,57),fontsize=9,color="#203f46")
        fig.suptitle(
            f"Added root width {plan['added_width_mm']:.2f} mm · "
            f"back height with reserved M5 head {plan['added_back_height_including_reserved_m5_head_mm']:.2f} mm\n"
            "Dimensions exclude cable bend radius and the installed gripper housing. Verify both jaw orientations.",
            fontsize=12,
        )
        save(fig,"l1_envelope")

        fig,axes=plt.subplots(1,2,figsize=(13,8),gridspec_kw={"width_ratios":[1,1.6]},constrained_layout=True)
        projected(axes[0],pieces[:2],0,1,.25)
        axes[0].set_title("Integrated finger · +Z force into page")
        for index,site in enumerate(sites):
            x,y,_=site["native_xyz_mm"]
            axes[0].scatter([x],[y],color="#9d4f2f",s=28,zorder=8)
            offset=7 if index%2 else -14
            axes[0].annotate(site["id"],(x,y),xytext=(offset,6 if index<4 else 0),textcoords="offset points",
                             ha="left" if offset>0 else "right",fontsize=8)
        axes[0].set_xlim(-33,16)
        ax=axes[1];ax.set_title("Cell/plate test · same force direction")
        ax.add_patch(Rectangle((-60,-55),140,70,facecolor="#f2ece1",edgecolor="#ad9468"))
        for port in plan["combined_load_ports"]:
            u,v=port["u_mm"],port["v_mm"]
            ax.add_patch(Circle((u,v),2.75 if u==v==0 else 1.7,facecolor="white",edgecolor="#536870"))
            ax.text(u+2,v+3,f"{u}, {v}",fontsize=8)
        for site in sites:ax.scatter([site["u_mm"]],[site["v_mm"]],color="#9d4f2f",s=22,zorder=5)
        ax.plot([plan["contact_lever_u_range_mm"][0],plan["contact_lever_u_range_mm"][1],
                 plan["contact_lever_u_range_mm"][1],plan["contact_lever_u_range_mm"][0],plan["contact_lever_u_range_mm"][0]],
                [plan["contact_lever_v_range_mm"][0],plan["contact_lever_v_range_mm"][0],
                 plan["contact_lever_v_range_mm"][1],plan["contact_lever_v_range_mm"][1],plan["contact_lever_v_range_mm"][0]],
                "--",color="#31847c",label="Projected hard-frame bounds")
        ax.set_xlim(-68,87);ax.set_ylim(-63,26);ax.set_aspect("equal");ax.grid(alpha=.15)
        ax.set_xlabel("U: cell length, relative to live-end M5 (mm)");ax.set_ylabel("V: transverse (mm)")
        ax.legend(loc="upper left",fontsize=8)
        fig.suptitle("Force location must be part of the experiment",fontsize=17)
        fig.text(.45,.025,"Red: planned finger contacts. Plate corner at (70, −45) mm produces\n"
                 "1.66 N·m at 20 N. This is a test condition, not a sensor moment rating.",fontsize=10)
        save(fig,"l1_test_map")

        with PdfPages(OUTPUT/"l1_review_drawings.pdf") as pdf:
            for part in plan["parts"]:
                mesh=trimesh.load_mesh(OUTPUT/part["stl"],process=True)
                fig,axes=plt.subplots(1,3,figsize=(11.7,8.3))
                color_key="cell" if part["kind"]=="reference_only" else "floating"
                for ax,(a,b) in zip(axes,((0,1),(0,2),(1,2))):
                    projected(ax,[(color_key,mesh)],a,b,.4)
                    ax.tick_params(labelsize=7);ax.xaxis.label.set_size(8);ax.yaxis.label.set_size(8)
                fig.suptitle(part["id"].replace("_"," "),fontsize=17,y=.95)
                fig.text(.06,.88,part["material"]+" · "+" × ".join(f"{value:.2f}" for value in mesh.extents)+" mm overall",fontsize=10)
                fig.text(.06,.83,part["purpose"],fontsize=9,wrap=True)
                fig.text(.06,.13,"CAD units: mm. STEP is the geometric master; these projected review views are not print-to-scale templates.",fontsize=9)
                fig.text(.06,.09,"Inspect the 13 mm cell seats, M5 fasteners and M3/key interface before machining. No strength qualification is implied.",fontsize=9)
                fig.text(.06,.05,"PETG copies of aluminum load-path parts are fit witnesses only. Original ENPIRE interface: Wenli Xiao / NVIDIA ENPIRE.",fontsize=8)
                fig.subplots_adjust(top=.72,bottom=.22,wspace=.42)
                pdf.savefig(fig);plt.close(fig)
        record["contact_sites"]=len(sites);record["drawing_pages"]=len(plan["parts"])
        print(json.dumps({"contact_sites":len(sites),"drawing_pages":len(plan["parts"]),"physical_measurements":0},indent=2))


if __name__=="__main__":
    main()
