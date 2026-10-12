#!/usr/bin/python3
"""Check the O1 LED ring with KiCad and export its two designed copper layers."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--kicad-cli", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.is_relative_to(ROOT/"build"):
        parser.error("Use a generated O1 board")
    with execution(ROOT/"build/records", "Independently check O1 LED copper/connectivity and export the two-layer fabrication files only after clean DRC") as record:
        env = dict(os.environ)
        for category in ("CONFIG", "CACHE", "DATA"):
            env["XDG_"+category+"_HOME"] = str(ROOT/"build/engineering/tools/optical-kicad"/category.lower())
        def run(argv, log):
            with log.open("w") as stream:
                process = subprocess.Popen(list(map(str, argv)), stdout=stream, stderr=subprocess.STDOUT, env=env)
                item = {"argv": list(map(str, argv)), "pid": process.pid}
                record.setdefault("commands", []).append(item)
                try:
                    code = process.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    item["intentional_stop"] = "50 second limit on this owned PCB tool"
                    process.terminate(); process.wait(timeout=5); raise
                item["returncode"] = code
                if code:
                    raise RuntimeError(log.read_text()[-3000:])
        run(["/usr/bin/python3", ROOT/"engineering/scripts/check_prototype_pcb.py", source,
             "--name", "o1_blue_ring", "--kicad-cli", args.kicad_cli], source/"native_check.log")
        check = json.loads((source/"latest_check.json").read_text())
        print(json.dumps(check, indent=2), flush=True)
        if check["violations"] or check["unconnected"]:
            raise ValueError("Resolve every native finding before manufacturing")
        output = source/check["directory"]
        manufacture = output/"manufacturing"; manufacture.mkdir()
        board = output/"o1_blue_ring.kicad_pcb"
        run([args.kicad_cli, "pcb", "export", "gerbers", "--output", str(manufacture)+"/",
             "--layers", "F.Cu,B.Cu,F.Paste,F.Mask,B.Mask,F.SilkS,Edge.Cuts", board], output/"gerbers.log")
        run([args.kicad_cli, "pcb", "export", "drill", "--output", str(manufacture)+"/",
             "--format", "excellon", board], output/"drills.log")
        report = {"schema": "yam-o1-led-fabrication/1",
                  **{key: check[key] for key in ("violations", "unconnected", "tool", "source_sha256", "physical_boards_tested")},
                  "checked_pcb_sha256": digest(board), "export_copper_layers": ["F.Cu", "B.Cu"],
                  "files": {p.name: digest(p) for p in sorted(manufacture.iterdir()) if p.is_file()},
                  "checker_sha256": digest(Path(__file__)),
                  "limits": "Digital copper/connectivity only. Physical assembly, brightness, optical uniformity and temperature are untested."}
        (output/"pcb_checks.json").write_text(json.dumps(report, indent=2)+"\n")
        with zipfile.ZipFile(output/"o1_blue_ring_fabrication.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(manufacture.iterdir()):
                archive.write(path, path.name)
            archive.write(output/"pcb_checks.json", "pcb_checks.json")
        record["result"] = {"directory": str(output.relative_to(ROOT)), "violations": 0, "unconnected": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
