#!/usr/bin/python3
"""Check K1 unloaded and full-stop material clearances in each cell's source chart."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/capacitive-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
from shapely.geometry import Polygon
from shapely.ops import unary_union
from tactile_kit.records import execution
from capacitive_cell_geometry import MECHANICS
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mechanics_run", type=Path)
    args = parser.parse_args()
    source = args.mechanics_run.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/capacitive/cell_mechanics"):
        parser.error("Use a generated K1 cell-mechanics run")
    plan = json.loads((source / "report.json").read_text())
    mechanism = json.loads(MECHANICS.read_text())
    if plan["input_sha256"][str(MECHANICS.relative_to(ROOT))] != digest(MECHANICS):
        raise ValueError("Mechanics parameters changed since generation")
    folder = source / "clearance_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check the K1 retaining lip against fixed stop quadrants over the nominal closure travel, and retain unqualified tolerance/adhesion behavior") as record:
        folder.mkdir(parents=True, exist_ok=False)
        results = []
        for cell in plan["cells"]:
            plate = Polygon(cell["plate_domain_native_us"])
            stops = unary_union([Polygon(p) for p in cell["stop_domains_native_us"]])
            lip = (unary_union([Polygon(p["outer"], p["holes"]) for p in cell["lip_domains_native_us"]])
                   if "lip_domains_native_us" in cell else
                   plate.difference(plate.buffer(-mechanism["cover"]["under_plate_lip_mm"], join_style="mitre")))
            overlap = lip.intersection(stops).area
            results.append({"site": cell["site"], "lip_stop_projected_overlap_mm2": overlap,
                            "lip_can_reach_stops_early_under_rigid_plate_motion": overlap > 1e-7,
                            "ground_bond_min_clearance_at_full_stop_mm": cell["stop_total_height_mm"]-mechanism["plate_ground_bonds"]["normal_margin_mm"],
                            "nominal_stop_travel_mm": cell["nominal_normal_travel_to_stop_mm"],
                            "nominal_post_height_at_stop_mm": cell["nominal_remaining_post_height_mm"],
                            "scope": "Conservative full lip footprint; actual vent/port cuts may remove portions. Any positive overlap needs explicit review or removal."})
        report = {"schema": "yam-k1-cell-clearance-screen/1", "physical_specimens_tested": 0,
                  "mechanics_report_sha256": digest(source / "report.json"), "cells": results,
                  "passed_lip_stop_screen": not any(r["lip_can_reach_stops_early_under_rigid_plate_motion"] for r in results)}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
