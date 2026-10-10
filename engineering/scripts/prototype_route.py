"""Deterministic, bounded grid routing for prototype boards.

It respects explicit copper/edge obstacles and leaves manufacturing acceptance
to KiCad's independent geometry/connectivity check. No hidden DRC exclusions.
"""

from __future__ import annotations

import heapq
import math
import time

import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from prototype_pcb import LAYERS


class Router:
    def __init__(self, board, grid=.1, width=.15, via_diameter=.45, via_drill=.2):
        self.board = board
        self.grid = grid
        self.width = width
        self.via_diameter = via_diameter
        self.via_drill = via_drill
        lo_x, lo_y, hi_x, hi_y = board.outline.bounds
        self.x0 = math.floor((lo_x-1)/grid)*grid
        self.y0 = math.floor((lo_y-1)/grid)*grid
        self.nx = math.ceil((hi_x+1-self.x0)/grid)+1
        self.ny = math.ceil((hi_y+1-self.y0)/grid)+1
        self.xx, self.yy = np.meshgrid(self.x0+np.arange(self.nx)*grid,
                                      self.y0+np.arange(self.ny)*grid)
        self.routed = []
        self.signal_layers = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
        self.layer_cost = (1,8,1,1)  # In1 is predominantly ground; short crossovers cost extra.
        self.guard = .018

    def mask(self, shape):
        return shapely.contains_xy(shape, self.xx, self.yy)

    def geometry(self, net, radius):
        b = self.board
        inside = b.outline.buffer(-b.edge-radius-self.guard)
        layer_forbidden = {}
        for layer in LAYERS:
            shapes = [shape for other, shape in b.copper(layer) if other != net]
            shapes.extend(b.keepouts)
            forbidden = unary_union(shapes).buffer(b.clearance+radius+self.guard)
            layer_forbidden[layer] = forbidden
        return inside, layer_forbidden

    def obstacles(self, net):
        inside, forbidden = self.geometry(net, self.width/2)
        within = self.mask(inside)
        free = np.array([within & ~self.mask(forbidden[layer]) for layer in self.signal_layers])
        v_inside, v_forbidden = self.geometry(net, self.via_diameter/2)
        # Newly placed vias stay out of all paste-covered pads. Existing B1
        # exposed-pad vias are separately retained and explicitly documented.
        paste = unary_union([p["shape"] for p in self.board.pads if p["paste"]])
        paste = paste.buffer(self.via_diameter/2+.10)
        via_obstacles = unary_union([*v_forbidden.values(), paste])
        via_free = self.mask(v_inside) & ~self.mask(via_obstacles)
        return free, via_free, inside, forbidden

    def coordinate(self, ix, iy):
        return (self.x0+ix*self.grid, self.y0+iy*self.grid)

    def snap(self, point, free, inside, forbidden, layer=0):
        x, y = point
        ix = round((x-self.x0)/self.grid)
        iy = round((y-self.y0)/self.grid)
        candidates = []
        for ox in range(-6, 7):
            for oy in range(-6, 7):
                xx, yy = ix+ox, iy+oy
                if not 0 <= xx < self.nx or not 0 <= yy < self.ny or not free[layer, yy, xx]:
                    continue
                p = self.coordinate(xx, yy)
                line = LineString([point, p])
                if inside.covers(line) and not forbidden[self.signal_layers[layer]].intersects(line):
                    candidates.append((math.dist(point, p), xx, yy))
        if not candidates:
            raise ValueError(f"No clear route escape for point {point}")
        _, ix, iy = min(candidates)
        return ix, iy

    def endpoint_layers(self, net, point):
        if any(v["net"]==net and math.dist(v["center"],point)<1e-5 for v in self.board.vias):
            return range(len(self.signal_layers))
        if any(p["net"]==net and p.get("drill") and math.dist(p["center"],point)<1e-5 for p in self.board.pads):
            return range(len(self.signal_layers))
        return (0,)

    def escape(self, pad):
        """Give a small SMD pad a reserved, non-paste via before long routing."""
        net = pad["net"]
        free, via_free, inside, forbidden = self.obstacles(net)
        center = pad["center"]
        ix = round((center[0]-self.x0)/self.grid)
        iy = round((center[1]-self.y0)/self.grid)
        candidates = []
        r = round(2.8/self.grid)
        for yy in range(max(0, iy-r), min(self.ny, iy+r+1)):
            for xx in range(max(0, ix-r), min(self.nx, ix+r+1)):
                if not via_free[yy, xx] or not free[0, yy, xx]:
                    continue
                p = self.coordinate(xx, yy)
                line = LineString([center, p])
                if inside.covers(line) and not forbidden["F.Cu"].intersects(line):
                    candidates.append((math.dist(center, p), p))
        if not candidates:
            raise ValueError(f"No via escape for {pad['reference']}.{pad['pad']} ({net})")
        _, target = min(candidates)
        self.board.trace(net, [center, target], width=self.width)
        self.board.via(net, target, self.via_diameter, self.via_drill)
        return target

    def ground(self, pads):
        """Fan each new ground pad to the In1.Cu ground pour."""
        for pad in pads:
            self.escape(pad)

    def connect(self, net, start, end, time_limit_s=40):
        started = time.monotonic()
        free, via_free, inside, forbidden = self.obstacles(net)
        size = self.nx*self.ny
        def index(layer, x, y):
            return layer*size+y*self.nx+x
        def unpack(n):
            layer, rem = divmod(n, size)
            y, x = divmod(rem, self.nx)
            return layer, x, y
        def nodes(point):
            result = []
            for layer in self.endpoint_layers(net,point):
                try:
                    x,y = self.snap(point,free,inside,forbidden,layer)
                except ValueError:
                    continue
                result.append((layer,x,y))
            if not result:
                raise ValueError(f"No layer escape for {net} at {point}")
            return result
        starts, targets = nodes(start), nodes(end)
        target_ids = {index(*node) for node in targets}
        def heuristic(layer, x, y):
            values = []
            for tl,tx,ty in targets:
                dx, dy = abs(x-tx), abs(y-ty)
                values.append(max(dx,dy)+.41421321337*min(dx,dy)+(20 if layer != tl else 0))
            return min(values)
        best = np.full(len(self.signal_layers)*size, np.inf, dtype=np.float64)
        previous = np.full(len(self.signal_layers)*size, -1, dtype=np.int32)
        queue = []
        for layer,sx,sy in starts:
            source = index(layer,sx,sy)
            cost = math.dist(start,self.coordinate(sx,sy))/self.grid
            best[source] = cost
            heapq.heappush(queue,(cost+heuristic(layer,sx,sy),cost,source))
        steps = [(1,0,1),(-1,0,1),(0,1,1),(0,-1,1),
                 (1,1,math.sqrt(2)),(1,-1,math.sqrt(2)),
                 (-1,1,math.sqrt(2)),(-1,-1,math.sqrt(2))]
        visited = 0
        while queue:
            _, cost, current = heapq.heappop(queue)
            if cost > best[current]+1e-8:
                continue
            if current in target_ids:
                target = current
                break
            visited += 1
            if visited % 4096 == 0 and time.monotonic()-started > time_limit_s:
                raise TimeoutError(f"Route search exceeded {time_limit_s}s for {net}")
            layer, x, y = unpack(current)
            for dx, dy, weight in steps:
                nx, ny = x+dx, y+dy
                if not 0 <= nx < self.nx or not 0 <= ny < self.ny or not free[layer, ny, nx]:
                    continue
                if dx and dy and (not free[layer, y, nx] or not free[layer, ny, x]):
                    continue
                new = index(layer, nx, ny)
                candidate = cost+weight*self.layer_cost[layer]
                if candidate+1e-8 < best[new]:
                    best[new] = candidate
                    previous[new] = current
                    heapq.heappush(queue, (candidate+heuristic(layer,nx,ny), candidate, new))
            if via_free[y, x]:
                for other in range(len(self.signal_layers)):
                    if other == layer or not free[other, y, x]:
                        continue
                    new = index(other, x, y)
                    candidate = cost+20
                    if candidate+1e-8 < best[new]:
                        best[new] = candidate
                        previous[new] = current
                        heapq.heappush(queue, (candidate+heuristic(other,x,y), candidate, new))
        else:
            self.last_failure = {"free":free,"via_free":via_free,
                                 "reached":np.isfinite(best).reshape(len(self.signal_layers),self.ny,self.nx),
                                 "origin":[self.x0,self.y0],"grid":self.grid,
                                 "start":start,"end":end,"net":net}
            raise ValueError(f"No route for {net}: {start} -> {end}; {visited} grid nodes")
        route = []
        current = target
        while current != -1:
            layer, x, y = unpack(current)
            route.append((layer, self.coordinate(x,y)))
            current = previous[current]
        route.reverse()
        self.board.trace(net, [start, route[0][1]], self.signal_layers[route[0][0]], self.width)
        # Compress only collinear runs. Avoid smoothing across unverified space.
        points = [route[0][1]]
        active_layer = route[0][0]
        direction = None
        vias_before = len(self.board.vias)
        for layer, p in route[1:]:
            if layer != active_layer:
                self.board.trace(net, points, self.signal_layers[active_layer], self.width)
                self.board.via(net, p, self.via_diameter, self.via_drill)
                active_layer = layer
                points = [p]
                direction = None
                continue
            last = points[-1]
            d = (round((p[0]-last[0])/self.grid), round((p[1]-last[1])/self.grid))
            if len(points)>1 and d == direction:
                points[-1] = p
            else:
                points.append(p)
                direction = d
        self.board.trace(net, points, self.signal_layers[active_layer], self.width)
        self.board.trace(net, [route[-1][1], end], self.signal_layers[route[-1][0]], self.width)
        self.routed.append({"net": net, "start": start, "end": end, "grid_nodes": visited,
                            "added_vias": len(self.board.vias)-vias_before,
                            "elapsed_s": round(time.monotonic()-started,3)})

    def tree(self, net, endpoints):
        """Connect explicit preconnected endpoint groups using a geometric MST."""
        if not endpoints:
            return
        connected = [endpoints[0]]
        remaining = list(endpoints[1:])
        while remaining:
            _, old, i = min((math.dist(a,b), a, i)
                            for a in connected for i,b in enumerate(remaining))
            new = remaining.pop(i)
            self.connect(net, old, new)
            connected.append(new)
