#!/usr/bin/python3
"""Verify KiCad rule loading on disposable copies of one F1 routing witness."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.is_relative_to(ROOT) or not args.name.replace("_", "").isalnum():
        parser.error("Select a named, repository-owned routing witness")
    output = source / "rule_probes" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    cli = ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/kicad-cli"
    environment = dict(os.environ)
    for category in ("CONFIG", "CACHE", "DATA"):
        environment["XDG_" + category + "_HOME"] = str(ROOT / "build/engineering/tools/f1-kicad" / category.lower())
    with execution(ROOT / "build/records", "Verify whether a minimal project is required for KiCad to apply custom flex rules; use disposable copies and retain every finding") as record:
        output.mkdir(parents=True, exist_ok=False)
        record["commands"] = []; results = []
        configurations = [(False, False, False), (True, False, False),
                         (False, True, False), (True, True, False), (False, False, True)]
        for project, sentinel, copper_short in configurations:
            case = output / f"project_{int(project)}_sentinel_{int(sentinel)}_short_{int(copper_short)}"
            case.mkdir()
            for suffix in ("kicad_pcb", "kicad_dru"):
                shutil.copyfile(source / f"{args.name}.{suffix}", case / f"{args.name}.{suffix}")
            shutil.copyfile(source / "fp-lib-table", case / "fp-lib-table")
            shutil.copytree(source / "F1.pretty", case / "F1.pretty")
            if project:
                (case / f"{args.name}.kicad_pro").write_text("{}\n")
            if sentinel:
                with (case / f"{args.name}.kicad_dru").open("a") as stream:
                    stream.write('\n(rule "QA sentinel 5 mm" (constraint clearance (min 5mm)))\n')
            if copper_short:
                data = json.loads((source / f"{args.name}.json").read_text())
                fingers = [row for row in data["fingers"] if row["net"]]
                first = fingers[0]
                second = next(row for row in fingers[1:] if row["net"] != first["net"])
                path = case / f"{args.name}.kicad_pcb"
                text = path.read_text()
                net = re.search(r'\(net (\d+) "' + re.escape(first["net"]) + r'"\)', text).group(1)
                a, b = first["center"], second["center"]
                injected = (f'(segment (start {a[0]} {a[1]}) (end {b[0]} {b[1]})'
                            f' (width 0.2) (layer "F.Cu") (net {net}))')
                path.write_text(text.rstrip()[:-1] + "\n" + injected + "\n)\n")
            command = [str(cli), "pcb", "drc", "--format", "json", "--all-track-errors",
                       "--output", str(case / "drc.json"), str(case / f"{args.name}.kicad_pcb")]
            with (case / "drc.log").open("w") as log:
                process = subprocess.Popen(command, cwd=case, env=environment, stdout=log, stderr=subprocess.STDOUT)
                entry = {"command": command, "pid": process.pid}
                record["commands"].append(entry)
                try:
                    code = process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    record["intentional_stop_requests"].append(f"Stop owned rule-probe process {process.pid}: timeout")
                    process.kill(); process.wait()
                    raise RuntimeError("KiCad rule probe timed out")
            entry["exit_code"] = code
            if code:
                raise RuntimeError((case / "drc.log").read_text()[-2000:])
            drc = json.loads((case / "drc.json").read_text())
            types = {}
            for item in drc["violations"]:
                types[item["type"]] = types.get(item["type"], 0) + 1
            results.append({"project_file": project, "sentinel_rule": sentinel, "injected_copper_short": copper_short,
                            "violation_types": types, "unconnected": len(drc["unconnected_items"])})
            if copper_short and not any(key in types for key in ("clearance", "shorting_items")):
                raise ValueError("The DRC failed to detect an injected copper short under the coverlay allowance")
        report = {"evidence_kind": "software_rule_loading_probe",
                  "source": str(source.relative_to(ROOT)), "cases": results}
        (output / "probe.json").write_text(json.dumps(report, indent=2) + "\n")
        record["result"] = report
        print(json.dumps({"directory": str(output.relative_to(ROOT)), **report}, indent=2))


if __name__ == "__main__":
    main()
