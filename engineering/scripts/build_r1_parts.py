#!/usr/bin/python3
"""Build real ENPIRE-matched saddle molds, nail cut templates, and material coupons."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"] = str(ROOT / "build/engineering/tools/cache")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cadquery as cq
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
import numpy as np
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import LineString, Point, Polygon, box
import trimesh

from analyze_baseline_meshes import PARTS, outer_profile
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/r1"


def polygon_solid(polygon, depth, plane="XY"):
    if polygon.geom_type != "Polygon" or not polygon.is_valid:
        raise ValueError("Expected one valid polygon")
    shape = cq.Workplane(plane).polyline(list(polygon.exterior.coords)[:-1]).close()
    for ring in polygon.interiors:
        shape = shape.polyline(list(ring.coords)[:-1]).close()
    return shape.extrude(depth).val()


def export_part(shape, name, parts, purpose, material, print_note):
    if not shape.isValid() or len(shape.Solids()) != 1 or shape.Volume() <= 0:
        raise ValueError(f"Invalid CAD solid: {name}")
    step = OUTPUT / "cad" / f"{name}.step"
    stl = OUTPUT / "cad" / f"{name}.stl"
    step.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(shape, str(step))
    cq.exporters.export(shape, str(stl), tolerance=.035, angularTolerance=.1)
    mesh = trimesh.load_mesh(stl, process=True)
    if not mesh.is_watertight or mesh.volume <= 0:
        raise ValueError(f"Exported mesh not a closed positive-volume solid: {name}")
    reimport = cq.importers.importStep(str(step)).val()
    if not reimport.isValid() or abs(reimport.Volume()-shape.Volume()) > max(1e-3,shape.Volume()*1e-5):
        raise ValueError(f"STEP round-trip volume changed: {name}")
    parts.append({
        "id": name, "purpose": purpose, "material": material, "print_note": print_note,
        "volume_mm3": shape.Volume(), "stl_extents_mm": mesh.extents.tolist(),
        "step": f"cad/{name}.step", "stl": f"cad/{name}.stl",
        "sha256_step": hashlib.sha256(step.read_bytes()).hexdigest(),
        "sha256_stl": hashlib.sha256(stl.read_bytes()).hexdigest(),
        "cad_solid_valid": True, "stl_watertight": True, "physical_fit_tested": False,
    })


def svg_polygon(polygon, shift=(0,0), stroke="#121212", fill="none", width=.12):
    coordinates = " ".join(f"{x+shift[0]:.4f},{y+shift[1]:.4f}" for x,y in polygon.exterior.coords)
    return f'<polygon points="{coordinates}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>'


def write_cut_sheet(nail_polygons, pads):
    """SVG uses millimetres physically; labelled outlines are NOT sensor readings."""
    content = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm" viewBox="0 0 210 297">',
        '<rect width="210" height="297" fill="white"/>',
        '<g font-family="sans-serif" fill="#111">',
        '<text x="12" y="12" font-size="5">R1.0 • ENPIRE electrode and film cut sheet</text>',
        '<text x="12" y="20" font-size="3">Print at 100%. Measure the 20 mm scale before cutting. Units: mm.</text>',
        '<text x="12" y="26" font-size="3">Copper active area: orange. Velostat: dashed boundary. Outer film: black.</text>',
        '<text x="12" y="32" font-size="3">Nail coordinates shown from contact side; mirror backing before assembly.</text>',
    ]
    for index, (outer,active,velostat) in enumerate(nail_polygons):
        shift = (35+50*index,48)
        content += [
            svg_polygon(outer, shift),
            svg_polygon(active, shift, "#a84e0d", "#ffce9c"),
            svg_polygon(velostat, shift, "#4461a3").replace('stroke-width="0.12"','stroke-width="0.12" stroke-dasharray=".6 .4"'),
            f'<text x="{15+50*index}" y="69" font-size="3">CH{index} nail • solder off contact area</text>',
        ]
    content += ['<text x="12" y="84" font-size="3">Pad lengths follow each smoothed saddle by measured arc length.</text>']
    for index, pad in enumerate(pads):
        x=18+(index%2)*85; y=95+(index//2)*45
        w=pad["width_mm"]; length=pad["laminate_cut_length_mm"]
        content += [
            f'<rect x="{x}" y="{y}" width="{length:.3f}" height="{w:.3f}" fill="none" stroke="#111" stroke-width=".12"/>',
            f'<rect x="{x+.6}" y="{y+.6}" width="{length-1.2:.3f}" height="{w-1.2:.3f}" fill="#ffce9c" stroke="#a84e0d" stroke-width=".12"/>',
            f'<text x="{x}" y="{y+w+6}" font-size="3">CH{index+2} • {length:.2f} × {w:.2f}</text>',
            f'<text x="{x}" y="{y+w+11}" font-size="2.6">Velostat inset .30; copper inset .60</text>',
        ]
    content += [
        '<path d="M15 196v-3m0 1.5h20m0-1.5v3" stroke="#111" fill="none" stroke-width=".2"/>',
        '<text x="20" y="203" font-size="3">20.00 mm</text>',
        '<text x="12" y="216" font-size="3">Make TWO copper electrodes and ONE separate Velostat island per cell.</text>',
        '<text x="12" y="223" font-size="3">Each electrode needs its own insulated lead. No continuous conductive sheet.</text>',
        '<text x="12" y="230" font-size="3">Insulate the exposed lead joint; secure it on the proximal side, outside contact.</text>',
        '<text x="12" y="237" font-size="3">Test for unloaded shorts before sealing. Cover thickness target: 0.40 mm.</text>',
        '<text x="12" y="249" font-size="3">Artwork excludes solder tabs: use a wire-to-foil joint outside the active footprint.</text>',
        '<text x="12" y="256" font-size="3">Hand-assembled prototype tooling. This is not a routed production FPC.</text>',
        '<text x="12" y="269" font-size="3">Derived contact fit: Wenli Xiao / ENPIRE; pinned community baseline; see provenance.</text>',
        '</g></svg>',
    ]
    (OUTPUT/"r1_cut_sheet.svg").write_text("\n".join(content)+"\n")
    # Vector A4 PDF with a full-page millimetre coordinate system. No tight
    # bounding-box crop: that would silently change the printed scale.
    fig=plt.figure(figsize=(210/25.4,297/25.4))
    ax=fig.add_axes([0,0,1,1]);ax.set_xlim(0,210);ax.set_ylim(297,0);ax.axis("off")
    ax.text(12,13,"R1.0 — ENPIRE electrode and film cut sheet",fontsize=13,weight="bold")
    ax.text(12,21,"A4 · Print at actual size / 100%. Verify the 20.00 mm scale.",fontsize=9)
    ax.text(12,28,"Black: carrier. Orange: copper. Blue: separate conductive-film island.",fontsize=8)
    for index,(outer,active,film) in enumerate(nail_polygons):
        shift=np.array([35+50*index,48])
        for polygon,color,fill in ((outer,"#111111",False),(active,"#ad6129",True),(film,"#4461a3",False)):
            points=np.asarray(polygon.exterior.coords)+shift
            ax.plot(points[:,0],points[:,1],color=color,linewidth=.5)
            if fill:ax.fill(points[:,0],points[:,1],color=color,alpha=.18)
        ax.text(15+50*index,69,f"CH{index} nail — contact-side view",fontsize=8)
    ax.text(12,84,"Pad cut lengths follow the nominal laminate neutral plane.",fontsize=9)
    for index,pad in enumerate(pads):
        x=18+(index%2)*85;y=95+(index//2)*45
        width=pad["width_mm"];length=pad["laminate_cut_length_mm"]
        for inset,color in ((0,"#111111"),(.3,"#4461a3"),(.6,"#ad6129")):
            points=np.array([[x+inset,y+inset],[x+length-inset,y+inset],
                [x+length-inset,y+width-inset],[x+inset,y+width-inset],[x+inset,y+inset]])
            ax.plot(points[:,0],points[:,1],color=color,linewidth=.5)
        ax.text(x,y+width+6,f"CH{index+2} · {length:.2f} × {width:.2f} mm",fontsize=8)
    ax.plot([15,35],[196,196],color="black",linewidth=.6)
    ax.plot([15,15],[194.5,197.5],color="black",linewidth=.6)
    ax.plot([35,35],[194.5,197.5],color="black",linewidth=.6)
    ax.text(18,204,"20.00 mm",fontsize=9)
    for y,text in (
        (218,"Two copper electrodes and one separate conductive-film island per cell."),
        (226,"Insulate the lead joints; keep solder outside the loaded contact patch."),
        (234,"Mirror the backing as needed so bare copper faces the conductive film."),
        (246,"Joint extensions and edge seals are assembled separately; see the build guide."),
        (258,"Hand-built prototype patterns; not a routed production FPC."),
        (275,"Fit source: Wenli Xiao / ENPIRE; pinned community baseline. See provenance."),
    ):
        ax.text(12,y,text,fontsize=8)
    fig.savefig(OUTPUT/"r1_cut_sheet.pdf",metadata={"Title":"R1.0 ENPIRE cut sheet — actual size","Creator":"ENPIRE tactile engineering study"})
    plt.close(fig)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with execution(ROOT/"build/records", "Generate fabrication solids and 1:1 patterns fitted to measured ENPIRE surfaces; verify CAD exports") as record:
        config=json.loads((ROOT/"engineering/designs/r1.json").read_text())
        for part,key in (("hard_frame","hard"),("soft_insert","soft")):
            if hashlib.sha256(PARTS[part].read_bytes()).hexdigest()!=config["source_mesh_sha256"][key]:
                raise ValueError(f"Wrong baseline mesh for {part}")
        contact=json.loads((ROOT/"build/engineering/contact_regions/contact_report.json").read_text())
        nail=Polygon(contact["nail_footprint"]["outer"])
        parts, nail_polygons = [], []
        for index, half in enumerate((box(-30,-4,-.6,30),box(.6,-4,30,30))):
            outer=nail.buffer(-config["nail"]["seal_inset_mm"]).intersection(half)
            active=nail.buffer(-config["nail"]["active_inset_mm"]).intersection(half.buffer(-.3))
            film=active.buffer(.2).intersection(outer.buffer(-.15))
            if outer.geom_type!="Polygon" or active.is_empty or not outer.contains(active):
                raise ValueError("Nail active region does not fit")
            nail_polygons.append((outer,active,film))
        # One open mold produces the forked cover. Tool bottom lies on the bed.
        nail_cover=nail.buffer(-config["nail"]["seal_inset_mm"])
        xmin,ymin,xmax,ymax=nail_cover.bounds
        cover_depth=config["nail"]["cover_nominal_mm"]
        block=cq.Workplane("XY").box(xmax-xmin+8,ymax-ymin+8,3+cover_depth,centered=(True,True,False)).translate(((xmin+xmax)/2,(ymin+ymax)/2,0)).val()
        cavity=polygon_solid(nail_cover,cover_depth+.05).translate((0,0,3))
        export_part(block.cut(cavity),"nail_cover_mold",parts,
            "Open mold for a 0.40 mm fork-shaped silicone nail cover","PETG tool; cast DS10 or DS20",
            "Flat bottom on bed; 0.12 mm layers; measure cavity depth. Strike excess flush.")
        soft=trimesh.load_mesh(PARTS["soft_insert"],process=True)
        profile,section_curves=outer_profile(soft,0,-7.5)
        baseline=Polygon(profile)
        full=np.loadtxt(ROOT/"build/engineering/contact_regions/tpu_contact_unroll.csv",delimiter=",",skiprows=1)
        sy,sz=full[:,1],full[:,2]
        pad_config=config["pad"]
        smoothed=gaussian_filter1d(sz,pad_config["smooth_sigma_mm"]/pad_config["surface_sampling_mm"],mode="nearest")
        pads=[]
        fig,axes=plt.subplots(2,1,figsize=(12,8),constrained_layout=True)
        axes[0].fill(profile[:,0],profile[:,1],color="#e1e9dc")
        for curve in section_curves:
            if len(curve)>3 and Polygon(curve).area < baseline.area*.8:
                axes[0].fill(curve[:,0],curve[:,1],color="white")
        for index,(start,end) in enumerate(pad_config["zones_native_y_mm"]):
            mask=(sy>=start)&(sy<=end)
            y,back,front=sy[mask],sz[mask].copy(),smoothed[mask].copy()
            front-=max(front-back)+pad_config["saddle_min_z_thickness_mm"]+pad_config["assembly_clearance_z_mm"]
            back-=pad_config["assembly_clearance_z_mm"]
            polygon=Polygon(np.vstack((np.column_stack((y,front)),np.column_stack((y,back))[::-1])))
            # The sampled line can chord across sharp tooth vertices. Trim against
            # the exact section plus a clearance before simplifying the tooling.
            polygon=polygon.difference(baseline.buffer(pad_config["assembly_clearance_z_mm"]+.005,quad_segs=4)).simplify(.003,preserve_topology=True)
            if polygon.intersection(baseline).area>1e-6 or not polygon.is_valid:
                raise ValueError("Saddle intersects original TPU outline")
            width=pad_config["width_mm"]
            solid=polygon_solid(polygon,width)
            # STEP represents a tooling witness in print coordinates Y_native,Z_native,X_width.
            export_part(solid,f"pad_{index+2}_saddle_witness",parts,
                f"Master / witness for CH{index+2}; nominal cast width {width} mm","Cast DS10; rigid witness for inspection only",
                "Prefer supplied mold to printing a thin flexible saddle.")
            xmin,ymin,xmax,ymax=polygon.bounds
            mold=cq.Workplane("XY").box(xmax-xmin+8,ymax-ymin+8,width+3,centered=(True,True,False)).translate(((xmin+xmax)/2,(ymin+ymax)/2,0)).val()
            cavity=solid.translate((0,0,3))
            mold=mold.cut(cavity)
            export_part(mold,f"pad_{index+2}_saddle_mold",parts,
                f"Open mold for CH{index+2}, matching actual TPU serrations","PETG mold; cast Dragon Skin 10 Slow",
                "Flat broad base on bed, no support. Fill thin cavity; degas and inspect for voids before use.")
            s=np.concatenate(([0],np.cumsum(np.sqrt(np.diff(y)**2+np.diff(front)**2))))
            slope=np.gradient(front,y); curvature=np.abs(np.gradient(slope,y))/(1+slope**2)**1.5
            outward=np.column_stack((slope,-np.ones(len(slope))))
            outward/=np.linalg.norm(outward,axis=1)[:,None]
            neutral=np.column_stack((y,front))+outward*(pad_config["laminate_nominal_mm"]/2)
            neutral_arc=np.concatenate(([0],np.cumsum(np.linalg.norm(np.diff(neutral,axis=0),axis=1))))
            pad={
                "id":index+2,"width_mm":width,"native_y_limits_mm":[float(y[0]),float(y[-1])],
                "surface_arc_length_mm":float(s[-1]),
                "laminate_cut_length_mm":float(neutral_arc[-1]),
                "unroll_basis":"Neutral plane at half the nominal laminate thickness; measure and allow for the actual adhesive layer.",
                "saddle_z_thickness_min_mm":float(np.min(back-front)),
                "saddle_z_thickness_max_mm":float(np.max(back-front)),
                "minimum_sampled_radius_mm":float(1/max(curvature)),
                "baseline_cross_section_overlap_mm2":float(polygon.intersection(baseline).area),
                "front_curve_native_yz_mm":np.column_stack((y,front)).tolist(),
                "back_curve_native_yz_mm":np.column_stack((y,back)).tolist(),
                "assembly_native_x_limits_mm":[-7.5-width/2,-7.5+width/2],
            }
            pads.append(pad)
            axes[0].fill(*np.asarray(polygon.exterior.coords).T,alpha=.9,label=f"CH{index+2}")
            axes[1].plot(s,back-front,label=f"CH{index+2}")
            with (OUTPUT/f"pad_{index+2}_unroll.csv").open("w",newline="") as stream:
                writer=csv.writer(stream)
                writer.writerow(["saddle_arc_mm","laminate_neutral_arc_mm","native_y_mm","saddle_front_native_z_mm","neutral_y_mm","neutral_z_mm"])
                writer.writerows(zip(s,neutral_arc,y,front,neutral[:,0],neutral[:,1]))
        axes[0].set_aspect("equal");axes[0].set_title("Actual TPU outline with four conforming saddle sections")
        axes[0].set_xlabel("Native Y (mm)");axes[0].set_ylabel("Native Z (mm)");axes[0].legend()
        axes[1].set_title("Added saddle thickness before 0.30 mm laminate and 0.40 mm cover")
        axes[1].set_xlabel("Distance along saddle (mm)");axes[1].set_ylabel("Z thickness (mm)");axes[1].legend()
        fig.savefig(OUTPUT/"r1_pad_sections.svg");fig.savefig(OUTPUT/"r1_pad_sections.png",dpi=180)
        plt.close(fig)
        # Three identical-area, different-thickness coupon tools. Casts compare material and cover thickness.
        for thickness in (.4,.8,1.2):
            block=cq.Workplane("XY").box(39,54,3+thickness,centered=(False,False,False))
            for index in range(3):
                cavity=cq.Workplane("XY").box(30,14,thickness+.05,centered=(False,False,False)).translate((4.5,3+index*16,3))
                block=block.cut(cavity)
            export_part(block.val(),f"coupon_mold_{str(thickness).replace('.','p')}",parts,
                f"Three 30×14×{thickness} mm cover-material coupons","PETG tool; DS10 / DS20 / Ecoflex / PU comparison",
                "Flat bottom down; verify depth with caliper or shim stock before casting.")
        # Explicitly a dimensional fit gauge, not a rated load-bearing adapter.
        gauge=cq.Workplane("XY").box(33,12,3,centered=(True,True,False)).faces(">Z").workplane().pushPoints([(-10.5,0),(10.5,0)]).hole(3.4)
        export_part(gauge.val(),"mount_pitch_fit_gauge",parts,
            "Check measured 21 mm bore pitch using M3 screws; does not replace a structural mount","PETG",
            "Flat on bed. Check 21 mm center spacing on the actual finger before making a load adapter.")
        write_cut_sheet(nail_polygons,pads)
        plan={
            "revision":config["revision"],"hardware_status":"unbuilt / untested",
            "source_mesh_sha256":config["source_mesh_sha256"], "nail_added_nominal_mm":.4,
            "nail_variants":config["nail"]["variants"],
            "nail_active_cells":[
                {"id":i,"active_area_mm2":a.area,"outer":list(o.exterior.coords),"active":list(a.exterior.coords),"velostat":list(f.exterior.coords)}
                for i,(o,a,f) in enumerate(nail_polygons)
            ],
            "pads":pads,"parts":parts,
            "checks":{"cad_solids":len(parts),"step_roundtrips":len(parts),"watertight_stl_exports":len(parts)},
            "limitations":[
                "Digital fit uses a pinned community mesh; original downloaded STEP and physical fit are still required.",
                "Saddles and laminates alter contact geometry, compliance, and friction; compare with the unmodified finger.",
                "Six cells leave gaps and cover-edge dead zones. Force on those regions may be underreported.",
                "The two nail cells do not measure force on the unsensorized back or lateral frame.",
                "No grip-force accuracy, response rate, endurance, or closed-loop stability has been measured.",
            ],
        }
        (OUTPUT/"r1_manifest.json").write_text(json.dumps(plan,indent=2)+"\n")
        record["checks"]=plan["checks"]
        print(json.dumps({"checks":plan["checks"],"parts":[p["id"] for p in parts],
            "pads":[{k:v for k,v in p.items() if "curve" not in k} for p in pads]},indent=2))


if __name__=="__main__":
    main()
