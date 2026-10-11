#!/usr/bin/python3
"""Repair the specifically reported R3 neck widths and unused layer transitions."""

import argparse
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import sys

from shapely.geometry import Point, Polygon

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_board_routes import NativeBoardGeometry
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board_directory", type=Path)
    parser.add_argument("check_directory", type=Path)
    args = parser.parse_args()
    source, checked = args.board_directory.resolve(), args.check_directory.resolve()
    if not all(p.is_relative_to(ROOT / "build") for p in (source, checked)):
        parser.error("Use repository-owned board and independent check")
    data_path = source / "f1_fanout_r3.json"
    data = json.loads(data_path.read_text())
    summary_path, drc_path = checked / "summary.json", checked / "drc.json"
    summary, drc = (json.loads(p.read_text()) for p in (summary_path, drc_path))
    if digest(source / "f1_fanout_r3.kicad_pcb") != summary["source_pcb_sha256"]:
        raise ValueError("Check uses another board")
    if summary["unconnected"] or any(row["type"] not in ("track_width", "via_dangling") for row in drc["violations"]):
        raise ValueError("This repair is limited to the reviewed neck/dangling-via findings")
    folder = ROOT / "build/engineering/prototypes/f1/r3_refinements" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Bring reported short R3 necks to the unchanged 0.15 mm minimum and remove only reported unused layer transitions; require fresh full KiCad connectivity/clearance checks") as record:
        folder.mkdir(parents=True, exist_ok=False)
        for p in (data_path, summary_path, drc_path, Path(__file__)):
            shutil.copyfile(p, folder / ("source_"+p.name))
        tracks, vias = copy.deepcopy(data["tracks"]), copy.deepcopy(data["vias"])
        changes = []
        for index, track in enumerate(tracks):
            if track["width"] >= .15-1e-7:
                continue
            if abs(track["width"]-.1124) > 1e-7:
                raise ValueError("Unexpected undersized trace width")
            changes.append({"kind": "widen_neck", "index": index, "net": track["net"],
                            "start": track["start"], "end": track["end"],
                            "old_width_mm": track["width"], "new_width_mm": .15})
            track["width"] = .15
        geometry = NativeBoardGeometry(data)
        for track in tracks:
            geometry.trace(track["net"], [track["start"], track["end"]], track["layer"], track["width"])
        removals = set()
        for finding in drc["violations"]:
            if finding["type"] != "via_dangling":
                continue
            item = finding["items"][0]
            match = re.fullmatch(r"Via \[([^]]+)\] on F.Cu - B.Cu", item["description"])
            if not match:
                raise ValueError("Unexpected reported via identity")
            net = match.group(1)
            position = [item["pos"]["x"], item["pos"]["y"]]
            candidates = [i for i, via in enumerate(vias) if via["net"] == net and math.dist(via["center"], position) < 1e-5]
            if len(candidates) != 1:
                raise ValueError("Reported via is not uniquely identified")
            index = candidates[0]
            via = vias[index]
            area = Point(via["center"]).buffer(via["diameter"]/2)
            layers = {track["layer"] for track in geometry.tracks
                      if track["net"] == net and track["shape"].intersects(area)}
            for pad in geometry.pads:
                if pad["net"] == net and pad["shape"].intersects(area):
                    layers.update(pad["layers"])
            if len(layers) > 1:
                raise ValueError("A reported via is a real interlayer connection; preserve it")
            removals.add(index)
            changes.append({"kind": "remove_reported_unused_transition", "net": net,
                            "center_mm": via["center"], "connected_layers": sorted(layers),
                            "final_connectivity_verification_required": True})
        plane = Polygon(data["outline_xy_mm"]).buffer(-data["edge_mm"])
        if plane.geom_type != "Polygon" or plane.interiors:
            raise ValueError("Review the ground-pour boundary")
        changes.append({"kind": "add_ground_pour", "layer": "In1.Cu", "net": "GND",
                        "note": "Restore the fanout's intended inner ground plane; native refill and all connectivity/clearance checks remain required."})
        result = {"schema": "yam-f1-r3-refinement/1", "physical_boards_tested": 0,
                  "source_manifest_sha256": digest(data_path), "source_check_sha256": digest(summary_path),
                  "changes": changes, "tracks": tracks,
                  "vias": [via for i, via in enumerate(vias) if i not in removals],
                  "zones": [{"net": "GND", "layer": "In1.Cu", "outline_xy_mm": list(plane.exterior.coords)}],
                  "status": "Specific repairs made; fresh independent DRC/connectivity required"}
        (folder / "routing.json").write_text(json.dumps(result, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "changes": changes,
                            "tracks": len(tracks), "vias": len(result["vias"])}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
