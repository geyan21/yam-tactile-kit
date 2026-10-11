#!/usr/bin/python3
"""Preserve a checked N1 development state before revising its geometry."""

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
import hashlib

WORK=ROOT/"build/engineering/prototypes/nail"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label",required=True)
    args=parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]{1,80}",args.label):
        parser.error("Use a short lowercase label")
    plan=json.loads((WORK/"nail_manifest.json").read_text())
    for name,expected in plan["source_hashes"].items():
        if digest(ROOT/name)!=expected:
            raise ValueError("Archive the actual checked source before changing it: "+name)
    with execution(ROOT/"build/records","Preserve the current N1 CAD, inputs and visual review before a named design revision") as record:
        folder=WORK/"iterations"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+"_"+args.label)
        folder.mkdir(parents=True,exist_ok=False)
        for name in ("cad","analysis"):
            shutil.copytree(WORK/name,folder/name)
        names=["nail_manifest.json","models.json","nail_assembly.png","nail_exploded.png",
               "nail_gauge_placement.svg","nail_placement.svg","nail_review_drawings.pdf"]
        for name in names:
            if (WORK/name).is_file():
                shutil.copyfile(WORK/name,folder/name)
        source=folder/"source";source.mkdir()
        files=[ROOT/name for name in plan["source_hashes"]]
        files+=[ROOT/"engineering/scripts/draw_nail.py",ROOT/"engineering/scripts/check_nail_fasteners.py"]
        for path in files:
            shutil.copyfile(path,source/path.name)
        receipt={"label":args.label,"physical_specimens_tested":0,
                 "files":{str(path.relative_to(folder)):digest(path) for path in sorted(folder.rglob("*")) if path.is_file()},
                 "note":"Development state preserved before revising the carrier clamp pads. Structural run inputs are preserved separately under fea/."}
        (folder/"iteration.json").write_text(json.dumps(receipt,indent=2)+"\n")
        record["archive"]={"directory":str(folder.relative_to(ROOT)),"files":len(receipt["files"])}
        print(json.dumps(record["archive"],indent=2))


if __name__=="__main__":
    main()
