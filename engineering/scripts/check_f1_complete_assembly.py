#!/usr/bin/python3
"""Check the complete F1 material assembly with retained skins and reinforced foils."""

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
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
from shapely.geometry import Polygon
from tactile_kit.records import execution
from source_brep import load as source_solid
from analyze_b1_interfaces import original_profile, extruded_profile
from prototype_cad import x_cylinder, yz_prism
from check_f1_tail_fit import check_pair
from screen_f1_feedback import digest

BASE = ROOT / "engineering/development/f1/r3"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("foils", "skin", "terminals"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ("foils", "skin", "terminals")}
    reports = {name: json.loads((path / "report.json").read_text()) for name, path in paths.items()}
    for report in reports.values():
        for name, expected in report["input_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError("Assembly input changed")
    for name in ("skin", "terminals"):
        key = str((paths[name] / "report.json").relative_to(ROOT))
        if reports["foils"]["input_sha256"].get(key) != digest(paths[name] / "report.json"):
            raise ValueError("Joined foil references belong to another material assembly")
    carrier = json.loads((BASE / "checks/carrier.json").read_text())
    folder = ROOT / "build/engineering/prototypes/f1/complete_assembly_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check every actual F1 material part against source, peers and installed board/carrier envelopes; retain unqualified manufacturer mating cavities explicitly") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [Path(__file__), BASE / "checks/carrier.json", ROOT / "engineering/scripts/check_f1_tail_fit.py",
                  *[path / "report.json" for path in paths.values()]]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        connector_by_foil = {case["foil"]: case["connector"] for case in reports["terminals"]["cases"]}
        objects = []
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
                    raise ValueError("Material part changed")
                own_connector = next((connector for foil, connector in connector_by_foil.items()
                                      if name.startswith(foil+"_")), None)
                objects.append({"name": name, "shape": cq.importers.importStep(str(path)).val(),
                                "own_connector": own_connector})
        hard, receipt = source_solid("hard_frame")
        mesh, profile, _ = original_profile(); soft = extruded_profile(profile)
        if abs(soft.Volume()-mesh.volume) > mesh.volume*1e-5:
            raise ValueError("TPU source conversion changed")
        obstacles = [("source_hard", hard), ("source_TPU", soft)]
        for part in carrier["parts"]:
            if part["kind"] not in ("fabricate", "reference_only"):
                continue
            path = BASE / part["step"]
            if digest(path) != part["sha256_step"]:
                raise ValueError("Board/carrier reference changed")
            obstacles.append((part["id"], cq.importers.importStep(str(path)).val()))
        for item in carrier["fastener_envelopes"]:
            y, z = item["center_yz_mm"]
            obstacles.append((item["name"], x_cylinder(item["start_x_mm"], item["height_mm"], y, z, item["diameter_mm"]/2)))
        components = [(item["reference"], yz_prism(Polygon(item["body_yz_mm"]), item["native_x_interval_mm"][0],
                                                   item["native_x_interval_mm"][1]-item["native_x_interval_mm"][0]))
                      for item in carrier["components"]]
        checks, unresolved = [], []
        for index, item in enumerate(objects):
            name, shape = item["name"], item["shape"]
            for other_name, other in obstacles:
                checks.append(check_pair(name, shape, other_name, other))
            for other_name, other in components:
                if other_name == item["own_connector"]:
                    unresolved.append({"part": name, "connector": other_name,
                                       "reason": "Unverified actual connector cavity/contact datum; no invented clearance volume."})
                    continue
                checks.append(check_pair(name, shape, other_name, other))
            for other in objects[index+1:]:
                checks.append(check_pair(name, shape, other["name"], other["shape"]))
            (folder / "partial.json").write_text(json.dumps(
                {"checks": checks, "unresolved": unresolved, "parts_checked": index+1}, indent=2)+"\n")
            print(name+f": {len(checks)} comparisons; {sum(not c['passed'] for c in checks)} findings", flush=True)
        failed = [row for row in checks if not row["passed"]]
        report = {"schema": "yam-f1-complete-assembly-fit/1", "physical_specimens_tested": 0,
                  "parts_checked": [item["name"] for item in objects], "checks": checks, "failures": failed,
                  "passed_declared_checks": not failed, "unqualified_mating_interfaces": unresolved,
                  "source_hard_conversion": receipt,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "limits": ["Static nominal material envelopes, not physical construction, loaded deformation or fatigue.",
                             "Unqualified connector cavities remain listed separately from the passing comparisons.",
                             "Neck sealing, strain relief, actual gripper drive and broad-object access require separate checks."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(objects),
                            "checks": len(checks), "failures": failed, "unqualified_interfaces": len(unresolved)}
        print(json.dumps(record["result"], indent=2))
        if failed:
            raise ValueError("Resolve F1 assembly intersections before release")


if __name__ == "__main__":
    main()
