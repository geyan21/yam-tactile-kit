#!/usr/bin/python3
"""Develop B2 board registration, removable backing and source-matched fit checks."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT/"build/engineering/tools/mpl-cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon, Point, box
from shapely.ops import unary_union
import trimesh

from analyze_baseline_meshes import PARTS
from build_b1_parts import regional_max_x, side_outline
from prototype_cad import digest, yz_prism, x_cylinder, block, export_part, packed
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/b2"


def main():
    config = json.loads((ROOT/"engineering/designs/b2.json").read_text())
    checks = json.loads((OUTPUT/"pcb/b2_design_checks.json").read_text())
    pcb_data = json.loads((OUTPUT/"pcb/b2_main.json").read_text())
    b1 = json.loads((ROOT/"engineering/release/b1/b1_manifest.json").read_text())
    frame = trimesh.load_mesh(PARTS["hard_frame"],process=True)
    if digest(PARTS["hard_frame"]) != b1["source_hashes"]["hard"]:
        raise ValueError("Unexpected original finger frame")
    with execution(ROOT/"build/records","Build B2 removable support and check CAD clearances while preserving original B1 sensor poses") as record:
        params = config["mechanical"]
        outline = Polygon(checks["pcb_outline_yz_mm"],checks["pcb_cutouts_yz_mm"])
        plane = b1["sensor_pcb_top_x_mm"]
        pcb_back = plane+config["pcb"]["thickness_mm"]
        backing_front = pcb_back+params["seat_compliance_mm"]
        backing_outer = backing_front+params["back_thickness_mm"]
        board = yz_prism(outline,plane,config["pcb"]["thickness_mm"])
        backer = yz_prism(outline,backing_front,params["back_thickness_mm"])
        # Open recesses allow wire solder joints to exit the rear without being
        # trapped between the PCB and the backing. Every cable is strain-relieved.
        cable_windows = []
        for ref in ("J1","J2"):
            pads = [p for p in pcb_data["pads"] if p["reference"] == ref]
            y = [-p["center"][0] for p in pads]
            z = [40-p["center"][1] for p in pads]
            region = box(min(y)-1.0,min(z)-1.0,max(y)+1.0,max(z)+1.0)
            if ref == "J1":
                region = box(min(y)-1.0,min(z)-1.0,outline.bounds[2]+1,max(z)+1.0)
            else:
                region = box(min(y)-1.0,outline.bounds[1]-.5,max(y)+1.0,max(z)+1.0)
            cable_windows.append({"port":ref,"bounds_yz_mm":list(region.bounds)})
            backer = backer.cut(yz_prism(region,backing_front-.1,params["back_thickness_mm"]+.2))
        parts = []
        shapes = {"board":board,"backer":backer}
        supports = []
        for index,mount in enumerate(b1["carrier_mounts"]):
            y,z = mount["center_yz_mm"]
            board = board.cut(x_cylinder(plane-.1,config["pcb"]["thickness_mm"]+.2,y,z,params["board_bore_mm"]/2))
            backer = backer.cut(x_cylinder(backing_front-.1,params["back_thickness_mm"]+.2,y,z,params["fastener_clearance_mm"]/2))
            annulus = Point(y,z).buffer(params["spacer_outer_diameter_mm"]/2).difference(Point(y,z).buffer(1.8))
            support_x = regional_max_x(frame,annulus)
            if plane-support_x < .8:
                raise ValueError("Insufficient room for a physical B2 standoff")
            spacer = x_cylinder(support_x,plane-support_x,y,z,params["spacer_outer_diameter_mm"]/2)
            spacer = spacer.fuse(x_cylinder(plane,params["shoulder_height_mm"],y,z,params["shoulder_outside_diameter_mm"]/2))
            spacer = spacer.cut(x_cylinder(support_x-.1,plane+params["shoulder_height_mm"]-support_x+.2,
                                           y,z,params["fastener_clearance_mm"]/2))
            part_name = f"b2_locating_spacer_{index+1}"
            export_part(spacer,part_name,OUTPUT,parts,
                        "Separate spacer sits against rigid frame, registers the PCB, and preserves the original side-fastener axis.",
                        params["material"])
            shapes[part_name] = spacer
            supports.append({"part":part_name,"center_yz_mm":[y,z],"cad_support_plane_x_mm":support_x,
                             "main_length_mm":plane-support_x,"shoulder_height_mm":params["shoulder_height_mm"],
                             "shoulder_wall_mm":(params["shoulder_outside_diameter_mm"]-params["fastener_clearance_mm"])/2})
        shapes["board"],shapes["backer"] = board,backer
        export_part(backer,"b2_removable_backer",OUTPUT,parts,
                    "Removable PCB backer with cable exits. Two M3 screws clamp PCB annuli onto the separate locating spacers.",
                    params["material"])
        export_part(board,"b2_pcb_fit_reference",OUTPUT,parts,
                    "PCB outline and bores for fit review; functional PCB is made from checked Gerbers, not this plastic witness.",
                    "0.8 mm FR4 board reference","reference_only")
        solid_checks = {}
        names = list(shapes)
        for i,name in enumerate(names):
            for other in names[i+1:]:
                volume = shapes[name].intersect(shapes[other]).Volume()
                solid_checks[f"{name}_vs_{other}_overlap_mm3"] = volume
                if volume > 1e-7:
                    raise ValueError(f"B2 rigid solids overlap: {name}, {other}")
        components = []
        for part in pcb_data["components"]:
            if part["reference"].startswith("TP") or part["reference"].startswith("J"):
                continue
            cx,cy = part["center_mm"]
            width,depth = part.get("body_mm",[1,.5])
            region = box(-width/2,-depth/2,width/2,depth/2)
            region = affinity.rotate(region,-part["rotation_deg"],origin=(0,0))
            region = affinity.translate(region,cx,cy)
            native_region = affinity.affine_transform(region,[-1,0,0,-1,0,40])
            height = part["height_mm"]
            maximum_x = regional_max_x(frame,native_region)
            clearance = plane-height-maximum_x
            if clearance < .3:
                raise ValueError(f"Insufficient nominal component/frame clearance for {part['reference']}: {clearance}")
            components.append({"reference":part["reference"],"body_yz_mm":list(native_region.exterior.coords),
                              "height_mm":height,"component_to_frame_gap_mm":clearance})
        combined = side_outline(frame).union(Polygon(json.loads(
            (ROOT/"engineering/release/b1/source_interface.json").read_text())["outer_yz"]))
        silhouette = Polygon(combined.exterior.coords)
        outside = outline.difference(silhouette).area
        if outside > .15:
            raise ValueError(f"B2 PCB lies outside source side silhouette: {outside}")
        result = {
            "revision":config["revision"],"status":"digital prototype; physical build and qualification pending",
            "parts":parts,"supports":supports,"cable_windows":cable_windows,
            "pcb_component_plane_x_mm":plane,"backer_outer_x_mm":backing_outer,
            "pcb_hole_diameter_mm":params["board_bore_mm"],
            "components":components,"minimum_component_to_frame_gap_mm":min(c["component_to_frame_gap_mm"] for c in components),
            "side_outline_outside_original_mm2":outside,"rigid_solid_checks":solid_checks,
            "added_reach_mm":0,
            "added_global_width_excluding_heads_and_wires_mm":max(0,backing_outer-frame.bounds[1,0]),
            "added_global_width_with_reserved_heads_excluding_wires_mm":max(
                0,backing_outer+params["reserved_fastener_head_height_mm"]-frame.bounds[1,0]),
            "reuse":["Original ENPIRE hard frame","Released B1 TPU insert, four magnets and four plugs","R1 N0 nail pads"],
            "physical_specimens_tested":0,
            "limits":["Unloaded CAD clearance only; source identity, installed jaw housing, cable motion and loaded fit require physical checks.",
                      "Spacer seating, board thickness, printed shrinkage, clamping and retention are not yet measured.",
                      "Wire joints/cables extend behind the board and are excluded from quoted width; check the actual routed harness.",
                      "Same Hall poses do not establish equal force calibration or compliance."],
            "source_hashes":{name:digest(ROOT/name) for name in (
                "engineering/designs/b2.json","engineering/scripts/build_b2_parts.py","engineering/scripts/prototype_cad.py",
                "engineering/release/b1/b1_manifest.json","engineering/release/b1/models.json")},
            "pcb_layout_sha256":digest(OUTPUT/"pcb/b2_main.json"),
        }
        (OUTPUT/"b2_manifest.json").write_text(json.dumps(result,indent=2)+"\n")
        record["checks"] = {"parts":len(parts),"minimum_gap_mm":result["minimum_component_to_frame_gap_mm"],
                            "outline_outside_mm2":outside,"intersection_pairs":len(solid_checks)}
        print(json.dumps(record["checks"],indent=2))


if __name__ == "__main__":
    main()
