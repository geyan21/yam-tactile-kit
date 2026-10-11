#!/usr/bin/python3
"""Draw the selected-column F1 signal topology from the reviewed parameters."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon, Circle

CONFIG = ROOT / "engineering/designs/f1_feedback_screen.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    path = args.config.resolve()
    if not path.is_relative_to(ROOT):
        parser.error("Use a repository-owned configuration")
    cfg = json.loads(path.read_text())
    destination = ROOT / "build/engineering/prototypes/f1/feedback_drawings" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Draw a readable F1 selected-column circuit with explicit gain and parking paths") as record:
        destination.mkdir(parents=True, exist_ok=False)
        fig, ax = plt.subplots(figsize=(17, 10))
        ax.set(xlim=(0, 1600), ylim=(950, 0), aspect="equal")
        ax.axis("off")
        wire_color = "#245562"
        ink = "#213344"

        def wire(points, color=wire_color, style="-", width=1.7):
            ax.plot([p[0] for p in points], [p[1] for p in points],
                    color=color, linestyle=style, linewidth=width, zorder=1)

        def label(x, y, text, size=10, align="center", color=ink):
            ax.text(x, y, text, ha=align, va="center", fontsize=size, color=color,
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": .94, "pad": 1.5},
                    zorder=5)

        def dot(x, y):
            ax.add_patch(Circle((x, y), 3.3, color=wire_color, zorder=4))

        def block(x, y, w, h, text, color="#edf4f7", size=10):
            ax.add_patch(Rectangle((x, y), w, h, facecolor=color, edgecolor="#567482", linewidth=1.3, zorder=3))
            label(x+w/2, y+h/2, text, size)

        def resistor(x0, x1, y, text, label_above=True):
            center = (x0+x1)/2
            length = min(68, (x1-x0)*.55)
            wire([(x0, y), (center-length/2, y)])
            wire([(center+length/2, y), (x1, y)])
            ax.add_patch(Rectangle((center-length/2, y-8), length, 16,
                                   facecolor="white", edgecolor=wire_color, linewidth=1.6, zorder=4))
            label(center, y-25 if label_above else y+25, text, 10)

        def capacitor(x0, x1, y, text):
            c = (x0+x1)/2
            wire([(x0, y), (c-6, y)])
            wire([(c+6, y), (x1, y)])
            wire([(c-6, y-16), (c-6, y+16)])
            wire([(c+6, y-16), (c+6, y+16)])
            label(c, y-28, text, 10)

        def ground(x, y):
            wire([(x, y), (x, y+12)])
            for dy, half in ((12, 15), (18, 10), (24, 5)):
                wire([(x-half, y+dy), (x+half, y+dy)], width=1.2)

        label(790, 25, "F1 wrist readout · selected-column signal stage", 17)
        label(790, 55, "Development topology — modeled at 3.3 V; complete row, reference and ADC stages remain to finish", 11)

        # The force-sensitive film and its FPC remain beyond the sense pickup.
        block(20, 365, 145, 105, "FPC + four cells\nof selected column\nC0–C15", size=10)
        wire([(165, 420), (205, 420)])
        dot(205, 420)
        label(210, 485, "Fanout pickup\nat sensor connector", 10)
        wire([(205, 420), (205, 250), (360, 250)])
        label(280, 220, "Ck_I · wrist FFC", 10)
        block(360, 205, 175, 90, "ADG706BRUZ\ncurrent mux", size=11)
        wire([(535, 250), (785, 250)])
        label(650, 223, "CURRENT_D", 10)
        dot(650, 250)
        wire([(650, 250), (650, 320)])
        wire([(635, 320), (665, 320)])
        wire([(635, 331), (665, 331)])
        ground(650, 342)
        label(720, 333, f"{cfg['current_drain_shunt_capacitance_pf']/1000:g} nF\nfixed C0G", 10)

        # The gain-bank table describes four complete switched R||C branches.
        block(785, 100, 420, 255, "", "#f4f7eb")
        label(995, 122, "TMUX1112PWR · one selected Rf || Cf branch", 11)
        label(995, 149, "OUTPUT BUS  —  switch  —  Rf || Cf  —  CURRENT_D", 9)
        for index, b in enumerate(cfg["gain_selection"]["branches"]):
            label(995, 183+38*index,
                  f"GAIN{b['id']}      {b['resistance_ohm']/1000:g} kΩ   ||   {b['feedback_capacitance_pf']:g} pF", 11)
        wire([(1205, 250), (1300, 250)])
        dot(1300, 250)
        label(1300, 210, "OUTPUT BUS", 10)
        wire([(1300, 250), (1380, 250)])
        block(1380, 175, 200, 150, "ADC input buffer\n↓\nADS8866IDGSR\n16-bit candidate\n(details pending)", size=11)

        # OPA392 uses the current/sense loop; output bus is measured after RISO.
        ax.add_patch(Polygon([(1080, 445), (1080, 585), (1220, 515)],
                             facecolor="#eaf2f1", edgecolor=wire_color, linewidth=1.7, zorder=3))
        label(1100, 475, "+", 16)
        label(1100, 556, "−", 16)
        label(1150, 515, "OPA392\nDBV", 10)
        label(1160, 414, "+3.3 V / GND", 10)
        wire([(1000, 475), (1080, 475)])
        label(1000, 445, "VBIAS ≈ 1.65 V", 10)
        wire([(1220, 515), (1300, 515)])
        dot(1300, 515)
        label(1370, 515, "AMP OUT", 10)
        wire([(1300, 515), (1300, 407)])
        ax.add_patch(Rectangle((1292, 369), 16, 38, facecolor="white", edgecolor=wire_color, linewidth=1.6, zorder=4))
        wire([(1300, 369), (1300, 250)])
        label(1380, 385, f"RISO {cfg['output_isolation_ohm']:g} Ω", 10)

        wire([(205, 420), (205, 590), (360, 590)])
        label(280, 540, "Ck_S · wrist FFC\n0 Ω pickup link on fanout", 9)
        block(360, 550, 175, 85, "ADG706BRUZ\nsense mux", size=11)
        wire([(535, 590), (650, 590)])
        dot(650, 590)
        label(615, 560, "SENSE_D", 10)
        resistor(650, 820, 590, f"{cfg['low_gain_compensation']['additional_series_resistance_ohm']:g} Ω")
        dot(820, 590)
        resistor(820, 1000, 590, f"RINPUT {cfg['sense_input_resistance_ohm']:g} Ω")
        dot(1000, 590)
        wire([(1000, 590), (1000, 556), (1080, 556)])

        # The bypass is controlled by the existing GAIN0 line.
        wire([(650, 590), (650, 668), (682, 668)])
        block(682, 646, 105, 44, "TMUX1102", size=9)
        wire([(787, 668), (820, 668), (820, 590)])
        label(735, 715, "SEL = GAIN0\nG0: 680 Ω retained\nG1–G3: bypassed", 9)

        # Local high-frequency feedback and active park share FB after RINPUT.
        wire([(1300, 515), (1300, 850)])
        capacitor(1000, 1300, 705, f"C local {cfg['local_park_feedback']['capacitance_pf']:g} pF")
        wire([(1000, 705), (1000, 590)])
        dot(1300, 705); dot(1000, 705)
        wire([(1000, 780), (1000, 705)])
        resistor(1000, 1160, 780, "1 kΩ")
        block(1160, 757, 120, 46, "TMUX1101\nPARK", size=9)
        wire([(1280, 780), (1300, 780)])
        dot(1300, 780); dot(1000, 780)
        label(1375, 778, "HIGH = parked\npull-up at reset", 9)

        # Weak DC return goes BEFORE the compensation resistors.
        wire([(650, 590), (650, 850)])
        resistor(650, 1300, 850, f"R park {cfg['local_park_feedback']['resistance_ohm']/1e6:g} MΩ", False)
        dot(1300, 850)
        label(480, 835, "Weak DC return\nbefore RBOOST/RINPUT", 10)

        # Shared control identities; dotted lines are annotations, not copper.
        label(447, 415, "Shared A[3:0]\nseparate CUR_EN / SNS_EN", 10, color="#70522e")
        wire([(447, 295), (447, 375)], color="#a08050", style=":", width=1)
        wire([(447, 455), (447, 550)], color="#a08050", style=":", width=1)
        label(1185, 927, "PARK → select channel/gain → release PARK → settle/baseline → excite row → settle/sample", 9)
        label(450, 927, "Signal topology only. Power bypassing, row drivers, reference generation,\nADC drive and complete hardware checks are still required.", 9)
        fig.tight_layout(pad=.4)
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(destination / ("f1_feedback_topology."+suffix), dpi=170, bbox_inches="tight")
        plt.close(fig)
        receipt = {"configuration": str(path.relative_to(ROOT)),
                   "configuration_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "physical_evidence": False,
                   "scope": "Selected-column signal topology, not a completed wrist board"}
        (destination / "drawing.json").write_text(json.dumps(receipt, indent=2)+"\n")
        record["drawing"] = receipt
        print(json.dumps({"directory": str(destination.relative_to(ROOT)), **receipt}, indent=2))


if __name__ == "__main__":
    main()
