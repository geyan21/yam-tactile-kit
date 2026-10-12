#!/usr/bin/python3
"""Generate and route the P1 four-transducer bench board from explicit pin maps."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/pneumatic-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
from shapely.geometry import box
from prototype_pcb import Board
from prototype_route import Router
from screen_f1_feedback import digest
from tactile_kit.records import execution

CONFIG = ROOT/"engineering/designs/pneumatic_electronics.json"
SOURCES = {
    "pressure": "All Sensors DS-0375 Rev C pp14,21, F1RD/PAD-27",
    "mux": "TI SCPS207H Table 4-1, PW0024A 0.65mm land pattern",
    "regulator": "TI SNVS798Q Table 4-2, DBV0005A land pattern",
    "adc": "TI SBAS444E DGS0010A, 0.5mm pitch",
    "pico": "Raspberry Pi Pico datasheet, original RP2040 40-pin top view",
}


def passive(board, ref, value, center, nets, rotation=0):
    board.component(ref, value, center, [
        (1, -.825, 0, .9, .95, nets[0]), (2, .825, 0, .9, .95, nets[1])
    ], rotation=rotation, body=[1.6, .8], height=.9,
        source="0603 metric 1608 prototype land pattern")


def placement(cfg):
    board = Board("p1_readout", box(0, 0, 80, 86), thickness=1.6, clearance=.15, edge=.3)
    for point in ([3, 3], [77, 3], [3, 83], [77, 83]):
        board.add_hole(point, 2.4, 5.4)
    pico = {pin: "GND" for pin in (3, 8, 13, 18, 23, 28, 33, 38)}
    pico.update({1: "P_SDA", 2: "P_SCL", 4: "N_SDA", 5: "N_SCL", 9: "MUX_RST",
                 36: "3V3", 40: "5V_USB"})
    for ref, x, pins in (("JP1", 31.11, range(1, 21)), ("JP2", 48.89, range(40, 20, -1))):
        board.component(ref, "1x20 2.54mm female socket for original Pico", [x, 30.13], [
            (i+1, 0, (i-9.5)*2.54, 1.85, 1.85, pico.get(pin, ""), False)
            for i, pin in enumerate(pins)
        ], body=[2.54, 50.8], height=8.5, source=SOURCES["pico"],
            note="Pin 1 on both sockets is at the USB end; right socket maps Pico 40 down to 21.")
        for pad in board.pads:
            if pad["reference"] == ref:
                pad["drill"] = 1.0
    for index, channel in enumerate(cfg["channels"]):
        nets = {1: "3V0", 2: "GND", 3: "", 4: "", 5: f"SC{index}", 6: "", 7: "", 8: f"SD{index}"}
        pads = []
        for i in range(4):
            pads += [(i+1, (i-1.5)*2.54, 8.13, 1.8, 1.8, nets[i+1], False),
                     (8-i, (i-1.5)*2.54, -8.13, 1.8, 1.8, nets[8-i], False)]
        board.component(channel["sensor"], cfg["pressure_sensor"], channel["center_mm"], pads,
                        rotation=channel["rotation_deg"], body=[12.7, 16.5], height=10.,
                        source=SOURCES["pressure"],
                        note="F1RD top view: pins 1..4 on bottom row, 8..5 on top, ports right before rotation. Pins 3/4/6/7 unconnected.")
        for pad in board.pads:
            if pad["reference"] == channel["sensor"]:
                pad["drill"] = .95
        x, y = channel["center_mm"]
        pass_x = 23 if x < 40 else 57
        cap_y = y-8.13 if x < 40 else y+8.13
        passive(board, f"CP{index}", "100nF 16V X7R 0603", [pass_x, cap_y], ("3V0", "GND"))
        passive(board, f"RD{index}", "2.2k 1% 0603", [pass_x, y+1], ("3V0", f"SD{index}"))
        passive(board, f"RC{index}", "2.2k 1% 0603", [pass_x, y+4], ("3V0", f"SC{index}"))
    mux_nets = {1: "GND", 2: "GND", 3: "MUX_RST", 4: "SD0", 5: "SC0", 6: "SD1",
                7: "SC1", 8: "SD2", 9: "SC2", 10: "SD3", 11: "SC3", 12: "GND",
                13: "", 14: "", 15: "", 16: "", 17: "", 18: "", 19: "", 20: "",
                21: "GND", 22: "P_SCL", 23: "P_SDA", 24: "3V0"}
    pads = []
    for i in range(12):
        pads += [(i+1, -2.9, (i-5.5)*.65, 1.5, .4, mux_nets[i+1]),
                 (24-i, 2.9, (i-5.5)*.65, 1.5, .4, mux_nets[24-i])]
    board.component("U1", cfg["mux"]["part"], [22, 66], pads, body=[4.4, 7.8],
                    height=1.2, source=SOURCES["mux"])
    adc_nets = {1: "GND", 2: "", 3: "GND", 4: "NAIL0", 5: "NAIL1",
                6: "MON_3V0", 7: "MON_3V3", 8: "3V3", 9: "N_SDA", 10: "N_SCL"}
    pads = []
    for i in range(5):
        pads += [(i+1, -2.2, (i-2)*.5, 1.45, .3, adc_nets[i+1]),
                 (10-i, 2.2, (i-2)*.5, 1.45, .3, adc_nets[10-i])]
    board.component("U2", cfg["adc"]["part"], [45, 66], pads, body=[3, 3],
                    height=1.1, source=SOURCES["adc"])
    board.component("U3", cfg["regulator"]["part"], [63, 66], [
        (1, -1.3, -.95, 1.1, .6, "5V_USB"), (2, -1.3, 0, 1.1, .6, "GND"),
        (3, -1.3, .95, 1.1, .6, "5V_USB"), (4, 1.3, .95, 1.1, .6, ""),
        (5, 1.3, -.95, 1.1, .6, "3V0")
    ], body=[1.6, 2.9], height=1.45, source=SOURCES["regulator"])
    for ref, value, xy, nets in [
        ("CM1", "100nF 16V X7R 0603", [28, 61.5], ("3V0", "GND")),
        ("CM2", "1uF 16V X7R 0603", [28, 58.5], ("3V0", "GND")),
        ("RM", "10k 1% 0603", [17, 59], ("3V0", "MUX_RST")),
        ("RPD", "4.7k 1% 0603", [17, 75], ("3V3", "P_SDA")),
        ("RPC", "4.7k 1% 0603", [22, 75], ("3V3", "P_SCL")),
        ("RND", "4.7k 1% 0603", [41, 58.5], ("3V3", "N_SDA")),
        ("RNC", "4.7k 1% 0603", [45, 58.5], ("3V3", "N_SCL")),
        ("CA", "100nF 16V X7R 0603", [50.5, 64], ("3V3", "GND")),
        ("RN0", "10k 1% 0603", [37, 71], ("NAIL0", "GND")),
        ("RN1", "10k 1% 0603", [37, 74], ("NAIL1", "GND")),
        ("RM0", "1k 1% 0603", [52, 72], ("3V0", "MON_3V0")),
        ("RM1", "1k 1% 0603", [57, 72], ("3V3", "MON_3V3")),
        ("CH0", "10nF 50V C0G 0603", [52, 75], ("MON_3V0", "GND")),
        ("CH1", "10nF 50V C0G 0603", [57, 75], ("MON_3V3", "GND")),
        ("CI", "2.2uF 16V X7R 0603 effective >=1uF at 5V", [58, 65.05], ("5V_USB", "GND")),
        ("CO", "2.2uF 16V X7R 0603 effective >=1uF at 3V", [68, 65.05], ("3V0", "GND")),
        ("CB", "2.2uF 16V X7R 0603", [64, 58], ("3V0", "GND"))
    ]:
        passive(board, ref, value, xy, nets)
    board.wire_port("JN", [42, 79], ["3V3", "NAIL0", "3V3", "NAIL1"], pitch=2.54)
    for pad in board.pads:
        if pad["reference"] == "JN":
            pad["drill"] = .6
    # These probe lands have no pin/socket body.
    board.wire_port("JT", [68, 78], ["GND", "3V0", "3V3", "5V_USB"], pitch=2.54)
    return board


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--placement-only", action="store_true")
    args = parser.parse_args()
    cfg = json.loads(CONFIG.read_text())
    folder = ROOT/"build/engineering/prototypes/pneumatic/boards"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Generate the explicit P1 pressure/nail readout and route its nets; export only source until a separate KiCad DRC passes") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [CONFIG, Path(__file__), ROOT/"engineering/scripts/prototype_pcb.py",
                  ROOT/"engineering/scripts/prototype_route.py"]
        for path in inputs:
            target = folder/"inputs"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        board = placement(cfg)
        board.write(folder/"placement")
        board.assembly_svg(folder/"placement.svg")
        completed = []
        def checkpoint(error=None):
            payload = board.write(folder)
            report = {"schema": "yam-p1-board-development/1", "physical_boards_tested": 0,
                      "components": len(board.components), "tracks": len(board.tracks),
                      "vias": len(board.vias), "routed_nets": completed,
                      "pcb_sha256": digest(folder/"p1_readout.kicad_pcb"), "error": error,
                      "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                      "status": "Independent native DRC and physical bring-up required"}
            (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
            return report
        if not args.placement_only:
            router = Router(board, grid=.2, width=.15, via_diameter=.45, via_drill=.2)
            router.signal_layers, router.layer_cost = ("F.Cu", "In2.Cu", "B.Cu"), (1, 1.3, 1)
            try:
                access = {}
                for pad in board.pads:
                    if not pad["net"]:
                        continue
                    access[(pad["reference"], pad["pad"])] = (pad["center"] if pad.get("drill")
                                                               else router.escape(pad))
                print("All connected SMD pads have reserved via escapes.", flush=True)
                grouped = {}
                for pad in board.pads:
                    if pad["net"] and pad["net"] != "GND":
                        grouped.setdefault(pad["net"], []).append(access[(pad["reference"], pad["pad"])])
                # Small local nets first, then power trees. Each route search
                # is bounded by the shared router's per-connection limit.
                names = sorted(grouped, key=lambda name: (name in ("3V0", "3V3", "5V_USB"), len(grouped[name]), name))
                for name in names:
                    pending = list(dict.fromkeys(tuple(p) for p in grouped[name]))
                    connected = [pending.pop(0)]
                    while pending:
                        _, a, b = min((math.dist(a, b), a, b) for a in connected for b in pending)
                        router.connect(name, a, b)
                        connected.append(b)
                        pending.remove(b)
                    completed.append(name)
                    checkpoint()
                    print("Routed "+name, flush=True)
                board.zones.append({"net": "GND", "layer": "In1.Cu", "shape": board.outline.buffer(-.3)})
                board.prune_unused_vias()
            except Exception as error:
                checkpoint(str(error))
                raise
        report = checkpoint()
        board.assembly_svg(folder/"assembly.svg")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
