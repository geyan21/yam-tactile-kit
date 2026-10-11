"""Explicit flex artwork for F1; independent KiCad DRC remains required."""

import csv
import hashlib
import json
import math
from pathlib import Path
import re
from xml.sax.saxutils import escape

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union


def number(value):
    return f"{float(value):.8f}".rstrip("0").rstrip(".") or "0"


def xy(point):
    return " ".join(number(value) for value in point)


def coords(polygon, origin=(0, 0)):
    return " ".join(f"(xy {xy((x-origin[0], y-origin[1]))})"
                    for x, y in list(polygon.exterior.coords)[:-1])


def path_polygon(points, widths):
    """Connected variable-width straight sections, with round joins."""
    if len(points) != len(widths) or len(points) < 2 or min(widths) <= 0:
        raise ValueError("Invalid conductor path")
    pieces = [Point(point).buffer(width / 2, quad_segs=12)
              for point, width in zip(points, widths)]
    for a, b, wa, wb in zip(points, points[1:], widths, widths[1:]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dy)
        if length < 1e-10:
            continue
        nx, ny = -dy / length, dx / length
        pieces.append(Polygon([
            (a[0]+nx*wa/2, a[1]+ny*wa/2), (b[0]+nx*wb/2, b[1]+ny*wb/2),
            (b[0]-nx*wb/2, b[1]-ny*wb/2), (a[0]-nx*wa/2, a[1]-ny*wa/2),
        ]))
    shape = unary_union(pieces).simplify(.0001, preserve_topology=True)
    if shape.geom_type != "Polygon" or not shape.is_valid or shape.interiors:
        raise ValueError("Conductor path is not one simply connected polygon")
    return shape


class FlexArtwork:
    def __init__(self, name, outline, physical_layers, covered_thickness, clearance=.15, edge=.3):
        self.name = name
        self.outline = outline.simplify(.003, preserve_topology=True)
        self.outline_deviation_mm = outline.hausdorff_distance(self.outline)
        segment_lengths = [math.dist(a, b) for ring in (self.outline.exterior, *self.outline.interiors)
                           for a, b in zip(ring.coords, list(ring.coords)[1:])]
        if (not self.outline.is_valid or self.outline.geom_type != "Polygon"
                or self.outline_deviation_mm > .00301 or min(segment_lengths) < .0015):
            raise ValueError("Flex outline cleanup exceeds its bound or leaves microscopic segments")
        self.physical_layers = physical_layers
        self.thickness = covered_thickness
        self.clearance, self.edge = clearance, edge
        self.regions = []
        self.fingers = []
        self.connections = []
        self.openings = []
        self.stiffeners = []
        self.paths = []
        self.labels = []
        self.nets = {"": 0}

    def net(self, name):
        if name not in self.nets:
            self.nets[name] = len(self.nets)
        return self.nets[name]

    def region(self, name, net, layer, shape, purpose):
        if layer not in ("F.Cu", "B.Cu") or self.physical_layers == 1 and layer != "F.Cu":
            raise ValueError("Copper does not match this physical flex stack")
        if shape.geom_type != "Polygon" or not shape.is_valid or shape.interiors or shape.area <= 0:
            raise ValueError("Custom copper needs one valid polygon without holes")
        self.net(net)
        self.regions.append({"name": name, "net": net, "layer": layer,
                             "shape": shape, "purpose": purpose})

    def finger(self, pin, net, center, width=.65, length=4.0, layer="F.Cu"):
        if layer not in ("F.Cu", "B.Cu") or self.physical_layers == 1 and layer != "F.Cu":
            raise ValueError("Cable contact layer does not match this flex stack")
        self.net(net)
        self.fingers.append({"pin": pin, "net": net, "center": list(center),
                             "width": width, "length": length, "layer": layer,
                             "shape": box(center[0]-width/2, center[1]-length/2,
                                          center[0]+width/2, center[1]+length/2)})

    def interlayer(self, name, net, center, pad=.8, drill=.3):
        if self.physical_layers != 2 or (pad-drill)/2 < .25-1e-9:
            raise ValueError("Interlayer connection needs two layers and a 0.25 mm annular ring")
        self.net(net)
        self.connections.append({"name": name, "net": net, "center": list(center),
                                 "pad_mm": pad, "drill_mm": drill,
                                 "shape": Point(center).buffer(pad/2, quad_segs=32)})

    def opening(self, layer, shape):
        if layer not in ("F.Mask", "B.Mask"):
            raise ValueError("Expected a coverlay opening layer")
        clipped = shape.intersection(self.outline)
        pieces = [clipped] if clipped.geom_type == "Polygon" else list(clipped.geoms)
        for piece in pieces:
            if piece.area > 1e-8:
                if piece.interiors:
                    raise ValueError("Split coverlay openings into simple polygons")
                self.openings.append({"layer": layer, "shape": piece})

    def conductor_path(self, net, layer, points, widths, role):
        self.paths.append({"net": net, "layer": layer, "points_mm": points,
                           "widths_mm": widths, "role": role})
        return path_polygon(points, widths)

    def check_geometry(self):
        items = [(r["name"], r["net"], r["layer"], r["shape"]) for r in self.regions]
        items += [(f"J1.{p['pin']}", p["net"], p["layer"], p["shape"]) for p in self.fingers]
        items += [(v["name"], v["net"], layer, v["shape"])
                  for v in self.connections for layer in ("F.Cu", "B.Cu")]
        minimum_edge = min(self.outline.boundary.distance(shape) for _, _, _, shape in items)
        outside = {name: shape.difference(self.outline).area for name, _, _, shape in items}
        distances = []
        for i, (name, net, layer, shape) in enumerate(items):
            for other, other_net, other_layer, other_shape in items[i+1:]:
                if layer == other_layer and (net != other_net or net == ""):
                    distances.append({"a": name, "b": other, "layer": layer,
                                      "clearance_mm": shape.distance(other_shape)})
        result = {"minimum_edge_clearance_mm": minimum_edge,
                  "minimum_different_net_clearance_mm": min(row["clearance_mm"] for row in distances),
                  "outside_outline_area_mm2": max(outside.values()),
                  "closest_pairs": sorted(distances, key=lambda row: row["clearance_mm"])[:8],
                  "physical_layers": self.physical_layers,
                  "connections": len(self.connections)}
        result["passed"] = (minimum_edge >= self.edge-.002 and max(outside.values()) < 1e-7
                            and result["minimum_different_net_clearance_mm"] >= self.clearance-.002)
        return result

    def write(self, destination):
        destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
        library = destination / "F1.pretty"; library.mkdir(exist_ok=True)
        def append_footprint(lines, name, anchor):
            text.extend(lines)
            module = "\n".join(lines).replace(f'"F1:{name}"', f'"{name}"', 1)
            module = module.replace(f'(at {xy(anchor)})', '(at 0 0)', 1)
            module = re.sub(r' \(net \d+ "[^"]*"\)', "", module)
            (library / (name + ".kicad_mod")).write_text(module + "\n")
        # KiCad uses F.Cu/B.Cu slots. For a physical one-layer flex, B.Cu
        # remains empty and must be omitted from its fabrication package.
        text = ['(kicad_pcb (version 20240108) (generator "pcbnew")',
                f'(general (thickness {number(self.thickness)})) (paper "A4")',
                '(layers (0 "F.Cu" signal) (31 "B.Cu" signal)'
                ' (32 "B.Adhes" user) (33 "F.Adhes" user)'
                ' (34 "B.Paste" user) (35 "F.Paste" user)'
                ' (36 "B.SilkS" user) (37 "F.SilkS" user)'
                ' (38 "B.Mask" user) (39 "F.Mask" user)'
                ' (40 "Dwgs.User" user) (41 "Cmts.User" user)'
                ' (44 "Edge.Cuts" user) (48 "B.Fab" user) (49 "F.Fab" user))',
                '(setup (pad_to_mask_clearance 0))']
        text += [f'(net {index} "{net}")' for net, index in self.nets.items()]
        lines = [
            '(footprint "F1:Foil" (layer "F.Cu") (at 0 0)'
            ' (attr board_only exclude_from_pos_files exclude_from_bom)',
            '(property "Reference" "FOIL" (at 0 0) (layer "F.Fab") hide'
            ' (effects (font (size 1 1) (thickness 0.15))))',
        ]
        for region in self.regions:
            shape = region["shape"]
            point = shape.representative_point()
            anchor = (point.x, point.y)
            layer = region["layer"]
            lines.append(
                f'(pad "{region["name"]}_COPPER" smd custom (at {xy(anchor)})'
                f' (size 0.01 0.01) (layers "{layer}")'
                f' (net {self.nets[region["net"]]} "{region["net"]}")'
                ' (options (clearance outline) (anchor circle))'
                f' (primitives (gr_poly (pts {coords(shape, anchor)}) (width 0) (fill yes))))')
        for finger in self.fingers:
            lines.append(f'(pad "J1_{finger["pin"]}" connect rect (at {xy(finger["center"])})'
                        f' (size {xy((finger["width"], finger["length"]))})'
                        f' (layers "{finger["layer"]}") (net {self.nets[finger["net"]]} "{finger["net"]}"))')
        for item in self.connections:
            # Explicit plated pads omit Mask layers: coverlay openings are
            # separately drawn. This makes backside tenting unambiguous.
            lines.append(f'(pad "{item["name"]}" thru_hole circle (at {xy(item["center"])})'
                     f' (size {number(item["pad_mm"])} {number(item["pad_mm"])})'
                     f' (drill {number(item["drill_mm"])}) (layers "*.Cu")'
                     f' (net {self.nets[item["net"]]} "{item["net"]}"))')
        for opening in self.openings:
            lines.append(f'(fp_poly (pts {coords(opening["shape"])}) (stroke (width 0) (type default))'
                        f' (fill solid) (layer "{opening["layer"]}"))')
        lines.append(')')
        append_footprint(lines, "Foil", (0, 0))
        for stiffener in self.stiffeners:
            text.append(f'(gr_poly (pts {coords(stiffener)}) (stroke (width 0.1) (type default))'
                        ' (fill none) (layer "Dwgs.User"))')
        for label in self.labels:
            text.append(f'(gr_text "{label["text"]}" (at {xy(label["position_mm"])})'
                        f' (layer "{label["layer"]}")'
                        ' (effects (font (size 1 1) (thickness 0.15))))')
        for ring in (self.outline.exterior, *self.outline.interiors):
            for a, b in zip(ring.coords, list(ring.coords)[1:]):
                text.append(f'(gr_line (start {xy(a)}) (end {xy(b)})'
                            ' (stroke (width 0.05) (type default)) (layer "Edge.Cuts"))')
        text.append(')')
        pcb = destination / (self.name + ".kicad_pcb")
        pcb.write_text("\n".join(text) + "\n")
        (destination / "fp-lib-table").write_text(
            '(fp_lib_table (lib (name "F1") (type "KiCad") (uri "${KIPRJMOD}/F1.pretty")'
            ' (options "") (descr "Generated F1 conductors and cable contacts")))\n')
        (destination / (self.name + ".kicad_dru")).write_text(
            '(version 1)\n'
            f'(rule "flex copper clearance" (constraint clearance (min {self.clearance}mm)))\n'
            f'(rule "flex copper to outline" (constraint edge_clearance (min {self.edge}mm)))\n'
            '(rule "flex trace width" (constraint track_width (min 0.125mm)))\n'
            '(rule "plated drill" (constraint hole_size (min 0.3mm)))\n'
            '# BEGIN_FPC_SHARED_COVERLAY\n'
            '# FOIL is an unsoldered flex: sensing electrodes and cable contacts\n'
            '# intentionally share coverlay windows. No paste is generated.\n'
            '# This permits only mask bridging, never copper shorts or missing connections.\n'
            '(rule "FOIL unsoldered shared coverlay"\n'
            ' (condition "A.memberOfFootprint(\'FOIL\')")\n'
            ' (constraint bridged_mask) (severity ignore))\n'
            '# END_FPC_SHARED_COVERLAY\n')
        payload = {
            "name": self.name, "status": "development artwork; independent DRC and assembly checks pending",
            "physical_layers": self.physical_layers, "covered_thickness_mm": self.thickness,
            "outline_mm": list(self.outline.exterior.coords),
            "outline_cleanup_maximum_deviation_mm": self.outline_deviation_mm,
            "regions": [{key: value for key, value in row.items() if key != "shape"}
                        | {"outline_mm": list(row["shape"].exterior.coords)} for row in self.regions],
            "fingers": [{key: value for key, value in row.items() if key != "shape"} for row in self.fingers],
            "plated_connections": [{key: value for key, value in row.items() if key != "shape"} for row in self.connections],
            "coverlay_openings": [{"layer": row["layer"], "outline_mm": list(row["shape"].exterior.coords)}
                                 for row in self.openings],
            "stiffeners_mm": [list(shape.exterior.coords) for shape in self.stiffeners],
            "labels": self.labels,
            "paths": self.paths, "geometry_checks": self.check_geometry(),
            "pcb_sha256": hashlib.sha256(pcb.read_bytes()).hexdigest(),
            "rules_sha256": hashlib.sha256((destination / (self.name + ".kicad_dru")).read_bytes()).hexdigest(),
            "manufacturing_intent": {
                "solder_paste_generated": False,
                "shared_coverlay_windows": len(self.openings),
                "mask_bridge_allowance": "Only mask apertures owned by unsoldered FOIL; copper clearance and connectivity remain checked.",
                "required_check": "Retain both unsuppressed and manufacturing-intent DRC reports before releasing fabrication files.",
            },
            "physical_specimens_tested": 0,
        }
        (destination / (self.name + ".json")).write_text(json.dumps(payload, indent=2) + "\n")
        return payload
