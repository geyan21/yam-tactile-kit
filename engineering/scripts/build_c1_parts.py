#!/usr/bin/python3
"""Build C1's transverse strain beam, independent carriers and bench fixtures."""

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
from shapely.geometry import Polygon
import trimesh

from analyze_baseline_meshes import PARTS
from build_l1_parts import extrude_xz, hole_y, hole_z, hull_solid
from prototype_cad import block, export_part, digest
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/c1"


def root_key(mesh,interface):
    region = max(interface["mount_plane"]["regions"],key=lambda item:item["area_mm2"])
    outline = Polygon(region["outer"]).simplify(.003)
    key_section = max((Polygon(r) for r in region["holes"]),key=lambda p:p.area)
    x0,z0,x1,z1 = key_section.bounds
    y = interface["mount_plane"]["native_y_mm"]
    v = mesh.vertices
    selected = v[(v[:,1]>=y-1e-5)&(v[:,0]>=x0-1e-4)&(v[:,0]<=x1+1e-4)
                 &(v[:,2]>=z0-1e-4)&(v[:,2]<=z1+1e-4)]
    key = hull_solid(trimesh.convex.convex_hull(selected))
    return outline,key_section,key


def gauges(config):
    b = config["beam"];g = config["gauges"]
    rows = []
    roles = [("R1","top",-1),("R2","bottom",-1),("R3","bottom",1),("R4","top",1)]
    for station,u in enumerate(b["gauge_stations_mm_from_fixed_boundary"]):
        for resistor,face,side in roles:
            x = b["fixed_boundary_native_x_mm"]+u
            y = b["center_native_y_mm"]+side*abs(b["gauge_y_offsets_mm"][0])
            z = b["bottom_native_z_mm"]+(b["thickness_mm"] if face=="top" else 0)
            rows.append({
                "id":("A","B")[station]+"_"+resistor,"bridge":station,"resistor":resistor,
                "face":face,"center_native_mm":[x,y,z],"grid_axis_native":[1,0,0],
                "tabs_toward_native_x":-1 if station==0 else 1,
                "grid_bounds_xy_mm":[x-g["grid_length_mm"]/2,y-g["grid_width_mm"]/2,
                                     x+g["grid_length_mm"]/2,y+g["grid_width_mm"]/2],
                "backing_keepout_xy_mm":[x-g["conservative_backing_extent_each_side_of_grid_center_mm"],
                                         y-g["backing_width_mm"]/2,
                                         x+g["conservative_backing_extent_each_side_of_grid_center_mm"],
                                         y+g["backing_width_mm"]/2],
                "part":g["selected_part"],
            })
    return rows


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    config = json.loads((ROOT/"engineering/designs/c1.json").read_text())
    interface = json.loads((ROOT/"engineering/release/l1/root_interface.json").read_text())
    baseline = json.loads((ROOT/"engineering/release/b1/b1_manifest.json").read_text())
    if digest(PARTS["hard_frame"]) != baseline["source_hashes"]["hard"]:
        raise ValueError("Unexpected source hard frame")
    original = trimesh.load_mesh(PARTS["hard_frame"],process=True)
    outline,key_section,key = root_key(original,interface)
    with execution(ROOT/"build/records","Generate C1 metal load-path parts, gauge registration and independent bench fixtures; preserve existing prototypes") as record:
        b = config["beam"];m = config["mount"]
        x0 = b["fixed_boundary_native_x_mm"];x1 = x0+b["active_length_mm"]
        xl = x0-b["end_clamp_length_mm"];xr = x1+b["end_clamp_length_mm"]
        yc = b["center_native_y_mm"];y0 = yc-b["width_mm"]/2;y1 = yc+b["width_mm"]/2
        z0 = b["bottom_native_z_mm"];z1 = z0+b["thickness_mm"]
        mount_y = interface["mount_plane"]["native_y_mm"]
        shift = config["mount"]["finger_translation_native_mm"][1]
        finger_y = mount_y+shift
        floating_rear_y = finger_y+m["floating_root_plate_thickness_mm"]
        shoe_bottom = z0-m["shoe_thickness_mm"]
        bridge_top = m["root_bridge_top_z_mm"]
        holes = [(x,yc+dy) for x in ((xl+x0)/2,(x1+xr)/2) for dy in b["end_hole_y_offsets_mm"]]
        beam = block(xl,xr,y0,y1,z0,z1)
        for x,y in holes:
            beam = beam.cut(hole_z(x,y,z0-1,z1+1,b["end_hole_diameter_mm"]))
        fixed = extrude_xz(outline,mount_y,m["fixed_root_plate_thickness_mm"]).fuse(key)
        fixed = fixed.fuse(block(xl,-15,mount_y-m["fixed_bridge_depth_mm"],mount_y,m["root_bridge_floor_z_mm"],bridge_top))
        fixed = fixed.fuse(block(xl,x0,y0,y1,shoe_bottom,z0))
        floating = extrude_xz(outline,floating_rear_y,m["floating_root_plate_thickness_mm"])
        floating = floating.cut(extrude_xz(key_section.buffer(m["root_key_clearance_mm"]),
                                           floating_rear_y+.1,m["floating_root_plate_thickness_mm"]+.2))
        floating = floating.fuse(block(m["floating_bridge_x_min_mm"],xr,finger_y,
                                      finger_y+m["floating_bridge_depth_mm"],m["root_bridge_floor_z_mm"],bridge_top))
        floating = floating.fuse(block(x1,xr,y0,y1,shoe_bottom,z0))
        centers = interface["bolt_centers_native_xz_mm"]
        fixed_clear = fixed;fixed_tap = fixed
        for x,z in centers:
            fixed_clear = fixed_clear.cut(hole_y(x,z,mount_y-8,mount_y+1,m["m3_clearance_mm"]))
            fixed_tap = fixed_tap.cut(hole_y(x,z,mount_y-8,mount_y+1,m["m3_tap_drill_mm"]))
            floating = floating.cut(hole_y(x,z,finger_y-1,floating_rear_y+1,m["m3_clearance_mm"]))
            sink_height = (m["fixed_m3_countersink_diameter_mm"]-m["m3_clearance_mm"])/2
            sink = cq.Solid.makeCone(m["fixed_m3_countersink_diameter_mm"]/2,m["m3_clearance_mm"]/2,
                                    sink_height,cq.Vector(x,mount_y-m["fixed_root_plate_thickness_mm"],z),cq.Vector(0,1,0))
            fixed_clear = fixed_clear.cut(sink)
            relief_end = max(mount_y-m["fixed_root_plate_thickness_mm"],
                            floating_rear_y+m["m3_rear_hardware_projection_mm"]+m["floating_m3_relief_end_clearance_mm"])
            relief = hole_y(x,z,floating_rear_y-.1,relief_end,
                            m["floating_m3_relief_diameter_mm"])
            fixed_clear = fixed_clear.cut(relief);fixed_tap = fixed_tap.cut(relief)
        for x,y in holes:
            bore = hole_z(x,y,shoe_bottom-3,z0+.1,m["m4_tap_drill_mm"])
            if x<x0:
                fixed_clear = fixed_clear.cut(bore);fixed_tap = fixed_tap.cut(bore)
            else:
                floating = floating.cut(bore)
        caps = []
        for index,(a,c) in enumerate(((xl,x0),(x1,xr))):
            cap = block(a,c,y0,y1,z1,z1+m["clamp_cap_thickness_mm"])
            for x,y in holes:
                if a<x<c:
                    cap = cap.cut(hole_z(x,y,z1-.1,z1+m["clamp_cap_thickness_mm"]+.1,m["m4_clearance_mm"]))
            caps.append(cap)
        parts = []
        shapes = {
            "c1_strain_beam":beam,
            "c1_fixed_carrier_m3_clearance":fixed_clear,
            "c1_fixed_carrier_m3_tap_drill":fixed_tap,
            "c1_floating_finger_carrier":floating,
            "c1_fixed_end_clamp":caps[0],"c1_floating_end_clamp":caps[1],
        }
        purposes = {
            "c1_strain_beam":"Transverse constant-section beam. Bond eight foil gauges at the specified grid centers.",
            "c1_fixed_carrier_m3_clearance":"Fixed carrier with M3 clearance and 90-degree countersinks. Use flush flat-head screws when the mating jaw is threaded.",
            "c1_fixed_carrier_m3_tap_drill":"Alternative fixed carrier; tap the 2.5 mm bores M3 when the mating jaw requires threads here.",
            "c1_floating_finger_carrier":"Carries the original finger with 18 mm reach extension; connects only to the beam floating end.",
            "c1_fixed_end_clamp":"Metal clamp cap for the fixed beam end.",
            "c1_floating_end_clamp":"Metal clamp cap for the floating beam end.",
        }
        for name,shape in shapes.items():
            export_part(shape,name,OUTPUT,parts,purposes[name],m["material"])
        active = block(x0+.001,x1-.001,y0-.7,y1+.7,z0-.7,z1+.7)
        overlap = {
            "fixed_floating_mm3":fixed_clear.intersect(floating).Volume(),
            "fixed_beam_mm3":fixed_clear.intersect(beam).Volume(),
            "floating_beam_mm3":floating.intersect(beam).Volume(),
            "fixed_active_keepout_mm3":fixed_clear.intersect(active).Volume(),
            "floating_active_keepout_mm3":floating.intersect(active).Volume(),
        }
        assembled_shapes = {"fixed":fixed_clear,"floating":floating,"beam":beam,
                            "fixed_cap":caps[0],"floating_cap":caps[1]}
        for i,(name,shape) in enumerate(assembled_shapes.items()):
            for other,other_shape in list(assembled_shapes.items())[i+1:]:
                overlap[f"{name}_vs_{other}_mm3"] = shape.intersect(other_shape).Volume()
        shifted = original.copy();shifted.apply_translation(config["mount"]["finger_translation_native_mm"])
        soft = trimesh.load_mesh(PARTS["soft_insert"],process=True)
        soft.apply_translation(config["mount"]["finger_translation_native_mm"])
        for name,mesh in (("hard",shifted),("soft",soft)):
            lo,hi = mesh.bounds
            distal = block(lo[0],hi[0],lo[1],min(hi[1],finger_y-1e-6),lo[2],hi[2])
            for carrier,shape in (("fixed",fixed_clear),("floating",floating),("beam",beam)):
                overlap[f"{carrier}_vs_{name}_distal_bounds_mm3"] = shape.intersect(distal).Volume()
        moved_key = key.translate((0,shift,0))
        for name,shape in (("fixed",fixed_clear),("floating",floating),("beam",beam)):
            overlap[f"{name}_vs_finger_key_mm3"] = shape.intersect(moved_key).Volume()
        for i,(x,z) in enumerate(centers):
            envelope = hole_y(x,z,floating_rear_y,floating_rear_y+m["m3_rear_hardware_projection_mm"],
                              m["m3_rear_hardware_diameter_mm"])
            overlap[f"fixed_vs_floating_m3_hardware_{i}_mm3"] = fixed_clear.intersect(envelope).Volume()
        if any(value>1e-7 for value in overlap.values()):
            raise ValueError(f"C1 load-path interference: {overlap}")
        bonded = fixed_clear.fuse(floating,beam,*caps).clean()
        if not bonded.isValid() or len(bonded.Solids())!=1:
            raise ValueError("Ideal bonded assembly is not a single connected solid")
        if abs(bonded.Volume()-sum(shape.Volume() for shape in assembled_shapes.values()))>1e-3:
            raise ValueError("Bonded analysis geometry changed the part volumes")
        analysis = OUTPUT/"analysis";analysis.mkdir(exist_ok=True)
        cq.exporters.export(bonded,str(analysis/"c1_bonded_assembly.step"))
        gauge_rows = gauges(config)
        for row in gauge_rows:
            a,c,d,e = row["backing_keepout_xy_mm"]
            if a<x0+.4 or d>x1-.4 or c<y0+.4 or e>y1-.4:
                raise ValueError("Gauge backing allowance enters an end clamp or beam edge")
        for face in ("top","bottom"):
            same_face = [row for row in gauge_rows if row["face"]==face]
            from shapely.geometry import box
            for i,row in enumerate(same_face):
                for other in same_face[i+1:]:
                    if box(*row["backing_keepout_xy_mm"]).intersection(box(*other["backing_keepout_xy_mm"])).area>1e-6:
                        raise ValueError("Gauge backing allowances overlap")
        # Removable marking stencil: no scribing or pockets in the strain beam.
        stencil = block(xl,xr,y0,y1,z1+.1,z1+.9)
        for x,y in holes:
            stencil = stencil.cut(hole_z(x,y,z1,z1+1.1,4.7))
        for row in gauge_rows:
            if row["face"]!="top":
                continue
            x,y,_ = row["center_native_mm"]
            stencil = stencil.cut(block(x-.9,x+.9,y-1.7,y+1.7,z1,z1+1.1))
        export_part(stencil,"c1_grid_alignment_stencil",OUTPUT,parts,
                    "Removable marking jig. Align active grid centers; use on both beam faces and remove before bonding.","PETG marking jig")
        # A independent receiver for the existing root interface, with recessed M6 stand attachments.
        cx = sum(x for x,_ in centers)/2;cz = centers[0][1]
        receiver = block(cx-35,cx+35,mount_y,mount_y+12,cz-35,cz+35)
        receiver = receiver.cut(extrude_xz(key_section.buffer(.25),mount_y+5.5,5.7))
        for x,z in centers:
            receiver = receiver.cut(hole_y(x,z,mount_y-.1,mount_y+12.1,m["m3_tap_drill_mm"]))
        for dx in (-25,25):
            for dz in (-25,25):
                receiver = receiver.cut(hole_y(cx+dx,cz+dz,mount_y-.1,mount_y+12.1,6.5))
                receiver = receiver.cut(hole_y(cx+dx,cz+dz,mount_y-.1,mount_y+6.5,11.5))
        export_part(receiver,"c1_bench_receiver",OUTPUT,parts,
                    "Independent bench receiver for the fixed carrier; M6 stand holes on a 50 mm square, M3 finger interface tapped.",m["material"])
        arm = extrude_xz(outline,finger_y,6).fuse(moved_key)
        for x,z in centers:
            arm = arm.cut(hole_y(x,z,finger_y-6.1,finger_y+.1,m["m3_clearance_mm"]))
        arm = arm.fuse(block(cx-12.7,cx+12.7,finger_y-120,finger_y,-2,8))
        arm = arm.fuse(block(cx-40,cx+40,finger_y-115,finger_y-100,-2,8))
        ports = []
        for distance,offsets in ((10,(0,)),(50,(-8,0,8)),(110,(-30,-8,0,8,30))):
            for offset in offsets:
                x,y = cx+offset,finger_y-distance
                arm = arm.cut(hole_z(x,y,-2.1,8.1,3.4))
                ports.append({"id":f"Y{distance}_X{offset:+d}","native_xyz_mm":[x,y,8],"force_axis_native":[0,0,1]})
        export_part(arm,"c1_bench_calibration_arm",OUTPUT,parts,
                    "Metal arm for independent normal-force and off-center calibration. Not part of the production finger.",m["material"])
        assembly_names = [name for name in shapes if name!="c1_fixed_carrier_m3_tap_drill"]
        vertices = [shifted.vertices,soft.vertices]
        for name in assembly_names:
            vertices.append(trimesh.load_mesh(OUTPUT/"cad"/f"{name}.stl",process=True).vertices)
        all_vertices = np.vstack(vertices)
        root_reference = [cx,finger_y,cz]
        contacts = json.loads((ROOT/"engineering/release/l1/contact_sites.json").read_text())["sites"]
        # L1 contacts used a -20 mm Y shift; recover the source position and apply C1's shift.
        contact_sites = []
        for item in contacts:
            point = np.asarray(item["native_xyz_mm"])+[0,20+shift,0]
            contact_sites.append({"id":item["id"],"native_xyz_mm":point.tolist(),
                                  "moment_about_root_at_20n_nmm":np.cross(point-root_reference,[0,0,20]).tolist()})
        result = {
            "revision":config["revision"],"status":"digital development; assembly and structural/force qualification pending",
            "parts":parts,"assembly_part_ids":assembly_names,"gauges":gauge_rows,"clamp_holes_native_xy_mm":holes,
            "finger_translation_native_mm":config["mount"]["finger_translation_native_mm"],
            "root_reference_native_mm":root_reference,"fixed_mount_plane_y_mm":mount_y,
            "floating_mount_plane_y_mm":finger_y,"beam_active_native_x_mm":[x0,x1],
            "beam_y_bounds_mm":[y0,y1],"beam_z_bounds_mm":[z0,z1],
            "assembly_bounds_mm":[all_vertices.min(axis=0).tolist(),all_vertices.max(axis=0).tolist()],
            "added_reach_mm":abs(shift),"added_global_width_mm":float(np.ptp(all_vertices[:,0])-original.extents[0]),
            "added_back_height_excluding_hardware_mm":float(all_vertices[:,2].max()-original.bounds[1,2]),
            "added_back_height_with_reserved_hardware_mm":float(z1+m["clamp_cap_thickness_mm"]+m["m4_washer_thickness_mm"]+m["m4_head_height_mm"]-original.bounds[1,2]),
            "floating_m3_hardware_to_fixed_plate_gap_mm":mount_y-m["fixed_root_plate_thickness_mm"]-floating_rear_y-m["m3_rear_hardware_projection_mm"],
            "rigid_overlap_checks_mm3":overlap,"bench_ports":ports,"contact_sites":contact_sites,
            "analysis_geometry":{"file":"analysis/c1_bonded_assembly.step",
                                 "sha256":digest(analysis/"c1_bonded_assembly.step"),
                                 "volume_mm3":bonded.Volume(),
                                 "assumption":"Same-metal parts bonded at intended clamp interfaces; bolt preload, friction and slip omitted"},
            "physical_specimens_tested":0,
            "limits":["CAD fit only; drive housing and actual source-finger identity remain to be checked.",
                      "Metal load-path parts required. Printed witnesses do not establish 20 N capacity.",
                      "Beam stiffness, clamped joints, gauge-area response, torsion, thermal drift and force accuracy require structural checks and measurements.",
                      "Original finger contact surfaces are retained; no local contact map or six-axis force claim."],
            "source_hashes":{name:digest(ROOT/name) for name in (
                "engineering/designs/c1.json","engineering/scripts/build_c1_parts.py","engineering/scripts/prototype_cad.py",
                "engineering/release/l1/root_interface.json","engineering/release/l1/contact_sites.json",
                "engineering/release/b1/b1_manifest.json")},
        }
        (OUTPUT/"c1_manifest.json").write_text(json.dumps(result,indent=2)+"\n")
        record["checks"] = {"parts":len(parts),"overlap_pairs":len(overlap),"gauges":len(gauge_rows),
                            "added_reach_mm":result["added_reach_mm"],"added_width_mm":result["added_global_width_mm"]}
        print(json.dumps(record["checks"],indent=2))


if __name__=="__main__":
    main()
