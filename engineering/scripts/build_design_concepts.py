#!/usr/bin/python3
"""Make B2 board-envelope and C1 beam-coupon concepts, with explicit readiness limits."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"]=str(ROOT/"build/engineering/tools/cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"engineering/software"))
import cadquery as cq
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Polygon as Patch, Rectangle, Circle
import numpy as np
from shapely.geometry import Polygon,box
from shapely.ops import unary_union
import trimesh
from architecture_math import beam_response,force_with_station_gain_error
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/architecture"
PUBLISHED=ROOT/"engineering/concepts"


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def projection(component):
    v=np.asarray(component["vertices"]);f=np.asarray(component["faces"])
    polygons=[Polygon(t) for t in v[f][:,:,[1,2]] if Polygon(t).area>1e-8]
    result=unary_union(polygons).buffer(.001).buffer(-.001).simplify(.01,preserve_topology=True)
    if result.geom_type!="Polygon":raise ValueError("Expected a connected side projection")
    return result


def export(shape,name,kind,parts):
    shape=shape.clean()
    if not shape.isValid() or len(shape.Solids())!=1:raise ValueError("Invalid concept solid")
    folder=OUTPUT/"cad";folder.mkdir(exist_ok=True)
    step=folder/f"{name}.step";stl=folder/f"{name}.stl"
    cq.exporters.export(shape,str(step))
    cq.exporters.export(shape,str(stl),tolerance=.025,angularTolerance=.1)
    loaded=cq.importers.importStep(str(step)).val()
    mesh=trimesh.load_mesh(stl,process=True)
    if not loaded.isValid() or abs(loaded.Volume()-shape.Volume())>max(.001,shape.Volume()*.001) or not mesh.is_watertight:
        raise ValueError("Concept export verification failed")
    parts.append({"id":name,"kind":kind,"step":"cad/"+step.name,"stl":"cad/"+stl.name,
                  "step_sha256":digest(step),"stl_sha256":digest(stl),
                  "volume_mm3":shape.Volume(),"bounds_mm":mesh.bounds.tolist(),"physical_tested":False})


def draw_outline(ax,polygon,**kwargs):
    ax.add_patch(Patch(list(polygon.exterior.coords),**kwargs))
    for ring in polygon.interiors:
        ax.add_patch(Patch(list(ring.coords),facecolor="white",edgecolor="#667",linewidth=.5))


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    config=json.loads((ROOT/"engineering/designs/architecture_study.json").read_text())
    plan_path=ROOT/"engineering/release/b1/b1_manifest.json"
    plan=json.loads(plan_path.read_text())
    model=json.loads((ROOT/"engineering/release/b1/models.json").read_text())[0]
    with execution(ROOT/"build/records","Explore simpler magnetic packaging and a magnet-free force coupon, preserving all released finger designs") as record:
        parts=[]
        spine=projection(next(c for c in model["components"] if c["group"]=="spine"))
        frame=projection(next(c for c in model["components"] if c["group"]=="frame"))
        frame_outer=Polygon(frame.exterior.coords)
        tpu=Polygon(json.loads((ROOT/"engineering/release/b1/source_interface.json").read_text())["outer_yz"])
        bay=box(*config["b2"]["controller_bay_yz_bounds_mm"])
        region=unary_union([spine,bay,*[Polygon(s["footprint_yz"]) for s in plan["sensor_poses"]]]).buffer(0).simplify(.01,preserve_topology=True)
        if region.geom_type!="Polygon":raise ValueError("B2 board outline disconnected")
        outside=region.difference(frame_outer.union(tpu)).area
        # The existing spine is clipped to the original side envelope. Report
        # any numerical contour simplification rather than claim an exact match.
        if outside>.15:raise ValueError(f"B2 outline extends outside finger silhouette: {outside}")
        for sensor in plan["sensor_poses"]:
            if not region.buffer(.03).covers(Polygon(sensor["footprint_yz"])):
                raise ValueError(f"B2 omits sensor allocation {sensor['id']}")
        x=plan["sensor_pcb_top_x_mm"]
        for sensor in plan["sensor_poses"]:
            if abs(sensor["pcb_top_origin_native_mm"][0]-x)>1e-7 or not np.allclose(
                    np.asarray(sensor["rotation_sensor_to_native"])[:,2],[-1,0,0]):
                raise ValueError("Sensor poses do not share a common rigid PCB plane")
            if bay.intersection(Polygon(sensor["footprint_yz"])).area>1e-6:
                raise ValueError("Controller bay overlaps an existing head")
        work=cq.Workplane("YZ",origin=(x,0,0)).polyline(list(region.exterior.coords)[:-1]).close()
        for hole in region.interiors:work=work.polyline(list(hole.coords)[:-1]).close()
        export(work.extrude(config["b2"]["pcb_thickness_mm"]).val(),"b2_pcb_fit_witness",
               "Print-only dimensional witness. Not a functional PCB or a force-bearing part.",parts)
        board_layout={
            "status":config["b2"]["status"],"pcb_component_plane_native_x_mm":x,
            "outline_yz_mm":list(region.exterior.coords),
            "holes_yz_mm":[list(hole.coords) for hole in region.interiors],
            "sensor_poses":plan["sensor_poses"],"controller_bay_yz_bounds_mm":list(bay.bounds),
            "area_mm2":region.area,"projection_outside_original_side_envelope_mm2":outside,
            "source_b1_manifest_sha256":digest(plan_path),
            "unfinished":["No PCB copper routing, electrical DRC, final controller footprint placement or Gerbers.",
                          "No new board clamp/retainer design; old adhesive-only head mount is not claimed as a production solution.",
                          "No installed drive/connector clearance test. Do not order PCBs from the outline witness."]}
        (OUTPUT/"b2_layout.json").write_text(json.dumps(board_layout,indent=2)+"\n")

        c1=config["c1"];length=c1["active_length_mm"];clamp=c1["end_clamp_length_mm"]
        coupon=cq.Workplane("XY").box(c1["beam_width_mm"],length+2*clamp,c1["beam_thickness_mm"],
                                     centered=(True,False,True)).translate((0,-clamp,0)).val()
        for y in (-clamp/2,length+clamp/2):
            for sx in (-c1["end_hole_x_spacing_mm"]/2,c1["end_hole_x_spacing_mm"]/2):
                bore=cq.Solid.makeCylinder(c1["end_hole_diameter_mm"]/2,c1["beam_thickness_mm"]+2,
                    cq.Vector(sx,y,-c1["beam_thickness_mm"]/2-1),cq.Vector(0,0,1))
                coupon=coupon.cut(bore)
        export(coupon,"c1_strain_beam_coupon","Machine from specified metal for bench exploration. No gripper adapter or qualified load cell is supplied.",parts)
        conditions=[]
        for thickness in (4,6,8,10):
            candidate={**c1,"beam_thickness_mm":thickness}
            for arm in c1["contact_arm_from_free_boundary_mm"]:
                conditions.append({"thickness_mm":thickness,**beam_response(candidate,20,arm)})
        chosen=beam_response(c1,20,max(c1["contact_arm_from_free_boundary_mm"]))
        low=beam_response(c1,.2,max(c1["contact_arm_from_free_boundary_mm"]))
        mismatch=[{"relative_station_gain_error":error,"force_error_n":force_with_station_gain_error(chosen,error)-20}
                  for error in c1["residual_station_gain_error_cases"]]
        c1_result={
            "evidence_kind":"analytical_screen_only","configuration":c1,"screen_20n":chosen,"screen_0_2n":low,
            "active_length_to_thickness_ratio":length/c1["beam_thickness_mm"],
            "thickness_sweep":conditions,"residual_gain_error_cases":mismatch,
            "limits":["Constant cross section, rigid clamps/distal arm, linear elasticity and small deflection.",
                      "End clamp/tab deformation, mounting interface, shear, torsion, gravity and thermal drift omitted.",
                      "All applied loads must enter beyond both stations; no mechanical bypass is allowed.",
                      "ADC-only noise is a lower-bound calculation with manufacturer typical shorted-input noise.",
                      "The active section is short relative to its thickness. Clamp/end effects require 3D FEA and gauge-area measurements; beam theory is an initial screen only.",
                      "The coupon's 18 mm active length is not a final gripper reach or envelope prediction.",
                      "No safety, fatigue, force-accuracy or contact-threshold rating."]}
        (OUTPUT/"c1_screen.json").write_text(json.dumps(c1_result,indent=2)+"\n")
        with PdfPages(OUTPUT/"concept_review.pdf") as pdf:
            fig,ax=plt.subplots(figsize=(13,5.8))
            fig.subplots_adjust(left=.07,right=.98,bottom=.18,top=.88)
            draw_outline(ax,frame_outer,facecolor="#cbd3d4",edgecolor="#879797",alpha=.6)
            draw_outline(ax,tpu,facecolor="#c5d6a7",edgecolor="#839a69",alpha=.5)
            draw_outline(ax,region,facecolor="#3b978a",edgecolor="#1f625c",alpha=.55)
            for sensor in plan["sensor_poses"]:
                p=np.array(sensor["footprint_yz"])
                ax.add_patch(Patch(p,facecolor="#8879a4",alpha=.8))
                y,z=sensor["native_yz_mm"];ax.text(y,z,sensor["id"],ha="center",va="center",color="white",fontsize=10)
            ax.add_patch(Rectangle((bay.bounds[0],bay.bounds[1]),bay.bounds[2]-bay.bounds[0],bay.bounds[3]-bay.bounds[1],
                                  facecolor="#f1dcb0",edgecolor="#a27d43"))
            ax.annotate("Reserved controller bay\nmux / nail ADC / harness",(-13.5,21),xytext=(-7,39),
                        arrowprops={"arrowstyle":"->"},ha="right",fontsize=10)
            ax.set_xlim(-122,2);ax.set_ylim(-9,44);ax.set_aspect("equal")
            ax.set_xlabel("Native Y (mm) · tip left");ax.set_ylabel("Native Z (mm)")
            ax.set_title("B2 concept: one rigid board, same five magnetic head poses",fontsize=17)
            fig.text(.08,.035,"Outline/placement study only. No routing, PCB order files, retention detail or assembled hardware.",fontsize=10)
            fig.savefig(OUTPUT/"b2_board_concept.svg");pdf.savefig(fig);plt.close(fig)
            fig,axes=plt.subplots(1,2,figsize=(12,5),layout="constrained")
            ax=axes[0];w=c1["beam_width_mm"]
            ax.add_patch(Rectangle((0,-w/2),length,w,facecolor="#d4e2e1",edgecolor="#5b7979"))
            for start in (-clamp,length):
                ax.add_patch(Rectangle((start,-w/2),clamp,w,facecolor="#8b9f9f",edgecolor="#536c6c"))
                for s in (-8,8):ax.add_patch(Circle((start+clamp/2,s),2.25,facecolor="white",edgecolor="#40565b"))
            for index,station in enumerate(c1["gauge_station_mm_from_fixed_boundary"]):
                for side in (-4,4):
                    ax.add_patch(Rectangle((station-1.5,side-1.2),3,2.4,facecolor="#c9884b"))
                ax.annotate(f"Station {index+1}\nfull bridge",xy=(station,0),xytext=((0,18)[index],-23),
                            arrowprops={"arrowstyle":"->"},ha="center",fontsize=9)
            ax.annotate("Rigid finger\nload interface",xy=(length+clamp,0),xytext=(39,-11),
                        arrowprops={"arrowstyle":"->"},ha="center",fontsize=8)
            ax.text(35,9,"⊙ Fz\nnormal to page",ha="center",fontsize=8)
            ax.set_xlim(-14,46);ax.set_ylim(-30,22);ax.set_aspect("equal")
            ax.set_title("C1 metal bench coupon · top view\nTwo more gauges per station on underside")
            ax.set_xlabel("Beam axis u (mm)");ax.set_ylabel("Width (mm)")
            for thickness in (4,6,8,10):
                selected=[r for r in conditions if r["thickness_mm"]==thickness]
                axes[1].plot([r["contact_arm_mm"] for r in selected],[r["added_contact_displacement_mm"] for r in selected],
                             marker="o",label=f"{thickness} mm thick")
            axes[1].axhline(c1["screen_assumption_allowed_added_tip_deflection_mm"],ls=":",color="#9c5438",label="0.1 mm screen assumption")
            axes[1].set_xlabel("Rigid arm beyond active beam (mm)")
            axes[1].set_ylabel("Calculated added tip displacement at 20 N (mm)")
            axes[1].set_title("Analytical stiffness screen\nShort beam and clamps still need 3D FEA")
            axes[1].legend(fontsize=8);axes[1].grid(alpha=.2)
            fig.suptitle("C1 exploration · no gripper mount, force calibration or fatigue qualification")
            fig.savefig(OUTPUT/"c1_concept.svg");pdf.savefig(fig);plt.close(fig)
        manifest={"status":"Exploration artifacts; separate from the released R1/L1/B1 build parts",
                  "parts":parts,"checks":{"valid_solids":2,"step_roundtrips":2,"watertight_meshes":2},
                  "b2":{"sensor_centers_changed_mm":0,"pcb_routed":False,"board_retention_designed":False},
                  "c1":{"gripper_adapter_designed":False,"gauge_bridge_assembled":False},
                  "physical_specimens_tested":0}
        (OUTPUT/"concept_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        PUBLISHED.mkdir(exist_ok=True)
        shutil.copytree(OUTPUT/"cad",PUBLISHED/"cad",dirs_exist_ok=True)
        for name in ("b2_layout.json","b2_board_concept.svg","c1_screen.json","c1_concept.svg",
                     "concept_review.pdf","concept_manifest.json","magnetic_scaling.json","magnetic_scaling.svg","magnetic_gap.svg"):
            shutil.copyfile(OUTPUT/name,PUBLISHED/name)
        (PUBLISHED/"NOTICE.md").write_text(
            "# Concept scope and attribution\n\n"
            "B2 derives its board envelope and placements from the preserved B1 design and the "
            "Wenli Xiao / NVIDIA ENPIRE finger geometry. Original model and source provenance "
            "remain documented in engineering/docs/GEOMETRY.md.\n\n"
            "B2 is an unrouted board-layout study and dimensional fit witness. It has no PCB fabrication release.\n"
            "C1 is a new analytical constant-section beam and metal bench coupon. No installed gripper adapter, "
            "assembled strain bridge, firmware or qualified force sensor is provided for C1.\n"
            "The magnetic and strain plots are calculations, not physical measurements or production yield.\n"
        )
        source_names=["engineering/designs/architecture_study.json","engineering/software/architecture_math.py",
                      "engineering/scripts/build_design_concepts.py","engineering/scripts/screen_magnetic_scaling.py",
                      "engineering/scripts/model_b1_field.py","engineering/designs/b1.json",
                      "engineering/software/b1_protocol.py",
                      "engineering/release/b1/b1_manifest.json","engineering/release/b1/models.json",
                      "engineering/release/b1/source_interface.json"]
        snapshot={"source_hashes":{name:digest(ROOT/name) for name in source_names},
                  "files":{str(p.relative_to(PUBLISHED)):digest(p) for p in sorted(PUBLISHED.rglob("*"))
                           if p.is_file() and p.name!="concept_snapshot.json"},
                  "basis_b1_release":digest(plan_path),"status":"Concept-only checks, not production verification"}
        (PUBLISHED/"concept_snapshot.json").write_text(json.dumps(snapshot,indent=2)+"\n")
        record["concepts"]={"parts":len(parts),"b2_area_mm2":region.area,
                            "c1_added_tip_deflection_mm":chosen["added_contact_displacement_mm"],
                            "c1_signal_at_0_2n_uv":low["difference_v_ideal"]*1e6,"c1_gain_error_cases":mismatch}
        print(json.dumps(record["concepts"],indent=2))


if __name__=="__main__":main()
