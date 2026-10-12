#!/usr/bin/python3
"""Add cleanable P1 tube sockets, flush end plugs and explicit sealed-air references."""

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
from shapely.geometry import Point
from tactile_kit.records import execution
from source_brep import load as source_solid
from prototype_cad import export_part, packed, yz_prism
from build_pneumatic_insert_witness import common_volume
from screen_f1_feedback import digest

CONFIG = ROOT/"engineering/designs/pneumatic_ports.json"


def cylinder(radius, length, x, y, z, sign):
    return cq.Solid.makeCylinder(radius, length, cq.Vector(x, y, z), cq.Vector(sign, 0, 0))


def hardware(y, z, sign, cfg):
    face = -15. if sign < 0 else 0.
    holder = cylinder(cfg["holder_outer_diameter_mm"]/2, cfg["holder_length_mm"], face, y, z, sign)
    seat = cfg["holder_length_mm"]-cfg["socket_depth_mm"]
    throat = cylinder(cfg["holder_throat_diameter_mm"]/2, cfg["holder_length_mm"]+.1, face-.05*sign, y, z, sign)
    socket = cylinder(cfg["socket_diameter_mm"]/2, cfg["socket_depth_mm"]+.05, face+seat*sign, y, z, sign)
    printed = holder.cut(throat).cut(socket).clean()
    tube_outer = cylinder(cfg["metal_tube_outer_diameter_mm"]/2, cfg["metal_tube_length_mm"], face+seat*sign, y, z, sign)
    tube_void = cylinder(cfg["metal_tube_inner_diameter_mm"]/2, cfg["metal_tube_length_mm"], face+seat*sign, y, z, sign)
    tube = tube_outer.cut(tube_void)
    bond = cylinder(cfg["socket_diameter_mm"]/2, cfg["socket_depth_mm"], face+seat*sign, y, z, sign).cut(tube_outer)
    envelope = holder.fuse(tube_outer).clean()
    opposite = 0. if sign < 0 else -15.
    plug = cylinder(cfg["plug_diameter_mm"]/2, cfg["plug_length_mm"], opposite, y, z, sign)
    return {"face": face, "seat": seat, "holder": printed, "tube": tube, "tube_bond": bond,
            "envelope": envelope, "plug": plug, "tube_void": tube_void, "opposite": opposite}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout", type=Path)
    parser.add_argument("witness", type=Path)
    args = parser.parse_args()
    layout, witness = args.layout.resolve(), args.witness.resolve()
    if not all(path.is_relative_to(ROOT/"build") for path in (layout, witness)):
        parser.error("Use this checkout's generated inputs")
    plan = json.loads((layout/"report.json").read_text())
    base = json.loads((witness/"report.json").read_text())
    for report in (plan, base):
        for name, expected in report["input_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError("P1 geometry input changed")
    if base["input_sha256"].get(str((layout/"report.json").relative_to(ROOT))) != digest(layout/"report.json"):
        raise ValueError("Witness uses another wall-pair layout")
    cfg = json.loads(CONFIG.read_text())
    if not (cfg["holder_throat_diameter_mm"] == cfg["metal_tube_inner_diameter_mm"]
            < cfg["plug_diameter_mm"] < plan["channel_diameter_mm"]
            < cfg["metal_tube_outer_diameter_mm"] < cfg["socket_diameter_mm"] < cfg["holder_outer_diameter_mm"]):
        raise ValueError("Port dimensions do not leave the intended bores and bond gaps")
    part = next(part for part in base["parts"] if part["id"] == "p1_soft_insert_channel_witness")
    path = witness/part["step"]
    if digest(path) != part["sha256_step"]:
        raise ValueError("Insert witness changed")
    body = cq.importers.importStep(str(path)).val()
    hard, receipt = source_solid("hard_frame")
    folder = ROOT/"build/engineering/prototypes/pneumatic/ported_insert"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Add eight integral external sockets and explicit tube/plug/bond/gas references; choose only frame-clear fitting sides and retain all physical sealing/motion limits") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        parts, models, cases, shapes = [], [], [], []
        selected_envelopes = []
        for case in plan["cases"]:
            for role in ("front", "back"):
                identifier = case[role]["id"]
                _, y, z = case[role]["center_native_mm"]
                options = []
                for sign in (cfg["preferred_exit_sign"], -cfg["preferred_exit_sign"]):
                    pieces = hardware(y, z, sign, cfg)
                    overlap = common_volume(pieces["envelope"], hard)
                    peers = [common_volume(pieces["envelope"], other) for other in selected_envelopes]
                    options.append({"sign": sign, "frame_overlap_mm3": overlap, "peer_overlap_mm3": max(peers or [0.])})
                    if overlap <= .001 and max(peers or [0.]) <= .001:
                        break
                else:
                    (folder/"failed_port.json").write_text(json.dumps({"port": identifier, "options": options}, indent=2)+"\n")
                    raise ValueError("No clear fitting side for "+identifier)
                selected_envelopes.append(pieces["envelope"])
                body = body.fuse(pieces["holder"]).clean()
                for key, material in (("tube", cfg["tube_material"]), ("tube_bond", cfg["bond_material"]),
                                      ("plug", cfg["insert_material"])):
                    name = identifier+"_"+key
                    display = export_part(pieces[key], name, folder, parts,
                                          {"tube": "External reinforced hose connection", "tube_bond": "Nominal annular socket bond",
                                           "plug": "Flush closure installed after channel cleaning"}[key],
                                          material, "fabricate" if key == "plug" else "reference_only")
                    models.append(packed(display, name, "p1_"+key, "#687f93" if key == "tube" else "#b4a178"))
                    shapes.append((name, pieces[key]))
                circle = Point(y, z).buffer(plan["channel_diameter_mm"]/2, quad_segs=64)
                plug_x0 = -cfg["plug_length_mm"] if sign < 0 else -15.
                plug_void = yz_prism(circle, plug_x0, cfg["plug_length_mm"])
                plug_bond = plug_void.cut(pieces["plug"]).clean()
                name = identifier+"_plug_bond"
                display = export_part(plug_bond, name, folder, parts, "Nominal seal around the flush plug",
                                      cfg["bond_material"], "reference_only")
                models.append(packed(display, name, "p1_plug_bond", "#bc9972"))
                shapes.append((name, plug_bond))
                channel_x0 = -15. if sign < 0 else -15.+cfg["plug_length_mm"]
                channel = yz_prism(circle, channel_x0, 15.-cfg["plug_length_mm"])
                neck = cylinder(cfg["holder_throat_diameter_mm"]/2, pieces["seat"], pieces["face"], y, z, sign)
                gas = channel.fuse(neck, pieces["tube_void"]).clean()
                gas_name = identifier+"_sealed_air_reference"
                display = export_part(gas, gas_name, folder, parts,
                                      "Air volume before the external PVC tube and transducer; not a solid printed part",
                                      "Gas-space reference", "reference_only")
                models.append(packed(display, gas_name, "p1_front_air" if role == "front" else "p1_back_air",
                                     "#327f9a" if role == "front" else "#805b95"))
                shapes.append((gas_name, gas))
                cases.append({"id": identifier, "site": case["site"], "role": role, "sign": sign,
                              "center_native_yz_mm": [y, z], "options_checked": options,
                              "gas_volume_before_hose_sensor_mm3": gas.Volume()})
                (folder/"partial.json").write_text(json.dumps({"parts": parts, "cases": cases}, indent=2)+"\n")
                print(identifier+": socket, tube, plug and air path generated", flush=True)
        checks = []
        for name, shape in shapes:
            checks.append({"part": name, "against": "ported_body", "overlap_mm3": common_volume(shape, body)})
            checks.append({"part": name, "against": "source_hard", "overlap_mm3": common_volume(shape, hard)})
        for index, (name, shape) in enumerate(shapes):
            for other_name, other in shapes[index+1:]:
                bb, oo = shape.BoundingBox(), other.BoundingBox()
                if any(max(getattr(bb, a+"min"), getattr(oo, a+"min")) > min(getattr(bb, a+"max"), getattr(oo, a+"max")) for a in "xyz"):
                    continue
                checks.append({"part": name, "against": other_name, "overlap_mm3": common_volume(shape, other)})
        body_overlap = common_volume(body, hard)
        checks.append({"part": "ported_body", "against": "source_hard", "overlap_mm3": body_overlap})
        failures = [row for row in checks if row["overlap_mm3"] > .001]
        display = export_part(body, "p1_ported_soft_insert", folder, parts,
                              "Flexible insert with eight cleanable through-channels and integral external tube sockets",
                              cfg["insert_material"], "fabricate")
        models.insert(0, packed(display, "p1_ported_soft_insert", "p1_insert", "#91ab8a"))
        inputs = [CONFIG, Path(__file__), layout/"report.json", witness/"report.json",
                  ROOT/"engineering/scripts/build_pneumatic_insert_witness.py", ROOT/"engineering/scripts/prototype_cad.py",
                  ROOT/"engineering/scripts/source_brep.py"]
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        report = {"schema": "yam-pneumatic-ported-insert/1", "physical_specimens_tested": 0,
                  "parts": parts, "ports": cases, "checks": checks, "failures": failures,
                  "passed_nominal_checks": not failures, "source_hard_conversion": receipt,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": cfg["limits"]+["Hose routes, transducer cases, nail sensors, electronics and physical qualification remain."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "checks": len(checks), "failures": failures}
        print(json.dumps(record["result"], indent=2))
        if failures:
            raise ValueError("Resolve P1 port/material overlap findings")


if __name__ == "__main__":
    main()
