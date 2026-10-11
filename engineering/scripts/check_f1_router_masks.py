#!/usr/bin/python3
"""Compare the optimized wrist drill mask with the previous conservative method."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_board_routes import NativeBoardGeometry, TwoFaceRouter
from route_f1_wrist import WristRouter
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement", type=Path)
    parser.add_argument("routing", type=Path)
    args = parser.parse_args()
    placement, routing = args.placement.resolve(), args.routing.resolve()
    if not all(path.is_relative_to(ROOT) for path in (placement, routing)):
        parser.error("Use repository-owned saved geometry")
    data = json.loads(placement.read_text())
    routes = json.loads(routing.read_text())
    folder = ROOT / "build/engineering/prototypes/f1/router_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Read the saved partial wrist layout and verify that combined drill masks do not permit any clearance violation allowed by neither original mask; no process or hardware control") as record:
        folder.mkdir(parents=True, exist_ok=False)
        board = NativeBoardGeometry(data)
        for track in routes["tracks"]:
            board.trace(track["net"], [track["start"], track["end"]], track["layer"], track["width"])
        for via in routes["vias"]:
            board.via(via["net"], via["center"], via["diameter"], via["drill"])
        original = TwoFaceRouter(board, grid=.2)
        original.signal_layers, original.layer_cost = ("F.Cu", "In2.Cu", "B.Cu"), (1, 1.5, 1)
        current = WristRouter(board, grid=.2)
        results = []
        for net in ("C7_I", "GND"):
            old_free, old_vias, _, _ = original.obstacles(net)
            for pad in board.pads:
                if pad.get("through_hole"):
                    radius = max(pad["drill_mm"])/2+original.via_drill/2+.25+original.guard
                    old_vias &= ~original.mask(Point(pad["center"]).buffer(radius))
            new_free, new_vias, _, _ = current.obstacles(net)
            unsafe = int(np.count_nonzero(new_vias & ~old_vias))
            extra_restricted = int(np.count_nonzero(old_vias & ~new_vias))
            results.append({"net": net, "track_masks_identical": bool(np.array_equal(old_free, new_free)),
                            "newly_allowed_via_points": unsafe, "extra_restricted_via_points": extra_restricted,
                            "passed": bool(np.array_equal(old_free, new_free) and unsafe == 0)})
        report = {"schema": "yam-f1-router-mask-check/1",
                  "placement_sha256": digest(placement), "routing_sha256": digest(routing),
                  "tracks": len(board.tracks), "vias": len(board.vias), "results": results,
                  "passed": all(row["passed"] for row in results), "physical_evidence": False,
                  "limits": "Same-grid mask comparison on this actual partial board; native KiCad DRC remains required."}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))
        if not report["passed"]:
            raise ValueError("Optimized masks relaxed a checked clearance")


if __name__ == "__main__":
    main()
