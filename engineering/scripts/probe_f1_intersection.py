#!/usr/bin/python3
"""Compare one owned F1 CAD part with the source frame using direct native intersection."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/f1-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
from tactile_kit.records import execution
from source_brep import load as source_solid
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("part", type=Path)
    args = parser.parse_args()
    path = args.part.resolve()
    if not path.is_relative_to(ROOT / "build/engineering/prototypes/f1") or path.suffix != ".step":
        parser.error("Select one generated F1 STEP in this repository")
    folder = ROOT / "build/engineering/prototypes/f1/intersection_probes" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Compare one named F1 foil envelope against the source hard frame with direct OpenCascade common volume; no process control or changed clearance criterion") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        shape = cq.importers.importStep(str(path)).val()
        source, receipt = source_solid("hard_frame")
        print("Loaded the selected F1 part and source frame; starting direct common", flush=True)
        started = time.monotonic()
        common = shape.intersect(source)
        volume = 0. if common.wrapped.IsNull() else common.Volume()
        report = {"schema": "yam-f1-native-intersection-probe/1", "physical_specimens_tested": 0,
                  "part": str(path.relative_to(ROOT)), "part_sha256": digest(path),
                  "source_hard_conversion": receipt, "method": "OpenCascade_direct_common",
                  "overlap_mm3": volume, "overlap_limit_mm3": .001,
                  "passed_overlap_criterion": volume <= .001, "elapsed_s": time.monotonic()-started,
                  "limits": ["One part/source comparison only; no minimum-clearance distance or physical fit measurement."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps({key: record["result"][key] for key in ("directory", "overlap_mm3", "passed_overlap_criterion", "elapsed_s")}, indent=2))


if __name__ == "__main__":
    main()
