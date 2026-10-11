#!/usr/bin/python3
"""Build a removable R2 fanout carrier against the original frame axes."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/f1-cad-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
import cadquery as cq
import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
import trimesh
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from build_b1_parts import regional_max_x
from develop_f1_fanout import transform
from prototype_cad import export_part, packed, x_cylinder, yz_prism
from screen_f1_feedback import digest

CONFIG = ROOT / "engineering/designs/f1_carrier_development.json"
STACK = ROOT / "engineering/designs/f1_formed_stack.json"


def native_region(region):
    return affinity.affine_transform(region, [-1, 0, 0, -1, 0, 44])


def hexagon(center, across_flats):
    radius = across_flats / math.sqrt(3)
    return Polygon([(center[0]+radius*math.cos(i*math.pi/3),
                     center[1]+radius*math.sin(i*math.pi/3)) for i in range(6)])


def intersection_volume(a, b):
    # Bounding separation includes deliberate coincident seating faces.
    aa, bb = a.BoundingBox(), b.BoundingBox()
    if any(min(getattr(aa, k+"max"), getattr(bb, k+"max")) -
           max(getattr(aa, k+"min"), getattr(bb, k+"min")) < 1e-9 for k in "xyz"):
        return 0.0
    result = a.intersect(b)
    return 0.0 if result.wrapped.IsNull() else result.Volume()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement_run", type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    source, config_path = args.placement_run.resolve(), args.config.resolve()
    if not source.is_relative_to(ROOT) or not config_path.is_relative_to(ROOT):
        parser.error("Use repository-owned inputs")
    cfg = json.loads(config_path.read_text())
    stack = json.loads(STACK.read_text())
    spec_path = source / "specification.json"
    spec = json.loads(spec_path.read_text())
    if spec["name"] != "f1_fanout_r2":
        raise ValueError("The carrier matches only the separate R2 board")
    if not json.loads((source / "placement_check.json").read_text())["passed"]:
        raise ValueError("Resolve the R2 placement findings first")
    hard_path = ROOT / stack["basis"]["hard_frame"]
    frame = trimesh.load_mesh(hard_path, process=True)
    if not frame.is_watertight:
        raise ValueError("Use the original closed frame mesh")
    folder = ROOT / "build/engineering/prototypes/f1/carrier_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Build a removable F1 R2 board carrier, source-matched seating feet and explicit fastener envelopes; preserve static-fit limitations") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = [config_path, STACK, spec_path, Path(__file__),
                  ROOT / "engineering/scripts/prototype_cad.py",
                  ROOT / "engineering/scripts/build_b1_parts.py",
                  ROOT / "engineering/scripts/develop_f1_fanout.py"]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        pcb_center = cfg["board_native_x_center_mm"]
        pcb_inner = pcb_center-spec["thickness_mm"]/2
        pcb_outer = pcb_center+spec["thickness_mm"]/2
        x0, x1 = cfg["backplate_native_x_mm"]
        if not frame.bounds[1, 0] < x0 < x1 < pcb_inner:
            raise ValueError("Backplate does not clear the frame and fit behind the PCB")
        all_mounts = [(-p["center_mm"][0], 44-p["center_mm"][1]) for p in spec["holes"]]
        mounts = [all_mounts[index] for index in cfg["active_board_mount_indices"]]
        # The four PCB mounts form a rectangular open frame. Separate diagonal
        # arms reach the retained source fasteners without a broad solid sheet.
        rear_left, rear_right = all_mounts[:2]
        front_left, front_right = cfg["rail_front_native_yz_mm"]
        paths = [(rear_left, rear_right), (rear_left, front_left),
                 (rear_right, front_right), (front_left, front_right),
                 (cfg["frame_mounts_native_yz_mm"][0], front_left),
                 (cfg["frame_mounts_native_yz_mm"][1], front_right)]
        rail = unary_union([LineString(points).buffer(cfg["rail_width_mm"]/2)
                            for points in paths])
        rail = rail.union(unary_union([Point(p).buffer(cfg["frame_post_outer_diameter_mm"]/2)
                                      for p in cfg["frame_mounts_native_yz_mm"]]))
        if rail.geom_type != "Polygon":
            raise ValueError("Carrier rails are disconnected")
        carrier = yz_prism(rail, x0, x1-x0)
        for y, z in mounts:
            carrier = carrier.fuse(x_cylinder(x1, pcb_inner-x1, y, z,
                                              cfg["board_post_outer_diameter_mm"]/2))
            carrier = carrier.cut(x_cylinder(x0-.1, pcb_inner-x0+.2, y, z,
                                             cfg["board_screw_clearance_mm"]/2))
            carrier = carrier.cut(yz_prism(hexagon((y, z), cfg["board_nut_across_flats_mm"]),
                                           x0-.01, cfg["board_nut_pocket_depth_mm"]+.01))
        support_rows = []
        for y, z in cfg["frame_mounts_native_yz_mm"]:
            annulus = Point(y, z).buffer(cfg["frame_post_outer_diameter_mm"]/2).difference(
                Point(y, z).buffer(cfg["frame_screw_clearance_mm"]/2))
            support_x = regional_max_x(frame, annulus)
            if support_x >= x1:
                raise ValueError("Source seating plane reaches beyond the carrier")
            carrier = carrier.fuse(x_cylinder(support_x, x1-support_x, y, z,
                                              cfg["frame_post_outer_diameter_mm"]/2))
            carrier = carrier.cut(x_cylinder(support_x-.1, x1-support_x+.2, y, z,
                                             cfg["frame_screw_clearance_mm"]/2))
            support_rows.append({"center_yz_mm": [y, z], "support_native_x_mm": support_x,
                                "distance_to_outer_carrier_mm": x1-support_x,
                                "basis": "Maximum source-frame X over the complete annular footprint; nominal nonpenetration, seating fraction unmeasured"})
        board_outline = native_region(Polygon(spec["outline_xy_mm"]))
        board = yz_prism(board_outline, pcb_inner, spec["thickness_mm"])
        for hole, (y, z) in zip(spec["holes"], all_mounts):
            board = board.cut(x_cylinder(pcb_inner-.1, spec["thickness_mm"]+.2,
                                        y, z, hole["diameter_mm"]/2))
        parts, models = [], []
        for name, shape, kind, material, color in (
                ("f1_r2_carrier", carrier, "fabricate", cfg["material"], "#7eacb4"),
                ("f1_r2_pcb_fit_reference", board, "reference_only", "1 mm FR4 reference; use independently checked PCB artwork for electronics", "#689969")):
            mesh = export_part(shape, name, folder, parts, name.replace("_", " "), material, kind)
            models.append(packed(mesh, name, "carrier" if kind == "fabricate" else "board", color))
        fastener_shapes, fastener_rows = [], []
        for family, points, start, diameter, height in (
                ("board_M2", mounts, pcb_outer, *cfg["board_screw_head_envelope_mm"]),
                ("frame_M3", cfg["frame_mounts_native_yz_mm"], x1, *cfg["frame_screw_head_envelope_mm"])):
            for index, (y, z) in enumerate(points):
                head = x_cylinder(start, height, y, z, diameter/2)
                fastener_shapes.append((family+str(index), head))
                mesh = trimesh.creation.cylinder(radius=diameter/2, height=height, sections=48)
                pose = trimesh.geometry.align_vectors([0, 0, 1], [1, 0, 0])
                pose[:3, 3] = [start+height/2, y, z]
                mesh.apply_transform(pose)
                models.append(packed(mesh, family+str(index), "fastener_envelopes", "#808a96"))
                fastener_rows.append({"name": family+str(index), "center_yz_mm": [y, z],
                                    "start_x_mm": start, "diameter_mm": diameter, "height_mm": height,
                                    "reference_envelope_only": True})
        component_rows, failures = [], []
        for part in spec["parts"]:
            region = native_region(transform(box(*part["body_envelope_mm"]), part))
            height = part["height_mm"]
            start = pcb_outer if part["side"] == "F" else pcb_inner-height
            shape = yz_prism(region, start, height)
            carrier_overlap = intersection_volume(carrier, shape)
            head_overlaps = [(name, intersection_volume(shape, head)) for name, head in fastener_shapes]
            if carrier_overlap > .001 or any(volume > .001 for _, volume in head_overlaps):
                failures.append({"kind": "component_mechanical_overlap", "reference": part["reference"],
                                 "carrier_mm3": carrier_overlap, "heads": head_overlaps})
            component_rows.append({"reference": part["reference"], "side": part["side"],
                                    "native_x_interval_mm": [start, start+height],
                                    "body_yz_mm": list(region.exterior.coords),
                                    "carrier_overlap_mm3": carrier_overlap,
                                    "head_overlap_mm3": dict(head_overlaps)})
            mesh_vertices, mesh_faces = shape.tessellate(.07)
            mesh = trimesh.Trimesh(vertices=[p.toTuple() for p in mesh_vertices], faces=mesh_faces, process=False)
            models.append(packed(mesh, part["reference"], "components", "#667887"))
        board_carrier_overlap = intersection_volume(board, carrier)
        if board_carrier_overlap > .001:
            failures.append({"kind": "board_carrier_overlap", "volume_mm3": board_carrier_overlap})
        for name, head in fastener_shapes:
            if intersection_volume(head, board) > .001:
                failures.append({"kind": "head_board_overlap", "fastener": name})
        models.append(packed(frame, "original_hard_frame", "source", "#687b85"))
        soft = trimesh.load_mesh(ROOT / stack["basis"]["soft_insert"], process=True)
        models.append(packed(soft, "original_TPU", "source", "#abc879"))
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        fig = plt.figure(figsize=(14, 7))
        for number, azimuth in ((121, -55), (122, 125)):
            ax = fig.add_subplot(number, projection="3d")
            for item in models:
                vertices = np.asarray(item["vertices"])
                faces = np.asarray(item["faces"])
                ax.add_collection3d(Poly3DCollection(vertices[faces][:, :, [1, 2, 0]],
                    facecolor=item["color"], edgecolor="none",
                    alpha=.35 if item["group"] == "source" else .8))
            ax.set(xlim=(-119, -4), ylim=(-8, 46), zlim=(-26, 20),
                   xlabel="Native Y (mm)", ylabel="Native Z (mm)", zlabel="Native X (mm)")
            ax.set_box_aspect((115, 54, 46))
            ax.view_init(elev=22, azim=azimuth)
        fig.suptitle("F1 R2 removable carrier · actual source frame and component envelopes\n"
                     "Flexible tails, cable, drive housing and physical fit are not yet included")
        fig.tight_layout()
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(folder / ("carrier_assembly."+suffix), dpi=160)
        plt.close(fig)
        report = {
            "schema": "yam-f1-r2-carrier/1", "passed_declared_static_checks": not failures,
            "physical_specimens_tested": 0, "complete_f1_assembly": False,
            "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs+[hard_path]},
            "parts": parts, "source_supports": support_rows,
            "pcb_native_x_interval_mm": [pcb_inner, pcb_outer],
            "active_board_mount_indices": cfg["active_board_mount_indices"],
            "backplate_global_frame_x_separation_lower_bound_mm": x0-float(frame.bounds[1, 0]),
            "board_carrier_overlap_mm3": board_carrier_overlap,
            "fastener_envelopes": fastener_rows, "components": component_rows,
            "failures": failures,
            "limits": ["Closed component bodies, nominal carrier and head envelopes only.",
                       "Source seating uses exact projected triangle maxima; actual print seating and clamping remain.",
                       "Tails, open latches, cable, nut sourcing, screw engagement, installed drive and loaded motion remain.",
                       "No strength, creep, contact accuracy or 20 N result follows from static CAD."]
        }
        (folder / "carrier_manifest.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)),
                            "parts": len(parts), "components_checked": len(component_rows),
                            "passed": not failures, "failures": failures}
        print(json.dumps(record["result"], indent=2))
        if failures:
            raise ValueError("Carrier findings retained for revision")


if __name__ == "__main__":
    main()
