"""K1 normal-offset mechanical parts in the common source surface chart."""

from pathlib import Path
import math

import cadquery as cq
import numpy as np
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from build_f1_stack_parts import slab
from prototype_cad import yz_prism

ROOT = Path(__file__).resolve().parents[2]
MECHANICS = ROOT / "engineering/designs/capacitive_cell_mechanics.json"


def polygons(shape):
    if shape.is_empty:
        return []
    if shape.geom_type == "Polygon":
        return [shape]
    result = []
    for item in shape.geoms:
        if item.geom_type in ("Polygon", "MultiPolygon", "GeometryCollection"):
            result.extend(polygons(item))
    if abs(sum(p.area for p in result)-shape.area) > 1e-8:
        raise ValueError("Polygon extraction changed material area")
    return result


def remove_duplicate_vertices(shape, tolerance=1e-6):
    """Drop only sub-tolerance consecutive vertices; do not move shared edges."""
    def ring(points):
        kept = []
        for point in list(points)[:-1]:
            if not kept or math.dist(point, kept[-1]) > tolerance:
                kept.append(point)
        if len(kept) > 1 and math.dist(kept[0], kept[-1]) <= tolerance:
            kept.pop()
        if len(kept) < 3:
            raise ValueError("Numerical cleanup would erase a material boundary")
        return kept
    cleaned = []
    for piece in polygons(shape):
        candidate = Polygon(ring(piece.exterior.coords), [ring(r.coords) for r in piece.interiors])
        if not candidate.is_valid or piece.symmetric_difference(candidate).area > tolerance*piece.length:
            raise ValueError("Vertex cleanup changes physical material")
        cleaned.append(candidate)
    return unary_union(cleaned)


def common_samples(surface, domains):
    values = [float(y) for p in domains for ring in (p.exterior, *p.interiors) for _, y in ring.coords]
    combined = sorted(set([*surface.s, *values]))
    result = [combined[0]]
    for value in combined[1:]:
        if value-result[-1] > 1e-5:
            result.append(value)
    return np.asarray(result)


def rectangular_strips(polygon):
    """Decompose an axis-aligned chart domain without changing its boundary."""
    breaks = sorted({x for ring in (polygon.exterior, *polygon.interiors) for x, _ in ring.coords})
    rectangles = []
    for x0, x1 in zip(breaks, breaks[1:]):
        if x1-x0 < 1e-6:
            continue
        section = polygon.intersection(LineString([[(x0+x1)/2, -1000], [(x0+x1)/2, 1000]]))
        lines = [section] if section.geom_type == "LineString" else list(section.geoms)
        for line in lines:
            if line.geom_type != "LineString" or line.length < 1e-6:
                continue
            _, s0, _, s1 = line.bounds
            rectangles.append(box(x0, s0, x1, s1))
    return rectangles


def chart_slab(surface, polygon, inner, outer, samples):
    if surface.kind == "nail":
        return slab(surface, polygon, inner, outer)
    rectangles = rectangular_strips(polygon)
    reconstructed = unary_union(rectangles)
    difference = polygon.symmetric_difference(reconstructed).area
    boundary_distance = polygon.boundary.hausdorff_distance(reconstructed.boundary)
    # Offset/intersection roundoff can leave sub-nanometre slopes. Accept
    # only a bounded boundary displacement, never an arbitrary area loss.
    if not rectangles or difference > 1e-6*polygon.length or boundary_distance > 1e-6:
        raise ValueError(f"Curved mechanical domain differs from rectangular strips by {difference:.12g} mm²; "
                         f"boundary={boundary_distance:.12g} mm, bounds={polygon.bounds}")
    shapes = []
    for rectangle in rectangles:
        x0, s0, x1, s1 = rectangle.bounds
        if s0 < -1e-8 or s1 > surface.length+1e-8:
            raise ValueError("Mechanical part leaves the defined curved surface")
        grid = np.r_[s0, samples[(samples > s0+1e-5) & (samples < s1-1e-5)], s1]
        low = surface.points(np.zeros(len(grid)), grid, inner)[:, 1:]
        high = surface.points(np.zeros(len(grid)), grid, outer)[:, 1:]
        profile = Polygon(np.vstack((low, high[::-1])))
        if not profile.is_valid or profile.area <= 0:
            raise ValueError("Invalid mechanical offset profile")
        shapes.append(yz_prism(profile, -7.5+x0, x1-x0))
    return shapes[0].fuse(*shapes[1:]).clean() if len(shapes) > 1 else shapes[0]


def shape_for(surface, domain, inner, outer, samples):
    parts = [chart_slab(surface, polygon, inner, outer, samples) for polygon in polygons(domain)]
    if not parts:
        raise ValueError("No material in this mechanical domain")
    return parts[0].fuse(*parts[1:]).clean() if len(parts) > 1 else parts[0]
