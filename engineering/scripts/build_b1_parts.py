#!/usr/bin/python3
"""Build a separate ENPIRE magnetic insert and fixed sensor spine; preserve existing releases."""

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
from shapely.geometry import LineString,Point,Polygon,box as polygon_box
from shapely.ops import unary_union
import trimesh

from analyze_baseline_meshes import PARTS
from analyze_b1_interfaces import original_profile,extruded_profile
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/b1"


def extrude_yz(polygon,x0,thickness):
    work=cq.Workplane("YZ",origin=(x0,0,0)).polyline(list(polygon.exterior.coords)[:-1]).close()
    for ring in polygon.interiors:work=work.polyline(list(ring.coords)[:-1]).close()
    return work.extrude(thickness).val()


def cylinder_x(x0,length,y,z,radius):
    return cq.Solid.makeCylinder(radius,length,cq.Vector(x0,y,z),cq.Vector(1,0,0))


def export_part(shape,name,parts,purpose,material,kind="fabricate"):
    shape=shape.clean()
    if not shape.isValid() or len(shape.Solids())!=1 or shape.Volume()<=0:
        raise ValueError(f"Invalid B1 solid: {name}")
    directory=OUTPUT/"cad";directory.mkdir(parents=True,exist_ok=True)
    step=directory/(name+".step");stl=directory/(name+".stl")
    cq.exporters.export(shape,str(step))
    cq.exporters.export(shape,str(stl),tolerance=.03,angularTolerance=.1)
    mesh=trimesh.load_mesh(stl,process=True)
    if not mesh.is_watertight or mesh.volume<=0:raise ValueError(f"Invalid B1 STL: {name}")
    imported=cq.importers.importStep(str(step)).val()
    if not imported.isValid() or abs(imported.Volume()-shape.Volume())>max(.001,shape.Volume()*.001):
        raise ValueError(f"B1 STEP round-trip failed: {name}")
    parts.append({"id":name,"purpose":purpose,"material":material,"kind":kind,
                  "step":"cad/"+name+".step","stl":"cad/"+name+".stl",
                  "bounds_mm":mesh.bounds.tolist(),"volume_mm3":shape.Volume(),
                  "sha256_step":hashlib.sha256(step.read_bytes()).hexdigest(),
                  "sha256_stl":hashlib.sha256(stl.read_bytes()).hexdigest(),
                  "digital_solid_valid":True,"physical_fit_tested":False})
    return mesh


def largest(polygon):
    if polygon.geom_type=="Polygon":return polygon
    return max(polygon.geoms,key=lambda value:value.area)


def side_outline(hard):
    triangles=hard.triangles[:,:,[1,2]]
    faces=[Polygon(triangle) for triangle in triangles if Polygon(triangle).area>1e-8]
    merged=largest(unary_union(faces).buffer(.0001).buffer(-.0001))
    return Polygon(merged.exterior.coords).simplify(.005)


def vertical_intervals(profile,y):
    intersection=profile.intersection(LineString([(y,-30),(y,50)]))
    lines=[intersection] if intersection.geom_type=="LineString" else list(intersection.geoms)
    return sorted((line.bounds[1],line.bounds[3]) for line in lines if line.length>1e-6)


def footprint(center,angle,bounds,padding=0):
    # Chip X axis points distally; chip Y axis points toward the back.
    u=np.array([-np.cos(angle),-np.sin(angle)])
    v=np.array([-np.sin(angle), np.cos(angle)])
    x0,y0,x1,y1=bounds
    points=[np.asarray(center)+a*u+b*v for a,b in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
    return Polygon(points).buffer(padding),u,v


def regional_max_x(hard,region):
    lo_y,lo_z,hi_y,hi_z=region.bounds
    tris=hard.triangles
    possible=(tris[:,:,1].max(axis=1)>=lo_y)&(tris[:,:,1].min(axis=1)<=hi_y)
    possible&=(tris[:,:,2].max(axis=1)>=lo_z)&(tris[:,:,2].min(axis=1)<=hi_z)
    maxima=[0.0]  # original TPU side plane, including open frame windows
    for triangle in tris[possible]:
        projection=Polygon(triangle[:,[1,2]])
        if projection.area<1e-10:continue
        clipped=projection.intersection(region)
        if clipped.is_empty:continue
        # Interpolate X only at vertices of the clipped projected triangle.
        # A triangle may reach the flared root outside this local footprint.
        plane=np.linalg.solve(np.column_stack((triangle[:,1:],np.ones(3))),triangle[:,0])
        polygons=[clipped] if clipped.geom_type=="Polygon" else getattr(clipped,"geoms",[])
        for polygon in polygons:
            if polygon.geom_type!="Polygon":continue
            points=np.asarray(polygon.exterior.coords)
            maxima.append(float(np.max(points@plane[:2]+plane[2])))
    return max(maxima)


def fit_board(target,preferred_angle,outline,bounds,occupied):
    """Place a fixed board near its magnet while retaining the hard-frame silhouette."""
    target=np.asarray(target)
    candidates=[]
    for y in np.arange(target[0]-10,target[0]+10.01,.5):
        if not -90<=y<=-18:continue
        lines=[outline.intersection(LineString([(sample,-20),(sample,45)])) for sample in (y-.5,y,y+.5)]
        if any(line.is_empty for line in lines):continue
        mids=[(line.bounds[1]+line.bounds[3])/2 for line in lines]
        angle=float(np.arctan2(mids[2]-mids[0],1.0))
        for orientation in (angle,preferred_angle,angle+np.pi):
            inward=np.array([-np.sin(orientation),np.cos(orientation)])
            for shift in np.arange(-3,3.01,.5):
                centre=np.array([y,mids[1]])+inward*(shift-1)
                candidates.append((float(np.linalg.norm(centre-target)),centre,orientation))
    for distance,centre,angle in sorted(candidates,key=lambda item:item[0]):
        region,u,v=footprint(centre,angle,bounds,.45)
        if outline.buffer(-.15).covers(region) and not any(region.buffer(.2).intersects(other) for other in occupied):
            return centre,region,u,v,distance
    return None


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    config=json.loads((ROOT/"engineering/designs/b1.json").read_text())
    with execution(ROOT/"build/records","Build the separate magnetic B1 insert and fixed spine while checking source geometry, preserved anchors and mechanical envelopes") as record:
        for part,key in (("hard_frame","hard"),("soft_insert","soft")):
            if hashlib.sha256(PARTS[part].read_bytes()).hexdigest()!=config["source_mesh_sha256"][key]:
                raise ValueError(f"Unexpected original mesh: {part}")
        soft,profile,holes=original_profile();original=extruded_profile(profile)
        outer=Polygon(profile.exterior.coords)
        outer_solid=extrude_yz(outer,-15,15)
        hard=trimesh.load_mesh(PARTS["hard_frame"],process=True)
        hard_outline=side_outline(hard)
        combined_outline=largest(hard_outline.union(outer).buffer(.0001).buffer(-.0001))
        interface=json.loads((OUTPUT/"source_interface.json").read_text())
        anchors=sorted(interface["anchors"],key=lambda value:value["center_yz_mm"][0])
        settings=config["insert"];r1=json.loads((ROOT/"engineering/release/r1/r1_manifest.json").read_text())
        modified=original;locations=[];bosses=[]
        for index,(target,pad) in enumerate(zip(settings["target_native_y_mm"],r1["pads"])):
            curve=np.asarray(pad["front_curve_native_yz_mm"])
            angle=float(np.arctan(np.polyfit(curve[:,0]-target,curve[:,1],1)[0]))
            # Keep the magnet and its radial skin entirely inside the original
            # outside profile. Only material inside existing voids is added.
            selected=None
            for offset in (0,.4,-.4,.8,-.8):
                y=target+offset
                front=vertical_intervals(profile,y)[0][0]
                for extra in np.arange(0,3.01,.2):
                    center=(y,float(front+settings["boss_radius_mm"]+extra))
                    radial=Point(center).buffer(settings["boss_radius_mm"],resolution=32)
                    protected=any(Point(anchor["center_yz_mm"]).distance(Point(center))<
                                  settings["anchor_keepout_radius_mm"]+settings["boss_radius_mm"]
                                  for anchor in anchors)
                    if outer.covers(radial) and not protected:
                        selected=center;break
                if selected:break
            if selected is None:raise ValueError(f"No protected magnet location near Y={target}")
            y,z=selected
            front=vertical_intervals(profile,y)[0][0]
            boss_region=LineString([(y,front+.7),selected]).buffer(settings["boss_radius_mm"],resolution=32).intersection(outer)
            boss=extrude_yz(boss_region,settings["boss_native_x_min_mm"],-settings["boss_native_x_min_mm"])
            modified=modified.fuse(boss)
            pocket=cylinder_x(settings["pocket_native_x_min_mm"],-settings["pocket_native_x_min_mm"]+.02,y,z,settings["pocket_diameter_mm"]/2)
            groove=cylinder_x(-.75,.30,y,z,settings["groove_diameter_mm"]/2)
            modified=modified.cut(pocket.fuse(groove))
            locations.append({
                "id":f"M{index}","native_xyz_mm":[settings["pocket_native_x_min_mm"]+config["magnet"]["thickness_mm"]/2,y,z],
                "contact_landmark_channel":index+2,"front_tangent_angle_deg":float(np.rad2deg(angle)),
                "pocket_axis_native":[1,0,0],"boss_radius_mm":settings["boss_radius_mm"],
            })
            bosses.append(boss)
        if modified.cut(outer_solid).Volume()>1e-6:
            raise ValueError("B1 insert changed the original exterior envelope")
        anchor_checks=[]
        for anchor in anchors:
            y,z=anchor["center_yz_mm"]
            protected=cylinder_x(-15,15,y,z,settings["anchor_keepout_radius_mm"])
            loss=original.intersect(protected).cut(modified).Volume()
            bore_region=Polygon(interface["holes_yz"][anchor["id"]])
            bore=extrude_yz(bore_region,-15,15)
            intrusion=modified.intersect(bore).Volume()
            if loss>1e-6 or intrusion>1e-6:raise ValueError("Original TPU anchor was altered")
            anchor_checks.append({"center_yz_mm":anchor["center_yz_mm"],"original_material_removed_mm3":loss,"bore_intrusion_mm3":intrusion})

        readout=config["readout"];carrier=config["carrier"]
        (OUTPUT/"layout_seed.json").write_text(json.dumps({
            "hard_outline_yz":list(hard_outline.exterior.coords),
            "tpu_outline_yz":list(outer.exterior.coords),
            "combined_outline_yz":list(combined_outline.exterior.coords),
            "magnets":locations,"anchors":anchors,
            "pcb_bounds_relative_to_chip_uv_mm":readout["pcb_bounds_relative_to_chip_uv_mm"],
        },indent=2)+"\n")
        sensor_poses=[]
        occupied=[]
        for index,magnet in enumerate(locations):
            angle=np.deg2rad(magnet["front_tangent_angle_deg"])
            inward=np.array([-np.sin(angle),np.cos(angle)])
            yz=np.asarray(magnet["native_xyz_mm"][1:])
            chosen=fit_board(yz,angle,combined_outline,readout["pcb_bounds_relative_to_chip_uv_mm"],occupied)
            if chosen is None:raise ValueError(f"Sensor board cannot fit inside the original side silhouette: {index}")
            centre,region,u,v,displacement=chosen
            occupied.append(region)
            sensor_poses.append({"id":f"S{index}","mux_channel":index,"role":"deformation",
                                "native_yz_mm":centre.tolist(),"u_yz":u.tolist(),"v_yz":v.tolist(),
                                "footprint_yz":list(region.exterior.coords),"projected_distance_from_magnet_mm":displacement})
        # Reference observes common-field changes. Its own magnet coupling is
        # retained in the later field model instead of assumed to be zero.
        centre=np.asarray(readout["reference_target_yz_mm"])
        for dz in np.arange(0,-6.01,-.25):
            region,u,v=footprint(centre+[0,dz],0,readout["pcb_bounds_relative_to_chip_uv_mm"],.45)
            if hard_outline.buffer(-.15).covers(region) and not any(region.buffer(.2).intersects(other) for other in occupied):
                centre=centre+[0,dz];break
        else:raise ValueError("Reference board does not fit inside the original side silhouette")
        sensor_poses.append({"id":"S4","mux_channel":4,"role":"common_field_reference",
                            "native_yz_mm":centre.tolist(),"u_yz":u.tolist(),"v_yz":v.tolist(),
                            "footprint_yz":list(region.exterior.coords)})
        regional=[]
        for sensor in sensor_poses:
            value=regional_max_x(hard,Polygon(sensor["footprint_yz"]))
            sensor["hard_frame_max_x_in_footprint_mm"]=value;regional.append(value)
        pcb_x=max(readout["pcb_top_native_x_min_mm"],
                     max(regional)+readout["package_height_allowance_mm"]+readout["minimum_component_to_frame_gap_mm"])
        back_x=pcb_x+readout["pcb_thickness_mm"]+carrier["adhesive_thickness_mm"]
        for sensor in sensor_poses:
            u=np.array([0,*sensor["u_yz"]]);v=np.array([0,*sensor["v_yz"]]);normal=np.array([-1.,0,0])
            sensor["pcb_top_origin_native_mm"]=[pcb_x,*sensor["native_yz_mm"]]
            sensor["die_center_native_mm"]=[pcb_x-readout["die_height_from_pcb_mm"],*sensor["native_yz_mm"]]
            sensor["rotation_sensor_to_native"]=np.column_stack((u,v,normal)).tolist()
        used=[anchors[index] for index in carrier["use_anchor_indices_sorted_by_y"]]
        paths=[]
        sample_y=np.linspace(-89,-16,40)
        backbone=[]
        for y in sample_y:
            line=hard_outline.intersection(LineString([(y,-20),(y,45)]))
            if line.is_empty:continue
            backbone.append([float(y),float(line.bounds[3]-2.2)])
        paths.append(LineString(backbone).buffer(carrier["backbone_width_mm"]/2))
        for sensor in sensor_poses:
            y,z=sensor["native_yz_mm"]
            back_z=float(np.interp(y, sample_y, np.asarray(backbone)[:,1]))
            paths.append(LineString([(y,z),(y,back_z)]).buffer(carrier["arm_width_mm"]/2))
            paths.append(Polygon(sensor["footprint_yz"]).buffer(.25))
        for anchor in used:
            y,z=anchor["center_yz_mm"];back_z=float(np.interp(y,sample_y,np.asarray(backbone)[:,1]))
            paths.append(LineString([(y,z),(y,back_z)]).buffer(carrier["arm_width_mm"]/2))
            paths.append(Point(y,z).buffer(carrier["mount_boss_radius_mm"]))
        carrier_region=unary_union(paths).intersection(combined_outline).intersection(polygon_box(-94.5,-10,-13.8,35)).buffer(0).simplify(.025,preserve_topology=True)
        if carrier_region.geom_type!="Polygon":
            raise ValueError("Sensor spine is disconnected")
        spine=extrude_yz(carrier_region,back_x,carrier["back_thickness_mm"])
        support_records=[]
        for anchor in used:
            y,z=anchor["center_yz_mm"]
            annulus=Point(y,z).buffer(3.2).difference(Point(y,z).buffer(2.0))
            support_x=regional_max_x(hard,annulus)
            post_region=Point(y,z).buffer(carrier["mount_boss_radius_mm"]).intersection(carrier_region).simplify(.015,preserve_topology=True)
            post=extrude_yz(post_region,support_x+.05,back_x+carrier["back_thickness_mm"]-support_x-.05)
            spine=spine.fuse(post)
            spine=spine.cut(cylinder_x(support_x-.1,back_x+carrier["back_thickness_mm"]-support_x+.3,y,z,carrier["mount_bore_mm"]/2))
            support_records.append({"center_yz_mm":[y,z],"measured_support_outer_x_mm":support_x,
                                    "added_stack_before_fastener_head_mm":back_x+carrier["back_thickness_mm"]-support_x,
                                    "reserved_head_origin_native_mm":[back_x+carrier["back_thickness_mm"],y,z],
                                    "reserved_head_diameter_mm":carrier["reserved_fastener_head_diameter_mm"],
                                    "reserved_head_height_mm":carrier["reserved_fastener_head_height_mm"]})
        parts=[]
        export_part(modified,"b1_magnetic_tpu_insert",parts,"Original external TPU profile with four side magnet pockets; original anchors retained.",config["insert"]["material"])
        # Plug is supplied in its insertion coordinate frame, axis +X.
        plug=cylinder_x(0,settings["plug_length_mm"],0,0,settings["plug_stem_diameter_mm"]/2)
        plug=plug.fuse(cylinder_x(.40,.30,0,0,settings["plug_bead_diameter_mm"]/2))
        export_part(plug,"b1_flush_magnet_plug",parts,"Flush retaining plug; print four and verify fit/pull retention before robot use.","TPU 95A")
        export_part(spine,"b1_fixed_sensor_spine",parts,"Fixed PCB backing and wire support attached at two original side fasteners; the soft insert bends independently.",carrier["material"])
        magnet_ref=cylinder_x(0,config["magnet"]["thickness_mm"],0,0,config["magnet"]["diameter_mm"]/2)
        export_part(magnet_ref,"b1_magnet_reference",parts,"Purchased 3 x 1 mm axially magnetized disc; do not fabricate this reference.","Purchased magnet","reference_only")
        board=cq.Workplane("XY").box(8,6.4,.8,centered=(True,False,False)).translate((0,-2.4,-.8)).val()
        package=cq.Workplane("XY").box(3,3,1.05,centered=(True,True,False)).val()
        export_part(board.fuse(package),"b1_sensor_pcb_reference",parts,"8 x 6.4 mm PCB and MLX90393 package envelope; fabricate the board from PCB manufacturing files.","PCB/component reference","reference_only")
        result={
            "revision":config["revision"],"architecture":config["name"],"parts":parts,
            "status":"digital prototype; assembly, bending mechanics and force accuracy untested",
            "source_hashes":config["source_mesh_sha256"],"magnet_locations":locations,"sensor_poses":sensor_poses,
            "anchor_checks":anchor_checks,"carrier_mounts":support_records,
            "sensor_pcb_top_x_mm":pcb_x,"carrier_outer_x_mm":back_x+carrier["back_thickness_mm"],
            "insert_volume_mm3":modified.Volume(),"original_insert_volume_mm3":original.Volume(),
            "removed_original_material_mm3":original.cut(modified).Volume(),"added_internal_material_mm3":modified.cut(original).Volume(),
            "insert_exterior_extension_mm3":modified.cut(outer_solid).Volume(),
            "unchanged_hard_frame":True,"added_reach_mm":0,
            "original_global_width_mm":float(hard.extents[0]),
            "added_global_width_excluding_fastener_heads_and_wires_mm":float(max(0,back_x+carrier["back_thickness_mm"]-hard.bounds[1,0])),
            "added_global_width_including_reserved_heads_excluding_wires_mm":float(max(0,back_x+carrier["back_thickness_mm"]+carrier["reserved_fastener_head_height_mm"]-hard.bounds[1,0])),
            "checks":{"cad_solids":len(parts),"step_roundtrips":len(parts),"watertight_stl_exports":len(parts)},
            "limitations":[
                "Internal magnet bosses change local stiffness; unchanged outer geometry does not prove unchanged compliance.",
                "The sensor spine occupies some side-window space and adds local side thickness. Check actual task clearances.",
                "Magnetic measurements are deformation/field observations; no force calibration is supplied without physical data.",
                "Reference subtraction cannot remove arbitrary motor-field gradients, gain mismatch or magnet temperature effects.",
                "Hard-nail contact requires the optional R1 N0 cells; magnetic insert sensing alone does not cover a rigid nail.",
            ],
        }
        (OUTPUT/"b1_manifest.json").write_text(json.dumps(result,indent=2)+"\n")
        record["checks"]=result["checks"]
        print(json.dumps({key:result[key] for key in (
            "checks","insert_volume_mm3","removed_original_material_mm3","added_internal_material_mm3",
            "added_global_width_excluding_fastener_heads_and_wires_mm","sensor_pcb_top_x_mm","added_reach_mm"
        )},indent=2))


if __name__=="__main__":
    main()
