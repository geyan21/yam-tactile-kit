#!/usr/bin/python3
"""Check K1 retained cell assemblies against the source finger, formed terminals and other cells."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/capacitive-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
from tactile_kit.records import execution
from source_brep import load as source_solid
from analyze_b1_interfaces import original_profile, extruded_profile
from check_f1_tail_fit import check_pair
from screen_f1_feedback import digest


def checked_parts(folder, report):
    result = {}
    for part in report["parts"]:
        path = folder / part["step"]
        if digest(path) != part["sha256_step"]:
            raise ValueError("CAD changed: "+str(path))
        result[part["id"]] = cq.importers.importStep(str(path)).val()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mechanics", type=Path)
    parser.add_argument("foil_fit", type=Path)
    parser.add_argument("--sites", type=int, nargs="+", default=list(range(6)))
    args = parser.parse_args()
    if len(set(args.sites)) != len(args.sites) or set(args.sites)-set(range(6)):
        parser.error("Use distinct sites 0..5")
    mechanics, fit = args.mechanics.resolve(), args.foil_fit.resolve()
    mech = json.loads((mechanics / "report.json").read_text())
    foil = json.loads((fit / "report.json").read_text())
    if not foil["passed_declared_checks"] or set(foil["sites_checked"]) != set(range(6)):
        raise ValueError("Use the complete passing formed-foil check")
    for name, expected in mech["input_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Mechanical inputs changed")
    folder = mechanics / "assembly_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check K1 actual cell compounds against the source finger, all formed terminals and the other cells; separately check nominal plate/cover/stop/ground-bond intersections") as record:
        folder.mkdir(parents=True)
        inputs = [Path(__file__), mechanics / "report.json", fit / "report.json",
                  ROOT / "engineering/scripts/check_f1_tail_fit.py"]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        all_parts = checked_parts(mechanics, mech)
        foil_parts = checked_parts(fit, foil)
        parts = {key: value for key, value in all_parts.items() if not key.startswith("k1_ref_")}
        cells = {site: {key: shape for key, shape in parts.items() if key.startswith(f"k1_ch{site}_")}
                 for site in range(6)}
        compounds = {site: cq.Compound.makeCompound(list(values.values())) for site, values in cells.items()}
        hard, receipt = source_solid("hard_frame")
        mesh, profile, _ = original_profile(); soft = extruded_profile(profile)
        if abs(mesh.volume-soft.Volume()) > mesh.volume*1e-5:
            raise ValueError("Source TPU conversion changed its volume")
        checks = []
        for site in args.sites:
            name = f"CH{site}_retained_cell"; shape = compounds[site]
            for other_name, other in (("source_hard", hard), ("source_TPU", soft)):
                checks.append(check_pair(name, shape, other_name, other))
                print(name+" / "+other_name+": "+str(checks[-1]["passed"]), flush=True)
            for other_name, other in foil_parts.items():
                checks.append(check_pair(name, shape, other_name, other))
            for peer in range(site+1, 6):
                checks.append(check_pair(name, shape, f"CH{peer}_retained_cell", compounds[peer]))
            # These interfaces depend on the actual Boolean vent and bond
            # ports, so inspect native CAD rather than assuming ideal layers.
            values = cells[site]
            seen = set()
            for role in ("retained_plate", "ground_bond_0", "ground_bond_1"):
                key = f"k1_ch{site}_"+role
                for other_key, other in values.items():
                    pair = tuple(sorted((key, other_key)))
                    if key == other_key or pair in seen:
                        continue
                    seen.add(pair)
                    checks.append(check_pair(key, values[key], other_key, other))
            (folder / "partial_checks.json").write_text(json.dumps(checks, indent=2)+"\n")
            print(name+f": {len(checks)} cumulative checks, {sum(not c['passed'] for c in checks)} findings", flush=True)
        failures = [row for row in checks if not row["passed"]]
        report = {"schema": "yam-k1-installed-cell-fit/1", "physical_specimens_tested": 0,
                  "sites_checked": args.sites, "checks": checks, "failures": failures,
                  "passed_declared_checks": not failures, "source_hard_conversion": receipt,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "limits": ["Nominal unloaded source geometry only; no moving jaw, loaded TPU or real fabrication tolerances.",
                             "Known stop/bond film layers and foot pieces are defined by separate source-chart intervals; their plate/cover ports are checked here.",
                             "The separate lip/stop review covers nominal full-stroke rigid-plate motion.",
                             "A reference cell is checked in its electronics case, separately from these six finger cells."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "checks": len(checks), "failures": failures}
        print(json.dumps(record["result"], indent=2))
        if failures:
            raise ValueError("Resolve K1 cell fit findings before release")


if __name__ == "__main__":
    main()
