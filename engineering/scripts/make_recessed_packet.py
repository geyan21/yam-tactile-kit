#!/usr/bin/python3
"""Prepare B3's BOM, wiring and exact sensor-position table from checked inputs."""

import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/prototypes/recessed"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    plan = json.loads((OUTPUT / "recessed_manifest.json").read_text())
    with execution(ROOT / "build/records", "Make B3 build material from the retained B2 circuit and checked recessed CAD; no procurement or hardware claim") as record:
        with (ROOT / "engineering/b2_bom.csv").open() as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            rows = list(reader)
        kept = []
        for row in rows:
            if row["category"] == "Mechanical" and row["item"] in ("Removable backer", "Locating spacer 1", "Locating spacer 2"):
                continue
            if row["item"] == "Original hard frame":
                continue
            if row["category"] == "Controller":
                row["reference"] = "engineering/scripts/prepare_recessed_firmware.py"
                row["notes"] = "Copy all five B3 files; protocol yam-b3/1; gain 5."
            if row["item"] == "Magnetic sensors":
                row["location"] = "U1-U5 on the retained B2 board; component face native X=6.00 mm"
                row["notes"] += "; gain 5 and RES 1 require B3's own physical calibration"
            if row["item"] == "Nail pull-downs":
                row["reference"] = "engineering/firmware/recessed/config.json"
            if row["category"] == "Cable":
                row["reference"] = "engineering/docs/BUILD_RECESSED.md"
            if row["item"] == "Fasteners and washers":
                row["reference"] = "engineering/designs/recessed.json"
                row["notes"] = "Select new screw lengths from actual recessed stack; include any washer inside the head reservation; preserve TPU retention."
            kept.append(row)
        for part in plan["parts"]:
            if part["kind"] == "reference_only":
                continue
            kept.append(dict(zip(fields, ("Mechanical", part["id"], "1", part["material"],
                                          part["purpose"], "engineering/prototypes/recessed/" + part["step"],
                                          "Print and inspect fit. Both spacer files have the same shape at different assembly coordinates."))))
        with (OUTPUT / "recessed_bom.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader(); writer.writerows(kept)
        svg = (ROOT / "engineering/web/b2-wiring.svg").read_text()
        replacements = {
            'viewBox="0 0 1280 820"': 'viewBox="0 0 1280 870"',
            'height="820"': 'height="870"',
            "B2 wiring: one magnetic PCB and two nail pads": "B3 wiring: recessed B2 board, gain 5 and two nail pads",
            "B2 · one PCB, four upstream wires, two nail pads": "B3 · recessed B2 board, gain 5, two nail pads",
            "MicroPython · yam-b2/1": "MicroPython · yam-b3/1",
        }
        for old, new in replacements.items():
            if old not in svg:
                raise ValueError("Retained wiring source changed: " + old)
            svg = svg.replace(old, new)
        svg = svg.replace("</g></svg>",
            '<text x="30" y="840" font-size="17" font-weight="bold">B3 setting: GAIN_SEL=5, RES=1 · X/Y 0.501 and Z 0.807 µT/count at 25°C · retain raw words.</text>\n</g></svg>')
        (OUTPUT / "recessed-wiring.svg").write_text(svg)
        with (OUTPUT / "recessed_sensor_placement.csv").open("w", newline="") as stream:
            fields = ("sensor", "part", "die_x_mm", "die_y_mm", "die_z_mm",
                      "component_face_x_mm", "rotation_sensor_to_native")
            writer = csv.writer(stream); writer.writerow(fields)
            for row in plan["sensor_poses"]:
                writer.writerow([row["id"], "MLX90393SLW-ABA-011", *row["die_center_native_mm"],
                                 plan["pcb_component_plane_x_mm"],
                                 json.dumps(row["rotation_sensor_to_native"], separators=(",", ":"))])
        record["packet"] = {"bom_rows": len(kept), "sensor_poses": len(plan["sensor_poses"]),
                            "physical_builds": 0}
        receipt = {
            "source_hashes": {str(path.relative_to(ROOT)): digest(path) for path in (
                OUTPUT / "recessed_manifest.json", ROOT / "engineering/b2_bom.csv",
                ROOT / "engineering/web/b2-wiring.svg", Path(__file__))},
            "files": {name: digest(OUTPUT / name) for name in
                      ("recessed_bom.csv", "recessed-wiring.svg", "recessed_sensor_placement.csv")},
        }
        (OUTPUT / "packet_inputs.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(record["packet"], indent=2))


if __name__ == "__main__":
    main()
