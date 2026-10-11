"""Individual F1 reference surfaces on the retained ENPIRE/R1 geometry."""

import json
from pathlib import Path

import numpy as np
from scipy.interpolate import CubicSpline
from scipy.integrate import cumulative_simpson
from shapely import affinity
from shapely.geometry import Polygon, box

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "engineering/designs/f1_formed_stack.json"


class Surface:
    def __init__(self, site, r1, nail, config):
        self.site = site
        self.config = config
        self.kind = "nail" if site < 2 else "tpu"
        if self.kind == "nail":
            entry = r1["nail_active_cells"][site]
            outer = Polygon(entry["outer"])
            low, top = outer.bounds[1], outer.bounds[3]
            section = outer.intersection(box(-100, low+.025, 100, low+.035))
            center_u = (section.bounds[0]+section.bounds[2])/2
            self.body = affinity.affine_transform(outer, [1, 0, 0, -1, -center_u, top])
            self.active = affinity.affine_transform(Polygon(entry["active"]), [1, 0, 0, -1, -center_u, top])
            u = np.asarray(nail["nail_plane_u_axis_native"])
            v = np.asarray(nail["nail_plane_v_axis_native"])
            origin = np.asarray(nail["nail_plane_origin_native_mm"])
            self.origin = origin+center_u*u+top*v
            self.u = u
            self.t = -v
            self.n = np.cross(u, v)
            self.y = np.linspace(0, self.body.bounds[3], max(3, int(self.body.bounds[3]/.025)+1))
            self.s = self.y.copy()
            self.length = float(self.s[-1])
        else:
            entry = r1["pads"][site-2]
            curve = np.asarray(entry["front_curve_native_yz_mm"])
            if np.any(np.diff(curve[:, 0]) <= 0):
                raise ValueError("R1 saddle coordinate must increase toward the root")
            self.spline = CubicSpline(curve[:, 0], curve[:, 1], extrapolate=False)
            self.y = np.linspace(curve[0, 0], curve[-1, 0],
                                 max(3, int((curve[-1, 0]-curve[0, 0])/config["body"]["sample_spacing_mm"])+1))
            slope = self.spline(self.y, 1)
            self.s = cumulative_simpson(np.sqrt(1+slope*slope), x=self.y, initial=0)
            self.length = float(self.s[-1])
            width = config["body"]["tpu_foil_width_mm"]
            trim = config["body"]["tpu_foil_arc_trim_each_end_mm"]
            self.body = box(-width/2, trim, width/2, self.length-trim)
            # Reserve the four side feeds separately from the sensing area.
            bus = 4*.225+3*.225
            self.active = box(-width/2+.6, trim+.6, width/2-.4-bus-.3, self.length-trim-.6)
            self.width = entry["width_mm"]

    def frame(self, s):
        scalar = np.ndim(s) == 0
        s = np.atleast_1d(s).astype(float)
        if np.any(s < -1e-8) or np.any(s > self.length+1e-8):
            raise ValueError("Surface coordinate outside the retained patch")
        if self.kind == "nail":
            p = self.origin+s[:, None]*self.t
            tangent = np.tile(self.t, (len(s), 1))
            normal = np.tile(self.n, (len(s), 1))
        else:
            y = np.interp(s, self.s, self.y)
            z = self.spline(y)
            slope = self.spline(y, 1)
            norm = np.sqrt(1+slope*slope)
            p = np.column_stack((np.full(len(s), -7.5), y, z))
            tangent = np.column_stack((np.zeros(len(s)), 1/norm, slope/norm))
            normal = np.column_stack((np.zeros(len(s)), slope/norm, -1/norm))
        return (p[0], tangent[0], normal[0]) if scalar else (p, tangent, normal)

    def points(self, u, s, offset):
        p, tangent, normal = self.frame(s)
        direction = self.u if self.kind == "nail" else np.array([1., 0., 0.])
        if np.ndim(s) == 0:
            return p+float(u)*direction+offset*normal
        return p+np.asarray(u)[..., None]*direction+offset*normal

    def offset_arc(self, offset):
        points = self.points(np.zeros_like(self.s), self.s, offset)
        return np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]

    def curvature(self):
        if self.kind == "nail":
            return np.zeros_like(self.s)
        slope = self.spline(self.y, 1)
        return self.spline(self.y, 2)/(1+slope*slope)**1.5


def layer_offsets(site, cfg):
    m = cfg["materials_mm"]
    mount = m["nail_mounting_layer"] if site < 2 else m["tpu_mounting_layer"]
    lower_contact = mount+m["polyimide"]+m["copper"]
    upper_contact = lower_contact+m["pressure_film"]
    row_outer = upper_contact+m["copper"]+m["polyimide"]
    if site < 2:
        row_outer += m["copper"]+m["coverlay"]
    return {
        "mount_outer": mount,
        "column_conductor_center": lower_contact-m["copper"]/2,
        "column_contact": lower_contact,
        "film_center": (lower_contact+upper_contact)/2,
        "row_contact": upper_contact,
        "row_conductor_center": upper_contact+m["copper"]/2,
        "row_outer": row_outer,
        "cover_outer": row_outer+(m["nail_outer_cover"] if site < 2 else m["tpu_outer_cover"]),
    }


def load_surfaces(path=CONFIG):
    cfg = json.loads(Path(path).read_text())
    r1 = json.loads((ROOT / cfg["basis"]["r1_manifest"]).read_text())
    nail = json.loads((ROOT / cfg["basis"]["nail_coordinates"]).read_text())
    return cfg, r1, nail, [Surface(site, r1, nail, cfg) for site in range(6)]
