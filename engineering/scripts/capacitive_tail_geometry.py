"""Length-preserving K1 nail-tail bends, separate from the flat copper artwork."""

import math
from pathlib import Path

import cadquery as cq
import numpy as np
from scipy.optimize import brentq
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from build_f1_stack_parts import slab

ROOT = Path(__file__).resolve().parents[2]
POSES = ROOT / "engineering/designs/capacitive_tail_poses.json"


def bend_parameters(poses):
    length, lift = poses["nail_free_bend_length_mm"], poses["nail_terminal_lift_normal_mm"]
    if lift == 0:
        return 0., math.inf
    angle = brentq(lambda a: length*(1-math.cos(a))/a-lift, 1e-6, math.pi/3)
    radius = length/(2*angle)
    if radius < poses["minimum_nail_bend_radius_mm"]:
        raise ValueError("Nail bend is tighter than the declared radius")
    return angle, radius


def nail_path(distance, poses):
    length, lift = poses["nail_free_bend_length_mm"], poses["nail_terminal_lift_normal_mm"]
    if lift == 0:
        return distance, 0., 0.
    angle, radius = bend_parameters(poses)
    if distance <= length/2:
        phi = distance/radius
        return radius*math.sin(phi), radius*(1-math.cos(phi)), phi
    if distance <= length:
        phi = angle-(distance-length/2)/radius
        return 2*radius*math.sin(angle)-radius*math.sin(phi), radius*(1+math.cos(phi)-2*math.cos(angle)), phi
    return 2*radius*math.sin(angle)+(distance-length), lift, 0.


def nail_slab(surface, polygon, inner, outer, neutral, poses, join):
    def material(shape):
        # A split exactly at the T-junction also returns shared boundary
        # lines. They have zero area and create no material extrusion.
        if shape.geom_type == "Polygon":
            return shape
        pieces = [p for p in shape.geoms if p.geom_type == "Polygon" and p.area > 0]
        result = unary_union(pieces) if pieces else Polygon()
        if abs(result.area-shape.area) > 1e-9 or not result.is_empty and result.geom_type != "Polygon":
            raise ValueError("Nail split would alter or disconnect real material")
        return result
    fixed = material(polygon.intersection(box(-1000, -1000, 1000, join)))
    moving = material(polygon.intersection(box(-1000, join, 1000, 1000)))
    solids = []
    if fixed.area > 1e-8:
        solids.append(slab(surface, fixed, inner, outer))
    if moving.area > 1e-8:
        x0, s0, x1, s1 = moving.bounds
        if moving.symmetric_difference(box(x0, s0, x1, s1)).area > 1e-8:
            raise ValueError("The formed nail tail needs a constant-width section")
        length = poses["nail_free_bend_length_mm"]
        raw = np.unique(np.r_[s0, s1, np.arange(s0, s1, poses["curve_sample_mm"]),
                              *[join+v for v in (length/2, length) if s0 < join+v < s1]])
        samples = [raw[0]]
        for value in raw[1:]:
            if value-samples[-1] > 1e-6:
                samples.append(value)
        def boundary(offset):
            result = []
            for s in samples:
                along, height, angle = nail_path(s-join, poses)
                delta = offset-neutral
                result.append([join+along-delta*math.sin(angle),
                               neutral+height+delta*math.cos(angle)])
            return result
        profile = Polygon(boundary(inner)+boundary(outer)[::-1])
        if not profile.is_valid:
            raise ValueError("Invalid formed nail-tail section")
        plane = cq.Plane(origin=tuple(surface.origin+x1*surface.u),
                         xDir=tuple(surface.t), normal=tuple(-surface.u))
        solids.append(cq.Workplane(plane).polyline(list(profile.exterior.coords)[:-1]).close().extrude(x1-x0).val())
    if not solids:
        raise ValueError("Empty formed nail part")
    return solids[0].fuse(*solids[1:]).clean() if len(solids) > 1 else solids[0]
