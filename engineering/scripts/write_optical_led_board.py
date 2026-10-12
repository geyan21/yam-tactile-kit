#!/usr/bin/python3
"""Write the small O1 two-layer blue LED ring with explicit polarity and lands."""

import argparse
import csv
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from f1_native_pcb import pcb, vector, mm, rectangle, shape_line, add_polygon_zone, digest

CONFIG = ROOT/"engineering/designs/optical_led_board.json"
MATERIALS = ROOT/"engineering/designs/optical_materials.json"
LAYERS = ("F.Cu", "B.Cu")


def specifications(cfg, materials):
    led = materials["illumination"]
    parts = []
    for i, center in enumerate(cfg["led_centers_mm"], 1):
        parts.append({"reference": f"D{i}", "value": led["led"], "center_mm": center, "rotation_deg": 0,
                      "body_mm": led["body_mm"], "body_bounds_mm": [-1, -.625, 1, .625],
                      "courtyard_bounds_mm": [-2.1, -.9, 2.1, .9],
                      "pads": [{"pad": str(p), "center_mm": [(p-1.5)*led["pad_pitch_mm"], 0],
                                "size_mm": led["pad_dimensions_mm"]} for p in (1, 2)],
                      "nets": {"1": "GND", "2": f"A{i}"}})
    for i, resistor in enumerate(cfg["resistors"], 1):
        parts.append({"reference": f"R{i}", "value": "220 ohm 1% 1206 >=0.25 W", **resistor,
                      "body_mm": cfg["resistor_body_mm"], "body_bounds_mm": [-1.6, -.8, 1.6, .8],
                      "courtyard_bounds_mm": [-2.4, -1.15, 2.4, 1.15],
                      "pads": [{"pad": str(p), "center_mm": [(p-1.5)*cfg["resistor_pad_pitch_mm"], 0],
                                "size_mm": cfg["resistor_pad_size_mm"]} for p in (1, 2)],
                      "nets": {"1": "LED_5V", "2": f"A{i}"}})
    parts.append({"reference": "J1", "value": "28 AWG soldered leads: 1=+5V, 2=GND",
                  "center_mm": cfg["connector_center_mm"], "rotation_deg": 0,
                  "body_mm": [3.2, 1.2, 1.2], "body_bounds_mm": [-1.6, -.6, 1.6, .6],
                  "courtyard_bounds_mm": [-1.85, -.85, 1.85, .85],
                  "pads": [{"pad": str(p), "center_mm": [(p-1.5)*cfg["connector_pin_pitch_mm"], 0],
                            "size_mm": [cfg["connector_pad_diameter_mm"]]*2,
                            "drill_mm": cfg["connector_drill_mm"]} for p in (1, 2)],
                  "nets": {"1": "LED_5V", "2": "GND"}})
    return parts


def footprint_for(board, spec):
    fp = pcb.FOOTPRINT(board)
    fp.SetAttributes(pcb.FP_THROUGH_HOLE if spec["reference"] == "J1" else pcb.FP_SMD)
    for data in spec["pads"]:
        pad = pcb.PAD(fp)
        pad.SetNumber(data["pad"])
        pad.SetPosition(vector(data["center_mm"]))
        pad.SetSize(vector(data["size_mm"]))
        if data.get("drill_mm"):
            pad.SetAttribute(pcb.PAD_ATTRIB_PTH)
            pad.SetShape(pcb.PAD_SHAPE_RECT if data["pad"] == "1" else pcb.PAD_SHAPE_CIRCLE)
            pad.SetDrillSize(vector([data["drill_mm"]]*2))
            layers = pcb.LSET.AllCuMask()
            layers.AddLayer(pcb.F_Mask); layers.AddLayer(pcb.B_Mask)
        else:
            pad.SetAttribute(pcb.PAD_ATTRIB_SMD); pad.SetShape(pcb.PAD_SHAPE_RECT)
            layers = pcb.LSET()
            for layer in (pcb.F_Cu, pcb.F_Mask, pcb.F_Paste):
                layers.AddLayer(layer)
        pad.SetLayerSet(layers); fp.Add(pad)
    rectangle(fp, spec["body_bounds_mm"], pcb.F_Fab, .08)
    rectangle(fp, spec["courtyard_bounds_mm"], pcb.F_CrtYd)
    if spec["reference"].startswith("D"):
        shape_line(fp, [-.85, -.8], [-.85, .8], pcb.F_Fab, .12)
        shape_line(fp, [-.6, -.8], [-.6, .8], pcb.F_Fab, .12)
    return fp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--routing", type=Path)
    args = parser.parse_args()
    target = args.destination.resolve()
    if not target.is_relative_to(ROOT/"build") or target.exists():
        parser.error("Use a fresh directory beneath build/")
    cfg, materials = json.loads(CONFIG.read_text()), json.loads(MATERIALS.read_text())
    parts = specifications(cfg, materials)
    route = json.loads(args.routing.read_text()) if args.routing else {"tracks": [], "vias": [], "zones": []}
    with execution(ROOT/"build/records", "Generate native O1 LED PCB with four independent 220-ohm branches, pin-1 cathode LEDs and a clear lens aperture") as record:
        target.mkdir(parents=True)
        library = target/"O1.pretty"; library.mkdir()
        board = pcb.BOARD(); board.SetCopperLayerCount(2)
        board.GetDesignSettings().SetBoardThickness(pcb.FromMM(cfg["thickness_mm"]))
        writer = pcb.PCB_IO_MGR.FindPlugin(pcb.PCB_IO_MGR.KICAD_SEXP)
        nets = {}
        for name in sorted({net for part in parts for net in part["nets"].values()}):
            nets[name] = pcb.NETINFO_ITEM(board, name); board.Add(nets[name])
        pads = []
        for part in parts:
            fp = footprint_for(board, part)
            fp.SetReference(part["reference"]); fp.SetValue(part["value"])
            fp.SetFPIDAsString("O1:"+part["reference"])
            fp.Reference().SetLayer(pcb.F_Fab)
            fp.Reference().SetTextSize(vector([.55, .55])); fp.Reference().SetTextThickness(pcb.FromMM(.08))
            fp.Reference().SetPosition(vector([0, -.1])); fp.Value().SetVisible(False)
            writer.FootprintSave(str(library), fp)
            for pad in fp.Pads():
                pad.SetNet(nets[part["nets"][pad.GetNumber()]])
                pad.SetLocalSolderMaskMargin(pcb.FromMM(.025))
            board.Add(fp); fp.SetOrientationDegrees(part["rotation_deg"]); fp.SetPosition(vector(part["center_mm"]))
            for pad in fp.Pads():
                local = next(p for p in part["pads"] if p["pad"] == pad.GetNumber())
                x, y = local["center_mm"]; angle = -math.radians(part["rotation_deg"])
                expected = [part["center_mm"][0]+x*math.cos(angle)-y*math.sin(angle),
                            part["center_mm"][1]+x*math.sin(angle)+y*math.cos(angle)]
                if math.dist(expected, mm(pad.GetPosition())) > 2e-6:
                    raise ValueError("Native pad orientation mismatch")
                pads.append({"reference": part["reference"], "pad": pad.GetNumber(), "net": pad.GetNetname(),
                             "center": mm(pad.GetPosition()), "size": mm(pad.GetSize()),
                             "rotation": pad.GetOrientationDegrees(), "layers": [n for n in LAYERS if pad.IsOnLayer(board.GetLayerID(n))],
                             "drill": mm(pad.GetDrillSize())[0], "paste": pad.IsOnLayer(pcb.F_Paste)})
        hole = cfg["lens_hole"]
        fp = pcb.FOOTPRINT(board); fp.SetReference("H1"); fp.SetValue("Lens aperture")
        fp.SetFPIDAsString("O1:H1")
        fp.SetAttributes(pcb.FP_BOARD_ONLY | pcb.FP_EXCLUDE_FROM_BOM | pcb.FP_EXCLUDE_FROM_POS_FILES)
        fp.Reference().SetVisible(False); fp.Value().SetVisible(False)
        pad = pcb.PAD(fp); pad.SetAttribute(pcb.PAD_ATTRIB_NPTH); pad.SetShape(pcb.PAD_SHAPE_CIRCLE)
        pad.SetSize(vector([hole["diameter_mm"]]*2)); pad.SetDrillSize(vector([hole["diameter_mm"]]*2))
        layers = pcb.LSET.AllCuMask(); layers.AddLayer(pcb.F_Mask); layers.AddLayer(pcb.B_Mask)
        pad.SetLayerSet(layers); fp.Add(pad); writer.FootprintSave(str(library), fp)
        board.Add(fp); fp.SetPosition(vector(hole["center_mm"]))
        points = [[8+hole["copper_keepout_diameter_mm"]/2*math.cos(a),
                   8+hole["copper_keepout_diameter_mm"]/2*math.sin(a)] for a in [2*math.pi*i/96 for i in range(97)]]
        add_polygon_zone(board, points, LAYERS, keepout=True)
        for a, b in zip(cfg["outline_mm"], cfg["outline_mm"][1:]):
            shape_line(board, a, b, pcb.Edge_Cuts)
        for text, xy in (("O1", [8, 15.5]), ("1+", [1.4, .42]), ("2-", [3.4, .42])):
            label = pcb.PCB_TEXT(board); label.SetText(text); label.SetPosition(vector(xy))
            label.SetLayer(pcb.F_SilkS); label.SetTextSize(vector([.5, .5])); label.SetTextThickness(pcb.FromMM(.1)); board.Add(label)
        for item in route["tracks"]:
            track = pcb.PCB_TRACK(board); track.SetStart(vector(item["start"])); track.SetEnd(vector(item["end"]))
            track.SetWidth(pcb.FromMM(item["width"])); track.SetLayer(board.GetLayerID(item["layer"]))
            track.SetNet(nets[item["net"]]); board.Add(track)
        for item in route["vias"]:
            via = pcb.PCB_VIA(board); via.SetPosition(vector(item["center"])); via.SetWidth(pcb.FromMM(item["diameter"]))
            via.SetDrill(pcb.FromMM(item["drill"])); via.SetLayerPair(pcb.F_Cu, pcb.B_Cu); via.SetNet(nets[item["net"]]); board.Add(via)
        if route["zones"]:
            raise ValueError("Use explicit routes, no unverified planes")
        name = cfg["name"]
        pcb.SaveBoard(str(target/(name+".kicad_pcb")), board)
        (target/"fp-lib-table").write_text('(fp_lib_table (lib (name "O1") (type "KiCad") (uri "${KIPRJMOD}/O1.pretty") (options "") (descr "Authored O1 light ring lands")))\n')
        (target/(name+".kicad_dru")).write_text(
            '(version 1)\n(rule "Clearance" (constraint clearance (min 0.20mm)))\n'
            '(rule "Hole clearance" (constraint hole_clearance (min 0.20mm)))\n'
            '(rule "Edge" (constraint edge_clearance (min 0.25mm)))\n'
            '(rule "Width" (constraint track_width (min 0.20mm)))\n'
            '(rule "Drill" (constraint hole_size (min 0.25mm)))\n'
            '(rule "Drill separation" (constraint hole_to_hole (min 0.25mm)))\n')
        (library/"ATTRIBUTION.md").write_text("Authored MIT-licensed footprints. LED functional land dimensions follow the Kingbright APT2012QBC/D data sheet; source hash is in optical_materials.json. Generic 1206 lands and solder-wire lands require purchased-component acceptance. No vendor artwork is redistributed.\n")
        data = {"schema": "yam-o1-native-light-board/1", "name": name, "parts": parts, "pads": pads,
                "outline_xy_mm": cfg["outline_mm"], "thickness_mm": cfg["thickness_mm"], "holes": [hole],
                "clearance_mm": cfg["clearance_mm"], "edge_mm": cfg["edge_clearance_mm"],
                **{key: route[key] for key in ("tracks", "vias", "zones")},
                "pcb_sha256": digest(target/(name+".kicad_pcb")),
                "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in (CONFIG, MATERIALS, Path(__file__), ROOT/"engineering/scripts/f1_native_pcb.py")},
                "physical_boards_tested": 0}
        (target/(name+".json")).write_text(json.dumps(data, indent=2)+"\n")
        for path in (CONFIG, MATERIALS):
            shutil.copyfile(path, target/path.name)
        with (target/"pin_net.csv").open("w") as stream:
            rows = csv.DictWriter(stream, fieldnames=["reference", "pad", "net", "x_mm", "y_mm"])
            rows.writeheader()
            for p in pads:
                rows.writerow({k: p[k] for k in ("reference", "pad", "net")} | {"x_mm": p["center"][0], "y_mm": p["center"][1]})
        record["result"] = {"directory": str(target.relative_to(ROOT)), "parts": len(parts), "tracks": len(route["tracks"]), "vias": len(route["vias"])}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
