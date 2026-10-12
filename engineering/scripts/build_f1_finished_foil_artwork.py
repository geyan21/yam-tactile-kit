#!/usr/bin/python3
"""Create R4 F1 foil artwork with the selected thin connector backing and unchanged copper."""

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from shapely.geometry import Polygon
from tactile_kit.records import execution
from flex_artwork import FlexArtwork
from screen_f1_feedback import digest

SOURCE = ROOT / "engineering/development/f1/fitted-foils-r3"
PLAN = ROOT / "engineering/designs/f1_finished_tip_r4.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tip_review", type=Path)
    args = parser.parse_args()
    review_path = args.tip_review.resolve() / "report.json"
    review = json.loads(review_path.read_text())
    if not review["proposed_contract_checks_pass"]:
        raise ValueError("Resolve the proposed terminal window checks first")
    for name, expected in review["input_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Terminal review inputs changed")
    original = json.loads((SOURCE / "provenance/artwork.json").read_text())
    checkpoint = json.loads((SOURCE / "checkpoint.json").read_text())
    contracts = {row["foil"]: row for row in review["cases"]}
    folder = ROOT / "build/engineering/prototypes/f1/artwork_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Generate a separate F1 R4 terminal-mask revision from the exact checked R3 copper; add the two needed rear-coverlay reliefs and preserve every original board") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [Path(__file__), PLAN, review_path, SOURCE / "checkpoint.json",
                  SOURCE / "provenance/artwork.json", ROOT / "engineering/scripts/flex_artwork.py"]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        boards, checks = [], []
        for entry in original["boards"]:
            name = entry["name"]; relative = f"foils/{name}/{name}.json"
            if digest(SOURCE / relative) != checkpoint["files_sha256"][relative]:
                raise ValueError("Frozen input foil changed")
            data = json.loads((SOURCE / relative).read_text())
            artwork = FlexArtwork(name, Polygon(data["outline_mm"]), data["physical_layers"],
                                  data["covered_thickness_mm"])
            # The source outline already passed native checks. Do not run a
            # second geometric simplification when only a mask is changing.
            artwork.outline = Polygon(data["outline_mm"])
            artwork.outline_deviation_mm = data["outline_cleanup_maximum_deviation_mm"]
            for region in data["regions"]:
                artwork.region(region["name"], region["net"], region["layer"],
                               Polygon(region["outline_mm"]), region["purpose"])
            for finger in data["fingers"]:
                artwork.finger(finger["pin"], finger["net"], finger["center"],
                               finger["width"], finger["length"], finger["layer"])
            for via in data["plated_connections"]:
                artwork.interlayer(via["name"], via["net"], via["center"], via["pad_mm"], via["drill_mm"])
            # Copy checked openings directly, avoiding another clip/rounding
            # operation on the retained front sensing windows.
            artwork.openings = [{"layer": row["layer"], "shape": Polygon(row["outline_mm"])}
                                for row in data["coverlay_openings"]]
            if contracts[name]["needs_back_coverlay_change"]:
                artwork.openings.append({"layer": "B.Mask",
                                         "shape": Polygon(contracts[name]["proposed_back_relief_polygon_mm"])})
            artwork.stiffeners = [Polygon(p) for p in data["stiffeners_mm"]]
            artwork.paths = copy.deepcopy(data["paths"])
            artwork.labels = copy.deepcopy(data["labels"])
            destination = folder / name
            artwork.write(destination)
            # Compare the serialized geometry on both sides; Shapely rings
            # are tuples in memory and JSON arrays after writing.
            updated = json.loads((destination / (name+".json")).read_text())
            pcb = destination / (name+".kicad_pcb")
            pcb.write_text(pcb.read_text().replace('(generator "pcbnew")', '(generator "yam_f1_flex")', 1))
            updated["pcb_sha256"] = digest(pcb)
            updated["foil_revision"] = "R4 terminal integration"
            updated["finished_tip_plan_sha256"] = digest(PLAN)
            updated["finished_tip_nominal_mm"] = contracts[name]["proposed_tip_nominal_mm"]
            (destination / (name+".json")).write_text(json.dumps(updated, indent=2)+"\n")
            preserved = {}
            for key in ("outline_mm", "regions", "fingers", "plated_connections", "paths", "stiffeners_mm"):
                preserved[key] = updated[key] == data[key]
            if not all(preserved.values()) or not updated["geometry_checks"]["passed"]:
                (folder / "failed_identity_check.json").write_text(json.dumps(
                    {"foil": name, "unchanged_fields": preserved, "geometry_checks": updated["geometry_checks"]}, indent=2)+"\n")
                raise ValueError(name+": a terminal-mask change altered the approved conductor or outline")
            metadata = copy.deepcopy(entry["metadata"])
            metadata["foil_revision"] = "R4 terminal integration"
            metadata["finished_tip_plan"] = str(PLAN.relative_to(ROOT))
            boards.append({"name": name, "directory": str(destination.relative_to(ROOT)), "metadata": metadata})
            checks.append({"name": name, "unchanged_fields": preserved,
                           "back_window_added": contracts[name]["needs_back_coverlay_change"],
                           "new_mask_count": len(updated["coverlay_openings"]),
                           "source_metadata_sha256": digest(SOURCE / relative)})
            print(name+": conductor identity retained; "+("rear window added" if contracts[name]["needs_back_coverlay_change"] else "terminal plan attached"), flush=True)
        result = {"schema": "yam-f1-fitted-artwork/1", "foil_revision": "R4 terminal integration",
                  "status": "New terminal-mask artwork; independent native checks, complete manufacturing drawings and installed integration remain",
                  "physical_specimens_tested": 0, "boards": boards, "requested_boards": [b["name"] for b in boards],
                  "failed_boards": [], "retained_copper_checks": checks,
                  "source_hashes": {str(p.relative_to(ROOT)): digest(p) for p in inputs}}
        (folder / "artwork.json").write_text(json.dumps(result, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "boards": len(boards),
                            "rear_windows_added": sum(row["back_window_added"] for row in checks)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
