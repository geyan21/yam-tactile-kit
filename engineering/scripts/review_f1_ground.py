#!/usr/bin/python3
"""Export the actual checked inner copper plane and its crossover inventory."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest

CLI = ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/kicad-cli"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checked_directory", type=Path)
    parser.add_argument("routing", type=Path)
    args = parser.parse_args()
    checked, routing = args.checked_directory.resolve(), args.routing.resolve()
    if not all(p.is_relative_to(ROOT) for p in (checked, routing)):
        parser.error("Use repository-owned checked geometry")
    summary = json.loads((checked / "summary.json").read_text())
    board = checked / "f1_wrist.kicad_pcb"
    if not summary["passed"] or digest(board) != summary["checked_pcb_sha256"]:
        raise ValueError("Use an unchanged, clean independent check")
    route = json.loads(routing.read_text())
    folder = checked / "ground_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Export the checked F1 inner plane for visual inspection and record its signal-crossing lengths; keep KiCad settings in the owned tool directory") as record:
        folder.mkdir(parents=True, exist_ok=False)
        env = dict(os.environ)
        for category in ("CONFIG", "CACHE", "DATA"):
            env["XDG_"+category+"_HOME"] = str(ROOT / "build/engineering/tools/f1-wrist-kicad" / category.lower())
        pdf = folder / "inner_ground.pdf"
        commands = [
            [str(CLI), "pcb", "export", "pdf", "--mode-single", "--layers", "In1.Cu,Edge.Cuts",
             "--black-and-white", "--scale", "0", "--output", str(pdf), str(board)],
            ["/usr/bin/pdftoppm", "-f", "1", "-singlefile", "-scale-to", "2400", "-png",
             str(pdf), str(folder / "inner_ground")],
        ]
        record["commands"] = []
        for index, command in enumerate(commands):
            with (folder / f"export_{index}.log").open("w") as stream:
                process = subprocess.Popen(command, cwd=folder, env=env, stdout=stream, stderr=subprocess.STDOUT)
                item = {"command": command, "pid": process.pid}
                record["commands"].append(item)
                try:
                    code = process.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    item["intentional_stop"] = "50-second bound on owned drawing export"
                    process.terminate(); process.wait(timeout=5)
                    raise
                item["exit_code"] = code
                if code:
                    raise RuntimeError((folder / f"export_{index}.log").read_text()[-2000:])
        lengths = route.get("inner_ground_layer_signal_length_mm", {})
        report = {"schema": "yam-f1-inner-plane-review/1", "physical_evidence": False,
                  "checked_pcb_sha256": digest(board), "independent_check_sha256": digest(checked / "summary.json"),
                  "routing_sha256": digest(routing),
                  "signal_length_by_net_mm": lengths, "total_signal_length_mm": sum(lengths.values()),
                  "unconnected_items_in_native_drc": summary["unconnected"],
                  "limits": "The plot shows actual filled copper. Connectivity DRC and visual inspection do not establish analog return impedance, EMC, force accuracy or physical reliability.",
                  "files_sha256": {p.name: digest(p) for p in folder.iterdir() if p.is_file()}}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["review"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["review"], indent=2))


if __name__ == "__main__":
    main()
