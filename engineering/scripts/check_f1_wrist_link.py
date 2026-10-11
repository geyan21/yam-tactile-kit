#!/usr/bin/python3
"""Check native connector pin correspondence for the stated F1 FFC mating pose."""

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest

FANOUT = ROOT / "engineering/development/f1/fanout/pcb"


def unrotated_contacts(folder, name):
    manifest = json.loads((folder / f"{name}.json").read_text())
    if digest(folder / f"{name}.kicad_pcb") != manifest["pcb_sha256"]:
        raise ValueError("Native board differs from its geometry manifest")
    part = next(p for p in manifest["parts"] if p["reference"] == "JW")
    if part["side"] != "F":
        raise ValueError("The declared inspection pose requires both connectors on the front face")
    theta = math.radians(part.get("rotation_deg", 0))
    c, s = math.cos(theta), math.sin(theta)
    contacts = {}
    for pad in manifest["pads"]:
        if pad["reference"] != "JW" or not pad["pad"].isdigit():
            continue
        x = pad["center"][0]-part["center_mm"][0]
        y = pad["center"][1]-part["center_mm"][1]
        contacts[int(pad["pad"])] = {"x": c*x-s*y, "y": s*x+c*y, "net": pad["net"]}
    if set(contacts) != set(range(1, 51)):
        raise ValueError("Expected exactly fifty numbered cable contacts")
    return manifest, part, contacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wrist_directory", type=Path)
    parser.add_argument("--fanout", type=Path, default=FANOUT)
    parser.add_argument("--fanout-name", choices=("f1_fanout", "f1_fanout_r3"), default="f1_fanout")
    args = parser.parse_args()
    wrist_folder = args.wrist_directory.resolve()
    fanout_folder = args.fanout.resolve()
    if not wrist_folder.is_relative_to(ROOT) or not fanout_folder.is_relative_to(ROOT):
        parser.error("Use a repository-owned wrist board")
    folder = ROOT / "build/engineering/prototypes/f1/mating_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check fifty native FFC pin identities for a stated same-side-contact cable inspection pose; no claim of physical continuity or installed cable fit") as record:
        folder.mkdir(parents=True, exist_ok=False)
        fanout, fp, first = unrotated_contacts(fanout_folder, args.fanout_name)
        wrist, wp, second = unrotated_contacts(wrist_folder, "f1_wrist")
        if fp["value"] != wp["value"]:
            raise ValueError("The contract assumes identical bottom-contact connector parts")
        rows = []
        for pin, contact in sorted(first.items()):
            # Rotate the second component 180 degrees in the same board
            # plane so that its cable mouth opposes the first. A straight
            # ribbon conductor retains its transverse position.
            other = min(second, key=lambda k: abs(contact["x"]+second[k]["x"]))
            transverse_error = abs(contact["x"]+second[other]["x"])
            rows.append({"fanout_pin": pin, "wrist_pin": other, "fanout_net": contact["net"],
                         "wrist_net": second[other]["net"], "transverse_error_mm": transverse_error,
                         "passed": bool(other == 51-pin and transverse_error < 2e-6
                                        and contact["net"] == second[other]["net"])})
        if len({r["wrist_pin"] for r in rows}) != 50:
            raise ValueError("Mating correspondence is not one-to-one")
        with (folder / "continuity_checklist.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["fanout_connector", "fanout_pin", "wrist_connector", "wrist_pin", "net",
                             "measured_continuity_ohm", "adjacent_short_check", "operator", "date"])
            for row in rows:
                writer.writerow(["JW", row["fanout_pin"], "JW", row["wrist_pin"], row["fanout_net"], "", "", "", ""])
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        fig, ax = plt.subplots(figsize=(12, 6), layout="constrained")
        for y in (5, 75):
            ax.add_patch(Rectangle((-14.55, y-2), 29.1, 4.4, facecolor="#d9e4ea", edgecolor="#43646c"))
        colors = {"GND": "#556979", "+3V3": "#bc5834", "R0_I": "#3a8b63", "R0_S": "#6ca786",
                  "C0_I": "#7254a0", "C0_S": "#a08bbe", "C15_I": "#aa6b25", "C15_S": "#c99f63"}
        for row in rows:
            x = first[row["fanout_pin"]]["x"]
            color = colors.get(row["fanout_net"], "#c3c9cf")
            ax.plot([x, x], [7.4, 73], color=color, lw=1.6 if row["fanout_net"] in colors else .6)
        for pin in (1, 2, 11, 12, 19, 20, 49, 50):
            x = first[pin]["x"]
            ax.text(x, 2, str(pin), ha="center", va="top", fontsize=9)
            ax.text(x, 80, str(51-pin), ha="center", va="bottom", fontsize=9)
        ax.text(-17, 5, "Finger fanout JW", ha="right", va="center", fontsize=11)
        ax.text(-17, 75, "Wrist JW", ha="right", va="center", fontsize=11)
        ax.text(17, 40, "Same-side contact FFC\nBoth connector board faces parallel\nCable mouths face one another\n\nPin n → pin 51−n\nUnpowered continuity check required",
                va="center", fontsize=11)
        ax.set(xlim=(-40, 50), ylim=(86, -7))
        ax.axis("off")
        fig.suptitle("F1 cable inspection pose · native pin correspondence\n"
                     "Illustration is not the installed cable route; solder-land transverse order represents contact order.", fontsize=13)
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(folder / f"mating_pose.{suffix}", dpi=160)
        plt.close(fig)
        report = {"schema": "yam-f1-wrist-link-correspondence/1",
                  "physical_continuity_measured": False, "installed_cable_geometry_verified": False,
                  "contract": "Identical bottom-contact connectors, same-side exposed FFC contacts, parallel board faces and opposing mouths in a straight inspection pose",
                  "fanout_source_sha256": fanout["pcb_sha256"], "wrist_source_sha256": wrist["pcb_sha256"],
                  "results": rows, "passed": all(r["passed"] for r in rows),
                  "maximum_transverse_error_mm": max(r["transverse_error_mm"] for r in rows),
                  "limits": "Checks connector numbering in the stated pose. Actual cable style, exposed-contact side, seating, continuity, shorts, strain relief and installed robot clearance require physical/geometry checks."}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "passed": report["passed"],
                            "connections": len(rows), "maximum_transverse_error_mm": report["maximum_transverse_error_mm"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
