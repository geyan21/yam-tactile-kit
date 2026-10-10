#!/usr/bin/python3
"""Run isolated KiCad DRC, keep the full report, and export only a checked PCB."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kicad-cli",type=Path,default=ROOT/"build/engineering/tools/b1-kicad/squashfs-root/bin/kicad-cli")
    parser.add_argument("--export",action="store_true")
    args=parser.parse_args()
    output=ROOT/"build/engineering/b1/pcb"
    output.mkdir(parents=True,exist_ok=True)
    source=ROOT/"engineering/electronics/b1"
    for suffix in ("kicad_pcb","kicad_dru"):
        shutil.copyfile(source/f"b1_head.{suffix}",output/f"b1_head.{suffix}")
    # The geometry is embedded, with a local footprint library for parity checks.
    if (source/"B1.pretty").exists():
        shutil.copytree(source/"B1.pretty",output/"B1.pretty",dirs_exist_ok=True)
        shutil.copyfile(source/"fp-lib-table",output/"fp-lib-table")
    environment=dict(os.environ)
    for category in ("CONFIG","CACHE","DATA"):
        environment[f"XDG_{category}_HOME"]=str(ROOT/f"build/engineering/tools/b1-kicad/{category.lower()}")
    with execution(ROOT/"build/records","Run KiCad DRC and manufacturing export on the isolated B1 PCB; no hardware programming") as record:
        record["commands"]=[]
        def run(arguments,name,accepted=(0,)):
            command=[str(args.kicad_cli),*arguments]
            with (output/f"{name}.log").open("w") as stream:
                process=subprocess.Popen(command,cwd=output,env=environment,stdout=stream,stderr=subprocess.STDOUT)
                item={"argv":command,"pid":process.pid};record["commands"].append(item)
                try:
                    code=process.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    item["intentional_stop"]="50 second command limit";process.terminate();process.wait(timeout=10)
                    raise
                item["returncode"]=code
                if code not in accepted:
                    print((output/f"{name}.log").read_text()[-4000:])
                    raise RuntimeError(f"KiCad {name} exited {code}")
        run(["--version"],"version")
        run(["pcb","drc","--refill-zones","--save-board","--format","json",
             "--all-track-errors","--output",str(output/"drc.json"),str(output/"b1_head.kicad_pcb")],"drc")
        report=json.loads((output/"drc.json").read_text())
        problems=report.get("violations",[])+report.get("unconnected_items",[])
        print(json.dumps({"violations":len(report.get("violations",[])),"unconnected":len(report.get("unconnected_items",[]))}))
        for problem in problems:
            print(problem.get("severity"),problem.get("description")," | ".join(
                item["description"]+" @ "+str(item.get("pos")) for item in problem.get("items",[])))
        record["drc_counts"]={key:len(report.get(key,[])) for key in ("violations","unconnected_items")}
        if not args.export:return
        if problems:raise ValueError("PCB cannot be exported until DRC findings are resolved")
        manufacturing=output/"manufacturing";manufacturing.mkdir(exist_ok=True)
        run(["pcb","export","gerbers","--output",str(manufacturing)+"/",
             "--layers","F.Cu,B.Cu,F.Paste,F.Mask,B.Mask,F.SilkS,Edge.Cuts",
             str(output/"b1_head.kicad_pcb")],"gerbers")
        run(["pcb","export","drill","--output",str(manufacturing)+"/",
             "--format","excellon",str(output/"b1_head.kicad_pcb")],"drills")
        receipt={"tool":(output/"version.log").read_text().strip(),
                 "source_pcb_sha256":hashlib.sha256((source/"b1_head.kicad_pcb").read_bytes()).hexdigest(),
                 "checked_pcb_sha256":hashlib.sha256((output/"b1_head.kicad_pcb").read_bytes()).hexdigest(),
                 "drc_violations":0,"unconnected_items":0,"physical_boards_tested":0,
                 "limits":"Copper/connectivity checks only. Assembly, power, field axis and I2C have not been tested on hardware.",
                 "files":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(manufacturing.iterdir()) if p.is_file()}}
        (output/"pcb_checks.json").write_text(json.dumps(receipt,indent=2)+"\n")
        with zipfile.ZipFile(output/"b1_head_fabrication.zip","w",zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(manufacturing.iterdir()):
                if path.is_file():archive.write(path,path.name)
            archive.write(output/"pcb_checks.json","pcb_checks.json")
        print(json.dumps(receipt,indent=2))


if __name__=="__main__":
    main()
