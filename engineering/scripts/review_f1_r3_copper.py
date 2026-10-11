#!/usr/bin/python3
"""Verify that final R3 copper retains the deliberate local electrical paths."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_board_routes import NativeBoardGeometry
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board_directory", type=Path)
    parser.add_argument("check_directory", type=Path)
    parser.add_argument("seed_routing", type=Path)
    args = parser.parse_args()
    source, checked, seed_path = (p.resolve() for p in (args.board_directory, args.check_directory, args.seed_routing))
    if not all(p.is_relative_to(ROOT / "build") for p in (source, checked, seed_path)):
        parser.error("Use repository-owned evidence")
    data_path, summary_path = source / "f1_fanout_r3.json", checked / "summary.json"
    data, summary, seed = (json.loads(p.read_text()) for p in (data_path, summary_path, seed_path))
    if not summary["passed"] or summary["stage"] != "routed_board" or summary["unconnected"]:
        raise ValueError("Use the completed independent board check")
    if digest(source / "f1_fanout_r3.kicad_pcb") != summary["source_pcb_sha256"]:
        raise ValueError("Board/check mismatch")
    folder = ROOT / "build/engineering/prototypes/f1/r3_copper_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Verify final R3 sense pickoffs, short bypass copper, ground-via proximity and solder-paste clearance after autorouting; retain limits of these geometric electrical checks") as record:
        folder.mkdir(parents=True, exist_ok=False)
        for path in (data_path, summary_path, seed_path, Path(__file__)):
            shutil.copyfile(path, folder / ("source_"+path.name))
        board = NativeBoardGeometry(data)
        for track in data["tracks"]:
            board.trace(track["net"], [track["start"], track["end"]], track["layer"], track["width"])
        for via in data["vias"]:
            board.via(via["net"], via["center"], via["diameter"], via["drill"])
        pad = {(p["reference"], p["pad"]): p for p in board.pads}
        unions = {}
        def copper(net, layer):
            key = (net, layer)
            if key not in unions:
                unions[key] = unary_union([shape for name, shape in board.copper(layer) if name == net])
            return unions[key]
        paths, failures = [], []
        tolerance = .0001
        for item in seed["local_paths"]:
            if item["reason"] not in ("sense pickup at the sensor connector land", "short VDD bypass connection"):
                continue
            first, second = pad[tuple(item["a"])], pad[tuple(item["b"])]
            common = set(first["layers"]).intersection(second["layers"])
            if len(common) != 1:
                raise ValueError("Local path no longer has a single common PCB face")
            layer = next(iter(common))
            expected = LineString([first["center"], second["center"]]).buffer(item["width_mm"]/2)
            covered = copper(item["net"], layer).buffer(tolerance).covers(expected)
            result = {"reason": item["reason"], "net": item["net"], "a": item["a"], "b": item["b"],
                      "layer": layer, "nominal_width_mm": item["width_mm"],
                      "straight_length_mm": math.dist(first["center"], second["center"]),
                      "original_direct_copper_preserved": covered}
            paths.append(result)
            if not covered:
                failures.append({"kind": "local_path_changed", **result})
        if len(paths) != 18:
            raise ValueError("Expected sixteen pickoffs and two VDD bypass paths")
        ground_paths = []
        for ref in ("CT1", "CT2"):
            p = pad[(ref, "2")]
            matches = []
            for via in data["vias"]:
                if via["net"] != "GND":
                    continue
                length = math.dist(p["center"], via["center"])
                expected = LineString([p["center"], via["center"]]).buffer(.15/2)
                if length <= 1.0 and copper("GND", "F.Cu").buffer(tolerance).covers(expected):
                    matches.append({"center_mm": via["center"], "length_mm": length})
            ground_paths.append({"capacitor": ref, "nearby_direct_ground_vias": matches})
            if not matches:
                failures.append({"kind": "bypass_ground_path_missing", "capacitor": ref})
        gaps = []
        paste_pads = [p for p in board.pads if p["paste"]]
        for via in data["vias"]:
            point = Point(via["center"])
            p = min(paste_pads, key=lambda p: point.distance(p["shape"]))
            gap = point.distance(p["shape"])-via["diameter"]/2
            gaps.append({"net": via["net"], "via": via["center"], "nearest_pad": [p["reference"], p["pad"]],
                        "copper_to_paste_mm": gap})
            if gap < .1-tolerance:
                failures.append({"kind": "via_near_paste", **gaps[-1]})
        widths = {}
        for track in data["tracks"]:
            if track["net"] in {f"R{i}_I" for i in range(4)}:
                key = str(track["width"])
                widths.setdefault(track["net"], {})
                widths[track["net"]][key] = widths[track["net"]].get(key, 0)+math.dist(track["start"], track["end"])
        result = {"schema": "yam-f1-r3-copper-review/1", "physical_boards_tested": 0,
                  "source_pcb_sha256": data["pcb_sha256"], "independent_check_sha256": digest(summary_path),
                  "seed_sha256": digest(seed_path), "local_paths": paths, "ground_paths": ground_paths,
                  "minimum_paste_gap_mm": min(p["copper_to_paste_mm"] for p in gaps),
                  "near_paste": sorted(gaps, key=lambda p: p["copper_to_paste_mm"])[:10],
                  "row_current_trace_length_by_width_mm": widths,
                  "geometry_tolerance_mm": tolerance, "passed": not failures, "failures": failures,
                  "limits": "Checks nominal copper paths and assembly spacing. It does not establish regulator stability, full-array resistance, EMC, current-sharing accuracy or physical force/contact performance."}
        (folder / "report.json").write_text(json.dumps(result, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "passed": not failures,
                            "local_paths_checked": len(paths), "bypass_ground_paths_checked": len(ground_paths),
                            "minimum_paste_gap_mm": result["minimum_paste_gap_mm"], "failures": failures}
        print(json.dumps(record["result"], indent=2))
        if failures:
            raise ValueError("Review the changed local electrical or solder-clearance paths")


if __name__ == "__main__":
    main()
