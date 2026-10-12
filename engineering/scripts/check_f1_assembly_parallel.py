#!/usr/bin/python3
"""Check the full F1 assembly with a bounded number of independent CAD workers."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/f1-cad-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest

BASE = ROOT / "engineering/development/f1/r3"
GEOMETRY = None


def selected_parts(paths, reports):
    connectors = {case["foil"]: case["connector"] for case in reports["terminals"]["cases"]}
    result = []
    for kind, report in reports.items():
        for part in report["parts"]:
            name = part["id"]
            if kind == "skin" and (part["kind"] == "fabricate_tool" or name.endswith(
                    ("_columns_body", "_rows_body", "_column_finish_envelope", "_row_finish_envelope"))):
                continue
            if kind == "terminals" and "_stiffener_" not in name:
                continue
            path = paths[kind] / part["step"]
            if digest(path) != part["sha256_step"]:
                raise ValueError("Material part changed: "+name)
            result.append({
                "name": name, "path": str(path), "sha256": part["sha256_step"],
                "own_connector": next((connector for foil, connector in connectors.items()
                                       if name.startswith(foil+"_")), None),
            })
    if len({item["name"] for item in result}) != len(result):
        raise ValueError("Duplicate assembly part identity")
    return result


def initialize(parts, carrier):
    """Load once per worker; no shared CAD kernel or shared output files."""
    global GEOMETRY
    import cadquery as cq
    from shapely.geometry import Polygon
    from source_brep import load as source_solid
    from analyze_b1_interfaces import original_profile, extruded_profile
    from prototype_cad import x_cylinder, yz_prism

    def entry(name, shape, connector=None):
        bb = shape.BoundingBox()
        return {"name": name, "shape": shape, "own_connector": connector,
                "bounds": [(getattr(bb, axis+"min"), getattr(bb, axis+"max")) for axis in "xyz"]}

    objects = []
    for part in parts:
        if digest(Path(part["path"])) != part["sha256"]:
            raise ValueError("CAD changed during worker initialization")
        objects.append(entry(part["name"], cq.importers.importStep(part["path"]).val(), part["own_connector"]))
    hard, receipt = source_solid("hard_frame")
    mesh, profile, _ = original_profile()
    soft = extruded_profile(profile)
    if abs(soft.Volume()-mesh.volume) > mesh.volume*1e-5:
        raise ValueError("TPU source conversion changed")
    obstacles = [entry("source_hard", hard), entry("source_TPU", soft)]
    for part in carrier["parts"]:
        if part["kind"] not in ("fabricate", "reference_only"):
            continue
        path = BASE / part["step"]
        if digest(path) != part["sha256_step"]:
            raise ValueError("Board/carrier reference changed")
        obstacles.append(entry(part["id"], cq.importers.importStep(str(path)).val()))
    for item in carrier["fastener_envelopes"]:
        y, z = item["center_yz_mm"]
        obstacles.append(entry(item["name"], x_cylinder(
            item["start_x_mm"], item["height_mm"], y, z, item["diameter_mm"]/2)))
    components = [entry(item["reference"], yz_prism(
        Polygon(item["body_yz_mm"]), item["native_x_interval_mm"][0],
        item["native_x_interval_mm"][1]-item["native_x_interval_mm"][0]))
        for item in carrier["components"]]
    GEOMETRY = (objects, obstacles, components, receipt)


def compare(a, b):
    # Identical broad-phase criterion to check_pair, with immutable cached
    # bounds. Every overlapping box still uses the original native CAD check.
    from check_f1_tail_fit import check_pair
    bound = max(max(aa[0], bb[0])-min(aa[1], bb[1])
                for aa, bb in zip(a["bounds"], b["bounds"]))
    if bound > 1e-8:
        return {"a": a["name"], "b": b["name"], "method": "separating_coordinate_bounds",
                "separation_lower_bound_mm": bound, "overlap_mm3": 0., "passed": True}
    return check_pair(a["name"], a["shape"], b["name"], b["shape"])


def check_object(index):
    objects, obstacles, components, receipt = GEOMETRY
    item = objects[index]
    checks = [compare(item, other) for other in obstacles]
    unresolved = []
    for other in components:
        if other["name"] == item["own_connector"]:
            unresolved.append({"part": item["name"], "connector": other["name"],
                               "reason": "Unverified actual connector cavity/contact datum; no invented clearance volume."})
        else:
            checks.append(compare(item, other))
    checks.extend(compare(item, other) for other in objects[index+1:])
    return {"index": index, "part": item["name"], "checks": checks, "unresolved": unresolved,
            "source_hard_conversion": receipt if index == 0 else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("foils", "skin", "terminals"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ("foils", "skin", "terminals")}
    if not all(path.is_relative_to(ROOT) for path in paths.values()):
        parser.error("Use repository-owned geometry")
    reports = {name: json.loads((path / "report.json").read_text()) for name, path in paths.items()}
    for report in reports.values():
        for name, expected in report["input_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError("Assembly input changed: "+name)
    for name in ("skin", "terminals"):
        key = str((paths[name] / "report.json").relative_to(ROOT))
        if reports["foils"]["input_sha256"].get(key) != digest(paths[name] / "report.json"):
            raise ValueError("Joined foils belong to another skin/terminal assembly")
    parts = selected_parts(paths, reports)
    carrier = json.loads((BASE / "checks/carrier.json").read_text())
    inputs = [Path(__file__), BASE / "checks/carrier.json", ROOT / "engineering/scripts/check_f1_tail_fit.py",
              ROOT / "engineering/scripts/source_brep.py", ROOT / "engineering/scripts/analyze_b1_interfaces.py",
              *[path / "report.json" for path in paths.values()]]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in inputs}
    folder = ROOT / "build/engineering/prototypes/f1/complete_assembly_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check the full F1 material assembly with bounded isolated CAD workers; retain the original collision criterion and every unresolved mating interface") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        record["owned_worker_limit"] = args.workers
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        results = {}
        with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
                                 initializer=initialize, initargs=(parts, carrier)) as pool:
            futures = [pool.submit(check_object, index) for index in range(len(parts))]
            for future in as_completed(futures):
                result = future.result()
                results[result["index"]] = result
                (folder / ("part_"+str(result["index"]).zfill(3)+".json")).write_text(json.dumps(result, indent=2)+"\n")
                print(result["part"]+f": {len(result['checks'])} comparisons, "
                      f"{sum(not row['passed'] for row in result['checks'])} findings "
                      f"({len(results)}/{len(parts)} parts complete)", flush=True)
        if set(results) != set(range(len(parts))):
            raise ValueError("Incomplete part coverage")
        checks = [row for index in sorted(results) for row in results[index]["checks"]]
        unresolved = [row for index in sorted(results) for row in results[index]["unresolved"]]
        identities = [(row["a"], row["b"]) for row in checks]
        expected = len(parts)*(len(carrier["components"])+2
                              + sum(p["kind"] in ("fabricate", "reference_only") for p in carrier["parts"])
                              + len(carrier["fastener_envelopes"])) + len(parts)*(len(parts)-1)//2 - len(unresolved)
        if len(identities) != expected or len(set(identities)) != expected:
            raise ValueError("Missing or duplicate collision comparisons")
        if any(digest(ROOT / name) != expected_hash for name, expected_hash in hashes.items()):
            raise ValueError("Input changed while assembly checking ran")
        failures = [row for row in checks if not row["passed"]]
        report = {"schema": "yam-f1-complete-assembly-fit/1", "physical_specimens_tested": 0,
                  "parts_checked": [item["name"] for item in parts], "checks": checks, "failures": failures,
                  "passed_declared_checks": not failures, "unqualified_mating_interfaces": unresolved,
                  "source_hard_conversion": results[0]["source_hard_conversion"], "input_sha256": hashes,
                  "coverage": {"expected_comparisons": expected, "unique_comparisons": len(set(identities)),
                               "worker_limit": args.workers, "native_overlap_limit_mm3": .001},
                  "limits": ["Static nominal material envelopes, not physical construction, loaded deformation or fatigue.",
                             "All actual parts are checked against source, carrier, board, fasteners, other components and peers.",
                             "Each part's own connector mating cavity is unqualified and listed separately.",
                             "Neck sealing, strain relief, actual drive and broad-object access require separate checks."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts),
                            "checks": len(checks), "failures": failures, "unqualified_interfaces": len(unresolved)}
        print(json.dumps(record["result"], indent=2))
        if failures:
            raise ValueError("Resolve F1 assembly intersections before release")


if __name__ == "__main__":
    main()
