#!/usr/bin/python3
"""Finalize release labels only after proving that checked physical inputs are unchanged."""

from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
OUTPUT=ROOT/"build/engineering/prototypes/nail"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def physical(configuration):
    return {key:value for key,value in configuration.items() if key not in ("revision","status")}


def main():
    configuration=ROOT/"engineering/designs/nail.json"
    manifest=OUTPUT/"nail_manifest.json"
    cfg=json.loads(configuration.read_text());plan=json.loads(manifest.read_text())
    for name,expected in plan["source_hashes"].items():
        if digest(ROOT/name)!=expected:
            raise ValueError("Finalize only an already checked source state")
    review=json.loads((OUTPUT/"nail_structural_review.json").read_text())
    if not review["convergence"]["passed"] or not review["motion_screen_met"]:
        raise ValueError("Finish the numerical review before finalizing labels")
    for entry in review["inputs"]:
        frozen=json.loads((ROOT/entry["directory"]/"inputs/configuration.json").read_text())
        if physical(frozen)!=physical(cfg):
            raise ValueError("Physical design values changed after the reviewed runs")
    artifacts={part[key]:part["sha256_"+key] for part in plan["parts"] for key in ("step","stl")}
    artifacts[plan["analysis_step"]]=plan["analysis_step_sha256"]
    for name,expected in artifacts.items():
        if digest(OUTPUT/name)!=expected:
            raise ValueError("Checked geometry export changed")
    with execution(ROOT/"build/records","Finalize N1 release labels while verifying unchanged physical parameters and every geometry export; retain original run configurations") as record:
        archive=OUTPUT/"revision_metadata"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        archive.mkdir(parents=True,exist_ok=False)
        (archive/"configuration_before.json").write_bytes(configuration.read_bytes())
        (archive/"manifest_before.json").write_bytes(manifest.read_bytes())
        old_hash=digest(configuration)
        cfg["revision"]="N1.1"
        cfg["status"]="Digital prototype source; physical assembly and qualification pending"
        configuration.write_text(json.dumps(cfg,indent=2)+"\n")
        plan["revision"]="N1.1"
        plan["status"]="digital prototype; physical qualification pending"
        plan["source_hashes"]["engineering/designs/nail.json"]=digest(configuration)
        plan["source_hashes"][str(Path(__file__).relative_to(ROOT))]=digest(Path(__file__))
        plan["release_label_finalization"]={
            "prior_configuration_sha256":old_hash,
            "physical_configuration_sha256":hashlib.sha256(json.dumps(physical(cfg),sort_keys=True).encode()).hexdigest(),
            "geometry_exports_unchanged":True,
            "note":"Only revision/status labels changed. The original structural-run configurations and results remain preserved."}
        manifest.write_text(json.dumps(plan,indent=2)+"\n")
        for name,expected in artifacts.items():
            if digest(OUTPUT/name)!=expected:
                raise ValueError("Metadata finalization unexpectedly changed geometry")
        record["finalized"]={"revision":"N1.1","geometry_files_unchanged":len(artifacts),
                             "prior_metadata_directory":str(archive.relative_to(ROOT))}
        print(json.dumps(record["finalized"],indent=2))


if __name__=="__main__":
    main()
