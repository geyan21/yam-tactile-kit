#!/usr/bin/python3
"""Write R3 with native courtyards, named mounting footprints and board labels."""

import argparse
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_native_pcb import build, pcb, vector, digest, mm
from inspect_f1_fanout_native import courtyards


def via_paste_keepouts(board, pads, margin):
    result = []
    for pad in pads:
        if not pad["paste"]:
            continue
        hx, hy = pad["size"][0]/2+margin, pad["size"][1]/2+margin
        angle = -math.radians(pad["rotation"])
        c, s = math.cos(angle), math.sin(angle)
        cx, cy = pad["center"]
        points = [[cx+c*x-s*y, cy+s*x+c*y] for x, y in
                 ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]
        zone = pcb.ZONE(board)
        layers = pcb.LSET()
        for name in ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"):
            layers.AddLayer(board.GetLayerID(name))
        zone.SetLayerSet(layers)
        zone.SetIsRuleArea(True)
        zone.SetDoNotAllowVias(True)
        zone.SetDoNotAllowTracks(False)
        zone.SetDoNotAllowZoneFills(False)
        zone.SetDoNotAllowPads(False)
        zone.SetDoNotAllowFootprints(False)
        outline = zone.Outline()
        outline.NewOutline()
        for point in points:
            outline.Append(*[pcb.FromMM(value) for value in point])
        board.Add(zone)
        result.append({"reference": pad["reference"], "pad": pad["pad"], "outline_mm": points})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specification", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--routing", type=Path)
    args = parser.parse_args()
    source, destination = args.specification.resolve(), args.destination.resolve()
    if not source.is_relative_to(ROOT) or not destination.is_relative_to(ROOT / "build"):
        parser.error("Use repository-owned specification and generated output")
    spec = json.loads(source.read_text())
    if spec["name"] != "f1_fanout_r3":
        raise ValueError("This writer is for the separate R3 revision")
    with execution(ROOT / "build/records", "Write the R3 fanout with complete native courtyard evidence and correct mechanical-package names; preserve original electrical pad identities") as record:
        route = json.loads(args.routing.read_text()) if args.routing else None
        data = build(spec, destination, route)
        pcb_path = destination / (spec["name"]+".kicad_pcb")
        board = pcb.LoadBoard(str(pcb_path))
        seed_locked = bool(route and route.get("schema") == "yam-f1-r3-seed/1")
        if seed_locked:
            for item in board.GetTracks():
                item.SetLocked(True)
        plugin = pcb.PCB_IO_MGR.FindPlugin(pcb.PCB_IO_MGR.KICAD_SEXP)
        mount_library_written = False
        for footprint in board.GetFootprints():
            ref = footprint.GetReference()
            if ref in spec["reference_positions_pcb_mm"]:
                footprint.Reference().SetPosition(vector(spec["reference_positions_pcb_mm"][ref]))
            if ref in ("H1", "H2"):
                footprint.SetFPIDAsString("F1:MOUNT_M2")
                footprint.SetValue("M2 clearance")
                for pad in footprint.Pads():
                    pad.SetNumber("")
                if not mount_library_written:
                    template = pcb.FOOTPRINT(footprint)
                    template.SetPosition(vector([0, 0]))
                    template.SetReference("REF**")
                    plugin.FootprintSave(str(destination / "F1.pretty"), template)
                    mount_library_written = True
        for drawing in board.GetDrawings():
            if isinstance(drawing, pcb.PCB_TEXT) and drawing.GetText() == "F1 FANOUT":
                drawing.SetText("F1 FA3")
                drawing.SetPosition(vector([44, 1.2]))
        data["via_paste_keepouts"] = via_paste_keepouts(board, data["pads"], spec["via_to_paste_clearance_mm"])
        pcb.SaveBoard(str(pcb_path), board)
        restored = pcb.LoadBoard(str(pcb_path))
        native_pads = {(fp.GetReference(), p.GetNumber()): p for fp in restored.GetFootprints() for p in fp.Pads()}
        for pad in data["pads"]:
            actual = native_pads[(pad["reference"], pad["pad"])]
            if actual.GetNetname() != pad["net"] or math.dist(mm(actual.GetPosition()), pad["center"]) > 1e-6:
                raise ValueError("Label/mount repair changed an electrical pad")
        for ref, hole in zip(("H1", "H2"), spec["holes"]):
            footprint = next(fp for fp in restored.GetFootprints() if fp.GetReference() == ref)
            mount_pads = list(footprint.Pads())
            if len(mount_pads) != 1:
                raise ValueError("Mount footprint no longer contains exactly one hole")
            pad = mount_pads[0]
            if math.dist(mm(pad.GetPosition()), hole["center_mm"]) > 1e-6:
                raise ValueError("Mount package naming moved a hole")
        data["courtyards"] = courtyards(restored)
        data["seed_copper_locked"] = seed_locked
        data["pcb_sha256"] = digest(pcb_path)
        data["revision_writer_sha256"] = digest(Path(__file__))
        data["status"] = "R3 native geometry; independent electrical/fabrication and installed-fit checks remain"
        (destination / (spec["name"]+".json")).write_text(json.dumps(data, indent=2)+"\n")
        snapshot = destination / "generation_inputs"
        snapshot.mkdir()
        for path in (source, Path(__file__), ROOT / "engineering/scripts/f1_native_pcb.py",
                     ROOT / "engineering/scripts/inspect_f1_fanout_native.py"):
            shutil.copyfile(path, snapshot / path.name)
        if args.routing:
            shutil.copyfile(args.routing, snapshot / "routing.json")
        record["result"] = {"directory": str(destination.relative_to(ROOT)), "pads": len(data["pads"]),
                            "courtyards": len(data["courtyards"]), "pcb_sha256": data["pcb_sha256"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
