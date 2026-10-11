#!/usr/bin/python3
"""Check nominal tail references against source solids and the R2 carrier."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/f1-cad-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
import cadquery as cq
import numpy as np
import trimesh
from shapely.geometry import Polygon
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from analyze_b1_interfaces import original_profile, extruded_profile
from prototype_cad import x_cylinder, yz_prism
from screen_f1_feedback import digest
from source_brep import load as load_source


def aabb_gap(a, b):
    aa, bb = a.BoundingBox(), b.BoundingBox()
    return max(max(getattr(aa, axis+"min"), getattr(bb, axis+"min")) -
               min(getattr(aa, axis+"max"), getattr(bb, axis+"max")) for axis in "xyz")


def check_pair(a_name, a, b_name, b):
    bound = aabb_gap(a, b)
    if bound > 1e-8:
        return {"a": a_name, "b": b_name, "method": "separating_coordinate_bounds",
                "separation_lower_bound_mm": bound, "overlap_mm3": 0., "passed": True}
    try:
        distance = a.distance(b)
        if distance > 1e-7:
            return {"a": a_name, "b": b_name, "method": "OpenCascade_minimum_distance",
                    "distance_mm": distance, "overlap_mm3": 0., "passed": True}
        common = a.intersect(b)
        volume = 0.0 if common.wrapped.IsNull() else common.Volume()
        return {"a": a_name, "b": b_name, "method": "OpenCascade_distance_and_common",
                "distance_mm": distance, "overlap_mm3": volume, "passed": volume <= .001}
    except (ValueError, RuntimeError) as error:
        return {"a": a_name, "b": b_name, "method": "kernel_result_unresolved",
                "error": str(error), "passed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fit_run", type=Path)
    parser.add_argument("carrier_run", type=Path)
    parser.add_argument("stack_run", type=Path)
    args = parser.parse_args()
    fit, carrier, stack = (p.resolve() for p in (args.fit_run, args.carrier_run, args.stack_run))
    if not all(p.is_relative_to(ROOT) for p in (fit, carrier, stack)):
        parser.error("Use repository-owned checked geometry")
    fit_manifest = json.loads((fit / "fit_manifest.json").read_text())
    carrier_manifest = json.loads((carrier / "carrier_manifest.json").read_text())
    hard, source_check = load_source("hard_frame")
    soft_mesh, soft_profile, _ = original_profile()
    soft = extruded_profile(soft_profile)
    if abs(soft.Volume()-soft_mesh.volume) > soft_mesh.volume*1e-5:
        raise ValueError("Soft solid differs from its source-mesh extrusion")
    folder = ROOT / "build/engineering/prototypes/f1/tail_fit_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check the new 3D tail references against actual source solids, carrier, other tails and closed body/head envelopes; preserve unresolved mating and kernel cases") as record:
        folder.mkdir(parents=True, exist_ok=False)
        paths = [fit / "fit_manifest.json", carrier / "carrier_manifest.json", Path(__file__),
                 ROOT / "engineering/scripts/source_brep.py", ROOT / "engineering/scripts/analyze_b1_interfaces.py"]
        for path in paths:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        tails = []
        for part, pattern in zip(fit_manifest["parts"], fit_manifest["patterns"]):
            path = fit / part["step"]
            if digest(path) != part["sha256_step"]:
                raise ValueError("Tail CAD changed")
            tails.append((part["id"], cq.importers.importStep(str(path)).val(), pattern))
        carrier_part = next(p for p in carrier_manifest["parts"] if p["id"] == "f1_r2_carrier")
        carrier_path = carrier / carrier_part["step"]
        if digest(carrier_path) != carrier_part["sha256_step"]:
            raise ValueError("Carrier CAD changed")
        obstacles = [("original_hard_frame", hard), ("original_TPU", soft),
                     ("carrier", cq.importers.importStep(str(carrier_path)).val())]
        board_part = next(p for p in carrier_manifest["parts"] if p["kind"] == "reference_only")
        obstacles.append(("board", cq.importers.importStep(str(carrier / board_part["step"])).val()))
        for item in carrier_manifest["fastener_envelopes"]:
            y, z = item["center_yz_mm"]
            obstacles.append((item["name"], x_cylinder(item["start_x_mm"], item["height_mm"],
                                                      y, z, item["diameter_mm"]/2)))
        components = []
        for item in carrier_manifest["components"]:
            x0, x1 = item["native_x_interval_mm"]
            components.append((item["reference"], yz_prism(Polygon(item["body_yz_mm"]), x0, x1-x0)))
        pairs, mating = [], []
        for index, (name, shape, pattern) in enumerate(tails):
            for other, solid in obstacles:
                pairs.append(check_pair(name, shape, other, solid))
            for other, solid in components:
                if other == pattern["connector"]:
                    mating.append({"tail": name, "connector": other,
                                   "status": "not_collision_qualified",
                                   "reason": "The connector cavity and exact contact plane are not modeled. A tail deliberately enters this closed body envelope."})
                    continue
                pairs.append(check_pair(name, shape, other, solid))
            for other, solid, _ in tails[index+1:]:
                pairs.append(check_pair(name, shape, other, solid))
            (folder / "partial_checks.json").write_text(json.dumps(pairs, indent=2)+"\n")
            print(f"Checked {name}: {sum(not p['passed'] for p in pairs)} findings so far", flush=True)
        failures = [p for p in pairs if not p["passed"]]
        models = []
        for source in (carrier / "models.json", stack / "models.json", fit / "models.json"):
            models.extend(json.loads(source.read_text()))
        (folder / "assembly_models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        fig = plt.figure(figsize=(16, 8))
        for number, azimuth in ((121, -60), (122, 120)):
            ax = fig.add_subplot(number, projection="3d")
            for item in models:
                vertices = np.asarray(item["vertices"])
                faces = np.asarray(item["faces"])
                alpha = .14 if item["group"] in ("source", "board") else .85
                ax.add_collection3d(Poly3DCollection(vertices[faces][:, :, [1, 2, 0]],
                    facecolor=item["color"], edgecolor="none", alpha=alpha))
            ax.set(xlim=(-121, -4), ylim=(-10, 49), zlim=(-26, 19),
                   xlabel="Native Y (mm)", ylabel="Native Z (mm)", zlabel="Native X (mm)")
            ax.set_box_aspect((117, 59, 45))
            ax.view_init(elev=25, azim=azimuth)
        fig.suptitle("F1 nominal integration references · six sensor stacks, twelve tails, R2 board and carrier\n"
                     "Fitted copper, connector cavities, stiffeners, slack and physical qualification remain")
        fig.tight_layout()
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(folder / ("nominal_assembly."+suffix), dpi=170)
        plt.close(fig)
        report = {
            "schema": "yam-f1-tail-fit-check/1", "physical_specimens_tested": 0,
            "complete_f1_assembly": False, "passed_declared_checks": not failures,
            "source_frame_conversion": source_check,
            "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in paths},
            "pairs": pairs, "findings": failures, "unqualified_connector_interfaces": mating,
            "limits": [
                "Static nominal solids only. No physical print, deflection, fatigue or 20 N data.",
                "Tails omit stiffeners and routed copper. Exact connector cavity and mating-datum uncertainty remain.",
                "Own sensor-body joins, seal geometry, interlayer contact/preload, open latches, cable and installed drive remain.",
                "A failed or unresolved kernel case is retained; it is never counted as a clear physical interface."
            ]
        }
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "pairs": len(pairs),
                            "passed": not failures, "findings": failures, "unqualified_mating_interfaces": len(mating)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
