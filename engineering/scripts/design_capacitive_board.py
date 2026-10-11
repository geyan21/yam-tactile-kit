#!/usr/bin/python3
"""Create the explicit K1 readout netlist and initial component placement."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    config_path = ROOT / "engineering/designs/capacitive_k1.json"
    cfg = json.loads(config_path.read_text())
    parts = []
    def part(ref, value, xy, library, nets, rotation=0, source=""):
        parts.append({"reference": ref, "value": value, "center_mm": xy,
                      "rotation_deg": rotation, "library": library,
                      "nets": {str(key): value for key, value in nets.items()}, "source": source})
    def passive(ref, value, xy, nets, capacitor=False, rotation=0):
        library = ("Capacitor_SMD.pretty/C_0603_1608Metric.kicad_mod" if capacitor
                   else "Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod")
        part(ref, value, xy, library, {1: nets[0], 2: nets[1]}, rotation)
    ic_library = "Package_SO.pretty/MSOP-10_3x3mm_P0.5mm.kicad_mod"
    part("U1", cfg["readout"]["converter"], [18, 17], ic_library,
         {1: "SHLD1", 2: "CIN1", 3: "CIN2", 4: "CIN3", 5: "CIN4",
          6: "SHLD2", 7: "GND", 8: "VDD_FDC", 9: "SCL", 10: "SDA"},
         source="https://www.ti.com/lit/ds/symlink/fdc1004.pdf")
    part("U2", cfg["readout"]["health_adc"], [27, 29], ic_library,
         {1: "GND", 2: "", 3: "GND", 4: "VDD_FDC", 5: "RET0_F",
          6: "RET1_F", 7: "RET2_F", 8: "3V3", 9: "SDA", 10: "SCL"},
         source="https://www.ti.com/lit/ds/symlink/ads1115.pdf")
    passive("CF1", "100nF 16V X7R", [22.8, 17], ("VDD_FDC", "GND"), True)
    passive("CF2", "1uF 16V X7R; verify effective capacitance", [22.3, 14], ("VDD_FDC", "GND"), True)
    passive("RF", "10 ohm 1%", [22.3, 20], ("VDD_FDC", "3V3"))
    passive("CD", "100nF 16V X7R", [32, 28.5], ("3V3", "GND"), True)
    passive("CB", "1uF 16V X7R", [19.5, 27], ("3V3", "GND"), True)
    passive("RSDA", "4.7k 1%", [22, 24], ("3V3", "SDA"))
    passive("RSCL", "4.7k 1%", [26, 24], ("3V3", "SCL"))
    for index, locations in enumerate((
            ([16, 32], [20, 32], [24, 32]),
            ([36, 31], [36, 28.5], [32, 32]),
            ([36, 26], [36, 23.5], [32, 25]))):
        pull, series, cap = locations
        passive("RP"+str(index), "100k 1%", pull, ("3V3", f"RET{index}"))
        passive("RI"+str(index), "1k 1%", series, (f"RET{index}", f"RET{index}_F"))
        passive("CI"+str(index), "1nF 50V C0G", cap, (f"RET{index}_F", "GND"), True)
    for index, y in enumerate((7, 17, 27)):
        part(f"JS{index}", "CIN / driven shield / ground drive / ground return",
             [7, y], None, {1: f"CIN{index+1}", 2: "SHLD1", 3: "GND", 4: f"RET{index}"}, rotation=90)
    part("JREF", "Protected reference: CIN4 / SHLD2 / GND / GND",
         [31.5, 20.5], None, {1: "CIN4", 2: "SHLD2", 3: "GND", 4: "GND"})
    part("JP", "3V3 / GND / SDA / SCL", [31, 34], None,
         {1: "3V3", 2: "GND", 3: "SDA", 4: "SCL"})
    spec = {"schema": "yam-k1-native-board/1", "name": "k1_readout", "thickness_mm": 1.0,
            "copper_layers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
            "outline_mm": [[0, 0], [42, 0], [42, 38], [0, 38], [0, 0]],
            "clearance_mm": .2, "edge_clearance_mm": .25, "minimum_track_mm": .2,
            "native_package_pad_clearance_mm": .15,
            "package_clearance_note": "The selected native MSOP-10 land pattern has 0.35 mm pads at 0.5 mm pitch. Its 0.15 mm adjacent-pad spacing is declared explicitly for U1/U2; routed trace clearance remains 0.20 mm.",
            "via_diameter_mm": .5, "via_drill_mm": .25,
            "holes": [{"center_mm": point, "diameter_mm": 2.2, "copper_keepout_mm": 5.2}
                      for point in ([2.8, 2.8], [39.2, 2.8], [2.8, 35.2], [39.2, 35.2])],
            "parts": parts,
            "reference_cell_body_xy_mm": [[24.5, 5.7], [38.5, 5.7], [38.5, 17.7], [24.5, 17.7], [24.5, 5.7]],
            "reference_cell_note": "Reserved for the separate shielded reference coupon and its protected metal plate. No ground plane under unguarded CIN routing.",
            "wire_port": {"pitch_mm": 1.75, "land_mm": 1.25, "drill_mm": .65,
                          "pin1": "square land; other lands circular", "assembly": "Soldered prototype leads with enclosure strain relief"},
            "physical_boards_tested": 0,
            "remaining": ["Native placement and pin audit", "Guarded input routes and actual shield polygons",
                          "Power/digital/health routing and native DRC", "Enclosure, physical bring-up and complete sensor tests"]}
    folder = ROOT / "build/engineering/prototypes/capacitive/pcb_placement" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Create an explicit K1 two-chip board contract for one bank of three pressure cells and a protected reference; preserve the initial layout before routing") as record:
        folder.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(config_path, folder / config_path.name)
        shutil.copyfile(Path(__file__), folder / Path(__file__).name)
        (folder / "specification.json").write_text(json.dumps(spec, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "components": len(parts),
                            "specification_sha256": digest(folder / "specification.json"),
                            "physical_boards_tested": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
