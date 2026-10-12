#!/usr/bin/python3
"""Re-export one retained O1 STEP into a fresh directory with bounded mesh checks."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/optical-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import cadquery as cq
from optical_cad import export_part
from screen_f1_feedback import digest
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", type=Path)
    args = parser.parse_args()
    source = args.step.resolve()
    if not source.is_relative_to(ROOT/"build") or source.suffix != ".step":
        parser.error("Use a retained generated STEP")
    folder = ROOT/"build/engineering/prototypes/optical/mesh_normalization_reviews"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Test bounded STL precision cleanup against one unchanged valid O1 STEP, preserving the unprocessed mesh and measured changes") as record:
        folder.mkdir(parents=True)
        parts = []
        export_part(cq.importers.importStep(str(source)).val(), source.stem, folder, parts,
                    "Unchanged STEP tessellation review", "Review only", "reference_only")
        report = {"source": str(source.relative_to(ROOT)), "source_sha256": digest(source), "parts": parts,
                  "exporter_sha256": digest(ROOT/"engineering/scripts/optical_cad.py")}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "checks": parts[0]["checks"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
