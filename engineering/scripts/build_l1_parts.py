#!/usr/bin/python3
"""Build the ENPIRE-matched L1 carrier and real load-cell moment-test tooling."""

from __future__ import annotations

import hashlib
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
from shapely.geometry import Polygon
import trimesh

from analyze_baseline_meshes import PARTS
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/l1"


def box(x0,x1,y0,y1,z0,z1):
    return cq.Workplane("XY").box(x1-x0,y1-y0,z1-z0,centered=(False,False,False)).translate((x0,y0,z0)).val()


def hole_z(x,y,z0,z1,diameter):
    return cq.Solid.makeCylinder(diameter/2,z1-z0,cq.Vector(x,y,z0),cq.Vector(0,0,1))


def hole_y(x,z,y0,y1,diameter):
    return cq.Solid.makeCylinder(diameter/2,y1-y0,cq.Vector(x,y0,z),cq.Vector(0,1,0))


def extrude_xz(polygon,y,depth):
    plane=cq.Plane(origin=(0,y,0),xDir=(1,0,0),normal=(0,-1,0))
    work=cq.Workplane(plane).polyline(list(polygon.exterior.coords)[:-1]).close()
    for ring in polygon.interiors:
        work=work.polyline(list(ring.coords)[:-1]).close()
    return work.extrude(depth).val()


def hull_solid(mesh):
    faces=[]
    for triangle in mesh.triangles:
        wire=cq.Wire.makePolygon([cq.Vector(*p) for p in triangle],close=True)
        faces.append(cq.Face.makeFromWires(wire))
    return cq.Solid.makeSolid(cq.Shell.makeShell(faces))


def export(shape,name,parts,purpose,material="6061-T6 aluminum",kind="fabricate"):
    if not shape.isValid() or len(shape.Solids())!=1 or shape.Volume()<=0:
        raise ValueError(f"Invalid L1 solid: {name}")
    directory=OUTPUT/"cad";directory.mkdir(parents=True,exist_ok=True)
    step=directory/f"{name}.step";stl=directory/f"{name}.stl"
    cq.exporters.export(shape,str(step))
    cq.exporters.export(shape,str(stl),tolerance=.04,angularTolerance=.12)
    mesh=trimesh.load_mesh(stl,process=True)
    if not mesh.is_watertight or mesh.volume<=0:
        raise ValueError(f"Open or inverted STL: {name}")
    roundtrip=cq.importers.importStep(str(step)).val()
    if not roundtrip.isValid() or abs(roundtrip.Volume()-shape.Volume())>max(.001,shape.Volume()*.001):
        raise ValueError(f"STEP round-trip changed {name}")
    parts.append({
        "id":name,"purpose":purpose,"kind":kind,"material":material,
        "step":f"cad/{name}.step","stl":f"cad/{name}.stl",
        "volume_mm3":shape.Volume(),"bounds_mm":mesh.bounds.tolist(),
        "sha256_step":hashlib.sha256(step.read_bytes()).hexdigest(),
        "sha256_stl":hashlib.sha256(stl.read_bytes()).hexdigest(),
        "digital_solid_valid":True,"physical_fit_tested":False,
    })
    return mesh


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Generate the source-matched L1 force carrier, sensor keep-outs, and off-center calibration tooling") as record:
        config=json.loads((ROOT/"engineering/designs/l1.json").read_text())
        interface=json.loads((OUTPUT/"root_interface.json").read_text())
        original=trimesh.load_mesh(PARTS["hard_frame"],process=True)
        mount=interface["mount_plane"];mount_y=mount["native_y_mm"]
        region=max(mount["regions"],key=lambda r:r["area_mm2"])
        outer=Polygon(region["outer"]).simplify(.003)
        key_region=max((Polygon(r) for r in region["holes"]),key=lambda p:p.area)
        key_bounds=key_region.bounds
        key_mask=(original.vertices[:,1]>=mount_y-1e-5)
        key_mask&=(original.vertices[:,0]>=key_bounds[0]-1e-4)&(original.vertices[:,0]<=key_bounds[2]+1e-4)
        key_mask&=(original.vertices[:,2]>=key_bounds[1]-1e-4)&(original.vertices[:,2]<=key_bounds[3]+1e-4)
        key_vertices=original.vertices[key_mask]
        key_hull=trimesh.convex.convex_hull(key_vertices)
        key=hull_solid(key_hull)
        protrusion_faces=(original.triangles[:,:,1].min(axis=1)>=mount_y-1e-5)&(original.triangles[:,:,1].max(axis=1)>mount_y+1e-5)
        _,distances,_=trimesh.proximity.closest_point(key_hull,original.triangles_center[protrusion_faces])
        if float(np.max(distances))>.01:
            raise ValueError("Locating feature is not represented by the hull within 0.01 mm")
        a=config["adapter"];cell=config["load_cell"];pose=cell["pose"]
        x0=pose["native_x_min_mm"];x1=x0+cell["width_mm"];cx=(x0+x1)/2
        yp=pose["native_y_wire_end_mm"];yd=yp-cell["length_mm"]
        z0=pose["native_z_bottom_mm"];z1=z0+cell["height_mm"]
        support=cell["supported_end_length_mm"];gap=a["cell_end_side_clearance_mm"];wall=a["end_locator_wall_mm"]
        outer_x0=x0-gap-wall;outer_x1=x1+gap+wall
        fixed_hole_y=yp-cell["mount_hole_offsets_from_wire_end_mm"][0]
        live_hole_y=yp-cell["mount_hole_offsets_from_wire_end_mm"][1]
        shift=config["finger_shift_native_y_mm"]
        finger_mount_y=mount_y+shift
        float_back_y=finger_mount_y+a["floating_root_plate_thickness_mm"]
        floor_z=z0-a["fixed_support_thickness_mm"]
        deck_bottom=z1+a["floating_spacer_mm"]
        deck_top=deck_bottom+a["floating_deck_thickness_mm"]
        knee_end=mount_y-10
        fixed=extrude_xz(outer,mount_y,a["fixed_root_plate_thickness_mm"]).fuse(key)
        fixed=fixed.fuse(box(outer.bounds[2]-2,outer_x1,knee_end,mount_y,floor_z,z0))
        fixed=fixed.fuse(box(outer_x0,outer_x1,yp-support,knee_end,floor_z,z0))
        for left,right in ((outer_x0,x0-gap),(x1+gap,outer_x1)):
            fixed=fixed.fuse(box(left,right,yp-support,yp,z0,z0+a["locator_height_mm"]))
        fixed=fixed.cut(hole_z(cx,fixed_hole_y,floor_z-1,z0+3,a["m5_clearance_diameter_mm"]))
        centers=interface["bolt_centers_native_xz_mm"]
        fixed_clear=fixed
        fixed_tap=fixed
        for x,z in centers:
            fixed_clear=fixed_clear.cut(hole_y(x,z,mount_y-8,mount_y+1,a["m3_clearance_diameter_mm"]))
            fixed_tap=fixed_tap.cut(hole_y(x,z,mount_y-8,mount_y+1,a["m3_tap_drill_diameter_mm"]))
        floating=extrude_xz(outer,float_back_y,a["floating_root_plate_thickness_mm"])
        for x,z in centers:
            floating=floating.cut(hole_y(x,z,finger_mount_y-1,float_back_y+1,a["m3_clearance_diameter_mm"]))
        key_clearance=extrude_xz(key_region.buffer(a["root_key_clearance_mm"]),float_back_y+1,a["floating_root_plate_thickness_mm"]+2)
        floating=floating.cut(key_clearance)
        # A riser above the original root connects to the side rail without
        # crossing the fixed sensor end or changing the finger's contact face.
        riser_x0=max(outer.bounds[0]+6,key_bounds[0])
        floating=floating.fuse(box(riser_x0,outer.bounds[2]-.5,finger_mount_y,float_back_y,outer.bounds[3]-2,deck_top))
        floating=floating.fuse(box(riser_x0,outer_x1,finger_mount_y,float_back_y,deck_bottom,deck_top))
        floating=floating.fuse(box(outer_x0,outer_x1,yd,float_back_y,deck_bottom,deck_top))
        floating=floating.fuse(box(x0-gap,x1+gap,yd,yd+support,z1,deck_bottom))
        for left,right in ((outer_x0,x0-gap),(x1+gap,outer_x1)):
            floating=floating.fuse(box(left,right,yd,yd+support,z1-a["locator_height_mm"],deck_bottom))
        floating=floating.cut(hole_z(cx,live_hole_y,z1-3,deck_top+1,a["m5_clearance_diameter_mm"]))
        sensor=box(x0,x1,yd,yp,z0,z1)
        for y in (fixed_hole_y,live_hole_y):
            sensor=sensor.cut(hole_z(cx,y,z0-1,z1+1,5))
        keepout=box(x0-1,x1+1,yd+14,yp-14,z0-1,z1+1)
        parts=[]
        export(fixed_clear,"l1_fixed_carrier_m3_clearance",parts,"Fixed carrier; same rear datum/key as the ENPIRE finger. Use when mating jaw has M3 threads.")
        export(fixed_tap,"l1_fixed_carrier_m3_tap_drill",parts,"Fixed carrier with 2.5 mm pilot bores; tap M3×0.5 if the mating jaw requires threads in this part.")
        export(floating,"l1_floating_finger_carrier",parts,"Carries the unmodified ENPIRE finger with a 20 mm reach extension; attaches only to the load-cell live end.")
        export(sensor,"tal220b_reference",parts,"Purchased TAL220B outline and mounting axes only; internal strain element is not modeled.","Purchased component","reference_only")
        intersections={
            "fixed_vs_floating":fixed_clear.intersect(floating).Volume(),
            "fixed_vs_sensor_envelope":fixed_clear.intersect(sensor).Volume(),
            "floating_vs_sensor_envelope":floating.intersect(sensor).Volume(),
            "fixed_vs_active_keepout":fixed_clear.intersect(keepout).Volume(),
            "floating_vs_active_keepout":floating.intersect(keepout).Volume(),
        }
        # A separation proof for the retrieved finger, rather than just a
        # triangle-sampling collision check: distal of its rear plane, the
        # original hard and soft meshes are inside disjoint bounding boxes.
        # Behind that plane, the only protrusion is the measured locating key.
        shifted=original.copy();shifted.apply_translation([0,shift,0])
        soft=trimesh.load_mesh(PARTS["soft_insert"],process=True)
        soft.apply_translation([0,shift,0])
        source_key=key.translate((0,shift,0))
        for source_name,mesh in (("hard_frame",shifted),("soft_insert",soft)):
            lo,hi=mesh.bounds
            upper_y=min(hi[1],finger_mount_y-1e-6)
            distal_box=box(lo[0],hi[0],lo[1],upper_y,lo[2],hi[2])
            for carrier_name,shape in (("fixed",fixed_clear),("floating",floating)):
                intersections[f"{carrier_name}_vs_{source_name}_distal_bounds"]=shape.intersect(distal_box).Volume()
        for carrier_name,shape in (("fixed",fixed_clear),("floating",floating)):
            intersections[f"{carrier_name}_vs_original_shifted_key"]=shape.intersect(source_key).Volume()
        hardware=[]
        for index,(x,z) in enumerate(centers):
            hardware.append({
                "id":f"finger_m3_rear_{index+1}","axis":[0,1,0],
                "origin_mm":[x,float_back_y,z],
                "diameter_mm":a["m3_rear_hardware_envelope_diameter_mm"],
                "height_mm":a["m3_rear_hardware_max_projection_mm"],
                "note":"Maximum combined washer, nut and bolt projection; choose and measure actual hardware.",
            })
            envelope=hole_y(x,z,float_back_y,float_back_y+a["m3_rear_hardware_max_projection_mm"],
                           a["m3_rear_hardware_envelope_diameter_mm"])
            intersections[f"fixed_vs_finger_m3_hardware_{index+1}"]=fixed_clear.intersect(envelope).Volume()
        for name,y,start,direction in (
            ("fixed_m5",fixed_hole_y,floor_z,-1),("live_m5",live_hole_y,deck_top,1),
        ):
            hardware.append({
                "id":name,"axis":[0,0,direction],"origin_mm":[cx,y,start],
                "diameter_mm":a["m5_head_and_washer_envelope_diameter_mm"],
                "height_mm":a["m5_head_and_washer_envelope_height_mm"],
                "note":"Reserved head/washer space, not a supplier screw drawing.",
            })
        if any(value>1e-6 for value in intersections.values()):
            raise ValueError(f"L1 contact-path interference: {intersections}")
        # Independent bench shoe: 3 mm air clearance under the active beam.
        shoe=box(-12.5,27.5,-21,21,-9,-3).fuse(box(0,support,-6.5,6.5,-3,0))
        for lo,hi in ((-8,-6.5),(6.5,8)):
            shoe=shoe.fuse(box(0,support,lo,hi,-3,1.5))
        shoe=shoe.cut(hole_z(7.5,0,-10,2,5.5))
        for y in (-14,14):
            shoe=shoe.cut(hole_z(7.5,y,-10,-2,6.5))
        export(shoe,"l1_bench_fixed_shoe",parts,"Bench mount for the cell wire end. Two M6 stand attachments; one M5 sensor attachment.")
        live_spacer=box(55-support,55,-6.5,6.5,12.7,15.7)
        for lo,hi in ((-8,-6.5),(6.5,8)):
            live_spacer=live_spacer.fuse(box(55-support,55,lo,hi,11.2,15.7))
        live_spacer=live_spacer.cut(hole_z(47.5,0,10,17,5.5))
        export(live_spacer,"l1_bench_live_spacer",parts,"13 mm end clamp and 3 mm gap above the active beam; shared by the two test arms.")
        arm_specs=[]
        for name,length,offsets,transverse in (
            ("l1_long_test_arm",config["bench"]["long_arm_length_mm"],config["bench"]["long_arm_test_offsets_mm"],False),
            ("l1_cross_test_arm",config["bench"]["cross_arm_length_mm"],config["bench"]["cross_arm_test_offsets_mm"],True),
        ):
            width=config["bench"]["bar_width_mm"];thick=config["bench"]["bar_thickness_mm"]
            arm=box(47.5-length/2,47.5+length/2,-width/2,width/2,15.7,15.7+thick) if not transverse else box(47.5-width/2,47.5+width/2,-length/2,length/2,15.7,15.7+thick)
            arm=arm.cut(hole_z(47.5,0,15,23,5.5))
            ports=[]
            for offset in offsets:
                x=47.5 if transverse else 47.5+offset
                y=offset if transverse else 0
                if offset:
                    arm=arm.cut(hole_z(x,y,15,23,3.4))
                ports.append({"offset_mm":offset,"x_mm":x,"y_mm":y,"moment_at_20n_nm":abs(offset)*.02})
            export(arm,name,parts,"20 N off-center response fixture. Use the load-cell live-end M5 attachment; ports are load locations, not a moment rating.")
            arm_specs.append({"id":name,"ports":ports,"orientation":"transverse" if transverse else "longitudinal"})
        cap=box(39.5,55.5,-8,8,22.05,31.05).cut(hole_z(47.5,0,21.9,28.55,11.5))
        export(cap,"l1_center_load_cap",parts,"Flat center-loading face over the arm's M5 screw head; test accessory.","PETG test accessory")
        plate=box(47.5-60,47.5+80,-55,15,15.7,22.05)
        plate=plate.cut(hole_z(47.5,0,15,23,5.5))
        combined_ports=[]
        for u in config["bench"]["combined_plate_u_mm"]:
            for v in config["bench"]["combined_plate_v_mm"]:
                if u or v:
                    plate=plate.cut(hole_z(47.5+u,v,15,23,3.4))
                combined_ports.append({"u_mm":u,"v_mm":v,"moment_at_20n_nm":.02*(u*u+v*v)**.5})
        export(plate,"l1_combined_load_plate",parts,"Combined longitudinal/transverse moment locations enclosing the side-mounted finger's contact envelope.")
        all_vertices=np.vstack((shifted.vertices,
            trimesh.load_mesh(OUTPUT/"cad/l1_fixed_carrier_m3_clearance.stl").vertices,
            trimesh.load_mesh(OUTPUT/"cad/l1_floating_finger_carrier.stl").vertices))
        contact_force=np.array([0.,0.,20.])
        relative=shifted.vertices-np.array([cx,live_hole_y,z1])
        moments=np.cross(relative,contact_force)/1000
        result={
            "revision":config["revision"],"status":"digital prototype; fabrication and load tests pending",
            "parts":parts,"source_interface":"root_interface.json","source_key_surface_match_mm":float(np.max(distances)),
            "cell_mount_centers_native_xyz_mm":[[cx,fixed_hole_y,z0],[cx,live_hole_y,z1]],
            "finger_translation_native_mm":[0,shift,0],
            "assembly_bounds_native_mm":[all_vertices.min(axis=0).tolist(),all_vertices.max(axis=0).tolist()],
            "added_width_mm":float(np.ptp(all_vertices[:,0])-original.extents[0]),
            "added_back_height_mm":float(all_vertices[:,2].max()-original.bounds[1,2]),
            "added_back_height_including_reserved_m5_head_mm":float(
                deck_top+a["m5_head_and_washer_envelope_height_mm"]-original.bounds[1,2]),
            "rear_hardware_to_fixed_plate_gap_mm":float(
                mount_y-a["fixed_root_plate_thickness_mm"]-float_back_y-a["m3_rear_hardware_max_projection_mm"]),
            "hardware_envelopes":hardware,
            "reach_extension_mm":abs(shift),
            "force_target_n":20,
            "max_normal_load_moment_at_cell_over_mesh_nm":float(np.linalg.norm(moments,axis=1).max()),
            "moment_component_abs_max_nm":np.abs(moments).max(axis=0).tolist(),
            "native_20n_moment_at_robot_mount_nm":20*(interface["distal_lever_from_mount_mm"]+abs(shift))/1000,
            "intersections_mm3":intersections,
            "original_mesh_clearance_method":"Distal mesh bounds are separated from carrier solids; original rear key is checked by CAD intersection. Shared mounting faces are intentional.",
            "bench_arms":arm_specs,
            "combined_load_ports":combined_ports,
            "contact_lever_u_range_mm":[float(-relative[:,1].max()),float(-relative[:,1].min())],
            "contact_lever_v_range_mm":[float(relative[:,0].min()),float(relative[:,0].max())],
            "checks":{"valid_solids":len(parts),"step_roundtrips":len(parts),"watertight_meshes":len(parts)},
            "limitations":[
                "The selected cell has no published long-finger moment rating; bench moment testing is a prerequisite.",
                "CNC aluminum is specified for load-path parts. PETG STLs are dimensional witnesses, not strength-qualified replacements.",
                "The maker finger mounting features are copied geometrically. Mating jaw fastening direction and housing clearance still need physical checks.",
                "This is one normal-force axis. Gravity, dynamics, shear, and torsional coupling require separate characterization.",
                "No measured force accuracy, durability, or robot-task result is included.",
            ],
        }
        (OUTPUT/"l1_manifest.json").write_text(json.dumps(result,indent=2)+"\n")
        record["checks"]=result["checks"];record["intersections_mm3"]=intersections
        print(json.dumps({key:result[key] for key in (
            "checks","source_key_surface_match_mm","added_width_mm","added_back_height_mm","reach_extension_mm",
            "max_normal_load_moment_at_cell_over_mesh_nm","native_20n_moment_at_robot_mount_nm","intersections_mm3"
        )},indent=2))


if __name__=="__main__":
    main()
