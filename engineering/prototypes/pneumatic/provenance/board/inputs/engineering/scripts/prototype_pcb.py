"""Small explicit PCB writer for the experimental finger boards.

This is source generation, not a replacement for the independent KiCad DRC.
Dimensions are millimetres. KiCad coordinates increase right and down.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box

LAYERS = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
LAYER_IDS = (0, 1, 2, 31)


def number(value):
    return f"{value:.8f}".rstrip("0").rstrip(".")


def xy(point):
    return " ".join(number(float(value)) for value in point)


class Board:
    def __init__(self, name, outline, thickness=.8, clearance=.15, edge=.2):
        self.name = name
        self.outline = outline
        self.thickness = thickness
        self.clearance = clearance
        self.edge = edge
        self.nets = {"": 0}
        self.components = []
        self.pads = []
        self.tracks = []
        self.vias = []
        self.holes = []
        self.paste = []
        self.zones = []
        self.keepouts = []

    def net(self, name):
        if name not in self.nets:
            self.nets[name] = len(self.nets)
        return self.nets[name]

    def component(self, ref, value, center, pads, rotation=0, body=None,
                  source="", height=1.05, note=""):
        if any(part["reference"] == ref for part in self.components):
            raise ValueError(f"Duplicate component {ref}")
        c = {"reference": ref, "value": value, "center_mm": center,
             "rotation_deg": rotation, "source": source,
             "height_mm": height, "note": note}
        if body:
            c["body_mm"] = body
        self.components.append(c)
        angle = -math.radians(rotation)
        cosine, sine = math.cos(angle), math.sin(angle)
        for pad in pads:
            n, dx, dy, width, depth, net = pad[:6]
            paste = pad[6] if len(pad) > 6 else True
            x = center[0] + dx*cosine - dy*sine
            y = center[1] + dx*sine + dy*cosine
            geometry = box(-width/2, -depth/2, width/2, depth/2)
            geometry = affinity.rotate(geometry, -rotation, origin=(0, 0))
            geometry = affinity.translate(geometry, x, y)
            self.net(net)
            self.pads.append({"reference": ref, "pad": str(n), "center": [x, y],
                              "size": [width, depth], "rotation": rotation,
                              "net": net, "paste": paste, "shape": geometry})
        return c

    def resistor(self, ref, value, center, nets, rotation=0):
        return self.component(ref, value, center, [
            (1, -.5, 0, .55, .55, nets[0]),
            (2, .5, 0, .55, .55, nets[1]),
        ], rotation, body=[1, .5], height=.55)

    def pad(self, reference, number):
        return next(p for p in self.pads
                    if p["reference"] == reference and p["pad"] == str(number))

    def wire_port(self, ref, center, nets, pitch=1.5, rotation=0):
        self.component(ref, "Rear-exit solder wires", center,
                       [(i+1, (i-(len(nets)-1)/2)*pitch, 0, 1.1, 1.1, net, False)
                        for i, net in enumerate(nets)], rotation, height=0,
                       note="0.6 mm finished plated holes; solder insulated wires from the back")
        for p in self.pads:
            if p["reference"] == ref:
                p["drill"] = .6

    def trace(self, net, points, layer="F.Cu", width=.15):
        self.net(net)
        for a, b in zip(points, points[1:]):
            if math.dist(a, b) < 1e-7:
                continue
            self.tracks.append({"net": net, "start": list(a), "end": list(b),
                                "layer": layer, "width": width,
                                "shape": LineString([a, b]).buffer(width/2)})

    def via(self, net, center, diameter=.45, drill=.2):
        self.net(net)
        if any(v["net"] == net and math.dist(v["center"], center) < 1e-5 for v in self.vias):
            return
        self.vias.append({"net": net, "center": list(center), "diameter": diameter,
                         "drill": drill, "shape": Point(center).buffer(diameter/2)})

    def add_hole(self, center, diameter, copper_keepout):
        self.holes.append({"center": list(center), "diameter": diameter})
        self.keepouts.append(Point(center).buffer(copper_keepout/2))

    def prune_unused_vias(self):
        """Remove only non-ground vias with copper on fewer than two layers."""
        retained = []
        removed = []
        for via in self.vias:
            if via["net"] == "GND":
                retained.append(via)
                continue
            layers = {t["layer"] for t in self.tracks
                      if t["net"]==via["net"] and t["shape"].intersects(via["shape"])}
            for pad in self.pads:
                if pad["net"]==via["net"] and pad["shape"].intersects(via["shape"]):
                    layers.update(LAYERS if pad.get("drill") else ("F.Cu",))
            if len(layers)>=2:
                retained.append(via)
            else:
                removed.append({"net":via["net"],"center":via["center"],"connected_layers":sorted(layers)})
        self.vias = retained
        # Virtual staging points sometimes leave the same tiny snap segment
        # traversed twice. If the via was unused and no pad lands there, that
        # single-neighbour leaf is redundant copper, not a required connection.
        for item in removed:
            point = item["center"]
            if any(p["net"]==item["net"] and p["shape"].covers(Point(point)) for p in self.pads):
                continue
            incident = [t for t in self.tracks if t["net"]==item["net"] and (
                math.dist(t["start"],point)<1e-7 or math.dist(t["end"],point)<1e-7)]
            neighbours = {tuple(round(v,7) for v in (t["end"] if math.dist(t["start"],point)<1e-7 else t["start"]))
                          for t in incident}
            if len(neighbours)==1:
                identities = {id(t) for t in incident}
                self.tracks = [t for t in self.tracks if id(t) not in identities]
        return removed

    def copper(self, layer):
        result = [(p["net"], p["shape"]) for p in self.pads
                  if layer == "F.Cu" or p.get("drill")]
        result += [(t["net"], t["shape"]) for t in self.tracks if t["layer"] == layer]
        result += [(v["net"], v["shape"]) for v in self.vias]
        return result

    def write(self, destination):
        # Mounting keepouts allow KiCad's noncopper NPTH pad primitive, but
        # actual electrical lands are separately prohibited here.
        for pad in self.pads:
            if any(pad["shape"].intersects(k) for k in self.keepouts):
                raise ValueError(f"Electrical pad overlaps a fastener annulus: {pad['reference']}.{pad['pad']}")
        destination.mkdir(parents=True, exist_ok=True)
        library = destination / "Prototype.pretty"
        library.mkdir(exist_ok=True)
        text = [
            '(kicad_pcb (version 20240108) (generator "pcbnew")',
            f'(general (thickness {number(self.thickness)})) (paper "A4")',
            '(layers ' + " ".join(f'({i} "{name}" signal)' for i, name in zip(LAYER_IDS, LAYERS))
            + ' (32 "B.Adhes" user) (33 "F.Adhes" user) (34 "B.Paste" user) (35 "F.Paste" user)'
              ' (36 "B.SilkS" user) (37 "F.SilkS" user) (38 "B.Mask" user) (39 "F.Mask" user)'
              ' (44 "Edge.Cuts" user) (46 "B.CrtYd" user) (47 "F.CrtYd" user)'
              ' (48 "B.Fab" user) (49 "F.Fab" user))',
            '(setup (pad_to_mask_clearance 0.025))',
        ]
        text += [f'(net {n} "{name}")' for name, n in self.nets.items()]
        for part in self.components:
            ref = part["reference"]
            cx, cy = part["center_mm"]
            attr = "through_hole" if any(p.get("drill") for p in self.pads if p["reference"] == ref) else "smd"
            lines = [
                f'(footprint "Prototype:{ref}" (layer "F.Cu") (at {xy((cx,cy))}) (attr {attr})',
                f'(property "Reference" "{ref}" (at 0 0) (layer "F.Fab")'
                ' (effects (font (size 0.6 0.6) (thickness 0.1))))',
                f'(property "Value" "{part["value"]}" (at 0 1) (layer "F.Fab") hide'
                ' (effects (font (size 0.5 0.5) (thickness 0.1))))',
            ]
            for pad in (p for p in self.pads if p["reference"] == ref):
                x, y = pad["center"]
                layers = '"F.Cu" "F.Mask"' + (' "F.Paste"' if pad["paste"] else "")
                pad_type, drill = "smd", ""
                if pad.get("drill"):
                    layers = '"*.Cu" "*.Mask"'
                    pad_type = "thru_hole"
                    drill = f' (drill {number(pad["drill"])})'
                lines.append(
                    f'(pad "{pad["pad"]}" {pad_type} rect (at {xy((x-cx,y-cy))} {number(pad["rotation"])})'
                    f' (size {xy(pad["size"])}){drill} (layers {layers}) (net {self.nets[pad["net"]]} "{pad["net"]}"))')
            # The footprint intentionally embeds the transformed copper
            # rather than relying on an installed external footprint library.
            lines.append(")")
            text += lines
            import re
            pattern = "\n".join(lines).replace(
                f'(footprint "Prototype:{ref}"', f'(footprint "{ref}"', 1).replace(
                    f'(at {xy((cx,cy))})', '(at 0 0)', 1)
            pattern = re.sub(r' \(net \d+ "[^"]*"\)', "", pattern)
            (library / f"{ref}.kicad_mod").write_text(pattern + "\n")
        for h in self.holes:
            text.append(
                f'(footprint "MountingHole" (layer "F.Cu") (at {xy(h["center"])}) (attr board_only exclude_from_pos_files exclude_from_bom)'
                f' (pad "" np_thru_hole circle (at 0 0) (size {number(h["diameter"])} {number(h["diameter"])})'
                f' (drill {number(h["diameter"])}) (layers "*.Cu" "*.Mask")))')
        for t in self.tracks:
            text.append(f'(segment (start {xy(t["start"])}) (end {xy(t["end"])})'
                        f' (width {number(t["width"])})(layer "{t["layer"]}") (net {self.nets[t["net"]]}))')
        for v in self.vias:
            text.append(f'(via (at {xy(v["center"])}) (size {number(v["diameter"])})'
                        f' (drill {number(v["drill"])}) (layers "F.Cu" "B.Cu") (net {self.nets[v["net"]]}))')
        for p in self.paste:
            coordinates = " ".join(f'(xy {xy(point)})' for point in list(p.exterior.coords)[:-1])
            text.append(f'(gr_poly (pts {coordinates}) (stroke (width 0) (type default)) (fill solid) (layer "F.Paste"))')
        for ring in (self.outline.exterior, *self.outline.interiors):
            for a, b in zip(ring.coords, list(ring.coords)[1:]):
                text.append(f'(gr_line (start {xy(a)}) (end {xy(b)}) (stroke (width 0.05) (type default)) (layer "Edge.Cuts"))')
        for zone in self.zones:
            coords = " ".join(f'(xy {xy(p)})' for p in list(zone["shape"].exterior.coords)[:-1])
            text.append(f'(zone (net {self.nets[zone["net"]]}) (net_name "{zone["net"]}")'
                        f' (layer "{zone["layer"]}") (hatch edge 0.5)'
                        f' (connect_pads yes (clearance {self.clearance})) (min_thickness 0.15)'
                        ' (fill yes (thermal_gap 0.2) (thermal_bridge_width 0.2))'
                        f' (polygon (pts {coords})))')
        for keepout in self.keepouts:
            coords = " ".join(f'(xy {xy(p)})' for p in list(keepout.exterior.coords)[:-1])
            text.append('(zone (net 0) (net_name "") (layers "F.Cu" "In1.Cu" "In2.Cu" "B.Cu")'
                        ' (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.15)'
                        ' (keepout (tracks not_allowed) (vias not_allowed) (pads allowed)'
                        ' (copperpour not_allowed) (footprints allowed))'
                        f' (polygon (pts {coords})))')
        text.append(")")
        (destination / f"{self.name}.kicad_pcb").write_text("\n".join(text) + "\n")
        (destination / f"{self.name}.kicad_dru").write_text(
            '(version 1)\n'
            f'(rule "clearance" (constraint clearance (min {self.clearance}mm)))\n'
            f'(rule "copper to edge" (constraint edge_clearance (min {self.edge}mm)))\n'
            '(rule "track width" (constraint track_width (min 0.15mm)))\n'
            '(rule "via drill" (constraint hole_size (min 0.20mm)))\n'
            '(rule "via diameter" (constraint via_diameter (min 0.45mm)))\n')
        (destination / "fp-lib-table").write_text(
            '(fp_lib_table (lib (name "Prototype") (type "KiCad")'
            ' (uri "${KIPRJMOD}/Prototype.pretty") (options "") (descr "Embedded generated prototype footprints")))\n')
        with (destination / f"{self.name}_pin_net.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["reference", "pad", "net", "x_mm", "y_mm"])
            for p in self.pads:
                writer.writerow([p["reference"], p["pad"], p["net"] or "unused", *p["center"]])
        payload = {
            "name": self.name, "thickness_mm": self.thickness,
            "layers": LAYERS, "outline_xy_mm": list(self.outline.exterior.coords),
            "holes": self.holes, "components": self.components,
            "pads": [{k: v for k, v in p.items() if k != "shape"} for p in self.pads],
            "tracks": [{k: v for k, v in p.items() if k != "shape"} for p in self.tracks],
            "vias": [{k: v for k, v in p.items() if k != "shape"} for p in self.vias],
            "physical_boards_tested": 0,
            "status": "Generated source; independent KiCad DRC and physical tests required",
        }
        (destination / f"{self.name}.json").write_text(json.dumps(payload, indent=2) + "\n")
        return payload

    def assembly_svg(self, path):
        left, top, right, bottom = self.outline.bounds
        scale = 12
        width = max(1050, (right-left)*scale + 80)
        height = (bottom-top)*scale + 165
        def point(p):
            return ((p[0]-left)*scale+40, (p[1]-top)*scale+110)
        def polygon(shape):
            return " ".join(",".join(number(v) for v in point(p)) for p in shape.exterior.coords)
        lines = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
                 '<rect width="100%" height="100%" fill="#fff"/>',
                 '<g font-family="sans-serif" fill="#173f45">',
                 f'<text x="30" y="32" font-size="23">{escape(self.name)} · PCB component-side view</text>',
                 '<text x="30" y="58" font-size="14">Generated copper and component placement. No assembled hardware is pictured.</text>',
                 '<text x="30" y="80" font-size="13">Screen dimensions are illustrative; fabricate from checked Gerbers/drill files.</text>',
                 f'<polygon points="{polygon(self.outline)}" fill="#e5f1e8" stroke="#345c4e"/>']
        colors = {"F.Cu": "#b35d50", "B.Cu": "#447dad", "In1.Cu": "#d89420", "In2.Cu": "#915cba"}
        for t in self.tracks:
            a, b = point(t["start"]), point(t["end"])
            lines.append(f'<path d="M{xy(a)}L{xy(b)}" fill="none" stroke="{colors[t["layer"]]}"'
                         f' stroke-width="{t["width"]*scale}" opacity=".65"/>')
        for p in self.pads:
            lines.append(f'<polygon points="{polygon(p["shape"])}" fill="#b78f47" stroke="#fff" stroke-width=".2"/>')
        for v in self.vias:
            x, y = point(v["center"])
            lines.append(f'<circle cx="{x}" cy="{y}" r="{v["diameter"]*scale/2}" fill="#557477"/>')
        for h in self.holes:
            x, y = point(h["center"])
            lines.append(f'<circle cx="{x}" cy="{y}" r="{h["diameter"]*scale/2}" fill="white" stroke="#557477"/>')
        for c in self.components:
            if not c["reference"].startswith("U"):
                continue
            x, y = point(c["center_mm"])
            lines.append(f'<text x="{x}" y="{y}" text-anchor="middle" font-size="12"'
                         f' stroke="white" stroke-width="3" paint-order="stroke">{escape(c["reference"])}</text>')
            pad = self.pad(c["reference"], 1)
            x, y = point(pad["center"])
            lines.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#dd3838"/>')
        lines.append(f'<text x="30" y="{height-15}" font-size="13">Red dot = pin 1. '
                     'F.Cu red · B.Cu blue · inner copper orange/purple. Ground fills omitted.</text></g></svg>')
        path.write_text("\n".join(lines) + "\n")
