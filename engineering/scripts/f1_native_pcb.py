#!/usr/bin/python3
"""Generate an F1 board with native KiCad placement/flip semantics.

Run with the prepared KiCad Python interpreter. The input is a saved, explicit
board specification; optional routing is produced by the separate CAD worker.
No changes to KiCad installations, user settings or older prototype generators.
"""

import argparse
import csv
from datetime import datetime, timezone
import faulthandler
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
for category in ("CONFIG", "CACHE", "DATA"):
    os.environ["XDG_" + category + "_HOME"] = str(
        ROOT / "build/engineering/tools/f1-kicad" / category.lower())
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
import pcbnew as pcb
faulthandler.enable()

LIBRARIES = ROOT / "build/engineering/tools/b1-kicad/AppDir/share/kicad/footprints"
COPPER = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vector(xy):
    return pcb.VECTOR2I(*(pcb.FromMM(float(v)) for v in xy))


def mm(position):
    return [pcb.ToMM(position.x), pcb.ToMM(position.y)]


def transform(point, part):
    x, y = point
    if part.get("side", "F") == "B":
        x = -x
    angle = -math.radians(part.get("rotation_deg", 0))
    c, s = math.cos(angle), math.sin(angle)
    return [part["center_mm"][0] + c*x - s*y,
            part["center_mm"][1] + s*x + c*y]


def shape_line(parent, start, end, layer, width=.05):
    item = pcb.PCB_SHAPE(parent)
    item.SetShape(pcb.SHAPE_T_SEGMENT)
    item.SetStart(vector(start)); item.SetEnd(vector(end))
    item.SetLayer(layer); item.SetWidth(pcb.FromMM(width))
    parent.Add(item)


def rectangle(parent, bounds, layer, width=.05):
    x0, y0, x1, y1 = bounds
    points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    for start, end in zip(points, points[1:]):
        shape_line(parent, start, end, layer, width)


def custom_footprint(board, part):
    footprint = pcb.FOOTPRINT(board)
    footprint.SetAttributes(pcb.FP_SMD)
    for data in part["pads"]:
        pad = pcb.PAD(footprint)
        pad.SetNumber(str(data["pad"]))
        pad.SetShape(pcb.PAD_SHAPE_RECT)
        pad.SetAttribute(pcb.PAD_ATTRIB_SMD)
        pad.SetPosition(vector(data["center_mm"]))
        pad.SetSize(vector(data["size_mm"]))
        layers = pcb.LSET()
        for layer in (pcb.F_Cu, pcb.F_Mask, pcb.F_Paste):
            layers.AddLayer(layer)
        pad.SetLayerSet(layers)
        footprint.Add(pad)
    if "body_envelope_mm" in part:
        rectangle(footprint, part["body_envelope_mm"], pcb.F_Fab, .1)
    rectangle(footprint, part["courtyard_mm"], pcb.F_CrtYd)
    # Pin-1 mark beside the signal toes, outside the mating/lead envelope.
    mark = [(-3.7, -2.95), (-3.3, -2.75), (-3.7, -2.55), (-3.7, -2.95)]
    for start, end in zip(mark, mark[1:]):
        shape_line(footprint, start, end, pcb.F_SilkS, .1)
    return footprint


def place(board, part, nets, library, sources):
    if part.get("library"):
        source = LIBRARIES / part["library"]
        footprint = pcb.FootprintLoad(str(source.parent), source.stem)
        if footprint is None:
            raise ValueError(f"Cannot load {source}")
        sources[str(source.relative_to(ROOT))] = digest(source)
    else:
        footprint = custom_footprint(board, part)
    footprint.SetPosition(vector([0, 0]))
    footprint.SetOrientationDegrees(0)
    footprint.SetReference(part["reference"])
    footprint.SetValue(part["value"])
    footprint.SetFPIDAsString("F1:" + part["reference"])
    # Portable board source uses separately generated mechanical CAD; it does
    # not retain unresolved global-library 3D model paths.
    footprint.Models().clear()
    footprint.Reference().SetLayer(pcb.F_Fab)
    if "pads" in part:
        # Put reference designators in the open lateral connector gaps.
        # The most distal pair is labeled to its left, inside the board.
        dx = -7.0 if part["center_mm"][0] > 60 else 7.0
        if part.get("side", "F") == "B":
            dx = -dx
        footprint.Reference().SetPosition(vector([dx, -.7]))
        footprint.Reference().SetLayer(pcb.F_SilkS)
    elif part["reference"] == "JW":
        footprint.Reference().SetPosition(vector([-16.7, 0]))
        footprint.Reference().SetLayer(pcb.F_SilkS)
    on_silk = footprint.Reference().GetLayer() == pcb.F_SilkS
    footprint.Reference().SetTextSize(vector([.8, .8] if on_silk else [.55, .55]))
    footprint.Reference().SetTextThickness(pcb.FromMM(.12 if on_silk else .08))
    footprint.Value().SetVisible(False)
    local = {}
    for pad in footprint.Pads():
        number = pad.GetNumber()
        if number in local:
            # The two independent mechanical lands on an FH12 share MP in
            # KiCad's library. Give them explicit unique board/library IDs.
            number += "2"
            pad.SetNumber(number)
        local[number] = {"center": mm(pad.GetPosition()),
                         "size": mm(pad.GetSize())}
    # An empty output library has no file from which KiCad can guess its
    # format. Select the native writer explicitly instead of auto-detection.
    plugin = pcb.PCB_IO_MGR.FindPlugin(pcb.PCB_IO_MGR.KICAD_SEXP)
    plugin.FootprintSave(str(library), footprint)
    for pad in footprint.Pads():
        net = part["nets"].get(pad.GetNumber(), "")
        if net:
            pad.SetNet(nets[net])
        pad.SetLocalSolderMaskMargin(pcb.FromMM(.025))
    # Imported library footprints have no board parent. Flip consults the
    # board layer stack, so adopt the footprint before applying the transform.
    board.Add(footprint)
    if part.get("side", "F") == "B":
        footprint.Flip(vector([0, 0]), pcb.FLIP_DIRECTION_LEFT_RIGHT)
    # KiCad's left/right Flip also changes the footprint's angle to 180 deg.
    # Apply the requested in-plane rotation relative to that native result.
    footprint.SetOrientationDegrees(footprint.GetOrientationDegrees() + part.get("rotation_deg", 0))
    footprint.SetPosition(vector(part["center_mm"]))
    result = []
    for pad in footprint.Pads():
        number = pad.GetNumber()
        expected = transform(local[number]["center"], part)
        actual = mm(pad.GetPosition())
        if math.dist(expected, actual) > 2e-6:
            raise ValueError(f"Native pad transform differs at {part['reference']}.{number}: "
                                f"expected {expected}, actual {actual}, local {local[number]}")
        copper = [name for name in COPPER if pad.IsOnLayer(board.GetLayerID(name))]
        expected_layer = "B.Cu" if part.get("side", "F") == "B" else "F.Cu"
        if copper != [expected_layer]:
            raise ValueError(f"Unexpected pad layer at {part['reference']}.{number}: {copper}")
        result.append({
            "reference": part["reference"], "pad": number,
            "net": pad.GetNetname(), "center": actual,
            "size": local[number]["size"],
            "rotation": pad.GetOrientationDegrees(),
            "layers": copper,
            "paste": pad.IsOnLayer(pcb.F_Paste) or pad.IsOnLayer(pcb.B_Paste),
            "native_shape": int(pad.GetShape()),
            "routing_envelope": "Conservative rectangle at native pad orientation"
        })
    return result


def add_polygon_zone(board, polygon, layers, net=None, keepout=False, clearance=.15):
    zone = pcb.ZONE(board)
    layer_set = pcb.LSET()
    for layer in layers:
        layer_set.AddLayer(board.GetLayerID(layer))
    zone.SetLayerSet(layer_set)
    zone.SetLocalClearance(pcb.FromMM(clearance))
    zone.SetMinThickness(pcb.FromMM(.15))
    if keepout:
        zone.SetIsRuleArea(True)
        zone.SetDoNotAllowTracks(True)
        zone.SetDoNotAllowVias(True)
        zone.SetDoNotAllowZoneFills(True)
        zone.SetDoNotAllowPads(False)
        zone.SetDoNotAllowFootprints(False)
    else:
        zone.SetNet(net)
        zone.SetPadConnection(pcb.ZONE_CONNECTION_FULL)
    outline = zone.Outline()
    outline.NewOutline()
    for point in polygon[:-1] if polygon[0] == polygon[-1] else polygon:
        outline.Append(*[pcb.FromMM(float(v)) for v in point])
    board.Add(zone)


def build(spec, destination, route):
    name = spec["name"]
    destination.mkdir(parents=True, exist_ok=False)
    library = destination / "F1.pretty"
    library.mkdir()
    (library / "ATTRIBUTION.md").write_text(
        "# Footprint sources\n\n"
        "J0R–J5R and J0C–J5C are separately authored land patterns from the "
        "Hirose dimensions listed in the board specification, under the kit's MIT license.\n\n"
        "The other footprints are adapted from the KiCad libraries by the KiCad library "
        "contributors, under CC BY-SA 4.0 with the KiCad Libraries Exception:\n"
        "https://www.kicad.org/libraries/license/\n"
        "https://creativecommons.org/licenses/by-sa/4.0/\n\n"
        "Changes include reference/value fields, mechanical-land numbering, removal of "
        "external 3D-model paths and local mask settings. Original source paths and SHA-256 "
        "hashes are retained in the board JSON. The exception permits the footprints to be "
        "used in PCB designs; the library files retain their stated license.\n")
    board = pcb.BOARD()
    board.SetCopperLayerCount(4)
    board.GetDesignSettings().SetBoardThickness(pcb.FromMM(spec["thickness_mm"]))
    names = {net for p in spec["parts"] for net in p["nets"].values() if net}
    nets = {}
    for net in sorted(names):
        item = pcb.NETINFO_ITEM(board, net)
        board.Add(item); nets[net] = item
    pads = []; sources = {}
    for part in spec["parts"]:
        print("Place", part["reference"], part.get("library", "custom"), flush=True)
        pads.extend(place(board, part, nets, library, sources))
    for i, hole in enumerate(spec["holes"]):
        footprint = pcb.FOOTPRINT(board)
        footprint.SetReference(f"H{i+1}")
        footprint.SetAttributes(pcb.FP_BOARD_ONLY | pcb.FP_EXCLUDE_FROM_BOM | pcb.FP_EXCLUDE_FROM_POS_FILES)
        footprint.SetPosition(vector(hole["center_mm"]))
        footprint.Reference().SetVisible(False)
        footprint.Value().SetVisible(False)
        pad = pcb.PAD(footprint)
        pad.SetShape(pcb.PAD_SHAPE_CIRCLE)
        pad.SetAttribute(pcb.PAD_ATTRIB_NPTH)
        diameter = [hole["diameter_mm"]]*2
        pad.SetSize(vector(diameter)); pad.SetDrillSize(vector(diameter))
        pad.SetPosition(vector(hole["center_mm"]))
        layers = pcb.LSET()
        for layer in (*[board.GetLayerID(n) for n in COPPER], pcb.F_Mask, pcb.B_Mask):
            layers.AddLayer(layer)
        pad.SetLayerSet(layers)
        footprint.Add(pad); board.Add(footprint)
        radius = hole["copper_keepout_diameter_mm"]/2
        ring = [[hole["center_mm"][0]+radius*math.cos(t*math.tau/96),
                 hole["center_mm"][1]+radius*math.sin(t*math.tau/96)] for t in range(96)]
        add_polygon_zone(board, ring, COPPER, keepout=True, clearance=0)
    ring = spec["outline_xy_mm"]
    for start, end in zip(ring, ring[1:] + ring[:1]):
        if math.dist(start, end) > 1e-6:
            shape_line(board, start, end, pcb.Edge_Cuts)
    for layer in (pcb.F_SilkS, pcb.B_SilkS):
        text = pcb.PCB_TEXT(board)
        text.SetText("F1 FANOUT")
        text.SetTextSize(vector([.8, .8]))
        text.SetTextThickness(pcb.FromMM(.12))
        text.SetPosition(vector([64.5, 4.0]))
        text.SetLayer(layer)
        text.SetMirrored(layer == pcb.B_SilkS)
        board.Add(text)
    if route:
        for data in route["tracks"]:
            track = pcb.PCB_TRACK(board)
            track.SetStart(vector(data["start"])); track.SetEnd(vector(data["end"]))
            track.SetWidth(pcb.FromMM(data["width"]))
            track.SetLayer(board.GetLayerID(data["layer"]))
            track.SetNet(nets[data["net"]]); board.Add(track)
        for data in route["vias"]:
            via = pcb.PCB_VIA(board)
            via.SetPosition(vector(data["center"]))
            via.SetWidth(pcb.FromMM(data["diameter"]))
            via.SetDrill(pcb.FromMM(data["drill"]))
            via.SetViaType(pcb.VIATYPE_THROUGH)
            via.SetLayerPair(pcb.F_Cu, pcb.B_Cu)
            via.SetNet(nets[data["net"]]); board.Add(via)
        for data in route.get("zones", []):
            add_polygon_zone(board, data["outline_xy_mm"], [data["layer"]],
                             nets[data["net"]], clearance=spec["clearance_mm"])
    pcb_path = destination / (name + ".kicad_pcb")
    pcb.SaveBoard(str(pcb_path), board)
    restored = pcb.LoadBoard(str(pcb_path))
    native_pads = {(f.GetReference(), p.GetNumber()): p
                   for f in restored.GetFootprints() for p in f.Pads()
                   if f.GetReference() in {p["reference"] for p in pads}}
    for data in pads:
        native = native_pads[(data["reference"], data["pad"])]
        if math.dist(mm(native.GetPosition()), data["center"]) > 1e-6 or native.GetNetname() != data["net"]:
            raise ValueError("Native board serialization changed a pad or net")
    rules = (
        "(version 1)\n"
        f'(rule "clearance" (constraint clearance (min {spec["clearance_mm"]}mm)))\n'
        f'(rule "edge" (constraint edge_clearance (min {spec["edge_mm"]}mm)))\n'
        '(rule "track" (constraint track_width (min 0.15mm)))\n'
        '(rule "drill" (constraint hole_size (min 0.2mm)))\n'
        '(rule "via" (constraint via_diameter (min 0.45mm)))\n')
    (destination / (name + ".kicad_dru")).write_text(rules)
    (destination / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "F1") (type "KiCad") (uri "${KIPRJMOD}/F1.pretty")'
        ' (options "") (descr "F1 embedded footprints; see source hashes and attribution")))\n')
    result = {
        "schema": "yam-f1-native-board/1", "name": name, "tool": pcb.GetBuildVersion(),
        "thickness_mm": spec["thickness_mm"], "clearance_mm": spec["clearance_mm"],
        "edge_mm": spec["edge_mm"], "outline_xy_mm": spec["outline_xy_mm"],
        "parts": spec["parts"], "holes": spec["holes"], "pads": pads,
        "library_source_hashes": sources,
        "library_attribution": "KiCad libraries, CC-BY-SA 4.0 with library exception; https://www.kicad.org/libraries/license/",
        "native_pad_transform_and_roundtrip_passed": True,
        "tracks": route["tracks"] if route else [], "vias": route["vias"] if route else [],
        "physical_boards_tested": 0, "pcb_sha256": digest(pcb_path),
        "native_generator_sha256": digest(Path(__file__)),
        "status": "Native generated board; independent DRC, circuit, fit and physical checks required"
    }
    (destination / (name + ".json")).write_text(json.dumps(result, indent=2)+"\n")
    with (destination / (name + "_pins.csv")).open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["reference", "pad", "net", "layer", "pcb_x_mm", "pcb_y_mm"])
        for pad in pads:
            writer.writerow([pad["reference"], pad["pad"], pad["net"], ",".join(pad["layers"]), *pad["center"]])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specification", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--routing", type=Path)
    args = parser.parse_args()
    paths = [args.specification.resolve(), args.destination.resolve()]
    if args.routing:
        paths.append(args.routing.resolve())
    if not all(path.is_relative_to(ROOT) for path in paths):
        parser.error("Use repository-owned input/output paths")
    with execution(ROOT / "build/records", "Generate and round-trip F1 component placements with the native KiCad API") as record:
        spec = json.loads(args.specification.read_text())
        route = json.loads(args.routing.read_text()) if args.routing else None
        result = build(spec, args.destination.resolve(), route)
        snapshot = args.destination.resolve() / "generation_inputs"
        snapshot.mkdir()
        shutil.copyfile(Path(__file__), snapshot / "f1_native_pcb.py")
        shutil.copyfile(args.specification, snapshot / "specification.json")
        if args.routing:
            shutil.copyfile(args.routing, snapshot / "routing.json")
        record["board"] = {"destination": str(args.destination), "pcb_sha256": result["pcb_sha256"]}
        print(json.dumps({"directory": str(args.destination), "pads": len(result["pads"]),
                          "tracks": len(result["tracks"]), "vias": len(result["vias"]),
                          "native_transform_roundtrip_passed": True}, indent=2))


if __name__ == "__main__":
    main()
