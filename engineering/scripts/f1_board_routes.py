"""Two-face geometry adapter for the checked F1 native KiCad placements.

This imports the frozen prototype router without changing older releases.
Native pad rectangles are conservative routing obstacles for rounded lands;
final copper acceptance belongs to KiCad's independent DRC.
"""

import math
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box

from prototype_pcb import Board, LAYERS
from prototype_route import Router


class NativeBoardGeometry(Board):
    def __init__(self, data):
        super().__init__(data["name"], Polygon(data["outline_xy_mm"]),
                        data["thickness_mm"], data["clearance_mm"], data["edge_mm"])
        self.components = data["parts"]
        for data_pad in data["pads"]:
            pad = dict(data_pad)
            w, h = pad["size"]
            shape = affinity.rotate(box(-w/2, -h/2, w/2, h/2),
                                    -pad["rotation"], origin=(0, 0))
            pad["shape"] = affinity.translate(shape, *pad["center"])
            self.pads.append(pad)
            self.net(pad["net"])
        for hole in data["holes"]:
            self.add_hole(hole["center_mm"], hole["diameter_mm"],
                          hole["copper_keepout_diameter_mm"])

    def copper(self, layer):
        result = [(p["net"], p["shape"]) for p in self.pads if layer in p["layers"]]
        result += [(t["net"], t["shape"]) for t in self.tracks if t["layer"] == layer]
        result += [(v["net"], v["shape"]) for v in self.vias]
        return result

    def payload(self):
        return {
            "tracks": [{k: v for k, v in t.items() if k != "shape"} for t in self.tracks],
            "vias": [{k: v for k, v in t.items() if k != "shape"} for t in self.vias],
            "zones": [{"net": z["net"], "layer": z["layer"],
                       "outline_xy_mm": list(z["shape"].exterior.coords)} for z in self.zones]
        }


class TwoFaceRouter(Router):
    def obstacles(self, net):
        free, via_free, inside, forbidden = super().obstacles(net)
        # Same-net copper may merge, but drilled holes may not. The first
        # routed board exposed an overlapping same-net via pair because the
        # shared prototype router excludes that net from copper obstacles.
        for via in self.board.vias:
            separation = via["drill"]/2 + self.via_drill/2 + .25 + self.guard
            via_free &= ~self.mask(Point(via["center"]).buffer(separation))
        return free, via_free, inside, forbidden

    def endpoint_layers(self, net, point):
        if any(v["net"] == net and math.dist(v["center"], point) < 1e-5 for v in self.board.vias):
            return range(len(self.signal_layers))
        matches = [p for p in self.board.pads
                   if p["net"] == net and math.dist(p["center"], point) < 1e-5]
        if matches:
            return tuple(i for i, layer in enumerate(self.signal_layers)
                         if any(layer in p["layers"] for p in matches))
        matches = [t for t in self.board.tracks if t["net"] == net and (
            math.dist(t["start"], point) < 1e-5 or math.dist(t["end"], point) < 1e-5)]
        if matches:
            return tuple(i for i, layer in enumerate(self.signal_layers)
                         if any(layer == t["layer"] for t in matches))
        raise ValueError(f"Endpoint has no native pad, via or routed trace: {net} at {point}")

    def escape(self, pad):
        """Reserve a non-paste via from either populated face."""
        net = pad["net"]
        free, via_free, inside, forbidden = self.obstacles(net)
        center = pad["center"]
        ix = round((center[0]-self.x0)/self.grid)
        iy = round((center[1]-self.y0)/self.grid)
        candidates = []
        radius = round(3.5/self.grid)
        for layer in self.endpoint_layers(net, center):
            name = self.signal_layers[layer]
            for yy in range(max(0, iy-radius), min(self.ny, iy+radius+1)):
                for xx in range(max(0, ix-radius), min(self.nx, ix+radius+1)):
                    if not via_free[yy, xx] or not free[layer, yy, xx]:
                        continue
                    point = self.coordinate(xx, yy)
                    line = LineString([center, point])
                    if inside.covers(line) and not forbidden[name].intersects(line):
                        candidates.append((math.dist(center, point), layer, point))
        if not candidates:
            raise ValueError(f"No via escape for {pad['reference']}.{pad['pad']} ({net})")
        _, layer, point = min(candidates)
        self.board.trace(net, [center, point], self.signal_layers[layer], self.width)
        self.board.via(net, point, self.via_diameter, self.via_drill)
        return point

    def direct(self, net, start, end, layer, width):
        before = self.width
        self.width = width
        inside, forbidden = self.geometry(net, width/2)
        line = LineString([start, end])
        if not inside.covers(line) or forbidden[layer].intersects(line):
            raise ValueError(f"Direct pickoff blocked: {net}")
        self.board.trace(net, [start, end], layer, width)
        self.width = before
