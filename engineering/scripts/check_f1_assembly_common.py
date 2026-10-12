#!/usr/bin/python3
"""Check every F1 assembly pair using native common volume, without costly distance searches."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import multiprocessing
from pathlib import Path
import shutil
import sys

import check_f1_assembly_parallel as geometry
from screen_f1_feedback import digest
from tactile_kit.records import execution

ROOT, BASE = geometry.ROOT, geometry.BASE


def compare(a, b):
    bound = max(max(aa[0], bb[0])-min(aa[1], bb[1]) for aa, bb in zip(a["bounds"], b["bounds"]))
    if bound > 1e-8:
        return {"a": a["name"], "b": b["name"], "method": "separating_coordinate_bounds",
                "separation_lower_bound_mm": bound, "overlap_mm3": 0., "passed": True}
    try:
        common = a["shape"].intersect(b["shape"])
        empty = common.wrapped.IsNull()
        valid = empty or common.isValid()
        volume = 0. if empty else abs(common.Volume())
        return {"a": a["name"], "b": b["name"], "method": "OpenCascade_direct_common",
                "overlap_mm3": volume, "valid_common": valid, "passed": valid and volume <= .001}
    except (ValueError, RuntimeError) as error:
        return {"a": a["name"], "b": b["name"], "method": "kernel_result_unresolved",
                "error": str(error), "passed": False}


def controls():
    import cadquery as cq
    def block(name, origin, size):
        shape = cq.Workplane("XY").box(*size, centered=(False, False, False)).val().translate(origin)
        bb = shape.BoundingBox()
        return {"name": name, "shape": shape,
                "bounds": [(getattr(bb, axis+"min"), getattr(bb, axis+"max")) for axis in "xyz"]}
    a = block("unit_cube", (0, 0, 0), (1, 1, 1))
    cases = [
        (block("half_overlap", (.5, 0, 0), (1, 1, 1)), .5, False),
        (block("nested", (.4, .4, .4), (.2, .2, .2)), .008, False),
        (block("touching", (1, 0, 0), (1, 1, 1)), 0., True),
        (block("clear", (1.00005, 0, 0), (1, 1, 1)), 0., True),
    ]
    result = []
    for b, volume, expected_pass in cases:
        row = compare(a, b)
        if row["passed"] != expected_pass or abs(row.get("overlap_mm3", -1)-volume) > 1e-7:
            raise ValueError("Native intersection analytical control failed")
        result.append(row)
    return result


def check_object(index):
    objects, obstacles, components, receipt = geometry.GEOMETRY
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
    reports = {name: json.loads((path/"report.json").read_text()) for name, path in paths.items()}
    for report in reports.values():
        for name, expected in report["input_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError("Assembly input changed: "+name)
    for name in ("skin", "terminals"):
        path = paths[name]/"report.json"
        if reports["foils"]["input_sha256"].get(str(path.relative_to(ROOT))) != digest(path):
            raise ValueError("Joined foils belong to another skin/terminal assembly")
    parts = geometry.selected_parts(paths, reports)
    carrier = json.loads((BASE/"checks/carrier.json").read_text())
    inputs = [Path(__file__), Path(geometry.__file__), BASE/"checks/carrier.json",
              ROOT/"engineering/scripts/source_brep.py", ROOT/"engineering/scripts/analyze_b1_interfaces.py",
              ROOT/"engineering/scripts/prototype_cad.py", *[path/"report.json" for path in paths.values()]]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in inputs}
    folder = ROOT/"build/engineering/prototypes/f1/complete_assembly_common_checks"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Check all F1 actual material/source/carrier/hardware/peer pairs by native common volume and conservative separating bounds; retain every unresolved own-connector interface") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        record["owned_worker_limit"] = args.workers
        numerical_controls = controls()
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        results = {}
        with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
                                 initializer=geometry.initialize, initargs=(parts, carrier)) as pool:
            futures = [pool.submit(check_object, index) for index in range(len(parts))]
            for future in as_completed(futures):
                result = future.result()
                results[result["index"]] = result
                (folder/("part_"+str(result["index"]).zfill(3)+".json")).write_text(json.dumps(result, indent=2)+"\n")
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
        if any(digest(ROOT/name) != expected_hash for name, expected_hash in hashes.items()):
            raise ValueError("An input changed during checking")
        failures = [row for row in checks if not row["passed"]]
        report = {"schema": "yam-f1-complete-assembly-fit/1", "physical_specimens_tested": 0,
                  "parts_checked": [item["name"] for item in parts], "checks": checks, "failures": failures,
                  "passed_declared_checks": not failures, "unqualified_mating_interfaces": unresolved,
                  "source_hard_conversion": results[0]["source_hard_conversion"], "input_sha256": hashes,
                  "analytical_kernel_controls": numerical_controls,
                  "coverage": {"expected_comparisons": expected, "unique_comparisons": len(set(identities)),
                               "worker_limit": args.workers, "native_overlap_limit_mm3": .001},
                  "limits": ["Static nominal material envelopes and a nonpenetration screen; no minimum-clearance distance claim.",
                             "Each actual part is checked against source, carrier, board, fasteners, other components and peers.",
                             "Own connector cavities remain explicitly unqualified; no invented mating holes are used.",
                             "Cured neck seals, strain relief, actual drive, loaded motion and physical performance remain unqualified."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts), "checks": len(checks),
                            "failures": failures, "unqualified_interfaces": len(unresolved)}
        print(json.dumps(record["result"], indent=2))
        if failures:
            raise ValueError("Resolve the retained F1 overlap findings")


if __name__ == "__main__":
    main()
