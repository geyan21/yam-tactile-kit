#!/usr/bin/python3
"""Check FB1 nominal assembly, free spans, contact face and open vent geometry."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/force-button-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
import numpy as np

from tactile_kit.records import execution
from force_button_mechanics import CONFIG
from source_brep import load as source_solid
from analyze_b1_interfaces import original_profile, extruded_profile
from check_f1_tail_fit import check_pair
from prototype_cad import block
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cad_run", type=Path)
    args = parser.parse_args()
    source = args.cad_run.resolve()
    if not source.is_relative_to(ROOT / "build"):
        parser.error("Use a generated FB1 CAD run")
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest["input_sha256"].get(str(CONFIG.relative_to(ROOT))) != digest(CONFIG):
        raise ValueError("The current configuration differs from the CAD run")
    cfg = json.loads(CONFIG.read_text())
    m = cfg["mechanism"]
    shapes = {}
    for part in manifest["parts"]:
        path = source / part["step"]
        if digest(path) != part["sha256_step"]:
            raise ValueError("CAD part changed")
        shapes[part["id"]] = cq.importers.importStep(str(path)).val()
    folder = ROOT / "build/engineering/prototypes/force_button/fit_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check FB1 solid clearances, explicit threaded mating exceptions, free guide spans, sensor contact and vent path against the retained finger geometry") as record:
        folder.mkdir(parents=True, exist_ok=False)
        checks = []
        record["checks"] = checks
        fabrication = [p["id"] for p in manifest["parts"] if p["kind"] == "fabricate"]
        for index, first in enumerate(fabrication):
            for second in fabrication[index+1:]:
                checks.append(check_pair(first, shapes[first], second, shapes[second]))
            print(f"Checked rigid part {first}", flush=True)
        hard, hard_receipt = source_solid("hard_frame")
        soft_mesh, profile, _ = original_profile()
        soft = extruded_profile(profile)
        if abs(soft.Volume()-soft_mesh.volume) > soft_mesh.volume*1e-5:
            raise ValueError("TPU solid differs from source")
        shift = tuple(m["finger_translation_native_mm"])
        hard, soft = hard.translate(shift), soft.translate(shift)
        for name in fabrication:
            for other, shape in (("shifted_source_hard", hard), ("shifted_source_TPU", soft)):
                checks.append(check_pair(name, shapes[name], other, shape))
        static = ["fb1_fixed_carrier", "fb1_floating_carrier", "fb1_sensor_backing_beam", "fb1_sensor_backing_clamp",
                 "fb1_sensor_pcb_reference", "fb1_fma25_envelope", "fb1_c1_body_reference", "fb1_c2_body_reference",
                 "fb1_pcb_insulating_film"]
        for first in ("fb1_sensor_pcb_reference", "fb1_fma25_envelope", "fb1_adjustable_plunger_reference",
                      "fb1_c1_body_reference", "fb1_c2_body_reference"):
            for second in static:
                if first == second or first == "fb1_adjustable_plunger_reference" and second == "fb1_floating_carrier":
                    continue
                checks.append(check_pair(first, shapes[first], second, shapes[second]))
        # Remove only the declared threaded shaft portion from hardware checks.
        hardware_checks = []
        for part in manifest["parts"]:
            name = part["id"]
            if part["kind"] != "hardware_reference":
                continue
            shape = shapes[name]
            mates = {}
            if name.startswith("fb1_leaf_screw_"):
                index, end, ox = name.removeprefix("fb1_leaf_screw_").split("_")
                index, end, ox = int(index), int(end), float(ox)
                center = manifest["geometry"]["reference_native_mm"]
                z = center[2]+m["guide_z_offsets_mm"][index//2]
                x = center[0]+m["guide_x_offsets_mm"][index%2]+ox
                y = (manifest["geometry"]["moving_guide_boundary_y"]-m["guide_clamp_length_mm"]/2 if end == 0 else
                     manifest["geometry"]["fixed_guide_boundary_y"]+m["guide_clamp_length_mm"]/2)
                y += m["moving_leaf_hole_shift_y_mm"] if end == 0 else 0
                mate = "fb1_floating_carrier" if end == 0 else "fb1_fixed_carrier"
                mates[mate] = cq.Solid.makeCylinder(1.01, 4.1, cq.Vector(x, y, z-4.05))
            elif name.startswith("fb1_pcb_screw_"):
                index = int(name.removeprefix("fb1_pcb_screw_"))
                cx, cy, _ = manifest["geometry"]["reference_native_mm"]
                dx, dy = m["sensor_board_mount_offsets_mm"][index]
                bottom = manifest["pcb_component_face_z_mm"]+m["sensor_board_thickness_mm"]
                mates["fb1_sensor_backing_beam"] = cq.Solid.makeCylinder(1.01, 6.1, cq.Vector(cx+dx, cy+dy, bottom-.05))
            elif name.startswith("fb1_beam_clamp_screw_"):
                index = int(name.removeprefix("fb1_beam_clamp_screw_"))
                x, y = manifest["beam_clamp_xy_mm"][index]
                bottom = m["sensor_support_top_z_mm"]-m["sensor_support_thickness_mm"]
                mates["fb1_fixed_carrier"] = cq.Solid.makeCylinder(1.51, 6.1, cq.Vector(x, y, bottom-6.05))
            elif name.startswith("fb1_fixed_root_m3x12_"):
                index = int(name.removeprefix("fb1_fixed_root_m3x12_").split("_")[0])
                interface = json.loads((ROOT / cfg["basis"]["root_interface"]).read_text())
                x, z = interface["bolt_centers_native_xz_mm"][index]
                root_y = manifest["geometry"]["root_plane_y"]
                mates["fb1_bench_receiver"] = cq.Solid.makeCylinder(1.51, 6.3, cq.Vector(x, root_y-.05, z), cq.Vector(0, 1, 0))
            elif name == "fb1_adjustable_plunger_reference":
                cx, cy, _ = manifest["geometry"]["reference_native_mm"]
                mates["fb1_floating_carrier"] = cq.Solid.makeCylinder(2.01, m["moving_tongue_top_z_mm"]+4.1, cq.Vector(cx, cy, -4.05))
            elif name.startswith("fb1_stop_screw_"):
                index = int(name.split("_")[3])
                x, y = manifest["stop_points_xy_mm"][index]
                mates["fb1_floating_carrier"] = cq.Solid.makeCylinder(1.51, 2.1, cq.Vector(x, y, m["moving_tongue_top_z_mm"]-2.05))
            for other in dict.fromkeys(static+fabrication):
                if other == name:
                    continue
                screened = shape.cut(mates[other]) if other in mates else shape
                result = check_pair(name, screened, other, shapes[other])
                if other in mates:
                    result["mating_scope"] = "Only the specified threaded shaft segment excluded; actual thread strength is unqualified"
                hardware_checks.append(result)
        checks.extend(hardware_checks)
        hardware_ids = [p["id"] for p in manifest["parts"] if p["kind"] == "hardware_reference"]
        for index, first in enumerate(hardware_ids):
            for second in hardware_ids[index+1:]:
                checks.append(check_pair(first, shapes[first], second, shapes[second]))
        for part in manifest["parts"]:
            if part["kind"] == "fabricate":
                continue
            for other, shape in (("shifted_source_hard", hard), ("shifted_source_TPU", soft)):
                checks.append(check_pair(part["id"], shapes[part["id"]], other, shape))
        center = np.asarray(manifest["geometry"]["reference_native_mm"])
        spans = []
        for index, (zoff, xoff) in enumerate((z, x) for z in m["guide_z_offsets_mm"] for x in m["guide_x_offsets_mm"]):
            x, z = center[0]+xoff, center[2]+zoff
            keepout = block(x-m["guide_width_mm"]/2-.05, x+m["guide_width_mm"]/2+.05,
                           manifest["geometry"]["moving_guide_boundary_y"]+.05,
                           manifest["geometry"]["fixed_guide_boundary_y"]-.05,
                           z-.1, z+m["guide_thickness_mm"]+.1)
            for name in ("fb1_fixed_carrier", "fb1_floating_carrier", "fb1_sensor_backing_beam"):
                spans.append(check_pair("free_span_"+str(index), keepout, name, shapes[name]))
        checks.extend(spans)
        fixed = shapes["fb1_fixed_carrier"]
        stop_faces = []
        for index, (x, y) in enumerate(manifest["stop_points_xy_mm"]):
            probe = cq.Solid.makeCylinder(m["stop_tip_diameter_mm"]/2, .05,
                                         cq.Vector(x, y, m["fixed_stop_bottom_z_mm"]))
            intersection = probe.intersect(fixed)
            volume = 0 if intersection.wrapped.IsNull() else intersection.Volume()
            fraction = volume/probe.Volume()
            stop_faces.append({"stop": index, "supported_tip_area_fraction": fraction,
                               "passed": fraction > .999})
        vent = cq.Solid.makeCylinder(.15, m["sensor_support_top_z_mm"]-manifest["pcb_component_face_z_mm"]+.1,
                                    cq.Vector(center[0], center[1], manifest["pcb_component_face_z_mm"]-.01))
        vents = [check_pair("clear_vent_path", vent, name, shapes[name])
                  for name in ("fb1_sensor_pcb_reference", "fb1_sensor_backing_beam")]
        contact_distance = shapes["fb1_adjustable_plunger_reference"].distance(shapes["fb1_fma25_envelope"])
        contact = {"purpose": "The unloaded flat plunger must touch the sensor sphere in the nominal just-contact CAD",
                   "distance_mm": contact_distance,
                   "sensor_lowest_z_mm": shapes["fb1_fma25_envelope"].BoundingBox().zmin,
                   "expected_contact_z_mm": manifest["sensor_contact_native_mm"][2],
                   "passed": contact_distance < 1e-6 and abs(shapes["fb1_fma25_envelope"].BoundingBox().zmin-
                                                           manifest["sensor_contact_native_mm"][2]) < 1e-6}
        failures = [p for p in checks+stop_faces+vents+[contact] if not p["passed"]]
        report = {"schema": "yam-fb1-fit/1", "physical_specimens_tested": 0,
                  "source_manifest_sha256": digest(manifest_path), "hard_source_conversion": hard_receipt,
                  "checks": checks, "stop_faces": stop_faces, "vent_checks": vents,
                  "sensor_contact": contact,
                  "passed_declared_checks": not failures, "failures": failures,
                  "limits": ["These are rigid nominal checks; loaded motion, preload setting, stop deflection, clamp slip and physical performance remain.",
                             "Thread and contact exceptions do not establish fastener strength or an operating force rating.",
                             "The installed YAM drive/housing has not been identified or qualified."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "checks": len(checks)+len(stop_faces)+len(vents)+1,
                            "failures": failures, "passed_declared_checks": not failures}
        print(json.dumps(record["result"], indent=2))
        if failures:
            raise ValueError("FB1 geometry has unresolved fit findings")


if __name__ == "__main__":
    main()
