#!/usr/bin/python3
"""Generate the FB1 two-layer sensor board from the reviewed FMA land pattern."""

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
from f1_native_pcb import pcb, vector, mm, rectangle, shape_line, add_polygon_zone, LIBRARIES, digest

CONFIG = ROOT / "engineering/designs/force_button_electronics.json"
LAYERS = ("F.Cu", "B.Cu")


def custom_footprint(board, spec):
    footprint = pcb.FOOTPRINT(board)
    footprint.SetAttributes(pcb.FP_SMD if spec["reference"] == "U1" else pcb.FP_THROUGH_HOLE)
    for row in spec["pads"]:
        pad = pcb.PAD(footprint)
        pad.SetNumber(row["pad"])
        pad.SetPosition(vector(row["center_mm"]))
        pad.SetSize(vector(row["size_mm"]))
        if row.get("drill_mm"):
            pad.SetAttribute(pcb.PAD_ATTRIB_PTH)
            pad.SetShape(pcb.PAD_SHAPE_RECT if row["pad"] == "1" else pcb.PAD_SHAPE_CIRCLE)
            pad.SetDrillSize(vector([row["drill_mm"]]*2))
            layers = pcb.LSET.AllCuMask()
            layers.AddLayer(pcb.F_Mask); layers.AddLayer(pcb.B_Mask)
        else:
            pad.SetAttribute(pcb.PAD_ATTRIB_SMD)
            pad.SetShape(pcb.PAD_SHAPE_RECT)
            layers = pcb.LSET()
            for layer in (pcb.F_Cu, pcb.F_Mask, pcb.F_Paste):
                layers.AddLayer(layer)
        pad.SetLayerSet(layers)
        footprint.Add(pad)
    if spec.get("vent_diameter_mm"):
        pad = pcb.PAD(footprint)
        pad.SetAttribute(pcb.PAD_ATTRIB_NPTH)
        pad.SetShape(pcb.PAD_SHAPE_CIRCLE)
        pad.SetPosition(vector([0, 0]))
        pad.SetSize(vector([spec["vent_diameter_mm"]]*2))
        pad.SetDrillSize(vector([spec["vent_diameter_mm"]]*2))
        layers = pcb.LSET.AllCuMask()
        layers.AddLayer(pcb.F_Mask); layers.AddLayer(pcb.B_Mask)
        pad.SetLayerSet(layers)
        footprint.Add(pad)
    rectangle(footprint, spec["body_bounds_mm"], pcb.F_Fab, .1)
    rectangle(footprint, spec["courtyard_bounds_mm"], pcb.F_CrtYd)
    if spec["reference"] == "U1":
        shape_line(footprint, [-1.1, -3.1], [-.4, -3.1], pcb.F_SilkS, .12)
    return footprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--routing", type=Path)
    args = parser.parse_args()
    target = args.destination.resolve()
    if not target.is_relative_to(ROOT / "build") or target.exists():
        parser.error("Use a fresh generated directory beneath build/")
    spec = json.loads(CONFIG.read_text())
    route = json.loads(args.routing.read_text()) if args.routing else {"tracks": [], "vias": [], "zones": []}
    with execution(ROOT / "build/records", "Write the FB1 native sensor PCB with six distinct FMA lands, the open reference vent and separate cable drive/sense wires") as record:
        target.mkdir(parents=True, exist_ok=False)
        library = target / "FB1.pretty"; library.mkdir()
        board = pcb.BOARD()
        board.SetCopperLayerCount(2)
        board.GetDesignSettings().SetBoardThickness(pcb.FromMM(spec["thickness_mm"]))
        plugin = pcb.PCB_IO_MGR.FindPlugin(pcb.PCB_IO_MGR.KICAD_SEXP)
        nets = {}
        for name in sorted({n for p in spec["parts"] for n in p["nets"].values() if n}):
            net = pcb.NETINFO_ITEM(board, name); board.Add(net); nets[name] = net
        pads, sources = [], {}
        for part in spec["parts"]:
            if part.get("library"):
                source = LIBRARIES / part["library"]
                footprint = pcb.FootprintLoad(str(source.parent), source.stem)
                if footprint is None:
                    raise ValueError("Missing native footprint "+str(source))
                sources[str(source.relative_to(ROOT))] = digest(source)
            else:
                footprint = custom_footprint(board, part)
            footprint.Models().clear()
            footprint.SetReference(part["reference"])
            footprint.SetValue(part["value"])
            footprint.SetFPIDAsString("FB1:"+part["reference"])
            footprint.SetPosition(vector([0, 0]))
            footprint.SetOrientationDegrees(0)
            footprint.Reference().SetLayer(pcb.F_Fab)
            footprint.Reference().SetTextSize(vector([.6, .6]))
            footprint.Reference().SetTextThickness(pcb.FromMM(.1))
            footprint.Value().SetVisible(False)
            local = {p.GetNumber(): mm(p.GetPosition()) for p in footprint.Pads() if p.GetNumber()}
            if set(local) != set(part["nets"]):
                raise ValueError("Pin contract mismatch at "+part["reference"])
            plugin.FootprintSave(str(library), footprint)
            for pad in footprint.Pads():
                if pad.GetNumber():
                    net = part["nets"][pad.GetNumber()]
                    if net:
                        pad.SetNet(nets[net])
                pad.SetLocalSolderMaskMargin(pcb.FromMM(.025))
            board.Add(footprint)
            footprint.SetOrientationDegrees(part["rotation_deg"])
            footprint.SetPosition(vector(part["center_mm"]))
            angle = -math.radians(part["rotation_deg"])
            for pad in footprint.Pads():
                if not pad.GetNumber():
                    continue
                x, y = local[pad.GetNumber()]
                expected = [part["center_mm"][0]+x*math.cos(angle)-y*math.sin(angle),
                            part["center_mm"][1]+x*math.sin(angle)+y*math.cos(angle)]
                if math.dist(expected, mm(pad.GetPosition())) > 2e-6:
                    raise ValueError("Native pad placement changed")
                pads.append({"reference": part["reference"], "pad": pad.GetNumber(),
                             "net": pad.GetNetname(), "center": mm(pad.GetPosition()), "size": mm(pad.GetSize()),
                             "rotation": pad.GetOrientationDegrees(), "layers": [n for n in LAYERS if pad.IsOnLayer(board.GetLayerID(n))],
                             "drill": mm(pad.GetDrillSize())[0], "native_shape": int(pad.GetShape()),
                             "paste": pad.IsOnLayer(pcb.F_Paste)})
        for index, hole in enumerate(spec["holes"]):
            fp = pcb.FOOTPRINT(board)
            fp.SetReference("H"+str(index+1)); fp.SetValue("M2 clearance")
            fp.SetFPIDAsString("FB1:MOUNT_M2")
            fp.SetAttributes(pcb.FP_BOARD_ONLY | pcb.FP_EXCLUDE_FROM_BOM | pcb.FP_EXCLUDE_FROM_POS_FILES)
            fp.Reference().SetVisible(False); fp.Value().SetVisible(False)
            pad = pcb.PAD(fp)
            pad.SetAttribute(pcb.PAD_ATTRIB_NPTH); pad.SetShape(pcb.PAD_SHAPE_CIRCLE)
            pad.SetSize(vector([hole["diameter_mm"]]*2)); pad.SetDrillSize(vector([hole["diameter_mm"]]*2))
            layers = pcb.LSET.AllCuMask(); layers.AddLayer(pcb.F_Mask); layers.AddLayer(pcb.B_Mask)
            pad.SetLayerSet(layers); fp.Add(pad)
            plugin.FootprintSave(str(library), fp)
            board.Add(fp); fp.SetPosition(vector(hole["center_mm"]))
            r = hole["copper_keepout_diameter_mm"]/2
            points = [[hole["center_mm"][0]+r*math.cos(a), hole["center_mm"][1]+r*math.sin(a)]
                      for a in [2*math.pi*i/64 for i in range(65)]]
            add_polygon_zone(board, points, LAYERS, keepout=True)
        for start, end in zip(spec["outline_mm"], spec["outline_mm"][1:]):
            shape_line(board, start, end, pcb.Edge_Cuts)
        for text, position in (("FB1 25N", [7.5, 1.5]), ("1  3  5", [6.5, 14.5]), ("2  4  6", [6.5, 19.3])):
            label = pcb.PCB_TEXT(board)
            label.SetText(text); label.SetPosition(vector(position)); label.SetLayer(pcb.F_SilkS)
            label.SetTextSize(vector([.8, .8])); label.SetTextThickness(pcb.FromMM(.1)); board.Add(label)
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
        if route["zones"]:
            raise ValueError("FB1 sensor board uses explicitly routed copper, without planes")
        name = spec["name"]
        pcb.SaveBoard(str(target / (name+".kicad_pcb")), board)
        (target / "fp-lib-table").write_text('(fp_lib_table (lib (name "FB1") (type "KiCad") (uri "${KIPRJMOD}/FB1.pretty") (options "") (descr "FB1 sensor lands, native passives and wire port")))\n')
        (target / (name+".kicad_dru")).write_text(
            '(version 1)\n'
            '(rule "FB1 clearance" (constraint clearance (min 0.20mm)))\n'
            '# The vendor land pattern leaves 0.245 mm between pad 6 and the reference vent.\n'
            '(rule "FB1 copper to hole" (constraint hole_clearance (min 0.20mm)))\n'
            '(rule "FB1 copper edge" (constraint edge_clearance (min 0.25mm)))\n'
            '(rule "FB1 width" (constraint track_width (min 0.20mm)))\n'
            '(rule "FB1 minimum drill" (constraint hole_size (min 0.25mm)))\n'
            '(rule "FB1 drill separation" (constraint hole_to_hole (min 0.25mm)))\n')
        (library / "ATTRIBUTION.md").write_text(
            "Capacitor footprint: KiCad library contributors, CC BY-SA 4.0 with KiCad Libraries Exception; "
            "source path/hash in the board metadata. FMA functional land geometry follows Honeywell data-sheet "
            "Figure 3. The footprint, open vent, wire port and holes are authored for this MIT-licensed kit. "
            "Vendor CAD and complete data sheets are not redistributed.\n")
        shutil.copyfile(ROOT / "engineering/development/f1/r3/pcb/F1.pretty/LICENSE.md", library / "LICENSE.md")
        holes = spec["holes"]+[{"center_mm": spec["force_axis_xy_mm"], "diameter_mm": .45,
                               "copper_keepout_diameter_mm": .85, "purpose": "Sensor reference vent"}]
        data = {"schema": "yam-fb1-native-board/1", "name": name, "parts": spec["parts"], "pads": pads,
                "outline_xy_mm": spec["outline_mm"], "thickness_mm": spec["thickness_mm"], "holes": holes,
                "clearance_mm": spec["clearance_mm"], "edge_mm": spec["edge_clearance_mm"],
                "tracks": route["tracks"], "vias": route["vias"], "zones": [],
                "source_footprints_sha256": sources, "specification_sha256": digest(CONFIG),
                "pcb_sha256": digest(target / (name+".kicad_pcb")), "physical_boards_tested": 0}
        (target / (name+".json")).write_text(json.dumps(data, indent=2)+"\n")
        shutil.copyfile(CONFIG, target / "specification.json")
        with (target / (name+"_pins.csv")).open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["reference", "pad", "net", "layers", "x_mm", "y_mm"])
            writer.writerows([p["reference"], p["pad"], p["net"], "/".join(p["layers"]), *p["center"]] for p in pads)
        record["result"] = {"directory": str(target.relative_to(ROOT)), "components": len(spec["parts"]),
                            "pads": len(pads), "tracks": len(route["tracks"]), "pcb_sha256": data["pcb_sha256"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
