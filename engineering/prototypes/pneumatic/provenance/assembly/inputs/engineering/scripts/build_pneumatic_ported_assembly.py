#!/usr/bin/python3
"""Combine checked P1 fitting poses, seals and air paths into one nominal assembly."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/pneumatic-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import cadquery as cq
import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from tactile_kit.records import execution
from prototype_cad import export_part, packed, yz_prism, block
from source_brep import load as source_solid
from build_pneumatic_insert_witness import common_volume
from screen_f1_feedback import digest

PORTS = ROOT/"engineering/designs/pneumatic_ports.json"
SLIM = ROOT/"engineering/designs/pneumatic_slim_port.json"
HOSE = ROOT/"engineering/designs/pneumatic_port_search.json"


def cyl(radius, length, origin, axis):
    return cq.Solid.makeCylinder(radius, length, cq.Vector(*origin), cq.Vector(*axis))


def volume(shape):
    return 0. if shape.wrapped.IsNull() else abs(shape.Volume())


def overlap(a, b):
    aa, bb = a.BoundingBox(), b.BoundingBox()
    if any(max(getattr(aa, axis+"min"), getattr(bb, axis+"min")) >
           min(getattr(aa, axis+"max"), getattr(bb, axis+"max")) for axis in "xyz"):
        return 0.
    return common_volume(a, b)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("layout", "poses", "slim"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ("layout", "poses", "slim")}
    if not all(path.is_relative_to(ROOT/"build") for path in paths.values()):
        parser.error("Use this checkout's generated inputs")
    reports = {name: json.loads((path/"report.json").read_text()) for name, path in paths.items()}
    for report in reports.values():
        for name, expected in report["input_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError("P1 assembly input changed: "+name)
    for name in ("poses", "slim"):
        key = str((paths["layout"]/"report.json").relative_to(ROOT))
        if reports[name]["input_sha256"].get(key) != digest(paths["layout"]/"report.json"):
            raise ValueError("P1 port inputs belong to different channel layouts")
    cfg, slim, hose_cfg = (json.loads(path.read_text()) for path in (PORTS, SLIM, HOSE))
    plan = reports["layout"]
    channel_entries = {case[role]["id"]: {**case[role], "site": case["site"], "role": role}
                       for case in plan["cases"] for role in ("front", "back")}
    slim_id = f"p1_ch{slim['site']}_{slim['role']}"
    if reports["poses"]["failed_ports"] != [slim_id]:
        raise ValueError("Unexpected unresolved port set")
    slim_cases = [case for case in reports["slim"]["cases"] if case["passed"]]
    if not slim_cases:
        raise ValueError("No passing guarded slim-port pose")
    chosen = next((case for case in slim_cases if case["sign"] == cfg["preferred_exit_sign"]), slim_cases[0])
    pose_by_id = {pose["id"]: pose for pose in reports["poses"]["poses"]}
    pose_by_id[slim_id] = {"id": slim_id, "kind": "embedded_slim", "sign": chosen["sign"],
                          "plug_faces_x_mm": [0. if chosen["sign"] < 0 else -15.]}
    if set(pose_by_id) != set(channel_entries):
        raise ValueError("Each of eight channels needs exactly one checked port")
    radius = plan["channel_diameter_mm"]/2
    disks = {name: Point(entry["center_native_mm"][1:]).buffer(radius, quad_segs=64)
             for name, entry in channel_entries.items()}
    cut_profile = Polygon(plan["modified_profile"]["outer"], plan["modified_profile"]["holes"])
    support_profile = unary_union([cut_profile, *disks.values()])
    body = yz_prism(support_profile, -15., 15.)
    hard, hard_receipt = source_solid("hard_frame")
    folder = ROOT/"build/engineering/prototypes/pneumatic/ported_assemblies"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Build the P1 ported insert from checked poses and dimensional seals; verify source/material overlaps and test nominal isolated air volumes with temporary outlet caps") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [PORTS, SLIM, HOSE, Path(__file__), ROOT/"engineering/scripts/prototype_cad.py",
                  ROOT/"engineering/scripts/source_brep.py", ROOT/"engineering/scripts/build_pneumatic_insert_witness.py",
                  *[path/"report.json" for path in paths.values()]]
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        holders, body_cuts, components, gases, caps, cases, hose_guards = [], [], [], [], [], [], []
        for name in sorted(channel_entries):
            entry, pose = channel_entries[name], pose_by_id[name]
            _, y, z = entry["center_native_mm"]
            main_air = yz_prism(disks[name], -15., 15.)
            body_cuts.append(main_air)
            component_set = []
            for face in pose["plug_faces_x_mm"]:
                axis = np.array([1., 0, 0]) if face < -1 else np.array([-1., 0, 0])
                plug = cyl(cfg["plug_diameter_mm"]/2, cfg["plug_length_mm"], [face, y, z], axis)
                whole = yz_prism(disks[name], face if face < -1 else face-cfg["plug_length_mm"], cfg["plug_length_mm"])
                bond = whole.cut(plug).clean()
                tag = "xm" if face < -1 else "xp"
                component_set += [(name+"_plug_"+tag, plug, cfg["insert_material"], "fabricate"),
                                  (name+"_plug_bond_"+tag, bond, cfg["bond_material"], "reference_only")]
                main_air = main_air.cut(whole).clean()
            if pose["kind"] == "embedded_slim":
                sign = pose["sign"]
                axis = np.array([sign, 0., 0.])
                face = -15. if sign < 0 else 0.
                start = np.array([face-sign*slim["embedded_length_mm"], y, z])
                length = slim["embedded_length_mm"]+slim["external_length_mm"]
                stem_outer = cyl(slim["stem_outer_diameter_mm"]/2, length, start, axis)
                stem_air = cyl(slim["stem_inner_diameter_mm"]/2, length, start, axis)
                stem = stem_outer.cut(stem_air)
                embedded = yz_prism(disks[name], face if sign < 0 else face-slim["embedded_length_mm"],
                                    slim["embedded_length_mm"])
                embedded_bond = embedded.cut(stem_outer).clean()
                main_air = main_air.cut(embedded).clean()
                sleeve_start = np.array([face+sign*(slim["external_length_mm"]-slim["sleeve_length_mm"]), y, z])
                sleeve_outer = cyl(slim["sleeve_outer_diameter_mm"]/2, slim["sleeve_length_mm"], sleeve_start, axis)
                sleeve_hole = cyl(slim["sleeve_inner_diameter_mm"]/2, slim["sleeve_length_mm"], sleeve_start, axis)
                sleeve = sleeve_outer.cut(sleeve_hole)
                sleeve_bond = sleeve_hole.cut(stem_outer).clean()
                component_set += [(name+"_slim_stem", stem, "304/316 stainless tube, dimensional target", "reference_only"),
                                  (name+"_embedded_bond", embedded_bond, cfg["bond_material"], "reference_only"),
                                  (name+"_hose_sleeve", sleeve, "304/316 stainless sleeve, dimensional target", "reference_only"),
                                  (name+"_sleeve_bond", sleeve_bond, cfg["bond_material"], "reference_only")]
                gas = main_air.fuse(stem_air).clean()
                outlet = np.array([face+sign*slim["external_length_mm"], y, z])
                cap = cyl(slim["stem_outer_diameter_mm"]/2, .25, outlet, axis)
            else:
                axis = np.asarray(pose["direction_native"], dtype=float)
                anchor = np.asarray(pose["anchor_native_mm"], dtype=float)
                tube_length = pose.get("metal_tube_length_mm", cfg["metal_tube_length_mm"])
                if abs(np.linalg.norm(axis)-1) > 1e-8:
                    raise ValueError("Port axis must be a unit vector")
                embed, seat = pose["holder_embed_mm"], cfg["holder_length_mm"]-cfg["socket_depth_mm"]
                holders.append(cyl(cfg["holder_outer_diameter_mm"]/2, cfg["holder_length_mm"]+embed,
                                   anchor-embed*axis, axis))
                if pose["kind"] == "angled":
                    begin = np.asarray(pose["branch_start_native_mm"])
                    distance = pose["branch_to_surface_length_mm"]
                    throat = cyl(cfg["holder_throat_diameter_mm"]/2, distance+seat, begin, axis)
                    body_cuts.append(cyl(cfg["holder_throat_diameter_mm"]/2, distance+cfg["holder_length_mm"]+.05, begin, axis))
                else:
                    throat = cyl(cfg["holder_throat_diameter_mm"]/2, seat, anchor, axis)
                    body_cuts.append(cyl(cfg["holder_throat_diameter_mm"]/2, cfg["holder_length_mm"]+.05, anchor, axis))
                socket_start = anchor+seat*axis
                socket = cyl(cfg["socket_diameter_mm"]/2, cfg["socket_depth_mm"], socket_start, axis)
                body_cuts.append(cyl(cfg["socket_diameter_mm"]/2, cfg["socket_depth_mm"]+.05, socket_start, axis))
                tube_outer = cyl(cfg["metal_tube_outer_diameter_mm"]/2, tube_length, socket_start, axis)
                tube_air = cyl(cfg["metal_tube_inner_diameter_mm"]/2, tube_length, socket_start, axis)
                tube = tube_outer.cut(tube_air)
                tube_bond = socket.cut(tube_outer).clean()
                component_set += [(name+"_metal_tube", tube, cfg["tube_material"], "reference_only"),
                                  (name+"_socket_bond", tube_bond, cfg["bond_material"], "reference_only")]
                gas = main_air.fuse(throat, tube_air).clean()
                outlet = socket_start+tube_length*axis
                cap = cyl(cfg["metal_tube_outer_diameter_mm"]/2, .25, outlet, axis)
            if not gas.isValid() or len(gas.Solids()) != 1:
                raise ValueError("Disconnected intended air path: "+name)
            engagement = hose_cfg["hose_engagement_mm"]
            departure = hose_cfg["straight_hose_beyond_outlet_mm"]
            hose_start = outlet-engagement*axis
            outer = cyl(hose_cfg["hose_outer_diameter_mm"]/2, engagement+departure, hose_start, axis)
            # Nominal 1/16-inch-ID PVC, with the engaged 3 mm expanded onto
            # the 1.6 mm stem. The remainder of each measured hose is not
            # constrained to this local straight reference segment.
            bore = cyl(.8, engagement, hose_start, axis).fuse(cyl(1.5875/2, departure, outlet, axis))
            local_hose = outer.cut(bore).clean()
            component_set.append((name+"_local_hose", local_hose, "PVC tube 1/16 inch ID, 1/8 inch OD; local installed reference", "reference_only"))
            guard = cyl(hose_cfg["hose_outer_diameter_mm"]/2+hose_cfg["hose_radial_guard_mm"],
                       engagement+departure, hose_start, axis)
            hose_guards.append((name, guard))
            components.extend(component_set)
            gases.append((name+"_air_space", gas, entry["role"]))
            caps.append(cap)
            cases.append({"id": name, "kind": pose["kind"], "pose": pose, "air_volume_before_hose_sensor_mm3": gas.Volume(),
                          "outlet_center_native_mm": outlet.tolist(), "outlet_axis_native": axis.tolist(),
                          "local_hose_engagement_mm": engagement, "local_hose_straight_departure_mm": departure})
        body = body.fuse(*holders).clean()
        for cut in body_cuts:
            body = body.cut(cut).clean()
        if not body.isValid() or len(body.Solids()) != 1:
            raise ValueError("Ported insert is disconnected or invalid")
        checks = [{"a": "p1_insert", "b": "source_hard", "overlap_mm3": overlap(body, hard)}]
        material_parts = [("p1_insert", body), *[(name, shape) for name, shape, _, _ in components]]
        objects = material_parts+[(name, shape) for name, shape, _ in gases]
        for index, (name, shape) in enumerate(objects):
            if name != "p1_insert":
                checks.append({"a": name, "b": "source_hard", "overlap_mm3": overlap(shape, hard)})
            for other_name, other in objects[index+1:]:
                checks.append({"a": name, "b": other_name, "overlap_mm3": overlap(shape, other)})
        failures = [row for row in checks if row["overlap_mm3"] > .001]
        guard_checks = []
        for index, (name, guard) in enumerate(hose_guards):
            for other_name, other in [("source_hard", hard), *material_parts]:
                if other_name.startswith(name+"_"):
                    continue  # Engagement deliberately surrounds its own fitting.
                guard_checks.append({"a": name+"_hose_guard", "b": other_name, "overlap_mm3": overlap(guard, other)})
            for other_name, other in hose_guards[index+1:]:
                guard_checks.append({"a": name+"_hose_guard", "b": other_name+"_hose_guard",
                                     "overlap_mm3": overlap(guard, other)})
        guard_failures = [row for row in guard_checks if row["overlap_mm3"] > .001]
        failures.extend(guard_failures)
        parts, models = [], []
        mesh = export_part(body, "p1_ported_insert", folder, parts,
                           "Flexible insert with four channel pairs, checked port poses and cleaning openings",
                           cfg["insert_material"], "fabricate")
        models.append(packed(mesh, "p1_ported_insert", "p1_insert", "#91ab8a"))
        for name, shape, material, kind in components:
            purpose = "Nominal seal/process envelope" if "bond" in name else "Cut stock or closure component; see material and assembly instructions"
            mesh = export_part(shape, name, folder, parts, purpose, material, kind)
            models.append(packed(mesh, name, "p1_seals" if "bond" in name else "p1_hardware",
                                 "#c2a26c" if "bond" in name else "#7c929f"))
        for name, shape, role in gases:
            mesh = export_part(shape, name, folder, parts, "Intended sealed air volume before hoses; do not fabricate as a solid part",
                               "Gas-space reference", "reference_only")
            models.append(packed(mesh, name, "p1_front_air" if role == "front" else "p1_back_air",
                                 "#327f9a" if role == "front" else "#805b95"))
        (folder/"material_checks.json").write_text(json.dumps({"checks": checks, "hose_guard_checks": guard_checks,
                                                              "failures": failures}, indent=2)+"\n")
        (folder/"partial_report.json").write_text(json.dumps({
            "parts": parts, "ports": cases, "checks": checks, "hose_guard_checks": guard_checks, "failures": failures,
            "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
            "closure": {"checked": False, "passed": False}}, indent=2)+"\n")
        print(f"{len(parts)} parts exported; {len(checks)} material/source/air comparisons; {len(failures)} findings", flush=True)
        closure = {"checked": False, "passed": False}
        if not failures:
            sealed = body.fuse(*[shape for _, shape in material_parts[1:]], *caps).clean()
            bb = sealed.BoundingBox()
            surrounding = block(bb.xmin-3, bb.xmax+3, bb.ymin-3, bb.ymax+3, bb.zmin-3, bb.zmax+3)
            free = surrounding.cut(sealed)
            regions = sorted(free.Solids(), key=lambda shape: shape.Volume(), reverse=True)
            cavities = regions[1:]
            matches, assigned = [], set()
            for name, gas, _ in gases:
                candidate = [(index, overlap(gas, cavity)) for index, cavity in enumerate(cavities)]
                best = max(candidate, key=lambda row: row[1]) if candidate else None
                tolerance = max(.02, .002*gas.Volume())
                match = (best is not None and best[0] not in assigned
                         and abs(best[1]-gas.Volume()) <= tolerance
                         and abs(cavities[best[0]].Volume()-gas.Volume()) <= tolerance)
                if match:
                    assigned.add(best[0])
                matches.append({"air_path": name, "matching_cavity": best[0] if best else None,
                                "cavity_volume_mm3": cavities[best[0]].Volume() if best else None, "passed": match})
            unexpected = [shape.Volume() for index, shape in enumerate(cavities) if index not in assigned and shape.Volume() > .005]
            closure = {"checked": True, "material_solids_after_union": len(sealed.Solids()),
                       "cavity_count": len(cavities), "matches": matches, "unexpected_cavity_volumes_mm3": unexpected,
                       "passed": all(row["passed"] for row in matches) and not unexpected,
                       "scope": "Temporary CAD caps seal the intended tube outlets for this topology check; no physical leak test is implied."}
        report = {"schema": "yam-pneumatic-ported-assembly/1", "physical_specimens_tested": 0,
                  "parts": parts, "ports": cases, "checks": checks, "hose_guard_checks": guard_checks, "failures": failures,
                  "closure": closure, "passed_nominal_checks": not failures and closure["passed"],
                  "source_hard_conversion": hard_receipt,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": cfg["limits"]+slim["limits"]+[
                      "The air-space topology check uses ideal solid/bond geometry; real resin, glue and tubing can leak.",
                      "The eight modeled PVC segments cover 3 mm engagement and 5 mm straight departure only; remaining hose routes need a measured slack loop.",
                      "Loaded motion and physical calibration remain."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts),
                            "checks": len(checks), "hose_guard_checks": len(guard_checks), "failures": failures, "closure": closure}
        print(json.dumps(record["result"], indent=2))
        if not report["passed_nominal_checks"]:
            raise ValueError("Resolve the nominal P1 material or air-path findings")


if __name__ == "__main__":
    main()
