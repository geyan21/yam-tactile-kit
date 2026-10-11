#!/usr/bin/python3
"""Route K1 around fixed input leads and dedicated driven-shield planes."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys

from shapely.geometry import LineString, Point, Polygon

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_board_routes import NativeBoardGeometry, TwoFaceRouter
from screen_f1_feedback import digest


class K1Router(TwoFaceRouter):
    def obstacles(self, net):
        free, via_free, inside, forbidden = super().obstacles(net)
        for pad in self.board.pads:
            if pad.get("drill", 0):
                radius = pad["drill"]/2+self.via_drill/2+.25+self.guard
                via_free &= ~self.mask(Point(pad["center"]).buffer(radius))
        return free, via_free, inside, forbidden


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path)
    args = parser.parse_args()
    source = args.board.resolve()
    if not source.is_relative_to(ROOT / "build"):
        parser.error("Use one generated native K1 placement")
    data_path = source / "k1_readout.json"
    data = json.loads(data_path.read_text())
    if digest(source / "k1_readout.kicad_pcb") != data["pcb_sha256"] or data["tracks"]:
        raise ValueError("Use the unchanged, unrouted placement")
    receipt = json.loads((source / "latest_check.json").read_text())
    if receipt["source_sha256"] != data["pcb_sha256"] or receipt["violations"]:
        raise ValueError("Resolve the placement findings first")
    folder = ROOT / "build/engineering/prototypes/capacitive/routing" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Route K1 with explicit short CIN leads, driven-shield planes, protected bypass paths and no signal routing on In1; require full native checking afterwards") as record:
        folder.mkdir(parents=True, exist_ok=False)
        for path in (data_path, source / "specification.json", Path(__file__)):
            shutil.copyfile(path, folder / ("source_"+path.name))
        board = NativeBoardGeometry(data)
        router = K1Router(board, grid=.1, width=.2, via_diameter=.5, via_drill=.25)
        router.signal_layers = ("F.Cu", "In2.Cu", "B.Cu")
        router.layer_cost = (1, 1.3, 1)
        critical = []
        def point(ref, pin):
            return board.pad(ref, pin)["center"]
        def trace(net, points, purpose):
            for start, end in zip(points, points[1:]):
                try:
                    router.direct(net, start, end, "F.Cu", .2)
                except ValueError:
                    line = LineString([start, end])
                    nearby = [{"kind": "pad", "reference": p["reference"], "pad": p["pad"], "net": p["net"],
                               "centerline_distance_mm": line.distance(p["shape"])}
                              for p in board.pads if p["net"] != net and "F.Cu" in p["layers"]]
                    nearby += [{"kind": "track", "net": t["net"], "start": t["start"], "end": t["end"],
                                "centerline_distance_mm": line.distance(t["shape"])}
                               for t in board.tracks if t["net"] != net and t["layer"] == "F.Cu"]
                    finding = {"net": net, "start": start, "end": end,
                               "nearest": sorted(nearby, key=lambda row: row["centerline_distance_mm"])[:5]}
                    (folder / "blocked_segment.json").write_text(json.dumps(finding, indent=2)+"\n")
                    print(json.dumps(finding, indent=2), flush=True)
                    raise
            critical.append({"net": net, "points": points, "purpose": purpose})
        def checkpoint(error=None):
            report = {"schema": "yam-k1-board-routing/1", **board.payload(),
                      "source_manifest_sha256": digest(data_path), "critical_routes": critical,
                      "physical_boards_tested": 0, "error": error,
                      "status": "Routing development; independent KiCad checking required"}
            (folder / "routing.json").write_text(json.dumps(report, indent=2)+"\n")
            return report
        try:
            trace("CIN1", [point("U1", 2), [14.5, 16.5], [14, 15.5], [12, 9.625], point("JS0", 1)],
                  "First guarded pressure input")
            trace("CIN2", [point("U1", 3), [12.5, 17], point("JS1", 1)], "Second guarded pressure input")
            trace("CIN3", [point("U1", 4), [14.5, 17.5], [14, 18.5], [12, 29.625], point("JS2", 1)],
                  "Third guarded pressure input")
            trace("CIN4", [point("U1", 5), [15.4, 18], [15.4, 22], [27.5, 22],
                           [27.5, 20.5], point("JREF", 1)], "Protected differential-reference input")
            trace("SHLD1", [point("U1", 1), [15.1, 16], [14.9, 15.5]], "Driven shield 1 to its plane")
            board.via("SHLD1", [14.9, 15.5], .5, .25)
            trace("SHLD2", [point("U1", 6), [20.5, 18.5], [20.5, 19]], "Driven shield 2 to its plane")
            board.via("SHLD2", [20.5, 19], .5, .25)
            trace("VDD_FDC", [point("U1", 8), point("CF1", 1)], "Direct 100 nF bypass supply")
            trace("VDD_FDC", [point("CF2", 1), [21.525, 14.8], [22.8, 15.2],
                              [22.025, 16], point("CF1", 1)], "Local bulk bypass supply")
            board.via("VDD_FDC", [22.8, 15.2], .5, .25)
            trace("GND", [point("CF1", 2), [23.85, 17.9]], "Short bypass ground")
            trace("GND", [point("U1", 7), [21.25, 17.5], [21.25, 18.3],
                          [23.85, 18.3], [23.85, 17.9]], "FDC ground to local bypass")
            board.via("GND", [23.85, 17.9], .5, .25)
            accesses = {}
            for net, ref, pin, path in (
                    ("SDA", "U1", 10, [[20.1, 15.0]]),
                    ("SCL", "U1", 9, [[21.2, 16.5], [21.2, 15.4], [21.05, 15.3]]),
                    ("SCL", "U2", 10, [[29.1, 26.8]]),
                    ("SDA", "U2", 9, [[30.2, 28.5], [30.2, 27.2]]),
                    ("RET0_F", "U2", 5, [[24.9, 31]]),
                    ("RET1_F", "U2", 6, [[29.1, 31]]),
                    ("RET2_F", "U2", 7, [[30.2, 29.5], [30.4, 30.2]]),
                    ("VDD_FDC", "U2", 4, [[23.2, 29.5]]),
                    ("GND", "U2", 1, [[24.9, 26.6]])):
                trace(net, [point(ref, pin), *path], "Reserved digital pin escape before long routing")
                board.via(net, path[-1], .5, .25)
                accesses[(ref, str(pin))] = path[-1]
            trace("GND", [point("U2", 1), [23.7, 28], [23.7, 29], point("U2", 3)],
                  "ADC ground/address link outside the unused ALERT land")
            accesses[("U2", "3")] = accesses[("U2", "1")]
            trace("3V3", [point("U2", 8), [30.4, 29], point("CD", 1)], "ADC supply directly to its bypass")
            accesses[("U2", "8")] = point("CD", 1)
            shield1 = Polygon([[5.9, 6.6], [13.1, 6.6], [15.2, 15.1], [17.1, 15.1],
                               [17.1, 17.72], [14.6, 17.72], [13.1, 30.9], [5.9, 30.9]])
            shield2 = Polygon([[15.2, 17.97], [22.2, 17.97], [22.2, 19.1], [31.4, 19.1],
                               [31.4, 22.9], [14.7, 22.9], [14.7, 18.9], [15.2, 18.9]])
            ground = Polygon([[32.5, .3], [41.7, .3], [41.7, 37.7], [.3, 37.7],
                              [.3, 32], [15.5, 32], [15.5, 24], [32.5, 24]])
            if shield1.distance(shield2) < .2:
                raise ValueError("Driven shield domains overlap")
            for net, polygon in (("SHLD1", shield1), ("SHLD2", shield2)):
                board.zones.append({"net": net, "layer": "In1.Cu", "shape": polygon})
            for layer in ("In2.Cu", "B.Cu"):
                board.zones.append({"net": "GND", "layer": layer, "shape": ground})
            connected = {
                "VDD_FDC": [point("U1", 8), point("CF1", 1), point("CF2", 1), [22.8, 15.2]],
                "GND": [point("U1", 7), point("CF1", 2), [23.85, 17.9]],
            }
            skip = {"CIN1", "CIN2", "CIN3", "CIN4", "SHLD1", "SHLD2"}
            for net in sorted(set(p["net"] for p in board.pads if p["net"])-skip,
                              key=lambda name: (name not in ("VDD_FDC", "GND", "3V3"), name)):
                pads = [p for p in board.pads if p["net"] == net]
                def endpoint(p):
                    return accesses.get((p["reference"], p["pad"]), p["center"])
                known = connected.setdefault(net, [endpoint(pads[0])])
                pending = list(pads)
                while pending:
                    pending = [p for p in pending if not any(math.dist(endpoint(p), q) < 1e-6 for q in known)]
                    if not pending:
                        break
                    _, index, destination = min((math.dist(endpoint(p), q), i, q)
                                                for i, p in enumerate(pending) for q in known)
                    pad = pending.pop(index)
                    router.connect(net, endpoint(pad), destination, time_limit_s=35)
                    known.append(endpoint(pad))
                checkpoint()
                print(f"{net}: all declared pads connected; {len(board.tracks)} total segments", flush=True)
            # Remove genuinely unused layer transitions, retaining connections
            # supplied by the declared same-net plane geometry.
            removed = []
            for via in list(board.vias):
                layers = {t["layer"] for t in board.tracks
                          if t["net"] == via["net"] and t["shape"].intersects(via["shape"])}
                for pad in board.pads:
                    if pad["net"] == via["net"] and pad["shape"].intersects(via["shape"]):
                        layers.update(pad["layers"])
                layers.update(z["layer"] for z in board.zones
                              if z["net"] == via["net"] and z["shape"].intersects(via["shape"]))
                if len(layers) < 2:
                    board.vias.remove(via)
                    removed.append({"net": via["net"], "center": via["center"], "layers": sorted(layers)})
            report = checkpoint()
            report["removed_unused_transitions"] = removed
            (folder / "routing.json").write_text(json.dumps(report, indent=2)+"\n")
            record["result"] = {"directory": str(folder.relative_to(ROOT)), "tracks": len(board.tracks),
                                "vias": len(board.vias), "zones": len(board.zones),
                                "signal_tracks_on_In1": sum(t["layer"] == "In1.Cu" for t in board.tracks),
                                "independent_check_pending": True}
            print(json.dumps(record["result"], indent=2))
        except Exception as error:
            checkpoint(str(error))
            record["failed_route"] = {"directory": str(folder.relative_to(ROOT)), "error": str(error)}
            raise


if __name__ == "__main__":
    main()
