#!/usr/bin/python3
"""Preserve a rejected R2 route with its actual native board and full findings."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("board", "check", "run", "imported"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ("board", "check", "run", "imported")}
    if not all(path.is_relative_to(ROOT / "build") for path in paths.values()):
        parser.error("Use generated, repository-owned evidence")
    destination = ROOT / "engineering/development/f1/r2-routing-study"
    if destination.exists():
        parser.error("Preserve prior studies; choose a separate revision")
    summary = json.loads((paths["check"] / "summary.json").read_text())
    if summary["passed"] or summary["violations"] == 0:
        raise ValueError("This archiver explicitly preserves a rejected routing attempt")
    pcb = paths["board"] / "f1_fanout_r2.kicad_pcb"
    if digest(pcb) != summary["source_pcb_sha256"]:
        raise ValueError("Native board differs from the rejection report")
    drc = json.loads((paths["check"] / "drc.json").read_text())
    counts = dict(Counter(item["type"] for item in drc["violations"]))
    with execution(ROOT / "build/records", "Preserve the rejected F1 R2 PCB, routing inputs and complete independent DRC evidence without exporting fabrication artwork") as record:
        destination.mkdir(parents=True, exist_ok=False)
        board = destination / "rejected-pcb"
        board.mkdir()
        for name in ("f1_fanout_r2.kicad_pcb", "f1_fanout_r2.kicad_dru", "f1_fanout_r2.json",
                     "f1_fanout_r2_pins.csv", "fp-lib-table"):
            shutil.copyfile(paths["board"] / name, board / name)
        shutil.copytree(paths["check"] / "F1.pretty", board / "F1.pretty")
        checks = destination / "checks"
        checks.mkdir()
        for name in ("summary.json", "drc.json"):
            shutil.copyfile(paths["check"] / name, checks / name)
        inputs = destination / "routing-evidence"
        inputs.mkdir()
        for name in ("f1_r2_input.dsn", "f1_r2_output.ses", "report.json", "rules.json", "router.log"):
            shutil.copyfile(paths["run"] / name, inputs / name)
        for name in ("report.json", "pad_correspondence.json", "normalized_session.ses", "routing.json"):
            shutil.copyfile(paths["imported"] / name, inputs / ("import_"+name))
        (destination / "README.md").write_text(
            "# R2 routing study — rejected, do not fabricate or power\n\n"
            f"The board has {summary['unconnected']} missing connections, but independent KiCad "
            f"checking reports **{summary['violations']} violations**. No Gerbers were exported.\n\n"
            "This is failure evidence for continued layout work, not a usable F1 electronics release.\n\n"
            "Findings by type:\n\n"+
            "".join(f"- {kind}: {count}\n" for kind, count in counts.items())+
            "\nThe route includes an R3_I-to-GND short and 0.1124 mm neck-down tracks below the "
            "declared 0.15 mm minimum. Courtyard, outline and silkscreen findings also remain. "
            "The full report is in `checks/drc.json`; every finding must be resolved before export.\n\n"
            "The official bundled-Java Freerouting 2.5.0 tool produced the stored session. "
            "Its own near-1000 score did not establish compliance with this board's native rules. "
            "The import restores a missing empty mounting-package string and records a "
            "0.1 µm placement-grid allowance; the final board is regenerated from its original "
            "placement, with no generated pad-net changes.\n\n"
            "Keep this study separate from the original checked fanout, the checked wrist module, "
            "and the mechanical fit packet. None supplies a physically qualified F1 finger. "
            "Fitted flex, reference/coupled-array checks and all contact/20 N tests remain.\n")
        checkpoint = {
            "schema": "yam-f1-rejected-route-checkpoint/1", "created_utc": datetime.now(timezone.utc).isoformat(),
            "status": "REJECTED R2 ROUTING ATTEMPT — do not fabricate or power",
            "integrated_f1_completed": False, "physical_specimens_tested": 0,
            "independent_check": summary, "findings_by_type": counts,
            "source_locations": {name: str(path.relative_to(ROOT)) for name, path in paths.items()},
            "archiver_sha256": digest(Path(__file__)),
            "files_sha256": {str(path.relative_to(destination)): digest(path)
                             for path in sorted(destination.rglob("*")) if path.is_file()},
        }
        (destination / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2)+"\n")
        record["result"] = {"directory": str(destination.relative_to(ROOT)), "findings": counts,
                            "files": len(checkpoint["files_sha256"]), "fabrication_exported": False}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
