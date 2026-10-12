"""F1 resistor networks from routed PCB centre lines, vias and idealized pads."""

import itertools
import math

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Point, box

LAYERS = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")


def intersection_points(shape):
    if shape.is_empty:
        return []
    if shape.geom_type == "Point":
        return [shape.coords[0]]
    if shape.geom_type in ("LineString", "LinearRing"):
        return [shape.coords[0], shape.coords[-1]]
    return [point for piece in shape.geoms for point in intersection_points(piece)]


class CopperNetwork:
    """A declared 1D metal model; this does not solve 2D pad/junction spreading."""

    def __init__(self, board, net, rho, thickness_mm, width_factor, via_wall_mm, via_length_mm):
        self.net = net
        self.keys, self.locations, parent = {}, [], []

        def node(layer, point):
            key = (layer, round(float(point[0]), 6), round(float(point[1]), 6))
            if key not in self.keys:
                self.keys[key] = len(parent); parent.append(len(parent))
                self.locations.append(key)
            return self.keys[key]

        def root(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def join(a, b):
            a, b = root(a), root(b)
            if a != b:
                parent[b] = a

        tracks = []
        for entry in board["tracks"]:
            if entry["net"] != net:
                continue
            line = LineString([entry["start"], entry["end"]])
            if line.length < 1e-8:
                continue
            tracks.append({"line": line, "width": entry["width"], "layer": entry["layer"],
                           "points": [tuple(entry["start"]), tuple(entry["end"])]})
        if not tracks:
            raise ValueError("No routed tracks for "+net)
        pads = []
        for entry in board["pads"]:
            if entry["net"] != net:
                continue
            x, y = entry["center"]; w, h = entry["size"]
            shape = affinity.rotate(box(x-w/2, y-h/2, x+w/2, y+h/2), -entry["rotation"], origin=(x, y))
            pads.append({"entry": entry, "shape": shape})
        vias = [v for v in board["vias"] if v["net"] == net]
        # Split at centre-line junctions and at pad boundaries. Collinear
        # overlaps become the same edge and use the wider conductor once.
        for first, second in itertools.combinations(tracks, 2):
            if first["layer"] != second["layer"]:
                continue
            points = intersection_points(first["line"].intersection(second["line"]))
            first["points"].extend(points); second["points"].extend(points)
        for track in tracks:
            for pad in pads:
                if track["layer"] in pad["entry"]["layers"]:
                    track["points"].extend(intersection_points(track["line"].intersection(pad["shape"])))
            for via in vias:
                point = Point(via["center"])
                if track["line"].distance(point) < 2e-6:
                    track["points"].append(tuple(via["center"]))
            for point in track["points"]:
                node(track["layer"], point)
        pad_nodes = {}
        for pad in pads:
            entry = pad["entry"]
            ids = [node(layer, entry["center"]) for layer in entry["layers"] if layer in LAYERS]
            if not ids:
                raise ValueError("Signal pad has no copper layer")
            for index in ids[1:]:
                join(ids[0], index)
            for index, (layer, x, y) in enumerate(self.locations):
                if layer in entry["layers"] and pad["shape"].distance(Point(x, y)) <= 2e-6:
                    join(ids[0], index)
            pad_nodes[(entry["reference"], entry["pad"])] = ids[0]
        via_ids = []
        for via in vias:
            ids = [node(layer, via["center"]) for layer in LAYERS]
            hub = node("via_hub", via["center"])
            via_ids.append((via, ids, hub))
        raw_edges = {}
        for track in tracks:
            points = sorted({node(track["layer"], p) for p in track["points"]},
                            key=lambda i: track["line"].project(Point(self.locations[i][1:])))
            for a, b in zip(points, points[1:]):
                length = math.dist(self.locations[a][1:], self.locations[b][1:])
                if length < 1e-7:
                    join(a, b); continue
                resistance = rho*length/(track["width"]*width_factor*thickness_mm)
                key = tuple(sorted((a, b)))
                raw_edges[key] = min(raw_edges.get(key, math.inf), resistance)
        for via, ids, hub in via_ids:
            # A star gives one full-barrel resistance between any two
            # layers without inventing parallel copies of the barrel.
            # Internal-layer Z is not supplied; this is an explicit pair
            # approximation, not an exact multi-terminal barrel model.
            resistance = rho*via_length_mm/(math.pi*via["drill"]*via_wall_mm)
            for terminal in ids:
                raw_edges[tuple(sorted((terminal, hub)))] = resistance/2
        roots = sorted({root(i) for i in range(len(parent))})
        mapping = {key: index for index, key in enumerate(roots)}
        self.pads = {name: mapping[root(index)] for name, index in pad_nodes.items()}
        self.node_positions = [self.locations[key] for key in roots]
        self.matrix = np.zeros((len(roots), len(roots)))
        self.edges = []
        for (a, b), resistance in raw_edges.items():
            a, b = mapping[root(a)], mapping[root(b)]
            if a == b:
                continue
            conductance = 1/resistance
            self.matrix[a, a] += conductance; self.matrix[b, b] += conductance
            self.matrix[a, b] -= conductance; self.matrix[b, a] -= conductance
            self.edges.append((a, b, resistance))
        self.track_count, self.via_count = len(tracks), len(vias)
        self._check_connected()

    def _check_connected(self):
        adjacent = [set() for _ in self.matrix]
        for a, b, _ in self.edges:
            adjacent[a].add(b); adjacent[b].add(a)
        seen = set()
        components = []
        for start in range(len(adjacent)):
            if start in seen:
                continue
            stack, component = [start], set()
            while stack:
                node = stack.pop()
                if node in component:
                    continue
                component.add(node); stack.extend(adjacent[node]-component)
            seen.update(component); components.append(component)
        if len(components) != 1:
            pad_groups = [[f"{ref}.{pin}" for (ref, pin), node in self.pads.items() if node in group]
                          for group in components]
            raise ValueError(f"{self.net}: centre-line model has {len(components)} components; pad groups={pad_groups}")

    def reduce(self, ports):
        """Kron-reduce internal metal nodes, keeping named physical pad ports."""
        indices = [self.pads[tuple(port)] for port in ports]
        if len(set(indices)) != len(indices):
            raise ValueError(self.net+": requested ports are already the same ideal pad")
        keep = np.asarray(indices)
        internal = np.asarray([i for i in range(len(self.matrix)) if i not in indices], dtype=int)
        result = self.matrix[np.ix_(keep, keep)].copy()
        if len(internal):
            result -= self.matrix[np.ix_(keep, internal)] @ np.linalg.solve(
                self.matrix[np.ix_(internal, internal)], self.matrix[np.ix_(internal, keep)])
        asymmetry = float(np.max(np.abs(result-result.T)))
        scale = max(float(np.max(np.abs(result))), 1)
        if asymmetry > scale*1e-9 or np.max(np.abs(result.sum(axis=1))) > scale*1e-9:
            raise ValueError("Metal network reduction failed reciprocity/current balance")
        # Remove only floating-point asymmetry and row-sum roundoff.
        result = (result+result.T)/2
        np.fill_diagonal(result, 0)
        np.fill_diagonal(result, -result.sum(axis=1))
        return result


def effective_resistance(matrix, a, b):
    keep = [i for i in range(len(matrix)) if i != b]
    rhs = np.zeros(len(keep)); rhs[keep.index(a)] = 1.
    values = np.linalg.solve(matrix[np.ix_(keep, keep)], rhs)
    resistance = float(values[keep.index(a)])
    if not math.isfinite(resistance) or resistance <= 0:
        raise ValueError("Invalid terminal resistance")
    return resistance
