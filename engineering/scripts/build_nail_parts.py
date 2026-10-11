#!/usr/bin/python3
"""Develop the independent sensing nail and its frame interfaces without changing releases."""

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
import numpy as np
from shapely.geometry import Point,box
import trimesh

from analyze_baseline_meshes import PARTS
from analyze_b1_interfaces import original_profile,extruded_profile
from build_b1_parts import side_outline,regional_max_x
from nail_geometry import basis,native,local_x,nail_solid,x_bore
from prototype_cad import block,yz_prism,digest,export_part
from source_brep import load as load_source
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/nail"


def source_support_x(mesh,region,index):
    if index==1:
        return regional_max_x(mesh,region)
    reflected = mesh.copy()
    reflected.vertices[:,0] *= -1
    reflected.invert()
    return -regional_max_x(reflected,region)


def sink(outer_x,y,z,direction,config):
    diameter = config["countersink_diameter_mm"]
    length = (diameter-config["m3_clearance_mm"])/2
    return cq.Solid.makeCone(diameter/2,config["m3_clearance_mm"]/2,length,
                            cq.Vector(outer_x,y,z),cq.Vector(direction,0,0))


def main():
    cfg = json.loads((ROOT/"engineering/designs/nail.json").read_text())
    if digest(PARTS["hard_frame"])!=cfg["source_frame"]["sha256"]:
        raise ValueError("Unexpected source hard frame")
    source,conversion = load_source("hard_frame")
    original = trimesh.load_mesh(PARTS["hard_frame"],process=True)
    soft_mesh,soft_profile,_ = original_profile()
    soft = extruded_profile(soft_profile)
    plane,footprint,contact = basis()
    with execution(ROOT/"build/records","Develop a separate bare sensing nail and checked mechanical interfaces; preserve the source frame, TPU and every prior package") as record:
        OUTPUT.mkdir(parents=True,exist_ok=True)
        n = cfg["nail"];m = cfg["mount"];parts=[]
        nail,webs = nail_solid(cfg,plane,footprint)
        nail = native(nail,plane)
        cut_cfg=cfg["source_frame"]
        cut_y=cut_cfg["distal_cut_native_y_mm"]
        cropped = source.intersect(block(-60,40,cut_y,20,-30,70)).clean()
        solids=sorted(cropped.Solids(),key=lambda value:value.Volume(),reverse=True)
        if not solids:
            raise ValueError("Frame cut removed the source component")
        frame=solids[0]
        discarded=[]
        for fragment in solids[1:]:
            bounds=fragment.BoundingBox()
            if fragment.Volume()>cut_cfg["maximum_disconnected_distal_fragment_mm3"] or bounds.ymax>cut_y+cut_cfg["distal_fragment_depth_limit_mm"]:
                raise ValueError("Frame cut detached material beyond the reviewed distal crescent")
            discarded.append({"volume_mm3":fragment.Volume(),
                           "bounds_mm":[[bounds.xmin,bounds.ymin,bounds.zmin],[bounds.xmax,bounds.ymax,bounds.zmax]]})
        pocket_clearance=cut_cfg["web_pocket_clearance_mm"]
        pockets=[]
        for index,web in enumerate(webs):
            side=-1 if index==0 else 1
            inner=web["center_x"]-side*n["web_thickness_mm"]/2
            outer=web["outer_x"]
            pocket=block(min(inner,outer)-pocket_clearance,max(inner,outer)+pocket_clearance,
                         n["web_free_end_local_y_mm"]-pocket_clearance,
                         n["web_fixed_boundary_local_y_mm"]+n["clamp_end_length_mm"]+pocket_clearance,
                         n["web_lower_local_z_mm"]-pocket_clearance,
                         n["web_lower_local_z_mm"]+n["web_height_mm"]+pocket_clearance)
            pockets.append(native(pocket,plane))
        before_pockets=frame.Volume()
        frame=frame.cut(*pockets).clean()
        if not frame.isValid() or len(frame.Solids())!=1:
            raise ValueError("Web clearance pockets disconnected or invalidated the revised frame")
        protected_x=cut_cfg["protected_middle_x_range_mm"]
        protected=block(protected_x[0],protected_x[1],cut_cfg["protected_region_start_native_y_mm"],20,-30,70)
        protected_loss=source.intersect(protected).cut(frame).Volume()
        if protected_loss>1e-6:
            raise ValueError("Web pockets changed the protected central frame")
        anchor_checks=[]
        anchors=json.loads((ROOT/"engineering/release/b1/source_interface.json").read_text())["anchors"]
        for anchor in anchors:
            y,z=anchor["center_yz_mm"]
            region=x_bore(-40,20,y,z,2*cut_cfg["preserved_attachment_region_radius_mm"])
            removed=source.intersect(region).cut(frame).Volume()
            anchor_checks.append({"center_native_yz_mm":[y,z],"removed_source_material_mm3":removed})
            if removed>1e-6:
                raise ValueError("Frame revision altered a required TPU attachment region")
        outline = side_outline(original).intersection(box(m["carrier_front_native_y_mm"],-30,
                                                          m["carrier_rear_native_y_mm"],60))
        if outline.geom_type!="Polygon":
            raise ValueError("Carrier outline is disconnected")
        carriers=[];mounts=[];clamp_holes=[]
        for index,(x0,x1) in enumerate(m["carrier_native_x_ranges_mm"]):
            body = yz_prism(outline,x0,x1-x0)
            web = webs[index]
            endpoint = web["outer_x"]+plane.origin.x
            inner = x1 if index==0 else x0
            outer = x0 if index==0 else x1
            # Complete clamp pads support the whole countersink rim. The left
            # pad also bridges the asymmetric source-root width.
            border=m["carrier_clamp_vertical_border_mm"]
            shoe = block(local_x(min(outer,endpoint),plane),local_x(max(outer,endpoint),plane),
                         n["web_fixed_boundary_local_y_mm"],
                         n["web_fixed_boundary_local_y_mm"]+n["clamp_end_length_mm"],
                         n["web_lower_local_z_mm"]-border,
                         n["web_lower_local_z_mm"]+n["web_height_mm"]+border)
            body = body.fuse(native(shoe,plane))
            for y,z in m["original_side_anchor_yz_mm"]:
                region = Point(y,z).buffer(m["post_radius_mm"])
                surface = source_support_x(original,region,index)
                surface += m["source_contact_gap_mm"]*(1 if index==1 else -1)
                # Continue the locating boss through the outer plate so the
                # complete countersink/thread surround has supporting metal.
                start,end = sorted((outer,surface))
                if start==end:
                    raise ValueError("A source mount post has zero length")
                post = x_bore(start,end,y,z,2*m["post_radius_mm"])
                body = body.fuse(post)
                body = body.cut(x_bore(min(x0,surface)-.1,max(x1,surface)+.1,y,z,m["m3_clearance_mm"]))
                if index==0:
                    # Put the M3 thread only in the outer 3 mm carrier. Keep
                    # the longer integral post a clearance bore.
                    sleeve = x_bore(x0,x1,y,z,m["m3_clearance_mm"])
                    body = body.fuse(sleeve).cut(x_bore(x0-.1,x1+.1,y,z,m["m3_tap_drill_mm"]))
                else:
                    body = body.cut(sink(outer,y,z,-1,m))
                mounts.append({"carrier":index,"center_native_yz_mm":[y,z],"contact_plane_x_mm":surface,
                               "outer_x_mm":outer,"inner_x_mm":inner})
            for height in n["clamp_bolt_local_z_mm"]:
                location = plane.toWorldCoords((web["center_x"],n["clamp_bolt_local_y_mm"],height))
                y,z = location.y,location.z
                body = body.cut(x_bore(min(outer,endpoint)-.1,max(outer,endpoint)+.1,y,z,m["m3_clearance_mm"]))
                body = body.cut(sink(outer,y,z,1 if index==0 else -1,m))
                a = web["inner_x"]+plane.origin.x;b = endpoint
                nail = nail.cut(x_bore(min(a,b)-.1,max(a,b)+.1,y,z,m["m3_tap_drill_mm"]))
                clamp_holes.append({"carrier":index,"center_native_yz_mm":[y,z],
                                    "outer_x_mm":outer,"nail_outer_x_mm":endpoint,
                                    "screw":m["clamp_screws"][index]})
            carriers.append(body.clean())
        shapes = {"nail_bare_sensing_fork":nail,"nail_left_fixed_carrier":carriers[0],
                  "nail_right_fixed_carrier":carriers[1],"nail_revised_hard_frame":frame}
        purposes = {
            "nail_bare_sensing_fork":"Bare source-shaped leading fork, two vertical shear webs and thick inactive clamp ends.",
            "nail_left_fixed_carrier":"Fixed metal support, original side attachment axes, M3 threaded mount and extended front clamp shoe.",
            "nail_right_fixed_carrier":"Fixed metal support with flush M3 side-mount and front-clamp screws.",
            "nail_revised_hard_frame":"Separate original-frame derivative with its hard nail removed; source root and TPU attachment geometry retained.",
        }
        for name,shape in shapes.items():
            export_part(shape,name,OUTPUT,parts,purposes[name],
                        "PETG: match original frame process" if name.endswith("hard_frame") else n["material_candidate"])
        checks={}
        for name,shape in shapes.items():
            if name=="nail_revised_hard_frame":
                continue
            checks[name+"_vs_frame_mm3"] = shape.intersect(frame).Volume()
            checks[name+"_vs_tpu_mm3"] = shape.intersect(soft).Volume()
        checks["nail_vs_left_carrier_mm3"] = nail.intersect(carriers[0]).Volume()
        checks["nail_vs_right_carrier_mm3"] = nail.intersect(carriers[1]).Volume()
        checks["left_vs_right_carrier_mm3"] = carriers[0].intersect(carriers[1]).Volume()
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        distances={}
        for name,other in (("nail_to_frame",frame),("nail_to_tpu",soft)):
            measure=BRepExtrema_DistShapeShape()
            measure.SetMultiThread(False)
            measure.LoadS1(nail.wrapped);measure.LoadS2(other.wrapped);measure.Perform()
            if not measure.IsDone():
                raise ValueError("Nail clearance measurement did not complete")
            distances[name]=measure.Value()
        gauge_rows=[]
        g = cfg["gauges"]
        for index,web in enumerate(webs):
            center = plane.toWorldCoords((web["center_x"]+(-1 if index==0 else 1)*n["web_thickness_mm"]/2,
                                          g["center_local_y_mm"],g["center_local_z_mm"]))
            gauge_rows.append({"id":("NL","NR")[index],"part":g["candidate"],"bridge":index,
                               "outer_face_native_x_mm":center.x,"center_native_xyz_mm":list(center.toTuple()),
                               "center_nail_yz_mm":[g["center_local_y_mm"],g["center_local_z_mm"]],
                               "carrier_size_yz_mm":[g["carrier_length_mm"],g["carrier_height_mm"]],
                               "note":"Full bridge carrier center and envelope. Internal grid locations are not inferred from a rendered illustration."})
        all_vertices=np.vstack([trimesh.load_mesh(OUTPUT/part["stl"],process=True).vertices for part in parts]+[soft_mesh.vertices])
        result={"schema":"yam-nail-development/1","revision":cfg["revision"],"status":"geometry development",
                "physical_specimens_tested":0,"parts":parts,"gauges":gauge_rows,
                "source_frame_conversion":conversion,"source_contact_report_sha256":digest(ROOT/"engineering/release/contact_regions/contact_report.json"),
                "source_hashes":{str(path.relative_to(ROOT)):digest(path) for path in
                    (ROOT/"engineering/designs/nail.json",Path(__file__),ROOT/"engineering/scripts/nail_geometry.py",ROOT/"engineering/scripts/source_brep.py")},
                "mounts":mounts,"clamp_holes":clamp_holes,"rigid_overlap_checks_mm3":checks,
                "discarded_distal_fragments":discarded,"preserved_attachment_checks":anchor_checks,
                "web_pocket_removed_material_mm3":before_pockets-frame.Volume(),
                "protected_central_frame_removed_mm3":protected_loss,
                "assembly_bounds_mm":[all_vertices.min(axis=0).tolist(),all_vertices.max(axis=0).tolist()],
                "nail_plane_origin_native_mm":list(plane.origin.toTuple()),
                "nail_plane_axes_native":[list(axis.toTuple()) for axis in (plane.xDir,plane.yDir,plane.zDir)],
                "force_axis_native":cfg["force_axis_native"],
                "minimum_rigid_distance_mm":distances,
                "notes":["Development geometry only. Gauge wiring, readout, structural screen, protection, physical fit and force tests remain.",
                         "The source contact-plane X-axis noise below 1e-8 is snapped to native X for planar side machining; the original plane origin and YZ angle are retained.",
                         "No existing prototype or original source component was overwritten.",
                         "The revised frame is a faceted derivative of the pinned STL; it is not the original author's analytic CAD."]}
        (OUTPUT/"nail_manifest.json").write_text(json.dumps(result,indent=2)+"\n")
        record["geometry"]={"parts":len(parts),"overlaps_mm3":checks,"bounds_mm":result["assembly_bounds_mm"]}
        print(json.dumps(record["geometry"],indent=2))
        if any(value>1e-5 for value in checks.values()):
            raise ValueError("Nail integration has unresolved rigid interference; review the saved geometry before fabrication")
        bonded=nail.fuse(*carriers).clean()
        if not bonded.isValid() or len(bonded.Solids())!=1:
            raise ValueError("Nail metal assembly is not one connected ideal bonded solid")
        if abs(bonded.Volume()-nail.Volume()-sum(shape.Volume() for shape in carriers))>.001:
            raise ValueError("Bonded analysis changed the part volumes")
        analysis=OUTPUT/"analysis";analysis.mkdir(exist_ok=True)
        cq.exporters.export(bonded,str(analysis/"nail_bonded_assembly.step"))
        result["analysis_step"]="analysis/nail_bonded_assembly.step"
        result["analysis_step_sha256"]=digest(OUTPUT/result["analysis_step"])
        (OUTPUT/"nail_manifest.json").write_text(json.dumps(result,indent=2)+"\n")


if __name__=="__main__":
    main()
