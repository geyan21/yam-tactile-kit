#!/usr/bin/python3
"""Remove only reported R3 copper leaves that touch the network inside one pad."""

import argparse
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import sys

from shapely.geometry import Point
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
    args = parser.parse_args()
    source, checked = args.board_directory.resolve(), args.check_directory.resolve()
    if not all(p.is_relative_to(ROOT / "build") for p in (source, checked)):
        parser.error("Use repository-owned generated evidence")
    data_path = source / "f1_fanout_r3.json"
    data = json.loads(data_path.read_text())
    summary_path, drc_path = checked / "summary.json", checked / "drc.json"
    summary, drc = (json.loads(p.read_text()) for p in (summary_path, drc_path))
    if digest(source / "f1_fanout_r3.kicad_pcb") != summary["source_pcb_sha256"] or summary["unconnected"]:
        raise ValueError("Board/check mismatch or an already disconnected net")
    if any(v["type"] != "track_dangling" for v in drc["violations"]):
        raise ValueError("Only the reported residual copper leaves may be removed")
    folder = ROOT / "build/engineering/prototypes/f1/r3_leaf_cleanup" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Remove reported R3 copper leaves only after proving they contact no other conductor outside their source pad; preserve ground plane and require full native rechecking") as record:
        folder.mkdir(parents=True, exist_ok=False)
        for p in (data_path, summary_path, drc_path, Path(__file__)):
            shutil.copyfile(p, folder / ("source_"+p.name))
        geometry = NativeBoardGeometry(data)
        for track in data["tracks"]:
            geometry.trace(track["net"], [track["start"], track["end"]], track["layer"], track["width"])
        for via in data["vias"]:
            geometry.via(via["net"], via["center"], via["diameter"], via["drill"])
        if len(geometry.tracks) != len(data["tracks"]):
            raise ValueError("Review zero-length tracks before using native segment indices")
        previous = json.loads((source / "generation_inputs/routing.json").read_text())
        old_ends = [item for item in previous.get("changes", [])
                    if item["kind"] == "remove_reported_unused_transition"]
        removed, details = set(), []
        for violation in drc["violations"]:
            item = violation["items"][0]
            match = re.match(r"Track \[([^]]+)\] on ([^,]+),", item["description"])
            if not match:
                raise ValueError("Unexpected track description")
            net, layer = match.groups()
            point = [item["pos"]["x"], item["pos"]["y"]]
            candidates = [i for i, track in enumerate(data["tracks"])
                          if track["net"] == net and track["layer"] == layer and
                          min(math.dist(track["start"], point), math.dist(track["end"], point)) < 1e-5]
            candidates = [i for i in candidates if any(
                old["net"] == net and min(math.dist(data["tracks"][i][key], old["center_mm"])
                                         for key in ("start", "end")) < 1e-5 for old in old_ends)]
            if len(candidates) != 1:
                raise ValueError("Reported seed leaf is not uniquely identified")
            index = candidates[0]
            track = geometry.tracks[index]
            anchors = [pad["shape"] for pad in geometry.pads if pad["net"] == net and layer in pad["layers"]
                       and pad["shape"].covers(Point(point))]
            if len(anchors) != 1:
                raise ValueError("Leaf does not start in one unambiguous native pad")
            other = [t["shape"] for i, t in enumerate(geometry.tracks)
                     if i != index and t["net"] == net and t["layer"] == layer]
            other += [v["shape"] for v in geometry.vias if v["net"] == net]
            other += [p["shape"] for p in geometry.pads if p["net"] == net and layer in p["layers"]]
            outside = track["shape"].intersection(unary_union(other)).difference(anchors[0].buffer(.0001)).area
            if outside > 1e-6:
                raise ValueError("Reported leaf also connects copper outside its pad; preserve it")
            removed.add(index)
            details.append({"net": net, "layer": layer, "start": track["start"], "end": track["end"],
                            "contacts_outside_source_pad_mm2": outside})
        route = copy.deepcopy(previous)
        route["tracks"] = [t for i, t in enumerate(data["tracks"]) if i not in removed]
        route["vias"] = data["vias"]
        route["leaf_cleanup"] = details
        route["source_pcb_sha256"] = data["pcb_sha256"]
        route["status"] = "Copper leaves removed with local connectivity proof; independent full-board checks pending"
        (folder / "routing.json").write_text(json.dumps(route, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "removed": details,
                            "tracks": len(route["tracks"]), "vias": len(route["vias"]),
                            "ground_zones_retained": len(route.get("zones", []))}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
