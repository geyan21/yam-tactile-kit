#!/usr/bin/python3
"""Preserve the exact configuration, analysis geometry and solver scripts per C1 run."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_inputs(folder,geometry):
    destination = folder/"inputs"
    destination.mkdir(exist_ok=True)
    sources = {
        "configuration.json":ROOT/"engineering/designs/c1.json",
        "assembly_manifest.json":ROOT/"build/engineering/prototypes/c1/c1_manifest.json",
        "analysis.step":geometry,
        "run_c1_fea.py":ROOT/"engineering/scripts/run_c1_fea.py",
        "structural_tools.py":ROOT/"engineering/scripts/structural_tools.py",
        "tools.json":ROOT/"build/engineering/tools/fea/tools.json",
    }
    result = {}
    for name,source in sources.items():
        target = destination/name
        checksum = digest(source)
        if target.exists() and digest(target)!=checksum:
            raise ValueError(f"Refusing to overwrite an earlier input snapshot: {target}")
        if not target.exists():
            shutil.copyfile(source,target)
        result[name] = checksum
    (destination/"manifest.json").write_text(json.dumps(result,indent=2)+"\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("completed_run",type=Path)
    args = parser.parse_args()
    folder = args.completed_run.resolve()
    if not folder.is_relative_to(ROOT/"build/engineering/prototypes/c1/fea"):
        parser.error("Select a C1 run within this checkout")
    report = json.loads((folder/"screen.json").read_text())
    geometry = ROOT/"build/engineering/prototypes/c1/analysis/c1_bonded_assembly.step"
    if digest(geometry)!=report["geometry_sha256"]:
        raise ValueError("The original analysis geometry is no longer current")
    for name,expected in report["input_hashes"].items():
        if digest(ROOT/name)!=expected:
            raise ValueError(f"Cannot backfill altered source: {name}")
    with execution(ROOT/"build/records","Preserve hash-matching inputs for the completed first C1 calculation before revising its geometry") as record:
        record["snapshot"] = save_inputs(folder,geometry)
        print(json.dumps({"preserved":str(folder/"inputs"),"files":len(record["snapshot"])},indent=2))


if __name__=="__main__":
    main()
