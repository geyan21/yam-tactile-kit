#!/usr/bin/python3
"""Check complete F1 terminal envelopes and backing pieces against source and peer hardware."""

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
    parser.add_argument("terminal_cad", type=Path)
    args = parser.parse_args()
    source = args.terminal_cad.resolve()
    plan = json.loads((source / "report.json").read_text())
    for name, expected in plan["input_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Terminal inputs changed")
    carrier = json.loads((BASE / "checks/carrier.json").read_text())
    folder = source / "fit_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check the twelve complete F1 terminal material assemblies against the source finger, carrier, fasteners, board and other components; retain the actual unqualified connector cavities") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [source / "report.json", BASE / "checks/carrier.json", Path(__file__),
                  ROOT / "engineering/scripts/check_f1_tail_fit.py",
                  ROOT / "engineering/scripts/source_brep.py", ROOT / "engineering/scripts/analyze_b1_interfaces.py"]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        shapes = {}
        for part in plan["parts"]:
            path = source / part["step"]
            if digest(path) != part["sha256_step"]:
                raise ValueError("Terminal CAD changed")
            shapes[part["id"]] = cq.importers.importStep(str(path)).val()
        hard, receipt = source_solid("hard_frame")
        mesh, profile, _ = original_profile(); soft = extruded_profile(profile)
        if abs(soft.Volume()-mesh.volume) > mesh.volume*1e-5:
            raise ValueError("Source TPU conversion changed")
        obstacles = [("source_hard", hard), ("source_TPU", soft)]
        for part in carrier["parts"]:
            if part["kind"] != "fabricate" and part["kind"] != "reference_only":
                continue
            path = BASE / part["step"]
            if digest(path) != part["sha256_step"]:
                raise ValueError("Carrier reference changed")
            obstacles.append((part["id"], cq.importers.importStep(str(path)).val()))
        for item in carrier["fastener_envelopes"]:
            y, z = item["center_yz_mm"]
            obstacles.append((item["name"], x_cylinder(item["start_x_mm"], item["height_mm"], y, z, item["diameter_mm"]/2)))
        components = [(item["reference"], yz_prism(Polygon(item["body_yz_mm"]), item["native_x_interval_mm"][0],
                                                   item["native_x_interval_mm"][1]-item["native_x_interval_mm"][0]))
                      for item in carrier["components"]]
        assemblies = []
        for case in plan["cases"]:
            chosen = [(name, shape) for name, shape in shapes.items() if name.startswith(case["foil"]+"_")]
            assemblies.append((case, chosen, cq.Compound.makeCompound([shape for _, shape in chosen])))
        checks, mating = [], []
        for index, (case, chosen, assembly) in enumerate(assemblies):
            for name, shape in obstacles:
                checks.append(check_pair(case["foil"], assembly, name, shape))
            for name, shape in components:
                if name == case["connector"]:
                    mating.append({"foil": case["foil"], "connector": name, "qualified": False,
                                   "reason": "The real internal cavity and seated contact datum are not supplied by the available geometry."})
                    continue
                checks.append(check_pair(case["foil"], assembly, name, shape))
            for other, _, shape in assemblies[index+1:]:
                checks.append(check_pair(case["foil"], assembly, other["foil"], shape))
            for first, (name, shape) in enumerate(chosen):
                for other_name, other_shape in chosen[first+1:]:
                    checks.append(check_pair(name, shape, other_name, other_shape))
            (folder / "partial.json").write_text(json.dumps(checks, indent=2)+"\n")
            print(case["foil"]+f": {len(checks)} cumulative checks; {sum(not c['passed'] for c in checks)} findings", flush=True)
        failed = [row for row in checks if not row["passed"]]
        report = {"schema": "yam-f1-finished-terminal-fit/1", "physical_specimens_tested": 0,
                  "checks": checks, "failures": failed, "passed_declared_checks": not failed,
                  "unqualified_mating_interfaces": mating, "source_hard_conversion": receipt,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "limits": ["Nominal static material geometry; no loaded TPU motion, cable fatigue, latch operation or actual drive fit.",
                             "The real mating cavities remain explicitly unqualified rather than being replaced with invented clearance holes.",
                             "Complete sensing-body plating, sealing and dynamic slack are separate work."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "checks": len(checks),
                            "failures": failed, "unqualified_connector_interfaces": len(mating)}
        print(json.dumps(record["result"], indent=2))
        if failed:
            raise ValueError("Resolve the terminal assembly findings before release")


if __name__ == "__main__":
    main()
