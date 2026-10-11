#!/usr/bin/python3
"""Preserve a named new-prototype development state before changing its inputs."""

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design",required=True)
    parser.add_argument("--label",required=True)
    args=parser.parse_args()
    if not all(re.fullmatch(r"[a-z0-9_-]{1,80}",value) for value in (args.design,args.label)):
        parser.error("Use bounded lowercase identifiers")
    work=ROOT/"build/engineering/prototypes"/args.design
    manifest=work/(args.design+"_manifest.json")
    plan=json.loads(manifest.read_text())
    for name,expected in plan["source_hashes"].items():
        if digest(ROOT/name)!=expected:
            raise ValueError("Archive the evaluated inputs before editing them: "+name)
    with execution(ROOT/"build/records","Preserve the evaluated "+args.design+" state before a named design revision") as record:
        folder=work/"iterations"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+"_"+args.label)
        folder.mkdir(parents=True,exist_ok=False)
        shutil.copytree(work/"cad",folder/"cad")
        shutil.copyfile(manifest,folder/manifest.name)
        source=folder/"source";source.mkdir()
        for name in plan["source_hashes"]:
            path=ROOT/name
            if path.suffix in (".py",".json"):
                shutil.copyfile(path,source/path.name)
        receipt={"design":args.design,"label":args.label,"physical_evidence":False,
                 "files":{str(path.relative_to(folder)):digest(path) for path in sorted(folder.rglob("*")) if path.is_file()},
                 "note":"Generated CAD and evaluated inputs only. Separate raw measurements and solver runs remain untouched."}
        (folder/"state.json").write_text(json.dumps(receipt,indent=2)+"\n")
        record["archive"]={"folder":str(folder.relative_to(ROOT)),"files":len(receipt["files"])}
        print(json.dumps(record["archive"],indent=2))


if __name__=="__main__":
    main()
