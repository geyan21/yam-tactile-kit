"""
ENPIRE-T: the ENPIRE finger rebuilt as a tactile cartridge for the shared YAM socket.

What stays from ENPIRE (Wenli Xiao, CC BY 4.0): the whole outer shape - the hard nail (flat face,
centre groove, wedge tip), the concave serrated cradle and its lobes, the side rails and back.
What changes:
  cradle   the compliant TPU lattice becomes part of one rigid core. Its front is a smooth seat
           set back by skin + flex, so the sensor never bends; a molded serrated skin restores
           the original surface (same teeth, same outline).
  nail     the cross-slot behind the face plate is filled and the flat face gets a flush pocket
           for the nail pad (U-shaped around the groove). The last 3 mm of the tip stay bare.
  root     the screw-on root block becomes a flange that docks on the v0.2 socket (same dowels,
           thumbscrews, pogo pins, PCB seat), so one socket takes either cartridge.
  flex     one two-sheet sensing laminate runs from the flange, down the cradle seat (strip) and
           onto the nail (pad). Every surface it touches is an extrusion across the finger width
           (or the nail plane), so its flat pattern is exact: no unfolding problem.

Frames: profiles are worked out in native ENPIRE (y, z); 3D parts are in the i2rt gripper frame,
right finger at q = 0 (as yam_tactile_finger.py). Units mm.
Run (from cartridge/):  python3 cad/enpire_finger.py   -> out/enpire/*.stl, *.step, params.json
"""
import json
import os
import sys
import numpy as np
import trimesh
from shapely.geometry import Polygon, LineString, Point, box as sbox
from shapely.ops import unary_union, substring

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enpire_source as ES        # noqa: E402
import yam_tactile_finger as F    # noqa: E402  (socket + dock interface)

OUT = os.path.join(F.OUT, "enpire")
FP = F.P                              # v0.2 / socket parameters (dock interface is shared)

# ----------------------------------------------------------------------------------------------
# Parameters
# ----------------------------------------------------------------------------------------------
P = dict(
    # placement: the socket (10.5) + flange (9.0) replace the stock 11 mm above the cradle
    DZ=-8.5,                     # finger lowered vs a stock ENPIRE mounted on its top rib
    TPU_X=(-15.0, 0.0),          # native x of the cradle slot (between the side rails)
    X_PROFILE=-7.5,              # native x of the profile section (the insert is an exact extrusion)
    OPEN_R=0.8,                  # morphological opening that strips the ~1 mm serration teeth
    # sensing stack on the cradle (object -> core): skin / flex / seat
    SKIN_T=1.5,                  # silicone over the flex on the cradle (teeth come on top)
    FLEX_T=0.45,                 # laminate: 2-layer cols FPC + Velostat + 2-layer rows FPC
    FLEX_CLR=0.05,               # seat / pocket allowance for the laminate
    FILM_T=0.20,                 # PU film over the nail pad, flush with the original nail face (3M 8562: 0.20 mm total)
    SKIN_END_T=0.3,              # skin thickness at its distal feather edge
    SKIN_END_Y=-95.0,            # native y of the skin's distal edge
    RAMP_Y=(-89.5, -95.5),       # native y where the flex climbs from the seat to the nail pocket
    Z_SLOT=6.0,                  # native z where the flex enters the flange (>= 1 mm under the corner)
    TOP_JOIN_Y=-19.5,            # native y where the flex path joins the seat below the top corner (sets the
                                 # flange-exit bend: R 1.8 mm, outside the sensing area)
    SMOOTH_SIGMA=0.3,            # arc-length smoothing of the flex path joins (mm)
    SEAT_R_MIN=3.0,              # no seat corner under the taxels tighter than this
    CLOSE_R=1.5,                 # closing that bridges the scallops left between the teeth
    STRIP_Y=(-19.8, -89.0),      # native y range of the taxel strip on the seat (starts below TOP_JOIN_Y)
    # tongue / skin side walls
    TONGUE_INSET=0.5,            # skin side wall: tongue is 0.5 mm narrower per side than the slot
    SKIN_SIDE_CLR=0.05,          # skin side wall to rail clearance (in front of the seat)
    RELIEF_DEPTH=2.6,            # side walls reach this far behind the seat
    RAIL_CUT=0.4,                # behind the seat the wall slots reach this far into the rails, so a wall can move
                                 # out while its hook rib passes the tongue lip (0.45 mm gap for a 0.25 mm rib)
    HOOK=dict(depth=0.3, d0=1.0, d1=1.9, clr=0.05),   # groove on the tongue sides (depth into the tongue), band behind the seat
    # nail
    NAIL_O=(-7.9068465, -105.2297016, -3.7000801),   # nail plane (native), from the engineering study
    NAIL_N=(0.0, 0.0501249, -0.998743),               # outward normal
    SLOT_FILL=dict(y=(-108.85, -97.25), z=(-2.33, 4.62)),
    TIP_BARE=3.0,                # pad stops this far (in-plane) before the tip edge
    PAD_EDGE=1.0,                # flex edge -> face edge (laminate seal)
    GROOVE_CLR=1.0,              # flex edge -> groove edge (keeps a 0.85 mm lip on the groove)
    POCKET_CLR=0.15,             # pocket outline clearance around the flex
    # flange (dock) - top face is the v0.2 docking face Zs, bottom Zf
    FLANGE_RECTS=[(-22.5, 22.5, 3.0, 25.5), (-15.3, 14.5, 0.72, 31.23)],
    FLANGE_R=1.5,
    PCB=dict(rects=[(-14.5, 14.5, 3.4, 20.3), (-13.0, 13.0, 20.3, 25.1)], recess=0.7, t=0.8),   # 29 x 21.7, notched at the dowels
    CAVITY=dict(inset=0.6, depth=3.4),                                 # bottom-side parts + connectors
    TAIL_SLOT_W=0.9,             # slot (in y) through the flange floor for the two stacked tails
    THUMB_RELIEF=dict(d=10.0, h=5.0),
    # sensor
    PITCH=2.0, ELECTRODE_W=1.4, STRIP_COLS=6,
)
Zs, Zf = F.DERIVED["Zs"], F.DERIVED["Zf"]
SEAT_SET = P["SKIN_T"] + P["FLEX_T"] + P["FLEX_CLR"]          # opened front -> seat
POCKET_D = P["FLEX_T"] + P["FLEX_CLR"] + P["FILM_T"]          # nail face -> pocket floor
NO, NN = np.array(P["NAIL_O"]), np.array(P["NAIL_N"])
NU = np.array([1.0, 0, 0])
NV = np.cross(NN, NU); NV /= np.linalg.norm(NV)                   # in-plane, toward the tip
CZ = -67.61 + P["DZ"]                                             # native y -> gripper z offset
TPU_TOP_Y = -13.77                                               # native y of the cradle top (= Zf)
assert abs(TPU_TOP_Y + CZ - Zf) < 0.01, "flange bottom must sit on the cradle top"


# ----------------------------------------------------------------------------------------------
# frames
# ----------------------------------------------------------------------------------------------
def n2g(pts):
    """native -> gripper (right finger, q = 0)."""
    return ES.to_gripper_pts(pts, P["DZ"])


def g2n(pts):
    return ES.to_native_pts(pts, P["DZ"])


def yz_to_g(y, z, x_n=P["X_PROFILE"]):
    return n2g(np.c_[np.full(np.size(y), x_n), np.atleast_1d(y), np.atleast_1d(z)])


def plane_to_native(u, v, w=0.0):
    u, v, w = np.broadcast_arrays(np.asarray(u, float), np.asarray(v, float), np.asarray(w, float))
    return NO + np.outer(u.ravel(), NU) + np.outer(v.ravel(), NV) + np.outer(w.ravel(), NN)


def native_to_plane(p):
    d = np.atleast_2d(p) - NO
    return np.c_[d @ NU, d @ NV, d @ NN]


def nail_face_z(y):
    """native z of the nail plane at native y (x-independent)."""
    return NO[2] + (NN[1] / -NN[2]) * (np.asarray(y) - NO[1])


# ----------------------------------------------------------------------------------------------
# mesh helpers (all booleans through manifold3d)
# ----------------------------------------------------------------------------------------------
def extrude_yz(poly, xn0, xn1):
    """Native (y, z) polygon extruded over native x in [xn0, xn1] -> gripper-frame mesh."""
    m = trimesh.creation.extrude_polygon(poly, xn1 - xn0)
    M = np.eye(4)
    M[:3, :3] = [[0, 0, -1], [0, 1, 0], [1, 0, 0]]     # (y_n, z_n, h) -> (x, y, z), det +1
    M[:3, 3] = [-xn0 - 7.96, 2.87, CZ]
    m.apply_transform(M)
    return m


def extrude_plane(poly, w0, w1):
    """Nail-plane (u, v) polygon extruded along the plane normal w in [w0, w1] -> gripper mesh."""
    m = trimesh.creation.extrude_polygon(poly, w1 - w0)
    v = m.vertices
    m.vertices = n2g(plane_to_native(v[:, 0], v[:, 1], v[:, 2] + w0))
    if np.linalg.det(np.c_[NU, NV, NN]) < 0:
        m.invert()
    return m


def extrude_xy(poly, z0, z1):
    m = trimesh.creation.extrude_polygon(poly, z1 - z0)
    m.apply_translation((0, 0, z0))
    return m


def gbox(x0, x1, y0, y1, z0, z1):
    b = trimesh.creation.box((x1 - x0, y1 - y0, z1 - z0))
    b.apply_translation(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    return b


def cyl_z(x, y, d, z0, z1, n=64):
    c = trimesh.creation.cylinder(radius=d / 2, height=z1 - z0, sections=n)
    c.apply_translation((x, y, (z0 + z1) / 2))
    return c


def frustum_z(x, y, d0, d1, z0, z1, n=64):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    pts = np.vstack([np.c_[x + d0 / 2 * np.cos(t), y + d0 / 2 * np.sin(t), np.full(n, z0)],
                     np.c_[x + d1 / 2 * np.cos(t), y + d1 / 2 * np.sin(t), np.full(n, z1)]])
    return trimesh.convex.convex_hull(pts)


def union(ms):
    ms = [m for m in ms if m is not None]
    return ms[0] if len(ms) == 1 else trimesh.boolean.union(ms, engine="manifold")


def diff(a, bs):
    bs = [b for b in bs if b is not None]
    return a if not bs else trimesh.boolean.difference([a] + bs, engine="manifold")


def inter(a, b):
    return trimesh.boolean.intersection([a, b], engine="manifold")


def clean(mesh, eps=2e-3):
    """Collapse sub-micron slivers that booleans leave behind, so the mesh stays watertight after
    the float32 round trip through STL."""
    def survives(m):
        t = trimesh.Trimesh(np.asarray(m.vertices, np.float32).astype(float), m.faces, process=True)
        return t.is_watertight and t.is_volume
    if survives(mesh):
        return mesh
    import manifold3d as m3
    mm = m3.Manifold(m3.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                             tri_verts=np.asarray(mesh.faces, np.uint32))).simplify(eps)
    out = mm.to_mesh()
    res = trimesh.Trimesh(np.asarray(out.vert_properties)[:, :3], np.asarray(out.tri_verts), process=True)
    if not survives(res):
        raise RuntimeError("mesh is not watertight after cleaning")
    return res


def rounded(poly, r):
    return poly.buffer(-r, join_style=1).buffer(r, join_style=1) if r > 0 else poly


# ----------------------------------------------------------------------------------------------
# source geometry
# ----------------------------------------------------------------------------------------------
_SRC = {}


def src_native():
    if not _SRC:
        p = ES.paths()
        for k in ("hard", "soft"):
            _SRC[k] = trimesh.load(p[k], force="mesh")
    return _SRC


def section_yz(mesh, x_n):
    sec = mesh.section(plane_origin=[x_n, 0, 0], plane_normal=[1, 0, 0])
    geom = None
    for ent in sec.discrete:
        p = Polygon(ent[:, [1, 2]]).buffer(0)
        geom = p if geom is None else geom.symmetric_difference(p)
    return geom


def lower_envelope(poly, ys):
    out = np.full(len(ys), np.nan)
    for i, y in enumerate(ys):
        seg = poly.intersection(LineString([(y, -60), (y, 60)]))
        if not seg.is_empty:
            out[i] = min(c[1] for g in getattr(seg, "geoms", [seg]) for c in g.coords)
    return out


# ----------------------------------------------------------------------------------------------
# 2D profile (native y, z): outline, seat, flex path, skin outer surface
# ----------------------------------------------------------------------------------------------
def hermite(p0, t0, p1, t1, n=60):
    s = np.linspace(0, 1, n)[:, None]
    h00, h10, h01, h11 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s, -2 * s**3 + 3 * s**2, s**3 - s**2
    L = np.linalg.norm(np.array(p1) - np.array(p0))
    return h00 * p0 + h10 * np.array(t0) * L + h01 * p1 + h11 * np.array(t1) * L


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def resample(pts, step):
    pts = np.asarray(pts, float)
    seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    s = np.arange(0, seg[-1], step)
    s = np.r_[s, seg[-1]] if seg[-1] - s[-1] > 1e-6 else s
    return np.c_[np.interp(s, seg, pts[:, 0]), np.interp(s, seg, pts[:, 1])]


def smooth_polyline(pts, sigma, exact_after_y=None, step=0.05):
    """Arc-length Gaussian smoothing (removes the kinks an offset leaves at tight corners). The end
    points stay exact, and so does everything past native y = exact_after_y (the ramp, a Hermite
    tangent to the seat and to the nail plane, and the straight nail floor), so no crease is left
    where the ramp meets the nail."""
    from scipy.ndimage import gaussian_filter1d
    r = resample(pts, step)
    k = max(1, int(round(sigma / step)))
    sm = np.c_[gaussian_filter1d(r[:, 0], k, mode="nearest"), gaussian_filter1d(r[:, 1], k, mode="nearest")]
    w = np.ones(len(r))
    w[:3 * k] = np.linspace(0, 1, 3 * k)                  # blend back to the exact ends
    w[-3 * k:] = np.minimum(w[-3 * k:], np.linspace(1, 0, 3 * k))
    if exact_after_y is not None:
        i0 = int(np.argmax(r[:, 0] <= exact_after_y))     # first sample past it (top -> tip)
        a = max(0, i0 - 3 * k)
        w[a:i0] = np.minimum(w[a:i0], np.linspace(1, 0, i0 - a))
        w[i0:] = 0.0
    out = r + (sm - r) * w[:, None]
    return LineString(out).simplify(0.002)


def curvature_radius(line, step=0.1):
    r = resample(np.asarray(line.coords), step)
    d1 = np.gradient(r, step, axis=0); d2 = np.gradient(d1, step, axis=0)
    k = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(np.linalg.norm(d1, axis=1) ** 3, 1e-12)
    return r, 1.0 / np.maximum(k, 1e-9)


def curve_at_y(line, y):
    """Point (y, z) of a top->tip polyline at native y (first crossing)."""
    c = np.asarray(line.coords)
    for a, b in zip(c[:-1], c[1:]):
        if (a[0] - y) * (b[0] - y) <= 0 and a[0] != b[0]:
            t = (y - a[0]) / (b[0] - a[0])
            return a + t * (b - a), unit(b - a)
    raise ValueError(f"curve does not reach y={y}")


def build_profile():
    S = src_native()
    raw = section_yz(S["soft"], P["X_PROFILE"])
    tpu = Polygon(max(getattr(raw, "geoms", [raw]), key=lambda g: g.area).exterior)   # filled outline
    r = P["OPEN_R"]
    opened = tpu.buffer(-r, join_style=1).buffer(r, join_style=1)
    ys = np.arange(opened.bounds[2] - 0.02, opened.bounds[0] + 0.02, -0.05)            # top -> tip
    zf = lower_envelope(opened, ys)
    ok = ~np.isnan(zf)
    front = LineString(np.c_[ys[ok], zf[ok]])
    # seat = the opened outline eroded by skin + flex, then opened again so no seat corner is
    # tighter than SEAT_R_MIN (the skin just gets locally thicker over the cradle edges)
    rm, rc = P["SEAT_R_MIN"], P["CLOSE_R"]
    valleys = opened.buffer(rc, join_style=1).buffer(-rc, join_style=1)     # bridge the tooth valleys
    seat_region = valleys.buffer(-SEAT_SET, join_style=1).buffer(-rm, join_style=1).buffer(rm, join_style=1)
    ys2 = ys[(ys <= seat_region.bounds[2] - 0.02) & (ys >= seat_region.bounds[0] + 0.02)]
    zs2 = lower_envelope(seat_region, ys2)
    ok2 = ~np.isnan(zs2)
    seat_full = LineString(np.c_[ys2[ok2], zs2[ok2]])
    raw_front = LineString(np.c_[ys, lower_envelope(tpu, ys)][ok])

    # --- flex path C (laminate bottom), top -> tip ---------------------------------------------
    # top: from the flange slot (heading down the finger axis) into the seat below the rounded
    # top corner, staying >= 1 mm under the original surface so the outer shape is unchanged
    st_all = np.asarray(seat_full.coords)
    p_top, t_top = curve_at_y(LineString(st_all), P["TOP_JOIN_Y"])
    top_seg = hermite(np.array([TPU_TOP_Y, P["Z_SLOT"]]), unit([-1.0, 0.0]), p_top, t_top, 40)
    st = st_all[st_all[:, 0] <= P["TOP_JOIN_Y"]]
    st = np.vstack([p_top, st])
    i_top = 0
    # ramp: seat -> nail pocket floor
    y0, y1 = P["RAMP_Y"]
    pa, ta = curve_at_y(LineString(st[i_top:]), y0)
    zb = nail_face_z(y1) + POCKET_D / -NN[2]
    pb = np.array([y1, zb])
    tb = unit([NV[1], NV[2]])                        # along the nail plane, toward the tip
    ramp = hermite(pa, ta, pb, tb, 60)
    seat_part = np.asarray(substring(LineString(st[i_top:]), 0,
                                     LineString(st[i_top:]).project(Point(pa))).coords)
    # nail pocket floor: straight along the plane to the pad's far end (plus margin)
    v_tip = native_to_plane([[NO[0], -117.45, nail_face_z(-117.45)]])[0, 1]
    v_end = v_tip - P["TIP_BARE"] + 0.5
    p_end = plane_to_native(0.0, v_end, -POCKET_D)[0]
    nail_floor = np.array([pb, [p_end[1], p_end[2]]])
    C = np.vstack([top_seg[:-1], seat_part[:-1], ramp[:-1], nail_floor])
    C = smooth_polyline(C, P["SMOOTH_SIGMA"], exact_after_y=y0)
    # laminate top surface
    Ctop = C.offset_curve(P["FLEX_T"], join_style=1)              # toward -z (object side)
    ct = np.asarray(Ctop.coords)
    if ct[0, 0] < ct[-1, 0]:
        ct = ct[::-1]
    Ctop = LineString(ct)

    # --- skin outer surface O (top -> skin end) -------------------------------------------------
    rf = np.asarray(raw_front.coords)
    ye = P["SKIN_END_Y"]
    pe_top, _ = curve_at_y(Ctop, ye)
    pe = pe_top - np.array([0, P["SKIN_END_T"]])
    yb = -92.6                                       # blend from the raw front into the feather edge
    pbld, tbld = curve_at_y(raw_front, yb)
    O = np.vstack([rf[rf[:, 0] > yb], hermite(pbld, tbld, pe, unit([-1.0, -0.02]), 30)])
    O = O[O[:, 0] <= TPU_TOP_Y + 1e-9]
    if O[0, 0] < TPU_TOP_Y:                          # start exactly on the flange face
        O = np.vstack([[TPU_TOP_Y, O[0, 1]], O])
    return dict(tpu=tpu, tpu_raw=raw, opened=opened, front=front, raw_front=raw_front, seat=seat_full, C=C,
                Ctop=Ctop, O=LineString(O), p_top=p_top, ramp=(pa, pb), v_tip=v_tip, v_end=v_end)


# ----------------------------------------------------------------------------------------------
# 2D regions
# ----------------------------------------------------------------------------------------------
def behind(line, top_ext=0.0, z_far=80.0):
    """Region on the +z (finger) side of a top->tip polyline (monotone in native y)."""
    c = np.asarray(line.coords)
    pts = np.vstack([[c[0, 0] + top_ext, c[0, 1]], c, [c[-1, 0], z_far], [c[0, 0] + top_ext, z_far]])
    return Polygon(pts).buffer(0)


def ybox(y_lo, y_hi, z_lo=-60.0, z_hi=80.0):
    return sbox(y_lo, z_lo, y_hi, z_hi)


def band_behind(C, d0, d1, y_lo, y_hi):
    """Points behind C at a distance in [d0, d1] from it, for native y in [y_lo, y_hi]."""
    reg = behind(C).intersection(C.buffer(d1, resolution=24))
    if d0 > 0:
        reg = reg.difference(C.buffer(d0, resolution=24))
    return reg.intersection(ybox(y_lo, y_hi))


def nail_face_polygon():
    """The nail's planar contact face in plane coordinates (u, v), from the mesh triangles."""
    hard = src_native()["hard"]
    fn, ctr = hard.face_normals, hard.triangles_center
    sel = (fn @ NN > 0.9999) & (np.abs((ctr - NO) @ NN) < 0.02)
    polys = []
    for t in hard.triangles[sel]:
        q = native_to_plane(t)
        polys.append(Polygon(q[:, :2]).buffer(1e-4))
    return unary_union(polys).buffer(-1e-4)


def build_regions(pr):
    C, Ctop, O = pr["C"], pr["Ctop"], pr["O"]
    top = TPU_TOP_Y
    out = {}
    gap_fill = sbox(-97.2, -4.0, -93.4, 3.2)                       # closes the ENPIRE gap to the nail
    top_fill = sbox(-17.6, P["Z_SLOT"] - 1.0, top + 0.3, 12.5)      # under the flange, behind the tail
    core = unary_union([pr["tpu"].buffer(0.4, join_style=1), gap_fill, top_fill])
    out["core"] = core.intersection(behind(C, top_ext=0.3)).intersection(ybox(-120, top + 0.3))
    out["relief"] = C.buffer(P["RELIEF_DEPTH"], resolution=24).intersection(ybox(P["SKIN_END_Y"] - 0.4, top + 0.5))
    h = P["HOOK"]
    out["relief_rail"] = band_behind(C, 0.0, P["RELIEF_DEPTH"], -93.0 - 0.3, -16.0 + 0.3)    # along the hook grooves
    out["hook_groove"] = band_behind(C, h["d0"], h["d1"], -93.0, -16.0)
    out["hook_rib"] = band_behind(C, h["d0"] + h["clr"], h["d1"] - h["clr"], -93.0 + 0.3, -16.0 - 0.3)
    skin_y = ybox(P["SKIN_END_Y"], top)
    out["skin"] = behind(O).difference(behind(Ctop)).intersection(skin_y).buffer(0)
    out["skin_wall"] = unary_union([behind(O).difference(behind(C)),
                                    band_behind(C, 0.0, P["RELIEF_DEPTH"] - 0.05, P["SKIN_END_Y"], top)]
                                   ).intersection(skin_y).buffer(0)
    out["flex"] = behind(Ctop).difference(behind(C)).intersection(ybox(pr["ramp"][1][0], top + 0.0)).buffer(0)
    return out


def nail_regions(pr):
    face = nail_face_polygon()
    hull = face.convex_hull.difference(face)
    groove = max(getattr(hull, "geoms", [hull]), key=lambda g: g.bounds[3] - g.bounds[1] if abs((g.bounds[0] + g.bounds[2]) / 2) < 2 else 0)
    groove = sbox(groove.bounds[0], groove.bounds[1], groove.bounds[2], groove.bounds[3] + 5)
    v_max = pr["v_tip"] - P["TIP_BARE"]
    pad = face.buffer(-P["PAD_EDGE"], join_style=2).difference(groove.buffer(P["GROOVE_CLR"], join_style=2))
    pad = pad.intersection(sbox(-30, -30, 30, v_max))
    # neck: the strip-wide band from the ramp end onto the pad (inside the cradle core width)
    u0, u1 = -14.5 - NO[0], -0.5 - NO[0]
    pb = pr["ramp"][1]
    v_pb = native_to_plane([[NO[0], pb[0], pb[1]]])[0, 1]
    neck = sbox(u0, v_pb - 0.4, u1, face.bounds[1] + 2.5)
    flex = unary_union([pad, neck]).buffer(0.3, join_style=1).buffer(-0.3, join_style=1)
    pocket = flex.buffer(P["POCKET_CLR"], join_style=1)
    v_skin = native_to_plane([[NO[0], P["SKIN_END_Y"], nail_face_z(P["SKIN_END_Y"])]])[0, 1]
    film = flex.buffer(0.1, join_style=2).intersection(sbox(-30, v_skin, 30, v_max + 0.5))
    return dict(face=face, groove=groove, pad=pad, neck=neck, flex=flex, pocket=pocket, film=film,
                v_pb=v_pb, v_skin=v_skin, v_max=v_max, u_strip=(u0, u1))


# ----------------------------------------------------------------------------------------------
# 3D parts (gripper frame, right finger, q = 0)
# ----------------------------------------------------------------------------------------------
def x_n_to_g(x_n):
    return -x_n - 7.96


def pcb_outline(clr=0.0):
    return unary_union([sbox(x0, y0, x1, y1) for (x0, x1, y0, y1) in P["PCB"]["rects"]]).buffer(-clr, join_style=2)


def make_flange():
    rects = [rounded(sbox(x0, y0, x1, y1), P["FLANGE_R"]) for (x0, x1, y0, y1) in P["FLANGE_RECTS"]]
    outline = rounded(unary_union(rects).buffer(1.0, join_style=1).buffer(-1.0, join_style=1), 0.0)
    return extrude_xy(outline, Zf, Zs), outline


def dock_cuts(pr):
    """Everything the flange shares with the v0.2 cartridge: PCB seat, cavity, dowels, thumbscrews,
    plus this finger's tail slot and the thumbscrew head reliefs below the flange."""
    pcb, cav = P["PCB"], P["CAVITY"]
    seat_z = Zs - pcb["recess"] - pcb["t"]
    cuts = [extrude_xy(pcb_outline(), seat_z, Zs + 1),
            extrude_xy(pcb_outline().buffer(-cav["inset"], join_style=2), seat_z - cav["depth"], seat_z + 0.01)]
    (dx0, dy0), (dx1, dy1) = FP["DOWEL_XY"]
    dd = FP["DOWEL_D"] + 0.05
    cuts.append(cyl_z(dx0, dy0, dd, Zs - FP["DOWEL_HOLE_DEPTH"], Zs + 1))
    slot = rounded(sbox(dx1 - (dd + 1.2) / 2, dy1 - dd / 2, dx1 + (dd + 1.2) / 2, dy1 + dd / 2), dd / 2 - 1e-3)
    cuts.append(extrude_xy(slot, Zs - FP["DOWEL_HOLE_DEPTH"], Zs + 1))
    for (dx, dy) in FP["DOWEL_XY"]:
        cuts.append(frustum_z(dx, dy, dd, dd + 1.2, Zs - 0.6, Zs + 0.001))
    for (tx, ty) in FP["THUMB_XY"]:
        cuts.append(cyl_z(tx, ty, FP["M3_CLEAR"], Zf - 1, Zs + 1))
        r = P["THUMB_RELIEF"]
        cuts.append(cyl_z(tx, ty, r["d"], Zf - r["h"], Zf + 0.01))
    # tail slot: strip-wide, through the flange floor into the cavity
    zc = P["Z_SLOT"]
    y0, y1 = zc - P["FLEX_T"] - 0.25 + 2.87, zc + 0.25 + 2.87
    x0, x1 = sorted((x_n_to_g(-0.5) - 0.4, x_n_to_g(-14.5) + 0.4))
    cuts.append(gbox(x0, x1, y0, y1, Zf - 0.6, seat_z - cav["depth"] + 0.02))
    return cuts


def make_slot_fill():
    hard = src_native()["hard"]
    f = P["SLOT_FILL"]
    s = hard.section(plane_origin=[0, 0, -2.3], plane_normal=[0, 0, 1])
    geom = None
    for e in s.discrete:
        p = Polygon(e[:, :2]).buffer(0)
        geom = p if geom is None else geom.symmetric_difference(p)
    plate = geom.intersection(sbox(-40, f["y"][0], 20, f["y"][1]))
    plate = max(getattr(plate, "geoms", [plate]), key=lambda g: g.area).buffer(-0.02, join_style=2)
    m = trimesh.creation.extrude_polygon(plate, f["z"][1] - f["z"][0])
    m.vertices = n2g(np.c_[m.vertices[:, 0], m.vertices[:, 1], m.vertices[:, 2] + f["z"][0]])
    return m


def build_all(verbose=True):
    pr = build_profile()
    R = build_regions(pr)
    N = nail_regions(pr)
    xs = P["TPU_X"]
    # --- core: ENPIRE frame (below the flange) + rigid cradle + slot fill + flange, then cuts
    frame = ES.load(P["DZ"])["hard"]
    frame = diff(frame, [gbox(-60, 60, -60, 80, Zf + 0.3, 0)])
    cradle = extrude_yz(R["core"], xs[0] - 0.02, xs[1] + 0.02)      # overlap the rails: no coplanar faces
    flange, outline = make_flange()
    core = union([frame, cradle, make_slot_fill(), flange])
    cuts = dock_cuts(pr)
    for xa, xb in ((xs[0] - 0.05, xs[0] + P["TONGUE_INSET"]), (xs[1] - P["TONGUE_INSET"], xs[1] + 0.05)):
        cuts.append(extrude_yz(R["relief"], xa, xb))
    rc = P["RAIL_CUT"]
    for xa, xb in ((xs[0] - rc, xs[0] - 0.04), (xs[1] + 0.04, xs[1] + rc)):
        cuts.append(extrude_yz(R["relief_rail"], xa, xb))
    hd = P["HOOK"]["depth"]
    for xa, xb in ((xs[0] + P["TONGUE_INSET"] - 0.01, xs[0] + P["TONGUE_INSET"] + hd),
                   (xs[1] - P["TONGUE_INSET"] - hd, xs[1] - P["TONGUE_INSET"] + 0.01)):
        cuts.append(extrude_yz(R["hook_groove"], xa, xb))
    cuts.append(extrude_plane(N["pocket"], -POCKET_D - 0.02, 1.5))
    core = diff(core, cuts)
    # --- skin (main body, side walls, hook ribs)
    ti, sc = P["TONGUE_INSET"], P["SKIN_SIDE_CLR"]
    skin = [extrude_yz(R["skin"], xs[0] + ti - 0.01, xs[1] - ti + 0.01)]       # overlaps the walls in front of the flex only
    skin += [extrude_yz(R["skin_wall"], xs[0] + sc, xs[0] + ti), extrude_yz(R["skin_wall"], xs[1] - ti, xs[1] - sc)]
    hc = P["HOOK"]["clr"]
    skin += [extrude_yz(R["hook_rib"], xs[0] + ti - 0.02, xs[0] + ti + hd - hc),
             extrude_yz(R["hook_rib"], xs[1] - ti - hd + hc, xs[1] - ti + 0.02)]
    skin = union(skin)
    # --- flex laminate (placeholder solid): strip + ramp on the cradle, pad on the nail, tail stub
    flex = [extrude_yz(R["flex"], xs[0] + ti, xs[1] - ti),
            extrude_plane(N["flex"], -POCKET_D, -POCKET_D + P["FLEX_T"])]
    zc = P["Z_SLOT"]
    x0, x1 = sorted((x_n_to_g(-0.5), x_n_to_g(-14.5)))
    seat_z = Zs - P["PCB"]["recess"] - P["PCB"]["t"]
    flex.append(gbox(x0, x1, zc - P["FLEX_T"] + 2.87, zc + 2.87, Zf - 0.05, seat_z - P["CAVITY"]["depth"] + 1.0))
    flex = union(flex)
    film = extrude_plane(N["film"], -P["FILM_T"], 0.0)
    parts = dict(core=core, skin=skin, flex=flex, film=film)
    parts.update(placeholders())
    if verbose:
        for k, m in parts.items():
            print(f"{k:14s} watertight {m.is_watertight!s:5s} vol {m.volume:10.1f}  bounds {np.round(m.bounds, 2).tolist()}")
    return parts, pr, R, N


def placeholders():
    pcb = P["PCB"]
    z1 = Zs - pcb["recess"]
    board = extrude_xy(pcb_outline(0.1), z1 - pcb["t"], z1)
    zone = pcb_outline(P["CAVITY"]["inset"] + 0.4).intersection(sbox(-30, 5.5, 30, 40))
    parts = extrude_xy(zone, z1 - pcb["t"] - 2.2, z1 - pcb["t"])
    return dict(ph_finger_pcb=board, ph_finger_pcb_parts=parts)


# ----------------------------------------------------------------------------------------------
# arc length along the flex path; (x_n, s) -> 3D
# ----------------------------------------------------------------------------------------------
class FlexPath:
    """Arc length s along C from the flange face (s = 0) toward the tip. The laminate's flat
    pattern is exact in (u, s): u = gripper x of the right finger, s = distance along C."""

    def __init__(self, pr, step=0.02):
        self.r = resample(np.asarray(pr["C"].coords), step)
        d = np.linalg.norm(np.diff(self.r, axis=0), axis=1)
        self.s = np.r_[0, np.cumsum(d)]
        t = np.gradient(self.r, axis=0)
        self.t = t / np.linalg.norm(t, axis=1)[:, None]
        self.n = np.c_[-self.t[:, 1], self.t[:, 0]]           # toward the object (-z side)
        self.length = self.s[-1]

    def at(self, s):
        s = np.clip(np.asarray(s, float), 0, self.length)
        p = np.c_[np.interp(s, self.s, self.r[:, 0]), np.interp(s, self.s, self.r[:, 1])]
        n = np.c_[np.interp(s, self.s, self.n[:, 0]), np.interp(s, self.s, self.n[:, 1])]
        return p, n / np.linalg.norm(n, axis=1)[:, None]

    def s_at_y(self, y):
        i = np.argmax(self.r[:, 0] <= y)
        return float(self.s[i])

    def point_g(self, u_g, s, lift=0.0):
        """Gripper-frame point at lateral u (gripper x) and arc length s, lifted along the normal."""
        p, n = self.at(np.atleast_1d(s))
        q = p + n * np.atleast_1d(lift)[:, None]
        x_n = -np.atleast_1d(u_g) - 7.96
        g = n2g(np.c_[x_n * np.ones(len(q)), q[:, 0], q[:, 1]])
        nrm = n2g(np.c_[np.zeros(len(q)), n[:, 0], n[:, 1]]) - n2g(np.zeros((1, 3)))
        return g, nrm


def derived(pr, N):
    fp = FlexPath(pr)
    s_strip = (fp.s_at_y(P["STRIP_Y"][0]), fp.s_at_y(P["STRIP_Y"][1]))
    s_ramp = (fp.s_at_y(P["RAMP_Y"][0]), fp.s_at_y(P["RAMP_Y"][1]))
    v_pb = N["v_pb"]
    tip_n = np.array([NO[0], -117.647, nail_face_z(-117.647)])
    tip_g = n2g(tip_n)[0]
    return dict(Zs=Zs, Zf=Zf, DZ=P["DZ"], SEAT_SET=SEAT_SET, POCKET_D=POCKET_D,
                C_length=round(float(fp.length), 3), s_strip=[round(float(v), 3) for v in s_strip],
                strip_length=round(float(s_strip[1] - s_strip[0]), 3), s_ramp=[round(float(v), 3) for v in s_ramp],
                s_nail0=round(float(s_ramp[1]), 3), v_nail0=round(float(v_pb), 3), v_pad_max=round(float(N["v_max"]), 3),
                nail_plane_g=dict(origin=n2g(NO)[0].round(4).tolist(),
                                  normal=(n2g(NN[None]) - n2g(np.zeros((1, 3))))[0].round(6).tolist(),
                                  u=(n2g(NU[None]) - n2g(np.zeros((1, 3))))[0].round(6).tolist(),
                                  v=(n2g(NV[None]) - n2g(np.zeros((1, 3))))[0].round(6).tolist()),
                tip_g=tip_g.round(3).tolist(), tip_below_carriage_mm=round(float(FP["Z_CARRIAGE"] - tip_g[2]), 2),
                strip_u=[round(x_n_to_g(-0.5), 3), round(x_n_to_g(-14.5), 3)])


PART_NAMES = ("core", "skin", "flex", "film", "ph_finger_pcb", "ph_finger_pcb_parts")


def skin_xranges():
    """Gripper-frame x ranges of the skin pieces (main body, two side walls, two hook ribs)."""
    xs, ti, sc = P["TPU_X"], P["TONGUE_INSET"], P["SKIN_SIDE_CLR"]
    hd, hc = P["HOOK"]["depth"], P["HOOK"]["clr"]
    nat = dict(skin=[(xs[0] + ti - 0.01, xs[1] - ti + 0.01)],
               skin_wall=[(xs[0] + sc, xs[0] + ti), (xs[1] - ti, xs[1] - sc)],
               hook_rib=[(xs[0] + ti - 0.02, xs[0] + ti + hd - hc), (xs[1] - ti - hd + hc, xs[1] - ti + 0.02)])
    return {k: [tuple(sorted((x_n_to_g(a), x_n_to_g(b)))) for a, b in v] for k, v in nat.items()}


def skin_step(R, path):
    """B-rep skin (for mold makers and CAD users): the 2D regions extruded along x with CadQuery.
    The profiles are simplified to 0.02 mm (Hausdorff), far below print resolution; that keeps the
    STEP near 3 MB instead of 9 MB. The STL and the mold are built from the exact regions."""
    import cadquery as cq
    solid = None
    for key, ranges in skin_xranges().items():
        polys = getattr(R[key], "geoms", [R[key]])
        for (x0, x1) in ranges:
            for poly in polys:
                poly = poly.simplify(0.02)
                ring = [(z + 2.87, y + CZ) for (y, z) in list(poly.exterior.coords)[:-1]]     # YZ plane: (Y, Z)
                s = cq.Workplane("YZ").polyline(ring).close().extrude(x1 - x0).translate((x0, 0, 0))
                solid = s if solid is None else solid.union(s)
    assert solid.val().isValid(), "skin STEP is not a valid solid"
    cq.exporters.export(solid, path)
    return solid


MOLD_PORTS = [(-45.0, 3.0),                                   # fill: bottom of the arch (lowest point)
              (TPU_TOP_Y - 1.5, 2.0), (-24.0, 2.0), (-72.0, 2.0), (P["SKIN_END_Y"] + 1.5, 2.0)]   # vents


def make_mold(parts, R, pr, wall=3.0):
    """Two-piece casting mold for the silicone skin: a core plug (replica of the tongue + laminate,
    with the hook grooves) and an outer shell (replica of the serrated surface). It is filled lying
    front face up, so the bottom of the arch is the lowest point (fill port) and the two lobes and
    both ends are the high points (vents)."""
    skin = parts["skin"]
    lo, hi = skin.bounds
    B = gbox(lo[0] - wall, hi[0] + wall, lo[1] - wall, hi[1] + 1.0, lo[2] - wall, hi[2] + wall)
    xw = skin_xranges()["skin_wall"]
    x0, x1 = min(r[0] for r in xw), max(r[1] for r in xw)
    plug2d = behind(pr["Ctop"]).intersection(ybox(P["SKIN_END_Y"] - 4.0, TPU_TOP_Y))
    core_pc = diff(inter(extrude_yz(plug2d, -(x1 + 7.96), -(x0 + 7.96)), B), [skin])
    shell = diff(B, [skin, core_pc])
    # fill port and vents, through the shell's front toward -y
    holes = []
    for z_n_y, d in MOLD_PORTS:
        p_o, _ = curve_at_y(pr["O"], z_n_y)
        g = n2g([[P["X_PROFILE"], p_o[0], p_o[1]]])[0]
        c = trimesh.creation.cylinder(radius=d / 2, height=40, sections=32)
        c.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
        c.apply_translation((g[0], g[1] - 20 + 0.3, g[2]))
        holes.append(c)
    shell = diff(shell, holes)
    return clean(core_pc), clean(shell)


def export(parts, pr, R, N):
    os.makedirs(OUT, exist_ok=True)
    for k in PART_NAMES:
        parts[k] = clean(parts[k])
        parts[k].export(os.path.join(OUT, f"{k}.stl"))
        back = trimesh.load(os.path.join(OUT, f"{k}.stl"))
        assert back.is_watertight and back.is_volume, f"{k}.stl is not a closed volume after export"
    skin_step(R, os.path.join(OUT, "skin.step"))
    mold_core, mold_shell = make_mold(parts, R, pr)
    mold_core.export(os.path.join(OUT, "skin_mold_core.stl"))
    mold_shell.export(os.path.join(OUT, "skin_mold_shell.stl"))
    D = derived(pr, N)
    prof = {k: np.round(np.asarray(pr[k].coords), 4).tolist() for k in ("C", "Ctop", "O")}
    json.dump(dict(params=P, derived=D, source=dict(commit=ES.COMMIT, files={k: v[1] for k, v in ES.FILES.items()},
                                                   attribution=ES.ATTRIBUTION)),
              open(os.path.join(OUT, "params.json"), "w"), indent=1)
    json.dump(dict(frame="native ENPIRE (y, z), mm", note="C: laminate bottom, Ctop: laminate top, O: skin outer",
                   **prof, nail_flex_uv=[list(map(list, g.exterior.coords)) for g in getattr(N["flex"], "geoms", [N["flex"]])]),
              open(os.path.join(OUT, "profile.json"), "w"))
    open(os.path.join(OUT, "NOTICE.txt"), "w").write(
        "ENPIRE-T parts in this folder are a modified version of the ENPIRE gripper finger.\n" + ES.ATTRIBUTION +
        "\nLicence: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ . Changes are listed above and in docs/ENPIRE_T.md.\n")
    return D


if __name__ == "__main__" and "--build" in sys.argv:
    parts, pr, R, N = build_all()
    D = export(parts, pr, R, N)
    print({k: v for k, v in D.items() if k != "nail_plane_g"})


if __name__ == "__main__" and "--profile" in sys.argv:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    pr = build_profile()
    H = section_yz(src_native()["hard"], P["X_PROFILE"])
    fig, axs = plt.subplots(2, 1, figsize=(20, 13))
    for ax, lim in zip(axs, (((-12, -120), (-8, 30)), ((-84, -100), (-6, 3)))):
        for g, c in ((H, "#8d99ab"), (pr["tpu_raw"], "#f2b35b")):
            for gg in getattr(g, "geoms", [g]):
                x, y = gg.exterior.xy; ax.fill(x, y, fc=c, ec="k", lw=0.3, alpha=0.6)
        for k, c in (("C", "r"), ("Ctop", "m"), ("O", "b"), ("seat", "g")):
            x, y = pr[k].xy; ax.plot(x, y, c, lw=1.0, label=k)
        ax.set_aspect("equal"); ax.set_xlim(*lim[0]); ax.set_ylim(*lim[1]); ax.grid(alpha=.3); ax.legend()
    plt.tight_layout(); plt.savefig(sys.argv[-1], dpi=70)
    print("p_top", pr["p_top"], "C length", round(pr["C"].length, 2), "v_tip", round(pr["v_tip"], 2))
