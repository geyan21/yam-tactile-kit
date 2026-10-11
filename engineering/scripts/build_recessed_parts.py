#!/usr/bin/python3
"""Build a separate B3 frame recess and board supports from retained source geometry."""

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
import numpy as np
from shapely.geometry import Polygon,Point,box
from shapely import affinity
from shapely.ops import unary_union
import trimesh

from source_brep import load as load_source
from analyze_baseline_meshes import PARTS
from prototype_cad import block,yz_prism,x_cylinder,export_part,digest
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/prototypes/recessed"
B2=ROOT/"engineering/prototypes/b2"
B1=ROOT/"engineering/release/b1"


def bore_y(x,z,y0,y1,radius):
    return cq.Solid.makeCylinder(radius,y1-y0,cq.Vector(x,y0,z),cq.Vector(0,1,0))


def distance(a,b):
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    operation=BRepExtrema_DistShapeShape()
    operation.SetMultiThread(False)
    operation.LoadS1(a.wrapped);operation.LoadS2(b.wrapped);operation.Perform()
    if not operation.IsDone():
        raise ValueError("B3 clearance calculation did not complete")
    return operation.Value()


def planar_component(component):
    width,height=component.get("body_mm",[1,.5])
    region=affinity.rotate(box(-width/2,-height/2,width/2,height/2),-component["rotation_deg"],origin=(0,0))
    region=affinity.translate(region,*component["center_mm"])
    return affinity.affine_transform(region,[-1,0,0,-1,0,40])


def main():
    cfg=json.loads((ROOT/"engineering/designs/recessed.json").read_text())
    mechanical=cfg["mechanical"]
    source,conversion=load_source("hard_frame")
    if digest(PARTS["hard_frame"])!=cfg["basis"]["source_frame_sha256"]:
        raise ValueError("Unexpected original frame")
    if digest(PARTS["soft_insert"])!=cfg["basis"]["source_tpu_sha256"]:
        raise ValueError("Unexpected original TPU")
    b1=json.loads((B1/"b1_manifest.json").read_text())
    b2=json.loads((B2/"b2_manifest.json").read_text())
    pcb=json.loads((B2/"pcb/b2_main.json").read_text())
    design=json.loads((B2/"pcb/b2_design_checks.json").read_text())
    interface=json.loads((ROOT/"engineering/release/l1/root_interface.json").read_text())
    anchors=json.loads((B1/"source_interface.json").read_text())["anchors"]
    with execution(ROOT/"build/records","Develop a separate B3 recessed frame, shortened registration spacers and unchanged B2 PCB; verify protected source features and actual solid clearances") as record:
        OUTPUT.mkdir(parents=True,exist_ok=True)
        plane=mechanical["pcb_component_plane_native_x_mm"]
        old_plane=b2["pcb_component_plane_x_mm"]
        shift=plane-old_plane
        outline=Polygon(design["pcb_outline_yz_mm"],design["pcb_cutouts_yz_mm"])
        original_backer=cq.importers.importStep(str(B2/"cad/b2_removable_backer.step")).val()
        backer=original_backer.translate((shift,0,0))
        board=cq.importers.importStep(str(B2/"cad/b2_pcb_fit_reference.step")).val().translate((shift,0,0))
        outside=source.BoundingBox().xmax+2
        cutters=[];pocket_specs=[]
        board_region=outline.buffer(mechanical["pocket_planar_clearance_mm"])
        pocket_regions=[board_region]
        common_floor=plane-mechanical["frame_board_clearance_mm"]
        components=[]
        for item in pcb["components"]:
            if item["reference"].startswith(("J","TP")):
                continue
            region=planar_component(item)
            package=yz_prism(region,plane-item["height_mm"],item["height_mm"])
            lower=plane-item["height_mm"]-mechanical["frame_component_clearance_mm"]
            pocket=region.buffer(mechanical["pocket_planar_clearance_mm"])
            pocket_regions.append(pocket)
            common_floor=min(common_floor,lower)
            components.append({"reference":item["reference"],"body_yz_mm":list(region.exterior.coords),
                               "height_mm":item["height_mm"],"shape":package})
            pocket_specs.append({"kind":"component","reference":item["reference"],
                                "floor_native_x_mm":lower,"bounds_yz_mm":list(pocket.bounds)})
        solder=[]
        for pad in pcb["pads"]:
            if pad["reference"] not in ("J1","J2"):
                continue
            y,z=-pad["center"][0],40-pad["center"][1]
            region=Point(y,z).buffer(.8)
            height=mechanical["front_solder_height_allowance_mm"]
            envelope=yz_prism(region,plane-height,height)
            pocket=region.buffer(mechanical["pocket_planar_clearance_mm"])
            floor=plane-height-mechanical["frame_component_clearance_mm"]
            pocket_regions.append(pocket)
            common_floor=min(common_floor,floor)
            solder.append({"reference":pad["reference"],"pad":pad["pad"],"center_yz_mm":[y,z],
                           "height_allowance_mm":height,"shape":envelope})
        common_pocket=unary_union(pocket_regions)
        if common_pocket.geom_type!="Polygon" or not common_pocket.is_valid:
            raise ValueError("PCB and component allowances do not form one valid recess")
        cutters.append(yz_prism(common_pocket,common_floor,outside-common_floor))
        for mount,target_x in zip(b1["carrier_mounts"],mechanical["mount_seat_native_x_mm"]):
            y,z=mount["center_yz_mm"]
            cutters.append(x_cylinder(target_x,outside-target_x,y,z,mechanical["mount_recess_radius_mm"]))
            pocket_specs.append({"kind":"mount_seat","center_yz_mm":[y,z],
                                 "floor_native_x_mm":target_x,"radius_mm":mechanical["mount_recess_radius_mm"]})
        frame=source.cut(*cutters).clean()
        if not frame.isValid() or len(frame.Solids())!=1:
            raise ValueError("B3 recesses disconnected or invalidated the hard frame")
        review_folder=OUTPUT/"geometry_review"
        review_folder.mkdir(exist_ok=True)
        cq.exporters.export(frame,str(review_folder/"recessed_frame_preview.step"))
        if abs(frame.intersect(source).Volume()-frame.Volume())>1e-5:
            raise ValueError("The recessed frame unexpectedly adds material outside the source")
        protected=cfg["protected_source_regions"]
        regions={
            "central_frame":block(-60,protected["central_material_max_native_x_mm"],-150,20,-40,70),
            "original_nail":block(-60,40,-150,protected["original_nail_max_native_y_mm"],-40,70),
            "jaw_mating_face_and_key":block(-60,40,interface["mount_plane"]["native_y_mm"]-protected["jaw_face_preserved_depth_mm"],20,-40,70),
        }
        for index,(x,z) in enumerate(interface["bolt_centers_native_xz_mm"]):
            regions[f"jaw_bolt_region_{index}"]=bore_y(x,z,-25,20,protected["jaw_bolt_region_radius_mm"])
        x0,x1=protected["tpu_anchor_x_range_mm"]
        for index,anchor in enumerate(anchors):
            y,z=anchor["center_yz_mm"]
            regions[f"tpu_anchor_{index}"]=x_cylinder(x0,x1-x0,y,z,protected["tpu_anchor_region_radius_mm"])
        preservation={}
        for name,region in regions.items():
            # Both protected intersections contain material. Comparing their
            # volumes avoids asking the CAD kernel to construct a null solid
            # for the exact difference of two identical regions.
            preservation[name]=source.intersect(region).Volume()-frame.intersect(region).Volume()
        parts=[];shapes={"recessed_hard_frame":frame,"recessed_removable_backer":backer,
                        "recessed_pcb_fit_reference":board}
        supports=[]
        for index,(mount,target_x) in enumerate(zip(b1["carrier_mounts"],mechanical["mount_seat_native_x_mm"])):
            y,z=mount["center_yz_mm"]
            length=plane-target_x
            foot=mechanical["spacer_foot_height_mm"]
            taper=mechanical["spacer_taper_height_mm"]
            flange=length-foot-taper
            if min(foot,taper)<=0 or flange<.5:
                raise ValueError("B3 spacer foot, taper or clamping flange is too short")
            foot_radius=mechanical["spacer_foot_diameter_mm"]/2
            flange_radius=mechanical["spacer_outer_diameter_mm"]/2
            spacer=x_cylinder(target_x,foot,y,z,foot_radius)
            spacer=spacer.fuse(cq.Solid.makeCone(foot_radius,flange_radius,taper,
                cq.Vector(target_x+foot,y,z),cq.Vector(1,0,0)))
            spacer=spacer.fuse(x_cylinder(target_x+foot+taper,flange,y,z,flange_radius))
            spacer=spacer.fuse(x_cylinder(plane,mechanical["shoulder_height_mm"],y,z,mechanical["shoulder_outer_diameter_mm"]/2))
            spacer=spacer.cut(x_cylinder(target_x-.1,length+mechanical["shoulder_height_mm"]+.2,
                                        y,z,mechanical["fastener_clearance_mm"]/2))
            name=f"recessed_locating_spacer_{index+1}"
            shapes[name]=spacer
            # The actual foot annulus must have source material behind its new
            # seating plane. This is checked separately from no-overlap tests.
            ring=x_cylinder(target_x-.15,.15,y,z,foot_radius)
            ring=ring.cut(x_cylinder(target_x-.2,.3,y,z,mechanical["fastener_clearance_mm"]/2))
            supports.append({"part":name,"center_yz_mm":[y,z],"seat_native_x_mm":target_x,
                            "body_length_mm":length,
                            "foot_diameter_mm":2*foot_radius,"foot_height_mm":foot,
                            "taper_height_mm":taper,"flange_height_mm":flange,
                            "missing_seat_support_mm3":ring.cut(frame).Volume()})
        for name,shape in shapes.items():
            purpose={
                "recessed_hard_frame":"Separate source-frame derivative with PCB/component pockets and shortened outer support seats.",
                "recessed_removable_backer":"Retained B2 backer geometry at the recessed plane; wire exits and clamping annuli retained.",
                "recessed_pcb_fit_reference":"Retained B2 PCB shape and bores at the new plane; use checked B2 Gerbers for electronics.",
            }.get(name,"Shortened shouldered spacer locates the retained PCB at the recessed plane.")
            export_part(shape,name,OUTPUT,parts,purpose,
                        "Retained 0.8 mm FR4 PCB reference" if "pcb_fit" in name else mechanical["material"],
                        "reference_only" if "pcb_fit" in name else "fabricate")
        overlaps={}
        names=list(shapes)
        for index,name in enumerate(names):
            for other in names[index+1:]:
                overlaps[name+"_vs_"+other]=shapes[name].intersect(shapes[other]).Volume()
        for part in components+solder:
            key=part["reference"]+("_"+part["pad"] if "pad" in part else "")
            part["frame_gap_mm"]=distance(part["shape"],frame)
            overlaps[key+"_vs_frame"]=part["shape"].intersect(frame).Volume()
        b1_insert=cq.importers.importStep(str(B1/"cad/b1_magnetic_tpu_insert.step")).val()
        for name,shape in shapes.items():
            overlaps[name+"_vs_b1_insert"]=shape.intersect(b1_insert).Volume()
        poses=[]
        for pose in b1["sensor_poses"]:
            copy=dict(pose)
            for key in ("die_center_native_mm","pcb_center_native_mm"):
                if key in copy:
                    copy[key]=[copy[key][0]+shift,*copy[key][1:]]
            poses.append(copy)
        for item in components+solder:
            item.pop("shape")
        front_min=min(item["frame_gap_mm"] for item in components+solder)
        result={"schema":"yam-recessed-prototype/1","revision":cfg["revision"],
                "status":"digital development; physical qualification pending",
                "physical_specimens_tested":0,"parts":parts,"source_frame_conversion":conversion,
                "b2_snapshot_sha256":digest(B2/"prototype_snapshot.json"),
                "source_hashes":{str(path.relative_to(ROOT)):digest(path) for path in
                    (ROOT/"engineering/designs/recessed.json",Path(__file__),ROOT/"engineering/scripts/source_brep.py",
                     ROOT/"engineering/scripts/prototype_cad.py",B2/"b2_manifest.json",B2/"pcb/b2_main.json",
                     B2/"pcb/b2_design_checks.json",B1/"b1_manifest.json")},
                "pcb_component_plane_x_mm":plane,"board_shift_native_x_mm":shift,
                "backer_outer_x_mm":plane+mechanical["pcb_thickness_mm"]+mechanical["backer_seat_allowance_mm"]+mechanical["backer_thickness_mm"],
                "source_material_removed_mm3":source.Volume()-frame.Volume(),
                "source_material_removed_fraction":(source.Volume()-frame.Volume())/source.Volume(),
                "protected_material_removed_mm3":preservation,"rigid_overlap_mm3":overlaps,
                "supports":supports,"component_envelopes":components,"front_solder_envelopes":solder,
                "pockets":pocket_specs,"common_pocket_floor_x_mm":common_floor,
                "common_pocket_yz_mm":list(common_pocket.exterior.coords),
                "common_pocket_holes_yz_mm":[list(ring.coords) for ring in common_pocket.interiors],
                "minimum_front_package_frame_gap_mm":front_min,
                "sensor_poses":poses,"magnet_locations":b1["magnet_locations"],
                "limits":["Unloaded geometry only; the motion/range study and physical installed tests remain.",
                          "The source TPU and existing B2 PCB are retained; component height and solder allowances require physical inspection.",
                          "Protected geometry is not a printed strength or fatigue rating."]}
        (OUTPUT/"recessed_manifest.json").write_text(json.dumps(result,indent=2)+"\n")
        record["geometry"]={"parts":len(parts),"removed_fraction":result["source_material_removed_fraction"],
                            "protected_losses":preservation,"minimum_frame_gap_mm":front_min,
                            "missing_seat_supports":[row["missing_seat_support_mm3"] for row in supports],
                            "maximum_overlap_mm3":max(overlaps.values(),default=0)}
        print(json.dumps(record["geometry"],indent=2))
        if any(abs(value)>1e-5 for value in preservation.values()) or any(value>1e-5 for value in overlaps.values()):
            raise ValueError("B3 geometry violates protected material or rigid-clearance checks")
        if any(row["missing_seat_support_mm3"]>.005 for row in supports):
            raise ValueError("B3 support annulus is not fully seated on the modified frame")
        if front_min<mechanical["frame_component_clearance_mm"]-.002:
            raise ValueError("B3 package/frame clearance is below the declared allowance")


if __name__=="__main__":
    main()
