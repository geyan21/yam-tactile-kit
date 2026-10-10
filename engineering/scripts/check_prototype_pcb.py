#!/usr/bin/python3
"""Independently check a generated prototype PCB and export only clean boards."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path,help="Directory with the generated PCB and its local footprint library")
    parser.add_argument("--name",required=True)
    parser.add_argument("--export",action="store_true")
    parser.add_argument("--kicad-cli",type=Path,
                        default=ROOT/"build/engineering/tools/b1-kicad/squashfs-root/bin/kicad-cli")
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.is_relative_to(ROOT) or not args.name.replace("_","").isalnum():
        parser.error("Use a repository-owned source directory and a simple board name")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = source/"checks"/stamp
    output.mkdir(parents=True,exist_ok=True)
    for suffix in ("kicad_pcb","kicad_dru"):
        shutil.copyfile(source/f"{args.name}.{suffix}",output/f"{args.name}.{suffix}")
    for library in source.glob("*.pretty"):
        shutil.copytree(library,output/library.name,dirs_exist_ok=True)
    shutil.copyfile(source/"fp-lib-table",output/"fp-lib-table")
    env = dict(os.environ)
    for category in ("CONFIG","CACHE","DATA"):
        env[f"XDG_{category}_HOME"] = str(ROOT/f"build/engineering/tools/prototype-kicad/{category.lower()}")
    with execution(ROOT/"build/records","Check prototype copper/connectivity using KiCad, retaining every DRC finding") as record:
        record["commands"] = []
        def run(command,name):
            argv = [str(args.kicad_cli),*command]
            with (output/f"{name}.log").open("w") as stream:
                process = subprocess.Popen(argv,cwd=output,env=env,stdout=stream,stderr=subprocess.STDOUT)
                receipt = {"argv":argv,"pid":process.pid}
                record["commands"].append(receipt)
                try:
                    code = process.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    receipt["intentional_stop"] = "50 second limit on this owned KiCad process"
                    process.terminate()
                    process.wait(timeout=10)
                    raise
                receipt["returncode"] = code
                if code:
                    print((output/f"{name}.log").read_text()[-4000:])
                    raise RuntimeError(f"KiCad {name} exited {code}")
        pcb = output/f"{args.name}.kicad_pcb"
        run(["--version"],"version")
        run(["pcb","drc","--refill-zones","--save-board","--format","json",
             "--all-track-errors","--output",str(output/"drc.json"),str(pcb)],"drc")
        drc = json.loads((output/"drc.json").read_text())
        violations = drc.get("violations",[])
        unconnected = drc.get("unconnected_items",[])
        summary = {"violations":len(violations),"unconnected":len(unconnected),
                   "tool":(output/"version.log").read_text().strip(),
                   "source_sha256":digest(source/f"{args.name}.kicad_pcb"),
                   "physical_boards_tested":0}
        record["checks"] = summary
        (source/"latest_check.json").write_text(json.dumps({
            "directory":str(output.relative_to(source)),**summary},indent=2)+"\n")
        print(json.dumps(summary,indent=2))
        for item in (violations+unconnected)[:25]:
            print(item.get("type"),item.get("description")," | ".join(
                p["description"]+" @ "+str(p.get("pos")) for p in item.get("items",[])))
        if not args.export:
            return
        if violations or unconnected:
            raise ValueError("Manufacturing export refused: resolve every DRC finding and unconnected item")
        manufacture = output/"manufacturing"
        manufacture.mkdir(exist_ok=True)
        run(["pcb","export","gerbers","--output",str(manufacture)+"/",
             "--layers","F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,F.Mask,B.Mask,F.SilkS,Edge.Cuts",str(pcb)],"gerbers")
        run(["pcb","export","drill","--output",str(manufacture)+"/","--format","excellon",str(pcb)],"drills")
        receipt = {
            "schema":"yam-prototype-pcb-check/1",**summary,"checked_pcb_sha256":digest(pcb),
            "files":{p.name:digest(p) for p in sorted(manufacture.iterdir()) if p.is_file()},
            "limits":"Copper and connectivity only. Physical assembly, power, sensor axes, fit, readout and performance remain untested.",
        }
        (output/"pcb_checks.json").write_text(json.dumps(receipt,indent=2)+"\n")
        with zipfile.ZipFile(output/f"{args.name}_fabrication.zip","w",zipfile.ZIP_DEFLATED) as archive:
            for p in sorted(manufacture.iterdir()):
                if p.is_file():
                    archive.write(p,p.name)
            archive.write(output/"pcb_checks.json","pcb_checks.json")
        print("Fabrication files exported after clean independent DRC.")


if __name__ == "__main__":
    main()
