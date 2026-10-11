"""Shared K1 contact footprints derived from the preserved ENPIRE/R1 surfaces."""

import json
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon, box

from f1_surfaces import Surface

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "engineering/designs/capacitive_k1.json"


def load():
    cfg = json.loads(CONFIG.read_text())
    r1 = json.loads((ROOT / cfg["basis"]["r1_manifest"]).read_text())
    nail = json.loads((ROOT / cfg["basis"]["nail_coordinates"]).read_text())
    surfaces = [Surface(site, r1, nail, cfg) for site in range(6)]
    for surface in surfaces[2:]:
        surface.active = surface.body.buffer(-cfg["body"]["tpu_active_inset_mm"], join_style="mitre")
    return cfg, surfaces


def reference_footprints(cfg):
    active_x, active_y = cfg["body"]["reference_active_size_mm"]
    outer_x, outer_y = cfg["body"]["reference_outer_size_mm"]
    return box(-outer_x/2, 0, outer_x/2, outer_y), box(-active_x/2, (outer_y-active_y)/2,
                                                               active_x/2, (outer_y+active_y)/2)


def offsets(site, cfg):
    b, f, d = cfg["body"], cfg["flex"], cfg["dielectric"]
    mount = b["nail_mounting_mm"] if site < 2 else b["tpu_mounting_mm"]
    saddle = 0 if site < 2 else b["tpu_rigid_saddle_mm"]
    bottom = mount+saddle
    flex_top = bottom+2*f["copper_each_mm"]+f["polyimide_core_mm"]+2*f["coverlay_each_mm"]
    plate_bottom = flex_top+d["base_mm"]+d["post_height_mm"]
    plate_top = plate_bottom+b["spreader_thickness_mm"]
    return {"mount": mount, "flex_bottom": bottom,
            "shield_center": bottom+f["coverlay_each_mm"]+f["copper_each_mm"]/2,
            "flex_top": flex_top, "post_base_middle": flex_top+d["base_mm"]/2,
            "plate_bottom": plate_bottom, "plate_top": plate_top,
            "cover_top": plate_top+(b["nail_cover_mm"] if site < 2 else b["tpu_cover_mm"])}


def unrolled(polygon, surface, offset):
    arc = surface.offset_arc(offset)
    def ring(coordinates):
        return [(x, float(np.interp(y, surface.s, arc))) for x, y in coordinates]
    return Polygon(ring(polygon.exterior.coords), [ring(r.coords) for r in polygon.interiors])


def formed_vertices(vertices, surface, offset, neutral_offset):
    """Form a flat reference mesh using the base mid-plane developed coordinate."""
    values = np.asarray(vertices)
    arc = surface.offset_arc(neutral_offset)
    s = np.interp(values[:, 1], arc, surface.s)
    points, _, normal = surface.frame(s)
    direction = surface.u if surface.kind == "nail" else np.array([1., 0., 0.])
    return points+values[:, 0, None]*direction+(offset+values[:, 2, None])*normal


def posts(active, cfg):
    d = cfg["dielectric"]
    radius, pitch = d["post_diameter_mm"]/2, d["post_pitch_mm"]
    allowed = active.buffer(-radius-d["post_edge_clearance_mm"])
    x0, y0, x1, y1 = allowed.bounds
    result = [[float(x), float(y)] for x in np.arange(np.ceil(x0/pitch)*pitch, x1+1e-9, pitch)
              for y in np.arange(np.ceil(y0/pitch)*pitch, y1+1e-9, pitch)
              if allowed.covers(Point(float(x), float(y)))]
    if len(result) < 4:
        raise ValueError("Too few complete supports in this contact footprint")
    return result
