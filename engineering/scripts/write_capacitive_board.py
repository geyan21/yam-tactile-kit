#!/usr/bin/python3
"""Write K1 using native KiCad footprints and explicit prototype wire ports."""

import argparse
import csv
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_native_pcb import pcb, vector, mm, rectangle, shape_line, add_polygon_zone, LIBRARIES, COPPER, digest


def wire_port(board, cfg):
    footprint = pcb.FOOTPRINT(board)
    footprint.SetAttributes(pcb.FP_THROUGH_HOLE)
    for number in range(1, 5):
        pad = pcb.PAD(footprint)
        pad.SetNumber(str(number))
        pad.SetAttribute(pcb.PAD_ATTRIB_PTH)
        pad.SetShape(pcb.PAD_SHAPE_RECT if number == 1 else pcb.PAD_SHAPE_CIRCLE)
        pad.SetPosition(vector([(number-2.5)*cfg["pitch_mm"], 0]))
        pad.SetSize(vector([cfg["land_mm"]]*2))
        pad.SetDrillSize(vector([cfg["drill_mm"]]*2))
        layers = pcb.LSET()
        for layer in (*[board.GetLayerID(name) for name in COPPER], pcb.F_Mask, pcb.B_Mask):
            layers.AddLayer(layer)
        pad.SetLayerSet(layers)
        footprint.Add(pad)
    rectangle(footprint, [-3.6, -1.1, 3.6, 1.1], pcb.F_CrtYd)
    rectangle(footprint, [-3.3, -.85, 3.3, .85], pcb.F_Fab)
    return footprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specification", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--routing", type=Path)
    args = parser.parse_args()
    source, target = args.specification.resolve(), args.destination.resolve()
    if not source.is_relative_to(ROOT) or not target.is_relative_to(ROOT / "build") or target.exists():
        parser.error("Use an owned specification and a fresh generated destination")
    spec = json.loads(source.read_text())
    if spec["name"] != "k1_readout":
        raise ValueError("This writer is only for the K1 readout")
    route = json.loads(args.routing.read_text()) if args.routing else {"tracks": [], "vias": [], "zones": []}
    with execution(ROOT / "build/records", "Generate a native K1 board with checked pad transforms, complete library courtyards and real plated wire ports; native routing/DRC remain separate") as record:
        target.mkdir(parents=True, exist_ok=False)
        library = target / "K1.pretty"; library.mkdir()
        board = pcb.BOARD()
        board.SetCopperLayerCount(4)
        board.GetDesignSettings().SetBoardThickness(pcb.FromMM(spec["thickness_mm"]))
        plugin = pcb.PCB_IO_MGR.FindPlugin(pcb.PCB_IO_MGR.KICAD_SEXP)
        nets = {}
        for name in sorted({n for p in spec["parts"] for n in p["nets"].values() if n}):
            item = pcb.NETINFO_ITEM(board, name); board.Add(item); nets[name] = item
        pads, sources = [], {}
        for part in spec["parts"]:
            if part["library"]:
                original = LIBRARIES / part["library"]
                footprint = pcb.FootprintLoad(str(original.parent), original.stem)
                if footprint is None:
                    raise ValueError("Cannot load native footprint "+str(original))
                sources[str(original.relative_to(ROOT))] = digest(original)
            else:
                footprint = wire_port(board, spec["wire_port"])
            footprint.Models().clear()
            footprint.SetReference(part["reference"])
            footprint.SetValue(part["value"])
            footprint.SetFPIDAsString("K1:"+part["reference"])
            footprint.SetPosition(vector([0, 0]))
            footprint.SetOrientationDegrees(0)
            footprint.Reference().SetLayer(pcb.F_Fab)
            footprint.Reference().SetTextSize(vector([.7, .7]))
            footprint.Reference().SetTextThickness(pcb.FromMM(.1))
            footprint.Value().SetVisible(False)
            local = {p.GetNumber(): mm(p.GetPosition()) for p in footprint.Pads()}
            if set(local) != set(part["nets"]):
                raise ValueError("The pin map does not cover every native pad: "+part["reference"])
            plugin.FootprintSave(str(library), footprint)
            for pad in footprint.Pads():
                name = part["nets"][pad.GetNumber()]
                if name:
                    pad.SetNet(nets[name])
                pad.SetLocalSolderMaskMargin(pcb.FromMM(.025))
            board.Add(footprint)
            footprint.SetOrientationDegrees(part["rotation_deg"])
            footprint.SetPosition(vector(part["center_mm"]))
            angle = -math.radians(part["rotation_deg"])
            for pad in footprint.Pads():
                x, y = local[pad.GetNumber()]
                expected = [part["center_mm"][0]+x*math.cos(angle)-y*math.sin(angle),
                            part["center_mm"][1]+x*math.sin(angle)+y*math.cos(angle)]
                if math.dist(expected, mm(pad.GetPosition())) > 2e-6:
                    raise ValueError("Native pad transform changed")
                pads.append({"reference": part["reference"], "pad": pad.GetNumber(), "net": pad.GetNetname(),
                             "center": mm(pad.GetPosition()), "size": mm(pad.GetSize()),
                             "rotation": pad.GetOrientationDegrees(),
                             "layers": [name for name in COPPER if pad.IsOnLayer(board.GetLayerID(name))],
                             "drill": mm(pad.GetDrillSize())[0], "native_shape": int(pad.GetShape()),
                             "paste": pad.IsOnLayer(pcb.F_Paste)})
        for index, hole in enumerate(spec["holes"]):
            footprint = pcb.FOOTPRINT(board)
            footprint.SetReference("H"+str(index+1))
            footprint.SetFPIDAsString("K1:MOUNT_M2")
            footprint.SetValue("M2 clearance")
            footprint.Reference().SetLayer(pcb.F_Fab)
            footprint.Value().SetVisible(False)
            footprint.SetAttributes(pcb.FP_BOARD_ONLY | pcb.FP_EXCLUDE_FROM_BOM | pcb.FP_EXCLUDE_FROM_POS_FILES)
            pad = pcb.PAD(footprint)
            pad.SetAttribute(pcb.PAD_ATTRIB_NPTH); pad.SetShape(pcb.PAD_SHAPE_CIRCLE)
            pad.SetSize(vector([hole["diameter_mm"]]*2)); pad.SetDrillSize(vector([hole["diameter_mm"]]*2))
            layers = pcb.LSET.AllCuMask()
            layers.AddLayer(pcb.F_Mask); layers.AddLayer(pcb.B_Mask)
            pad.SetLayerSet(layers)
            footprint.Add(pad)
            plugin.FootprintSave(str(library), footprint)
            board.Add(footprint); footprint.SetPosition(vector(hole["center_mm"]))
            radius = hole["copper_keepout_mm"]/2
            points = [[hole["center_mm"][0]+radius*math.cos(a), hole["center_mm"][1]+radius*math.sin(a)]
                      for a in [2*math.pi*i/64 for i in range(65)]]
            add_polygon_zone(board, points, COPPER, keepout=True)
        for start, end in zip(spec["outline_mm"], spec["outline_mm"][1:]):
            shape_line(board, start, end, pcb.Edge_Cuts)
        for start, end in zip(spec["reference_cell_body_xy_mm"], spec["reference_cell_body_xy_mm"][1:]):
            shape_line(board, start, end, pcb.F_Fab, .1)
        for text, position in (("K1  3 + REF", [20, 2]), ("JS0", [10, 7]),
                               ("JS1", [10, 17]), ("JS2", [10, 27]),
                               ("JP", [31, 36.3]), ("JREF", [31.5, 18.7])):
            label = pcb.PCB_TEXT(board)
            label.SetText(text); label.SetPosition(vector(position)); label.SetLayer(pcb.F_SilkS)
            label.SetTextSize(vector([.8, .8])); label.SetTextThickness(pcb.FromMM(.1))
            board.Add(label)
        for item in route["tracks"]:
            track = pcb.PCB_TRACK(board)
            track.SetStart(vector(item["start"])); track.SetEnd(vector(item["end"]))
            track.SetWidth(pcb.FromMM(item["width"])); track.SetLayer(board.GetLayerID(item["layer"]))
            track.SetNet(nets[item["net"]]); board.Add(track)
        for item in route["vias"]:
            via = pcb.PCB_VIA(board)
            via.SetPosition(vector(item["center"])); via.SetWidth(pcb.FromMM(item["diameter"]))
            via.SetDrill(pcb.FromMM(item["drill"])); via.SetLayerPair(pcb.F_Cu, pcb.B_Cu)
            via.SetNet(nets[item["net"]]); board.Add(via)
        for zone in route["zones"]:
            add_polygon_zone(board, zone["outline_xy_mm"], [zone["layer"]], nets[zone["net"]], clearance=spec["clearance_mm"])
        name = spec["name"]
        pcb.SaveBoard(str(target / (name+".kicad_pcb")), board)
        (target / "fp-lib-table").write_text('(fp_lib_table (lib (name "K1") (type "KiCad") (uri "${KIPRJMOD}/K1.pretty") (options "") (descr "K1 native footprints and prototype wire ports")))\n')
        (target / (name+".kicad_dru")).write_text(
            '(version 1)\n'
            f'(rule "K1 clearance" (constraint clearance (min {spec["clearance_mm"]}mm)))\n'
            f'(rule "K1 copper edge" (constraint edge_clearance (min {spec["edge_clearance_mm"]}mm)))\n'
            f'(rule "K1 width" (constraint track_width (min {spec["minimum_track_mm"]}mm)))\n'
            f'(rule "K1 minimum drill" (constraint hole_size (min {spec["via_drill_mm"]}mm)))\n'
            '(rule "K1 drill separation" (constraint hole_to_hole (min 0.25mm)))\n'
            '# Stock MSOP-10 package lands: 0.35 mm pads on 0.5 mm pitch.\n'
            '# This exception is only pad-to-pad within the same U1/U2 package.\n'
            '# Track-to-pad, track-to-track and all other clearances remain 0.20 mm.\n'
            '(rule "K1 native package pad spacing"\n'
            ' (condition "A.Type == \'Pad\' && B.Type == \'Pad\' && '
            '((A.memberOfFootprint(\'U1\') && B.memberOfFootprint(\'U1\')) || '
            '(A.memberOfFootprint(\'U2\') && B.memberOfFootprint(\'U2\')))")\n'
            f' (constraint clearance (min {spec["native_package_pad_clearance_mm"]}mm)))\n')
        (library / "ATTRIBUTION.md").write_text(
            "Library components: KiCad library contributors, CC BY-SA 4.0 with the KiCad Libraries Exception. "
            "Original paths and hashes are in the board metadata. Local changes are reference/value fields, "
            "mask margin and removal of external 3D paths. Wire ports and mounting holes are authored for this MIT-licensed kit.\n")
        license_path = ROOT / "engineering/development/f1/r3/pcb/F1.pretty/LICENSE.md"
        shutil.copyfile(license_path, library / "LICENSE.md")
        data = {"schema": "yam-k1-native-board/1", "name": name, "parts": spec["parts"], "pads": pads,
                "outline_xy_mm": spec["outline_mm"], "thickness_mm": spec["thickness_mm"],
                "holes": [dict(h, copper_keepout_diameter_mm=h["copper_keepout_mm"]) for h in spec["holes"]],
                "clearance_mm": spec["clearance_mm"], "edge_mm": spec["edge_clearance_mm"],
                "tracks": route["tracks"], "vias": route["vias"], "zones": route["zones"],
                "source_footprints_sha256": sources, "specification_sha256": digest(source),
                "pcb_sha256": digest(target / (name+".kicad_pcb")), "physical_boards_tested": 0,
                "status": "Native routed geometry; independent checks remain" if route["tracks"] else
                          "Native placement; independent routing and integration checks remain"}
        (target / (name+".json")).write_text(json.dumps(data, indent=2)+"\n")
        shutil.copyfile(source, target / "specification.json")
        with (target / (name+"_pins.csv")).open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["reference", "pad", "net", "layers", "x_mm", "y_mm"])
            writer.writerows([p["reference"], p["pad"], p["net"], "/".join(p["layers"]), *p["center"]] for p in pads)
        record["result"] = {"directory": str(target.relative_to(ROOT)), "components": len(spec["parts"]),
                            "pads": len(pads), "tracks": len(route["tracks"]), "pcb_sha256": data["pcb_sha256"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
