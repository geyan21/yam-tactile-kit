#!/usr/bin/python3
"""Check cross-module P1 fit and the board pin contract; draw an assembly card."""

import argparse
from datetime import datetime, timezone
import html
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/pneumatic-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import cadquery as cq
from build_pneumatic_ported_assembly import overlap
from screen_f1_feedback import digest
from tactile_kit.records import execution


def card(board, path):
    def point(x, y):
        return 42+12*x, 112+12*y
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1380 1210" role="img" aria-labelledby="title desc">',
             '<title id="title">P1 PCB component-side orientation and pin-one map</title>',
             '<desc id="desc">Actual generated footprint positions. Left pressure sensors face outward to the left, right sensors to the right. Red marks identify pin one; the two Pico socket pin-one positions are at the USB end.</desc>',
             '<rect width="1380" height="1210" fill="#f7f9f5"/><g font-family="sans-serif" fill="#203e47">',
             '<text x="36" y="38" font-size="27" font-weight="700">P1.0 · PCB assembly orientation</text>',
             '<text x="36" y="70" font-size="17">Component side · red marks = pin 1 · confirm physical parts before soldering</text>',
             '<rect x="42" y="112" width="960" height="1032" fill="#e3eee3" stroke="#4a7063" stroke-width="2"/>']
    for component in board["components"]:
        if "body_mm" not in component:
            continue
        x, y = point(*component["center_mm"])
        w, h = component["body_mm"]
        rotation = -component["rotation_deg"]
        color = "#b9ccd7" if component["reference"].startswith("PS") else "#e3d6bb"
        lines.append(f'<rect x="{x-w*6:.3f}" y="{y-h*6:.3f}" width="{w*12:.3f}" height="{h*12:.3f}" transform="rotate({rotation} {x} {y})" fill="{color}" stroke="#81998f" stroke-width=".7"/>')
    for pad in board["pads"]:
        x, y = point(*pad["center"])
        w, h = pad["size"]
        lines.append(f'<rect x="{x-w*6:.3f}" y="{y-h*6:.3f}" width="{w*12:.3f}" height="{h*12:.3f}" transform="rotate({-pad["rotation"]} {x} {y})" fill="#b39458" stroke="white" stroke-width=".5"/>')
        if pad.get("drill"):
            lines.append(f'<circle cx="{x}" cy="{y}" r="{pad["drill"]*6}" fill="#f7f9f5"/>')
        if pad["pad"] == "1":
            lines.append(f'<circle cx="{x}" cy="{y}" r="4" fill="#c64239"/>')
        if pad["reference"].startswith("PS"):
            lines.append(f'<text x="{x}" y="{y+4}" text-anchor="middle" font-size="11" font-weight="700">{pad["pad"]}</text>')
    for hole in board["holes"]:
        x, y = point(*hole["center"])
        lines.append(f'<circle cx="{x}" cy="{y}" r="{hole["diameter"]*6}" fill="white" stroke="#557365"/>')
    for component in board["components"]:
        ref = component["reference"]
        x, y = point(*component["center_mm"])
        large = ref.startswith(("PS", "JP", "U"))
        label = ref+(f" / CH{int(ref[2:])+2}" if ref.startswith("PS") else "")
        lines.append(f'<text x="{x}" y="{y+4}" text-anchor="middle" font-size="{18 if large else 11}" font-weight="700" stroke="white" stroke-width="3" paint-order="stroke">{html.escape(label)}</text>')
        if ref.startswith("PS"):
            sign = -1 if component["rotation_deg"] == 180 else 1
            lines.append(f'<path d="M{x+sign*72} {y}h{sign*34}m{-sign*10} -6l{sign*10} 6l{-sign*10} 6" fill="none" stroke="#345f78" stroke-width="3"/>')
    x, y = point(40, 2.2)
    lines.append(f'<text x="{x}" y="{y}" text-anchor="middle" font-size="19" font-weight="700">Pico USB end ↑</text>')
    notes = [
        ("SENSOR ORIENTATION", "21"),
        ("PS0 / PS1: ports left", "17"),
        ("PS2 / PS3: ports right", "17"),
        ("All sensors: B → front", "17"),
        ("A → back of the same CH", "17"),
        ("", "17"),
        ("F1RD PINS", "21"),
        ("1 = 3V0; 2 = GND", "17"),
        ("5 = SCL; 8 = SDA", "17"),
        ("3 / 4 / 6 / 7 unconnected", "17"),
        ("Row spacing = 16.26 mm", "17"),
        ("Pin pitch = 2.54 mm", "17"),
        ("", "17"),
        ("PICO SOCKETS", "21"),
        ("JP1 pin 1 = Pico pin 1", "17"),
        ("JP2 pin 1 = Pico pin 40", "17"),
        ("Both start at the USB end.", "17"),
        ("", "17"),
        ("JN NAIL LEADS", "21"),
        ("1: +3V3   2: CH0 signal", "17"),
        ("3: +3V3   4: CH1 signal", "17"),
        ("", "17"),
        ("JT TEST POINTS", "21"),
        ("1 GND · 2 3V0", "17"),
        ("3 3V3 · 4 USB VBUS", "17"),
        ("", "17"),
        ("PCB: 80 × 86 × 1.6 mm", "18"),
        ("Copper hidden on this card.", "17"),
        ("Use checked fabrication files.", "17"),
    ]
    for index, (text, size) in enumerate(notes):
        lines.append(f'<text x="1032" y="{145+31*index}" font-size="{size}">{html.escape(text)}</text>')
    lines.append('<text x="36" y="1181" font-size="17">Generated from the actual board component/pad positions. This is an assembly guide, not a copper mask or a physical board photograph.</text></g></svg>')
    path.write_text("\n".join(lines)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assembly", "bench", "board"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ("assembly", "bench", "board")}
    if not all(path.is_relative_to(ROOT/"build") for path in paths.values()):
        parser.error("Use this checkout's generated P1 inputs")
    reports = {name: json.loads((path/"report.json").read_text()) for name, path in paths.items()}
    for report in reports.values():
        for name, expected in report["input_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError("Input changed before integration review: "+name)
    if any(not reports[name]["passed_nominal_checks"] for name in ("assembly", "bench")):
        raise ValueError("Resolve the module checks first")
    board = json.loads((paths["board"]/"p1_readout.json").read_text())
    native = json.loads((paths["board"]/"latest_check.json").read_text())
    if native["violations"] or native["unconnected"] or native["source_sha256"] != reports["board"]["pcb_sha256"]:
        raise ValueError("A matching complete native PCB check is required")
    folder = ROOT/"build/engineering/prototypes/pneumatic/integration_reviews"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Check the P1 nail/air-module interface and source-referenced board pin/power contract; draw pin-one and sensor orientation without altering copper") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        loaded = {}
        for module in ("assembly", "bench"):
            for part in reports[module]["parts"]:
                if module == "bench" and not part["id"].startswith(("p1_ch0_", "p1_ch1_")):
                    continue
                path = paths[module]/part["step"]
                if digest(path) != part["sha256_step"]:
                    raise ValueError("CAD changed")
                loaded[part["id"]] = cq.importers.importStep(str(path)).val()
        nails = [name for name in loaded if name.startswith(("p1_ch0_", "p1_ch1_"))]
        air_parts = [part["id"] for part in reports["assembly"]["parts"]]
        cross_checks = [{"a": a, "b": b, "overlap_mm3": overlap(loaded[a], loaded[b])}
                        for a in nails for b in air_parts]
        failures = [row for row in cross_checks if row["overlap_mm3"] > .001]
        maps = {}
        for pad in board["pads"]:
            maps.setdefault(pad["reference"], {})[int(pad["pad"])] = pad["net"]
        contracts = []
        def expect(ref, expected, source):
            good = maps.get(ref) == expected
            contracts.append({"reference": ref, "expected_pin_nets": expected, "source": source, "passed": good})
            if not good:
                failures.append({"reference": ref, "reason": "pin_contract"})
        for index in range(4):
            expect("PS"+str(index), {1: "3V0", 2: "GND", 3: "", 4: "", 5: "SC"+str(index),
                                     6: "", 7: "", 8: "SD"+str(index)}, "DS-0375 Rev C F1RD page14")
        expect("U1", {1: "GND", 2: "GND", 3: "MUX_RST", 4: "SD0", 5: "SC0", 6: "SD1", 7: "SC1",
                      8: "SD2", 9: "SC2", 10: "SD3", 11: "SC3", 12: "GND", 13: "", 14: "", 15: "",
                      16: "", 17: "", 18: "", 19: "", 20: "", 21: "GND", 22: "P_SCL", 23: "P_SDA", 24: "3V0"},
               "TI SCPS207H Table4-1 PW/TSSOP column; A0/A1/A2 grounded")
        expect("U2", {1: "GND", 2: "", 3: "GND", 4: "NAIL0", 5: "NAIL1", 6: "MON_3V0",
                      7: "MON_3V3", 8: "3V3", 9: "N_SDA", 10: "N_SCL"}, "TI ADS1115 MSOP-10")
        expect("U3", {1: "5V_USB", 2: "GND", 3: "5V_USB", 4: "", 5: "3V0"}, "TI SNVS798Q Table4-2 SOT-23")
        expect("JN", {1: "3V3", 2: "NAIL0", 3: "3V3", 4: "NAIL1"}, "P1 nail harness")
        expect("JT", {1: "GND", 2: "3V0", 3: "3V3", 4: "5V_USB"}, "P1 supply test points")
        dimensions = []
        for index in range(4):
            pads = [pad for pad in board["pads"] if pad["reference"] == "PS"+str(index)]
            by_number = {int(pad["pad"]): pad for pad in pads}
            pitch = math.dist(by_number[1]["center"], by_number[2]["center"])
            rows = math.dist(by_number[1]["center"], by_number[8]["center"])
            good = abs(pitch-2.54) < 1e-8 and abs(rows-16.26) < 1e-8 and all(.89 <= p["drill"] <= 1 for p in pads)
            dimensions.append({"sensor": "PS"+str(index), "pitch_mm": pitch, "row_spacing_mm": rows, "passed": good})
            if not good:
                failures.append({"reference": "PS"+str(index), "reason": "F1RD_lands"})
        card(board, folder/"p1_pcb_orientation.svg")
        inputs = [Path(__file__), ROOT/"engineering/scripts/build_pneumatic_ported_assembly.py",
                  *[path/"report.json" for path in paths.values()], paths["board"]/"p1_readout.json",
                  paths["board"]/"latest_check.json", paths["board"]/"p1_readout.kicad_pcb"]
        report = {"schema": "yam-p1-integration-review/1", "physical_specimens_tested": 0, "passed": not failures,
                  "cross_module_checks": cross_checks, "electrical_contracts": contracts, "land_checks": dimensions,
                  "failures": failures, "native_pcb_check": native,
                  "module_comparisons": {"air_module_material_source_and_gas": len(reports["assembly"]["checks"]),
                                         "local_hose_guards": len(reports["assembly"]["hose_guard_checks"]),
                                         "bench_and_nail_module": len(reports["bench"]["checks"]),
                                         "nail_to_air_module": len(cross_checks)},
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "files_sha256": {"p1_pcb_orientation.svg": digest(folder/"p1_pcb_orientation.svg")},
                  "limits": ["Nominal CAD and explicit pin nets; no fitted hardware, actual port mating, leak, loaded clearance or tactile performance test.",
                             "The PCB review checks the declared connectivity, not a physical continuity measurement or circuit certification."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report["module_comparisons"], "failures": failures}
        print(json.dumps(record["result"], indent=2))
        if failures:
            raise ValueError("Resolve the integration findings")


if __name__ == "__main__":
    main()
