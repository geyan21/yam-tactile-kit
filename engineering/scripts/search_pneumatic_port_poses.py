#!/usr/bin/python3
"""Search bounded straight/angled P1 fitting poses against actual frame and insert solids."""

import argparse
from datetime import datetime, timezone
import itertools
import json
import math
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
from source_brep import load as source_solid
from prototype_cad import yz_prism, export_part, packed
from build_pneumatic_ports import hardware
from build_pneumatic_insert_witness import common_volume
from screen_f1_feedback import digest

CONFIG = ROOT/"engineering/designs/pneumatic_port_search.json"


def cyl(radius, length, origin, direction):
    return cq.Solid.makeCylinder(radius, length, cq.Vector(*origin), cq.Vector(*direction))


def overlap(a, b):
    aa, bb = a.BoundingBox(), b.BoundingBox()
    if any(max(getattr(aa, axis+"min"), getattr(bb, axis+"min")) >
           min(getattr(aa, axis+"max"), getattr(bb, axis+"max")) for axis in "xyz"):
        return 0.
    return common_volume(a, b)


def internal_exit(profile, exterior, start, direction, cfg):
    previous = 0.
    for distance in np.arange(cfg["ray_step_mm"], cfg["maximum_branch_length_mm"], cfg["ray_step_mm"]):
        point = start+distance*direction
        if not -15. < point[0] < 0.:
            return None
        if profile.contains(Point(point[1:])):
            previous = distance
            continue
        lo, hi = previous, distance
        for _ in range(25):
            mid = (lo+hi)/2
            if profile.contains(Point((start+mid*direction)[1:])):
                lo = mid
            else:
                hi = mid
        face = start+(lo+hi)/2*direction
        if not exterior.contains(Point((face+.1*direction)[1:])):
            return None
        return face, float((lo+hi)/2)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout", type=Path)
    parser.add_argument("witness", type=Path)
    args = parser.parse_args()
    layout, witness = args.layout.resolve(), args.witness.resolve()
    if not all(path.is_relative_to(ROOT/"build") for path in (layout, witness)):
        parser.error("Use generated inputs from this checkout")
    plan = json.loads((layout/"report.json").read_text())
    base = json.loads((witness/"report.json").read_text())
    for report in (plan, base):
        for name, expected in report["input_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError("Input changed before pose search")
    if base["input_sha256"].get(str((layout/"report.json").relative_to(ROOT))) != digest(layout/"report.json"):
        raise ValueError("The insert witness belongs to another wall-pair layout")
    cfg = json.loads(CONFIG.read_text())
    port_path = ROOT/cfg["port_dimensions"]
    port = json.loads(port_path.read_text())
    all_channels = [(row[role]["id"], np.asarray(row[role]["center_native_mm"]))
                    for row in plan["cases"] for role in ("front", "back")]
    air_disks = [Point(center[1:]).buffer(plan["channel_diameter_mm"]/2, quad_segs=64) for _, center in all_channels]
    cut_profile = Polygon(plan["modified_profile"]["outer"], plan["modified_profile"]["holes"])
    support_profile = unary_union([cut_profile, *air_disks])
    exterior = Polygon(support_profile.exterior.coords)
    support = yz_prism(support_profile, -15, 15)
    part = next(part for part in base["parts"] if part["id"] == "p1_soft_insert_channel_witness")
    path = witness/part["step"]
    if digest(path) != part["sha256_step"]:
        raise ValueError("Witness changed")
    body = cq.importers.importStep(str(path)).val()
    hard, receipt = source_solid("hard_frame")
    folder = ROOT/"build/engineering/prototypes/pneumatic/port_pose_searches"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Search bounded P1 port poses that clear the actual hard frame and leave free tube ends; check branch-wall support without changing or waiving the frame") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        selected, failed, parts, models, peer_envelopes = [], [], [], [], []
        for entry in plan["cases"]:
            for role in ("front", "back"):
                identifier = entry[role]["id"]
                _, y, z = entry[role]["center_native_mm"]
                trials, accepted = [], None
                for sign in (port["preferred_exit_sign"], -port["preferred_exit_sign"]):
                    pieces = hardware(y, z, sign, port)
                    frame = overlap(pieces["envelope"], hard)
                    peer = max([overlap(pieces["envelope"], other) for other in peer_envelopes] or [0.])
                    trials.append({"kind": "straight", "sign": sign, "frame_overlap_mm3": frame, "peer_overlap_mm3": peer})
                    if max(frame, peer) <= .001:
                        accepted = {"id": identifier, "site": entry["site"], "role": role, "kind": "straight",
                                    "direction_native": [sign, 0, 0], "anchor_native_mm": [pieces["face"], y, z],
                                    "holder_embed_mm": 0., "branch_start_native_mm": None,
                                    "plug_faces_x_mm": [pieces["opposite"]], "sign": sign}
                        envelope = pieces["envelope"]
                        break
                if accepted is None:
                    grid = itertools.product((port["preferred_exit_sign"], -port["preferred_exit_sign"]),
                                             cfg["inside_distance_from_x_end_mm"], cfg["elevation_from_x_deg"],
                                             cfg["yaw_deg"], cfg["holder_embed_mm"])
                    for sign, inset, elevation, yaw, embed in grid:
                        a, b = math.radians(elevation), math.radians(yaw)
                        direction = np.array([sign*math.cos(a)*math.cos(b), math.sin(b),
                                              (1 if role == "front" else -1)*math.sin(a)*math.cos(b)])
                        start = np.array([(-15 if sign < 0 else 0)-sign*inset, y, z])
                        found = internal_exit(support_profile, exterior, start, direction, cfg)
                        if found is None:
                            continue
                        anchor, distance = found
                        seat = port["holder_length_mm"]-port["socket_depth_mm"]
                        end = anchor+(seat+port["metal_tube_length_mm"])*direction
                        if ((sign < 0 and end[0] > -15-cfg["outlet_x_clearance_mm"])
                                or (sign > 0 and end[0] < cfg["outlet_x_clearance_mm"])):
                            continue
                        holder = cyl(port["holder_outer_diameter_mm"]/2, port["holder_length_mm"]+embed,
                                     anchor-embed*direction, direction)
                        tube = cyl(port["metal_tube_outer_diameter_mm"]/2, port["metal_tube_length_mm"],
                                   anchor+seat*direction, direction)
                        envelope = holder.fuse(tube).clean()
                        frame = overlap(envelope, hard)
                        trial = {"kind": "angled", "sign": sign, "inset_mm": inset, "elevation_deg": elevation,
                                 "yaw_deg": yaw, "embed_mm": embed, "frame_overlap_mm3": frame}
                        trials.append(trial)
                        if frame > .001:
                            continue
                        free_tube = cyl(port["metal_tube_outer_diameter_mm"]/2,
                                        port["metal_tube_length_mm"]-port["socket_depth_mm"],
                                        anchor+port["holder_length_mm"]*direction, direction)
                        trial["free_tube_insert_overlap_mm3"] = overlap(free_tube, body)
                        trial["peer_overlap_mm3"] = max([overlap(envelope, other) for other in peer_envelopes] or [0.])
                        if max(trial["free_tube_insert_overlap_mm3"], trial["peer_overlap_mm3"]) > .001:
                            continue
                        guard = cyl(port["holder_throat_diameter_mm"]/2+cfg["minimum_branch_wall_mm"],
                                    distance+seat, start, direction)
                        missing = guard.cut(support).cut(holder)
                        trial["unsupported_branch_wall_mm3"] = 0. if missing.wrapped.IsNull() else abs(missing.Volume())
                        if trial["unsupported_branch_wall_mm3"] > .001:
                            continue
                        other_air = [yz_prism(disk, -15, 15) for (name, _), disk in zip(all_channels, air_disks) if name != identifier]
                        trial["other_channel_guard_overlap_mm3"] = max([overlap(guard, air) for air in other_air] or [0.])
                        if trial["other_channel_guard_overlap_mm3"] > .001:
                            continue
                        accepted = {"id": identifier, "site": entry["site"], "role": role, "kind": "angled",
                                    "direction_native": direction.tolist(), "anchor_native_mm": anchor.tolist(),
                                    "branch_start_native_mm": start.tolist(), "branch_to_surface_length_mm": distance,
                                    "holder_embed_mm": embed, "plug_faces_x_mm": [-15., 0.],
                                    "outlet_native_mm": end.tolist(), "sign": sign}
                        break
                if accepted is None:
                    failed.append(identifier)
                else:
                    peer_envelopes.append(envelope)
                    mesh = export_part(envelope, identifier+"_fitting_envelope", folder, parts,
                                       "Conservative fitting clearance reference; not the printable socket or tube",
                                       "Combined outside envelope", "reference_only")
                    models.append(packed(mesh, identifier+"_fitting_envelope", "p1_port_envelopes", "#779ba7"))
                    selected.append({**accepted, "trials": trials})
                (folder/(identifier+"_trials.json")).write_text(json.dumps(trials, indent=2)+"\n")
                print(identifier+(": "+accepted["kind"]+" pose found" if accepted else ": no pose found")
                      +f" after {len(trials)} native frame checks", flush=True)
        inputs = [CONFIG, port_path, Path(__file__), layout/"report.json", witness/"report.json",
                  ROOT/"engineering/scripts/build_pneumatic_ports.py", ROOT/"engineering/scripts/source_brep.py"]
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        report = {"schema": "yam-pneumatic-port-pose-search-result/1", "physical_specimens_tested": 0,
                  "poses": selected, "failed_ports": failed, "parts": parts, "passed": not failed and len(selected) == 8,
                  "source_hard_conversion": receipt,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": cfg["limits"]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "poses": len(selected), "failed_ports": failed}
        print(json.dumps(record["result"], indent=2))
        if not report["passed"]:
            raise ValueError("Resolve the remaining port routes")


if __name__ == "__main__":
    main()
