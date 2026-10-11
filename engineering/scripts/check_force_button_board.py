#!/usr/bin/python3
"""Use the retained native PCB checker, then export FB1's two copper layers."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--kicad-cli", type=Path, default=ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/kicad-cli")
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.is_relative_to(ROOT / "build"):
        parser.error("Use a generated FB1 board directory")
    with execution(ROOT / "build/records", "Independently check FB1 using the preserved native checker, then export only the two designed copper layers") as record:
        environment = dict(os.environ)
        for category in ("CONFIG", "CACHE", "DATA"):
            environment["XDG_"+category+"_HOME"] = str(ROOT / "build/engineering/tools/prototype-kicad" / category.lower())

        def run(argv, destination):
            with destination.open("w") as stream:
                process = subprocess.Popen(list(map(str, argv)), stdout=stream, stderr=subprocess.STDOUT, env=environment)
                item = {"argv": list(map(str, argv)), "pid": process.pid}
                record.setdefault("commands", []).append(item)
                try:
                    code = process.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    item["intentional_stop"] = "50 second limit on this owned PCB tool"
                    process.terminate(); process.wait(timeout=5); raise
                item["returncode"] = code
                if code:
                    raise RuntimeError(destination.read_text()[-3000:])

        run(["/usr/bin/python3", ROOT / "engineering/scripts/check_prototype_pcb.py", source,
             "--name", "fb1_sensor", "--kicad-cli", args.kicad_cli], source / "fb1_check.log")
        receipt = json.loads((source / "latest_check.json").read_text())
        if receipt["violations"] or receipt["unconnected"]:
            raise ValueError("Resolve all native PCB findings before manufacturing export")
        output = source / receipt["directory"]
        manufacture = output / "manufacturing"; manufacture.mkdir(exist_ok=False)
        board = output / "fb1_sensor.kicad_pcb"
        run([args.kicad_cli, "pcb", "export", "gerbers", "--output", str(manufacture)+"/",
             "--layers", "F.Cu,B.Cu,F.Paste,F.Mask,B.Mask,F.SilkS,Edge.Cuts", board], output / "gerbers.log")
        run([args.kicad_cli, "pcb", "export", "drill", "--output", str(manufacture)+"/",
             "--format", "excellon", board], output / "drills.log")
        result = {"schema": "yam-prototype-pcb-check/1", **{k: receipt[k] for k in (
            "violations", "unconnected", "tool", "source_sha256", "physical_boards_tested")},
                  "checked_pcb_sha256": digest(board), "export_copper_layers": ["F.Cu", "B.Cu"],
                  "files": {p.name: digest(p) for p in sorted(manufacture.iterdir()) if p.is_file()},
                  "checker_sha256": digest(ROOT / "engineering/scripts/check_prototype_pcb.py"),
                  "limits": "Copper/connectivity and manufacturing export only; physical PCB assembly, force and contact remain untested."}
        (output / "pcb_checks.json").write_text(json.dumps(result, indent=2)+"\n")
        with zipfile.ZipFile(output / "fb1_sensor_fabrication.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(manufacture.iterdir()):
                archive.write(path, path.name)
            archive.write(output / "pcb_checks.json", "pcb_checks.json")
        record["result"] = {"directory": str(output.relative_to(ROOT)), "violations": 0,
                            "unconnected": 0, "export_copper_layers": ["F.Cu", "B.Cu"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
