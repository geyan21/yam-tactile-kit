#!/usr/bin/python3
"""Route the independently checked O1 LED placement on two copper layers."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from route_force_button_board import FB1Router
from f1_board_routes import NativeBoardGeometry
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement", type=Path)
    args = parser.parse_args()
    source = args.placement.resolve()
    if not source.is_relative_to(ROOT/"build"):
        parser.error("Use the generated O1 placement")
    data = json.loads((source/"o1_blue_ring.json").read_text())
    check = json.loads((source/"latest_check.json").read_text())
    if data["tracks"] or check["violations"] or check["source_sha256"] != data["pcb_sha256"] or digest(source/"o1_blue_ring.kicad_pcb") != data["pcb_sha256"]:
        raise ValueError("Resolve the unchanged native placement first")
    target = ROOT/"build/engineering/prototypes/optical/led_routes"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Route four O1 LED/resistor branches and their supply/return around the mechanical lens aperture") as record:
        target.mkdir(parents=True)
        board = NativeBoardGeometry(data)
        router = FB1Router(board, grid=.05, width=.2, via_diameter=.5, via_drill=.25)
        router.signal_layers = ("F.Cu", "B.Cu"); router.layer_cost = (1, 1)
        def save(error=None):
            (target/"routing.json").write_text(json.dumps({"schema": "yam-o1-light-routing/1", **board.payload(),
                "placement_sha256": digest(source/"o1_blue_ring.json"), "error": error, "physical_boards_tested": 0,
                "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in (Path(__file__), ROOT/"engineering/scripts/route_force_button_board.py", ROOT/"engineering/scripts/f1_board_routes.py")}}, indent=2)+"\n")
        try:
            for net in ("A1", "A2", "A3", "A4", "LED_5V", "GND"):
                pending = [p for p in board.pads if p["net"] == net]
                connected = [pending.pop(0)["center"]]
                while pending:
                    _, i, destination = min((math.dist(p["center"], q), i, q) for i, p in enumerate(pending) for q in connected)
                    pad = pending.pop(i)
                    router.connect(net, pad["center"], destination, time_limit_s=20)
                    connected.append(pad["center"])
                save()
                print(net+": connected", flush=True)
            record["result"] = {"directory": str(target.relative_to(ROOT)), "tracks": len(board.tracks), "vias": len(board.vias)}
            print(json.dumps(record["result"], indent=2))
        except Exception as error:
            save(str(error)); raise


if __name__ == "__main__":
    main()
