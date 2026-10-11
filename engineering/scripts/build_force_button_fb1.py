#!/usr/bin/python3
"""Build the first complete nominal FB1 mechanical load-path geometry."""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/force-button-matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/force-button-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
import numpy as np
import trimesh

from tactile_kit.records import execution
from force_button_mechanics import CONFIG, geometry
from build_c1_parts import root_key
from build_l1_parts import extrude_xz, hole_y, hole_z
from prototype_cad import block, export_part, packed
from screen_f1_feedback import digest
from export_force_button_reference import export_reference


def nut(cx, cy, z, across_flats, height, bore):
    radius = across_flats/math.sqrt(3)
    points = [(cx+radius*math.cos(math.pi*i/3), cy+radius*math.sin(math.pi*i/3)) for i in range(6)]
    return cq.Workplane("XY", origin=(0, 0, z)).polyline(points).close().extrude(height).val().cut(
        hole_z(cx, cy, z-.1, z+height+.1, bore))


def main():
    cfg = json.loads(CONFIG.read_text())
    m, sensor = cfg["mechanism"], cfg["sensor"]
    electronics_path = ROOT / "engineering/designs/force_button_electronics.json"
    electronics = json.loads(electronics_path.read_text())
    interface_path = ROOT / cfg["basis"]["root_interface"]
    interface = json.loads(interface_path.read_text())
    source_path = ROOT / cfg["basis"]["hard_frame"]
    original = trimesh.load_mesh(source_path, process=True)
    outline, key_section, key = root_key(original, interface)
    g = geometry(cfg)
    cx, cy, cz = g["reference_native_mm"]
    root_y = g["root_plane_y"]
    fixed_front = root_y-m["root_plate_thickness_mm"]
    fixed_end, moving_end = g["fixed_guide_boundary_y"], g["moving_guide_boundary_y"]
    clamp = m["guide_clamp_length_mm"]
    leaf_half = m["guide_width_mm"]/2
    clamp_half = leaf_half+1
    beam_half = m["sensor_support_width_mm"]/2
    finger_y = root_y+m["finger_translation_native_mm"][1]
    finger_back = finger_y+m["root_plate_thickness_mm"]
    if abs(finger_back-(moving_end-clamp)) > 1e-8:
        raise ValueError("Floating carrier and guide clamp do not meet")
    beam_fixed_y = cy+m["sensor_support_active_length_mm"]+m["sensor_load_overhang_mm"]
    beam_end_y = cy+m["sensor_load_overhang_mm"]
    beam_top = m["sensor_support_top_z_mm"]
    beam_bottom = beam_top-m["sensor_support_thickness_mm"]
    carrier_bottom = beam_top-m["sensor_support_end_block_thickness_mm"]
    pcb_back = carrier_bottom-m["sensor_board_insulation_mm"]
    pcb_bottom = pcb_back-m["sensor_board_thickness_mm"]
    package_plane = pcb_bottom-m["sensor_solder_standoff_mm"]
    contact_z = package_plane-m["sensor_nominal_overall_height_mm"]
    folder = ROOT / "build/engineering/prototypes/force_button/cad_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Generate FB1 metal carriers, four-leaf guide, compliant sensor support, plunger and overload-stop references; no physical strength or force qualification claimed") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = [CONFIG, electronics_path, Path(__file__), interface_path, ROOT / "engineering/scripts/force_button_mechanics.py",
                  ROOT / "engineering/scripts/build_c1_parts.py", ROOT / "engineering/scripts/build_l1_parts.py",
                  ROOT / "engineering/scripts/prototype_cad.py", ROOT / "engineering/scripts/export_force_button_reference.py"]
        for source in inputs:
            destination = folder / "inputs" / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        parts, models, hardware, clamp_holes = [], [], [], []
        record["parts"] = parts
        fixed = extrude_xz(outline, root_y, m["root_plate_thickness_mm"]).fuse(key)
        floating = extrude_xz(outline, finger_back, m["root_plate_thickness_mm"])
        floating = floating.cut(extrude_xz(key_section.buffer(m["root_key_clearance_mm"]),
                                           finger_back+.1, m["root_plate_thickness_mm"]+.2))
        lower_z, upper_z = [cz+z for z in m["guide_z_offsets_mm"]]
        for dx in m["guide_x_offsets_mm"]:
            x = cx+dx
            for z in (lower_z, upper_z):
                fixed = fixed.fuse(block(x-clamp_half, x+clamp_half, fixed_end, fixed_front+.1, z-4, z))
                floating = floating.fuse(block(x-clamp_half, x+clamp_half, finger_back-.1, moving_end, z-4, z))
                for end_name, y in (("fixed", fixed_end+clamp/2), ("floating", moving_end-clamp/2)):
                    y += m["moving_leaf_hole_shift_y_mm"] if end_name == "floating" else 0
                    for ox in m["leaf_clamp_screw_x_offsets_mm"]:
                        clamp_holes.append({"end": end_name, "x": x+ox, "y": y, "blade_z": z})
            fixed = fixed.fuse(block(x-clamp_half, x+clamp_half,
                                    fixed_end+clamp+m["clamp_end_clearance_mm"], fixed_front+.1,
                                    lower_z-4, upper_z))
            # The source key ends 1 mm ahead of the carrier back. Keep this
            # rear web inside that unused interval, behind the key and ahead
            # of the leaf/clamp seating surfaces.
            floating = floating.fuse(block(x-clamp_half, x+clamp_half,
                                          finger_back-.8, finger_back, lower_z-4, upper_z))
        # A fixed, independent path carries overload-stop reactions.
        left, right = cx-22, cx+22
        fixed = fixed.fuse(block(left, right, fixed_front-2, fixed_front+2, 14, 22))
        for x0, x1 in ((left, left+4), (right-4, right)):
            fixed = fixed.fuse(block(x0, x1, cy-8, fixed_front+2, 14, 22))
        fixed = fixed.fuse(block(left, right, cy-8, cy+8,
                                m["fixed_stop_bottom_z_mm"], m["fixed_stop_top_z_mm"]))
        fixed = fixed.cut(hole_z(cx, cy, m["fixed_stop_bottom_z_mm"]-.1,
                                 m["fixed_stop_top_z_mm"]+.1, m["fixed_stop_center_bore_mm"]))
        # Recess the fixed stop-frame top around both bypass capacitors.
        # The underside remains intact for the independent overload stops.
        fixed = fixed.cut(block(cx-5.2, cx-2.35, cy-3, cy+2,
                                pcb_bottom-m["capacitor_max_body_mm"][2]-.3,
                                m["fixed_stop_top_z_mm"]+.1))
        # Back-side support of the complete PCB, with an open sensor vent.
        fixed = fixed.fuse(block(cx-7, cx+7, beam_fixed_y, root_y, beam_bottom-6, beam_bottom))
        floating = floating.fuse(block(cx-6, cx+6, finger_back-.1, cy+7, 0, m["moving_tongue_top_z_mm"]))
        floating = floating.fuse(block(cx-18, cx+18, finger_back-.1, finger_back+4, -3, 1))
        floating = floating.fuse(block(cx-10, cx+10, cy-9, cy+9,
                                      m["moving_tongue_top_z_mm"]-2, m["moving_tongue_top_z_mm"]))
        floating = floating.cut(hole_z(cx, cy, -4, m["moving_tongue_top_z_mm"]+.1, 3.3))
        stop_points = [(cx+m["stop_radius_mm"]*math.cos(math.radians(a)),
                        cy+m["stop_radius_mm"]*math.sin(math.radians(a))) for a in m["stop_angles_deg"]]
        for x, y in stop_points:
            floating = floating.cut(hole_z(x, y, -4, m["moving_tongue_top_z_mm"]+.1, 2.5))
            floating = floating.cut(hole_z(x, y, -4, m["moving_tongue_top_z_mm"]-2, 6.8))
        for x, z in interface["bolt_centers_native_xz_mm"]:
            fixed = fixed.cut(hole_y(x, z, fixed_front-1, root_y+1, m["m3_root_clearance_mm"]))
            sink_h = (6.3-m["m3_root_clearance_mm"])/2
            fixed = fixed.cut(cq.Solid.makeCone(3.15, m["m3_root_clearance_mm"]/2, sink_h,
                                                cq.Vector(x, fixed_front, z), cq.Vector(0, 1, 0)))
            # Fixed mount is tightened before installing the floating carriage.
            fixed = fixed.cut(hole_y(x, z, cy-9, fixed_front+.01, 7.0))
            floating = floating.cut(hole_y(x, z, finger_y-1, finger_back+4.6, m["m3_root_clearance_mm"]))
            floating = floating.cut(hole_y(x, z, finger_back, finger_back+4.6, 7.0))
        for h in clamp_holes:
            bore = hole_z(h["x"], h["y"], h["blade_z"]-4.1, h["blade_z"]+.1, m["m2_tap_drill_mm"])
            if h["end"] == "fixed":
                fixed = fixed.cut(bore)
            else:
                floating = floating.cut(bore)
        beam_root_end = root_y-m["sensor_clamp_to_mount_plane_clearance_mm"]
        fixed = fixed.cut(block(cx-6.65, cx+6.65, beam_fixed_y-.1, root_y-.1,
                                beam_bottom, beam_top+7))
        beam = block(cx-beam_half, cx+beam_half, beam_end_y, beam_root_end, beam_bottom, beam_top)
        beam = beam.fuse(block(cx-7, cx+7, cy-7, cy+7, carrier_bottom, beam_top))
        beam = beam.cut(hole_z(cx, cy, carrier_bottom-.1, beam_top+.1, m["sensor_carrier_vent_mm"]))
        beam_cap = block(cx-6.5, cx+6.5, beam_fixed_y, beam_root_end, beam_top, beam_top+3)
        beam_mounts = [(cx-3, (beam_fixed_y+root_y)/2), (cx+3, (beam_fixed_y+root_y)/2)]
        for x, y in beam_mounts:
            beam = beam.cut(hole_z(x, y, beam_bottom-.1, beam_top+.1, 3.4))
            beam_cap = beam_cap.cut(hole_z(x, y, beam_top-.1, beam_top+3.1, 3.4))
            fixed = fixed.cut(hole_z(x, y, beam_bottom-6.1, beam_bottom+.1, 2.5))
            shaft = cq.Solid.makeCylinder(1.5, 10, cq.Vector(x, y, beam_top+3), cq.Vector(0, 0, -1))
            head = cq.Solid.makeCylinder(2.75, 3, cq.Vector(x, y, beam_top+3))
            hardware.append((f"fb1_beam_clamp_screw_{len(hardware)}", shaft.fuse(head), "M3×10 sensor-support clamp screw reference"))
        pcb_x0, pcb_y0, pcb_x1, pcb_y1 = m["sensor_board_bounds_about_force_axis_mm"]
        pcb_shape = block(cx+pcb_x0, cx+pcb_x1, cy+pcb_y0, cy+pcb_y1, pcb_bottom, pcb_back)
        insulation = block(cx-7, cx+7, cy-7, cy+7, pcb_back, carrier_bottom)
        pcb_shape = pcb_shape.cut(hole_z(cx, cy, pcb_bottom-.1, pcb_back+.1, m["sensor_pcb_vent_mm"]))
        insulation = insulation.cut(hole_z(cx, cy, pcb_back-.1, carrier_bottom+.1, m["sensor_carrier_vent_mm"]))
        pcb_index = 0
        for dx, dy in m["sensor_board_mount_offsets_mm"]:
            x, y = cx+dx, cy+dy
            pcb_shape = pcb_shape.cut(hole_z(x, y, pcb_bottom-.1, pcb_back+.1, 2.2))
            insulation = insulation.cut(hole_z(x, y, pcb_back-.1, carrier_bottom+.1, 2.4))
            beam = beam.cut(hole_z(x, y, carrier_bottom-.1, beam_top+.1, 1.6))
            fixed = fixed.cut(hole_z(x, y, pcb_bottom-2.5,
                                     m["fixed_stop_top_z_mm"]+.1, 4.8))
            shaft = cq.Solid.makeCylinder(1., 6, cq.Vector(x, y, pcb_bottom), cq.Vector(0, 0, 1))
            head = cq.Solid.makeCylinder(1.9, 2, cq.Vector(x, y, pcb_bottom), cq.Vector(0, 0, -1))
            hardware.append((f"fb1_pcb_screw_{pcb_index}", shaft.fuse(head), "PCB M2×6 screw reference; unmodeled threads"))
            pcb_index += 1
        def output(shape, name, purpose, material, group, kind="fabricate", color="#67929d"):
            exporter = export_reference if name == "fb1_fma25_envelope" else export_part
            mesh = exporter(shape, name, folder, parts, purpose, material, kind)
            models.append(packed(mesh, name, group, color))
        output(fixed, "fb1_fixed_carrier", "Fixed root carrier, guide anchors, independent stop frame and sensor-beam anchor",
               "6061-T6 aluminum; tap designated holes after machining", "fixed")
        output(floating, "fb1_floating_carrier", "Original-finger carrier, guide anchors, plunger tongue and adjustable-stop supports",
               "6061-T6 aluminum; tap M3/M4 threads as documented", "floating")
        output(beam, "fb1_sensor_backing_beam", "Compliant backing beam and fully supported sensor-PCB seat with open vent",
               m["sensor_support_material"], "support")
        output(beam_cap, "fb1_sensor_backing_clamp", "Clamp for the sensor-support beam root",
               "6061-T6 aluminum", "support")
        output(pcb_shape, "fb1_sensor_pcb_reference", "Sensor PCB mechanical reference, not fabrication artwork",
               "1 mm FR4 reference; electrical design remains separate", "pcb", "reference_only", "#95b38e")
        output(insulation, "fb1_pcb_insulating_film", "Flat 50 µm polyimide film between supported PCB back and metal; keep vent and mounting holes open",
               "Polyimide film, 0.05 mm; no adhesive or folds under the sensor", "insulation", color="#d3b76c")
        for component in electronics["parts"]:
            if not component["reference"].startswith("C"):
                continue
            x, y = np.array(component["center_mm"])-electronics["force_axis_xy_mm"]+[cx, cy]
            width, length, height = m["capacitor_max_body_mm"]
            envelope = block(x-width/2, x+width/2, y-length/2, y+length/2, pcb_bottom-height, pcb_bottom)
            output(envelope, "fb1_"+component["reference"].lower()+"_body_reference",
                   "Maximum selected 0603 capacitor body; verify purchased component envelope",
                   component["value"], "pcb_components", "reference_only", "#997455")
        for index, (z, dx) in enumerate((z, dx) for z in (lower_z, upper_z) for dx in m["guide_x_offsets_mm"]):
            x = cx+dx
            leaf = block(x-leaf_half, x+leaf_half, moving_end-clamp, fixed_end+clamp, z, z+m["guide_thickness_mm"])
            for end_index, y in enumerate((moving_end-clamp/2, fixed_end+clamp/2)):
                cap = block(x-5, x+5, y-clamp/2, y+clamp/2,
                            z+m["guide_thickness_mm"], z+m["guide_thickness_mm"]+m["leaf_clamp_cap_thickness_mm"])
                for ox in m["leaf_clamp_screw_x_offsets_mm"]:
                    hole_y_center = y+(m["moving_leaf_hole_shift_y_mm"] if end_index == 0 else 0)
                    leaf = leaf.cut(hole_z(x+ox, hole_y_center, z-.1, z+m["guide_thickness_mm"]+.1, m["m2_clearance_mm"]))
                    cap = cap.cut(hole_z(x+ox, hole_y_center, z, z+3, m["m2_clearance_mm"]))
                    seat = z+m["guide_thickness_mm"]+m["leaf_clamp_cap_thickness_mm"]
                    shaft = cq.Solid.makeCylinder(1., 6, cq.Vector(x+ox, hole_y_center, seat), cq.Vector(0, 0, -1))
                    head = cq.Solid.makeCylinder(1.9, 2, cq.Vector(x+ox, hole_y_center, seat), cq.Vector(0, 0, 1))
                    hardware.append((f"fb1_leaf_screw_{index}_{end_index}_{ox:g}", shaft.fuse(head), "M2×6 clamp screw reference"))
                output(cap, f"fb1_leaf_clamp_{index}_{end_index}", "Metal leaf clamp; assembled on the specified deck",
                       "6061-T6 aluminum", "clamps", color="#9ab1b8")
            output(leaf, f"fb1_guide_leaf_{index}", "Flat spring strip, active span between two clamped ends",
                   m["guide_material"], "leaves", color="#c69b4e")
        body_center_x = cx-sensor["sphere_offset_from_package_center_mm"][0]
        body = block(body_center_x-2.5, body_center_x+2.5, cy-2.5, cy+2.5,
                     package_plane-sensor["body_height_excluding_sphere_mm"], package_plane)
        body = body.cut(hole_z(cx, cy, package_plane-.6, package_plane+.01, .35))
        # CadQuery defaults to the upper hemisphere. This package faces -Z,
        # so explicitly include both halves of the sphere.
        ball = cq.Solid.makeSphere(.79375, cq.Vector(cx, cy, package_plane-1.83875),
                                   angleDegrees1=-90, angleDegrees2=90)
        sensor_shape = body.fuse(ball)
        if abs(sensor_shape.BoundingBox().zmin-contact_z) > 1e-8:
            raise ValueError("FMA sphere contact height is missing or incorrect")
        output(sensor_shape, "fb1_fma25_envelope", "Own conservative package/sphere envelope based on manufacturer dimensions; not the vendor CAD",
               "Purchased FMAMSDXX025WC2C3 reference", "sensor", "reference_only", "#df8052")
        plunger = cq.Solid.makeCylinder(2, contact_z-.8+5, cq.Vector(cx, cy, -5))
        plunger = plunger.fuse(cq.Solid.makeCylinder(m["plunger_contact_diameter_mm"]/2, .8, cq.Vector(cx, cy, contact_z-.8)))
        plunger = plunger.cut(block(cx-.5, cx+.5, cy-2.1, cy+2.1, -5.1, -3.5))
        output(plunger, "fb1_adjustable_plunger_reference", "M4×0.7 adjustable plunger with flat 5 mm contact face and 1 mm wide × 1.5 mm deep bottom drive slot; helical threads not modeled",
               m["plunger_contact_material"], "plunger", "hardware_reference", "#b7b9b6")
        output(nut(cx, cy, -2.2, 7, 2.2, 4.1), "fb1_plunger_locknut_reference",
               "M4 thin locknut below the floating tongue", "Steel; reference only", "hardware", "hardware_reference")
        for index, (x, y) in enumerate(stop_points):
            top = m["fixed_stop_bottom_z_mm"]-m["overload_gap_mm_target"]
            stop = cq.Solid.makeCylinder(1.5, 7.6, cq.Vector(x, y, top-8))
            stop = stop.fuse(cq.Solid.makeCylinder(m["stop_tip_diameter_mm"]/2, .4, cq.Vector(x, y, top-.4)))
            output(stop, f"fb1_stop_screw_{index}_reference", "Inverted M3×8 flat-point stop; establish gap by measurement",
                   "Hardened steel; thread/socket details omitted", "stops", "hardware_reference", "#bd8c68")
            output(nut(x, y, m["moving_tongue_top_z_mm"]-4.4, 5.5, 2.4, 3.1),
                   f"fb1_stop_locknut_{index}_reference", "M3 thin locknut below the upper flange",
                   "Steel; reference only", "hardware", "hardware_reference")
        for name, shape, purpose in hardware:
            output(shape, name, purpose, "Steel hardware reference; actual part dimensions must be checked", "hardware", "hardware_reference")
        # Explicit fixed-side screws for the common bench receiver. Installed
        # jaw screw length still depends on the real jaw's thread depth.
        for index, (x, z) in enumerate(interface["bolt_centers_native_xz_mm"]):
            head_start = fixed_front+.15
            head = cq.Solid.makeCone(3, 1.5, 1.5, cq.Vector(x, head_start, z), cq.Vector(0, 1, 0))
            shaft = cq.Solid.makeCylinder(1.5, 10.5, cq.Vector(x, head_start+1.5, z), cq.Vector(0, 1, 0))
            output(head.fuse(shaft), f"fb1_fixed_root_m3x12_{index}_reference",
                   "M3×12 countersunk reference for the independent bench receiver; installed-drive length remains conditional",
                   "Steel hardware reference", "root_hardware", "hardware_reference")
            rear_nut = nut(x, z, 0, 5.5, 2.4, 3.1).rotate((0, 0, 0), (1, 0, 0), -90).translate((0, finger_back+.5, 2*z))
            # The transformed hexagon uses its second sketch coordinate as
            # native Z; reflect that sign once by the explicit final shift.
            washer = hole_y(x, z, finger_back, finger_back+.5, 7).cut(
                hole_y(x, z, finger_back-.1, finger_back+.6, 3.2))
            output(washer.fuse(rear_nut), f"fb1_finger_m3_retention_{index}_reference",
                   "Rear M3 washer and nut envelope; retain a compatible original-finger head and choose the measured through-bolt length",
                   "Steel hardware reference", "root_hardware", "hardware_reference")
        # Reuse the common root receiver as a separate bench fixture.
        receiver_path = ROOT / "engineering/prototypes/c1/cad/c1_bench_receiver.step"
        receiver = cq.importers.importStep(str(receiver_path)).val()
        output(receiver, "fb1_bench_receiver", "Common ENPIRE root bench receiver; M3 tapped interface and 50 mm square M6 stand pattern",
               "6061-T6 aluminum; tap M3 pilot bores", "bench_fixture")
        inputs.append(receiver_path)
        receiver_input = folder / "inputs" / receiver_path.relative_to(ROOT)
        receiver_input.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(receiver_path, receiver_input)
        report = {"schema": "yam-fb1-cad/1", "physical_specimens_tested": 0, "integrated_prototype_complete": False,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "parts": parts, "geometry": {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in g.items()},
                  "finger_translation_native_mm": m["finger_translation_native_mm"],
                  "sensor_contact_native_mm": [cx, cy, contact_z],
                  "sensor_package_plane_z_mm": package_plane, "pcb_component_face_z_mm": pcb_bottom,
                  "pcb_back_face_z_mm": pcb_back, "insulation_top_z_mm": carrier_bottom,
                  "stop_points_xy_mm": stop_points, "leaf_clamp_holes": clamp_holes,
                  "beam_clamp_xy_mm": beam_mounts,
                  "limits": ["Nominal just-contact geometry; actual preload is not represented by rigid interpenetration.",
                             "Threaded engagements and selected fastener references need separate mating/clearance checks.",
                             "The source finger, moving clearances, vent path, loaded frame stiffness and stops remain to be checked.",
                             "Printed force-path parts are fit witnesses only; metal fabrication and physical qualification remain."]}
        (folder / "manifest.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts),
                            "sensor_contact_native_mm": [cx, cy, contact_z], "physical_specimens_tested": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
