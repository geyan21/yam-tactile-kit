#!/usr/bin/python3
"""Route the small FB1 sensor board after native placement verification."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys

from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_board_routes import NativeBoardGeometry, TwoFaceRouter
from screen_f1_feedback import digest


class FB1Router(TwoFaceRouter):
    def obstacles(self, net):
        free, via_free, inside, forbidden = super().obstacles(net)
        for pad in self.board.pads:
            if pad.get("drill", 0):
                r = pad["drill"]/2+self.via_drill/2+.25+self.guard
                via_free &= ~self.mask(Point(pad["center"]).buffer(r))
        return free, via_free, inside, forbidden


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement", type=Path)
    args = parser.parse_args()
    source = args.placement.resolve()
    if not source.is_relative_to(ROOT / "build"):
        parser.error("Use a generated FB1 placement")
    data = json.loads((source / "fb1_sensor.json").read_text())
    receipt = json.loads((source / "latest_check.json").read_text())
    if (data["tracks"] or receipt["violations"] or receipt["source_sha256"] != data["pcb_sha256"]
            or digest(source / "fb1_sensor.kicad_pcb") != data["pcb_sha256"]):
        raise ValueError("Use the unchanged, independently checked placement")
    target = ROOT / "build/engineering/prototypes/force_button/routing" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Route FB1 on two copper layers, reserving direct local bypass links and keeping the reference vent and screw-head areas clear") as record:
        target.mkdir(parents=True, exist_ok=False)
        for path in (source / "fb1_sensor.json", source / "specification.json", Path(__file__)):
            shutil.copyfile(path, target / ("input_"+path.name))
        board = NativeBoardGeometry(data)
        router = FB1Router(board, grid=.05, width=.2, via_diameter=.5, via_drill=.25)
        router.signal_layers = ("F.Cu", "B.Cu")
        router.layer_cost = (1, 1)
        point = lambda ref, pin: board.pad(ref, pin)["center"]
        critical = []

        def trace(net, points, purpose):
            for a, b in zip(points, points[1:]):
                router.direct(net, a, b, "F.Cu", .2)
            critical.append({"net": net, "points": points, "purpose": purpose})

        def save(error=None):
            payload = {"schema": "yam-fb1-board-routing/1", **board.payload(),
                       "source_placement_sha256": digest(source / "fb1_sensor.json"),
                       "critical_routes": critical, "error": error, "physical_boards_tested": 0}
            (target / "routing.json").write_text(json.dumps(payload, indent=2)+"\n")

        try:
            trace("VDD_REMOTE", [point("U1", 1), point("C1", 1), point("C2", 1)],
                  "Direct local bypass supply")
            trace("GND_REMOTE", [point("C1", 2), point("C2", 2)], "Direct bypass return")
            known = {"VDD_REMOTE": [point("U1", 1), point("C1", 1), point("C2", 1)],
                     "GND_REMOTE": [point("C1", 2), point("C2", 2)]}
            for net in ("SCL", "SDA", "GND_REMOTE", "VDD_REMOTE"):
                pads = [p for p in board.pads if p["net"] == net]
                connected = known.setdefault(net, [pads[0]["center"]])
                pending = list(pads)
                while pending:
                    pending = [p for p in pending if not any(math.dist(p["center"], q) < 1e-6 for q in connected)]
                    if not pending:
                        break
                    _, i, destination = min((math.dist(p["center"], q), i, q)
                                             for i, p in enumerate(pending) for q in connected)
                    pad = pending.pop(i)
                    router.connect(net, pad["center"], destination, time_limit_s=25)
                    connected.append(pad["center"])
                save()
                print(f"{net}: connected", flush=True)
            for via in list(board.vias):
                layers = {t["layer"] for t in board.tracks if t["net"] == via["net"] and t["shape"].intersects(via["shape"])}
                for pad in board.pads:
                    if pad["net"] == via["net"] and pad["shape"].intersects(via["shape"]):
                        layers.update(pad["layers"])
                if len(layers) < 2:
                    board.vias.remove(via)
            save()
            record["result"] = {"directory": str(target.relative_to(ROOT)), "tracks": len(board.tracks),
                                "vias": len(board.vias), "native_check_pending": True}
            print(json.dumps(record["result"], indent=2))
        except Exception as error:
            save(str(error))
            record["failure"] = {"directory": str(target.relative_to(ROOT)), "error": str(error)}
            raise


if __name__ == "__main__":
    main()
