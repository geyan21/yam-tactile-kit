#!/usr/bin/python3
"""Reserve compliant row escapes, sense pickoffs and short mux supply paths."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_board_routes import NativeBoardGeometry
from route_f1_wrist import WristRouter
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement_run", type=Path)
    args = parser.parse_args()
    source = args.placement_run.resolve()
    if not source.is_relative_to(ROOT):
        parser.error("Use a repository-owned placement")
    if not json.loads((source / "placement_check.json").read_text())["passed"]:
        raise ValueError("Resolve placement findings first")
    native_path = source / "placement/f1_fanout_r3.json"
    data = json.loads(native_path.read_text())
    if digest(source / "placement/f1_fanout_r3.kicad_pcb") != data["pcb_sha256"]:
        raise ValueError("Native placement changed")
    cfg_path = source / "inputs/engineering/designs/f1_fanout_development.json"
    cfg = json.loads(cfg_path.read_text())
    folder = source / "seed_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Reserve only the necessary F1 R3 local copper before global routing: 0.15 mm row-pin escapes, direct sense pickoffs and close bypass supply/ground connections") as record:
        folder.mkdir(parents=True, exist_ok=False)
        for path in (native_path, cfg_path, Path(__file__)):
            shutil.copyfile(path, folder / path.name)
        board = NativeBoardGeometry(data)
        board.clearance = max(board.clearance, .18)
        router = WristRouter(board, grid=cfg["routing_grid_mm"], width=.15,
                             via_diameter=.45, via_drill=.2)
        routes = []
        def pad(ref, number):
            return board.pad(ref, number)
        def direct(a, b, width, reason):
            if a["net"] != b["net"]:
                raise ValueError("Local path connects different nets")
            router.direct(a["net"], a["center"], b["center"], a["layers"][0], width)
            routes.append({"reason": reason, "net": a["net"], "a": [a["reference"], a["pad"]],
                           "b": [b["reference"], b["pad"]], "width_mm": width,
                           "length_mm": math.dist(a["center"], b["center"])})
        columns = [p for p in board.pads if p["reference"].startswith("J")
                   and p["reference"].endswith("C") and p["net"]]
        for p in columns:
            direct(p, pad("RK"+p["net"][:-2], "1"), .2, "sense pickup at the sensor connector land")
        wrist_pads = sorted((p for p in board.pads if p["reference"] == "JW" and p["net"]),
                            key=lambda p: int(p["pad"]))
        for p in wrist_pads:
            router.width = .15
            target = router.escape(p)
            routes.append({"reason": "explicit wrist-connector escape", "net": p["net"],
                           "pad": [p["reference"], p["pad"]], "via_mm": target,
                           "width_mm": .15, "length_mm": math.dist(p["center"], target)})
        for ref in ("CT1", "CT2"):
            direct(pad("UT", "1"), pad(ref, "1"), .2, "short VDD bypass connection")
            p = pad(ref, "2")
            router.width = .15
            target = router.escape(p)
            routes.append({"reason": "bypass capacitor ground via", "net": p["net"],
                           "pad": [ref, "2"], "via_mm": target,
                           "width_mm": .15, "length_mm": math.dist(p["center"], target)})
        report = {
            "schema": "yam-f1-r3-seed/1", "physical_boards_tested": 0,
            "source_manifest_sha256": digest(native_path), "source_pcb_sha256": data["pcb_sha256"],
            "local_paths": routes, "minimum_trace_width_mm": min(t["width"] for t in board.tracks),
            "planning_clearance_mm": board.clearance,
            "purpose": "Every wrist-connector pad uses an explicit 0.15 mm escape. This avoids the automatic fanout stage's sub-minimum necks; row-current trunks may then widen to 0.5 mm. Complete routing and independent checks remain.",
            **board.payload(),
        }
        (folder / "routing.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "tracks": len(board.tracks),
                            "vias": len(board.vias), "minimum_width_mm": report["minimum_trace_width_mm"],
                            "local_paths": routes[-8:]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
