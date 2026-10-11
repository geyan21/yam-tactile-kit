#!/usr/bin/python3
"""Check the bundled KiCad API's native backside placement semantics."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for category in ("CONFIG", "CACHE", "DATA"):
    os.environ["XDG_" + category + "_HOME"] = str(ROOT / "build/engineering/tools/f1-kicad" / category.lower())
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
import pcbnew


def point(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def mm(position):
    return [pcbnew.ToMM(position.x), pcbnew.ToMM(position.y)]


def main():
    folder = ROOT / "build/engineering/prototypes/f1/api_probes" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Verify native KiCad footprint flipping on a disposable asymmetric pad pattern before placing inner-face F1 connectors") as record:
        folder.mkdir(parents=True, exist_ok=False)
        board = pcbnew.BOARD()
        footprint = pcbnew.FOOTPRINT(board)
        footprint.SetReference("PROBE")
        footprint.SetPosition(point(20, 20))
        pad = pcbnew.PAD(footprint)
        pad.SetNumber("1")
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetShape(pcbnew.PAD_SHAPE_RECT)
        pad.SetSize(point(.6, 1.3))
        pad.SetPosition(point(18, 19))
        layers = pcbnew.LSET()
        for layer in (pcbnew.F_Cu, pcbnew.F_Mask, pcbnew.F_Paste):
            layers.AddLayer(layer)
        pad.SetLayerSet(layers)
        footprint.Add(pad); board.Add(footprint)
        before = mm(pad.GetPosition())
        footprint.Flip(footprint.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        after = mm(pad.GetPosition())
        if after != [22., 19.] or not pad.IsOnLayer(pcbnew.B_Cu):
            raise ValueError("Unexpected backside placement transform")
        pcbnew.SaveBoard(str(folder / "backside_probe.kicad_pcb"), board)
        restored = pcbnew.LoadBoard(str(folder / "backside_probe.kicad_pcb"))
        checked = list(list(restored.GetFootprints())[0].Pads())[0]
        if mm(checked.GetPosition()) != after or not checked.IsOnLayer(pcbnew.B_Cu):
            raise ValueError("Backside transform did not survive serialization")
        result = {"tool": pcbnew.GetBuildVersion(), "before_mm": before, "after_mm": after,
                  "pad_layer": "B.Cu", "roundtrip_passed": True, "physical_evidence": False}
        (folder / "probe.json").write_text(json.dumps(result, indent=2)+"\n")
        record["result"] = result
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), **result}, indent=2))


if __name__ == "__main__":
    main()
