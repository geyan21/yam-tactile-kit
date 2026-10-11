"""
Checks and measurements for ENPIRE-T Tip against the i2rt YAM Linear-4310 meshes and the original ENPIRE.

  fit       clearance of socket / core / TPU insert / thumbscrews to the housing and the opposite carriage
            over the full stroke, overlap volumes, and the first finger-to-finger contact vs stock ENPIRE
  internal  overlap volumes between the parts of one finger (stock TPU insert included), and the gap
            between the laminate and the insert along the route
  shape     the contact side seen by an approaching object vs stock ENPIRE; the core vs the stock frame
            away from the modified zones; the film vs the nail plane
  walls     nail behind the pocket, pocket lips, spine behind the channel, slit fill, back block, flange
  measure   numbers quoted in docs/ENPIRE_T_TIP.md (so the docs can't drift)

Usage (from cartridge/): python3 cad/enpire_tip_check.py [i2rt_repo_root]
  -> out/enpire_tip/check/checks.json, measurements.json
"""
import json
import os
import sys
import numpy as np
import trimesh
from shapely import contains_xy
from shapely.geometry import Point, box as sbox
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_fit as cf          # noqa: E402
import enpire_check as EC       # noqa: E402  (distance, clearance, placement and ray helpers)
import enpire_finger as E       # noqa: E402
import enpire_source as ES      # noqa: E402
import enpire_tip as T          # noqa: E402

CHK = os.path.join(T.OUT, "check")
SOCKET_SIDE = ("socket", "ph_socket_pcb", "ph_pogo_pins", "ph_thumbscrews", "ph_dowels")
RT = T.build_route()
RR = T.route_regions(RT)
NR = T.nail_regions(RT)
D = T.derived(RT, NR)
FPATH = E.FlexPath(dict(C=RT["C"]))


def load_parts():
    out = {k: trimesh.load(os.path.join(T.OUT, k + ".stl")) for k in T.PART_NAMES}
    for k in SOCKET_SIDE:
        out[k] = trimesh.load(os.path.join(E.F.OUT, k + ".stl"))
    out["tpu"] = T.tpu_stock()
    return out


# ----------------------------------------------------------------------------------------------
def first_contact(parts):
    q = EC.touch_q({k: parts[k] for k in ("core", "tpu", "film")})
    src = ES.load(T.P["DZ"])
    q_stock = EC.touch_q({"hard": src["hard"], "soft": src["soft"]})
    R, L = EC.placed(parts, q + 0.00005, 1), EC.placed(parts, q + 0.00005, -1)
    names = ("core", "tpu", "film", "flex", "socket", "ph_thumbscrews")
    pairs = {f"{a}-{b}": EC.clearance(R[a], L[b], n=3000, margin=3.0) for a in names for b in names if a <= b}
    pts = np.vstack([R["film"].vertices, R["core"].vertices, R["tpu"].vertices])
    touch = pts[pts[:, 1] < pts[:, 1].min() + 0.02]
    return dict(q_touch_mm=round(q * 1000, 3), stock_q_touch_mm=round(q_stock * 1000, 3), gap_by_pair_at_touch_mm=pairs,
                touch_z_range=[round(float(touch[:, 2].min()), 2), round(float(touch[:, 2].max()), 2)])


def internal(parts):
    pairs = [("core", "tpu"), ("flex", "tpu"), ("film", "tpu"), ("core", "flex"), ("core", "film"), ("flex", "film"),
             ("core", "ph_finger_pcb"), ("core", "ph_finger_pcb_parts"), ("flex", "ph_finger_pcb"),
             ("core", "socket"), ("tpu", "socket"), ("core", "ph_thumbscrews"), ("core", "ph_dowels"), ("core", "ph_pogo_pins"),
             ("ph_finger_pcb", "ph_pogo_pins"), ("ph_finger_pcb_parts", "socket"), ("ph_finger_pcb", "socket"), ("flex", "socket")]
    out = {f"{a} x {b}": round(cf.ivol(parts[a], parts[b]), 4) for a, b in pairs}
    return out


def route_gaps(parts):
    """Gap between the laminate (with the film where it wraps round the nail root) and the TPU insert, by
    stretch of the route (the insert is used as is). The cavity part of the tails is checked in 2D by
    enpire_tip_fpc.finger_pcb (tail_room_mm)."""
    tpu = parts["tpu"]
    pts = np.vstack([trimesh.sample.sample_surface(parts[k], n, seed=4)[0] for k, n in (("flex", 40000), ("film", 8000))])
    pts = cf._near(pts, tpu, 3.0)
    pts = pts[E.g2n(pts)[:, 1] > -99.5]                       # the route and the bend, not the nail pad
    near = EC.dist(tpu, pts)
    pn = E.g2n(pts)
    zones = dict(top=(pn[:, 1] > -52.0) & (pn[:, 2] > 20.0), diagonal=(pn[:, 1] <= -52.0) & (pn[:, 1] > -94.0),
                 slit_and_bend=(pn[:, 1] <= -94.0))
    out = {}
    for k, m in zones.items():
        out[f"{k}_mm"] = round(float(near[m].min()), 3) if m.any() else None
    out["min_mm"] = round(float(near.min()), 3)
    # stock ENPIRE for comparison: the root face beside the insert's lower end, over the laminate's width
    hard = ES.load(T.P["DZ"])["hard"]
    pts = trimesh.sample.sample_surface(hard, 200000, seed=5)[0]
    pn = E.g2n(pts)
    cx0, cx1 = T.P["CHANNEL_X"]
    m = (pn[:, 0] > cx0 + 0.2) & (pn[:, 0] < cx1 - 0.2) & (pn[:, 1] > -97.0) & (pn[:, 1] < -95.2) & (pn[:, 2] > -3.3) & (pn[:, 2] < 4.0)
    out["stock_root_face_to_tpu_mm"] = round(float(EC.dist(tpu, pts[m]).min()), 3)
    return out


# ----------------------------------------------------------------------------------------------
def in_pocket_zone(pn, margin=0.5, depth=1.2):
    """Native points within `depth` of the nail plane and inside the pocket outline (plane coordinates)."""
    uvw = E.native_to_plane(pn)
    return (np.abs(uvw[:, 2]) < depth) & contains_xy(NR["pocket"].buffer(margin), uvw[:, 0], uvw[:, 1])


def changed_zone(pn, margin=0.6):
    """Native points in the zones this version changes on purpose: the route's channel, slit fill and
    ledge across the channel, the back block across the insert, the cross-slot fill and the nail pocket."""
    cx0, cx1 = T.P["CHANNEL_X"]
    tx0, tx1 = T.P["TPU_X"]
    in_ch = (pn[:, 0] > cx0 - margin) & (pn[:, 0] < cx1 + margin)
    in_tpu = (pn[:, 0] > tx0 - margin) & (pn[:, 0] < tx1 + margin)
    route = unary_union([RR["channel"], RR["slit_fill"], RR["ledge"]]).buffer(margin)
    in_slot = (pn[:, 1] < -96.8) & (pn[:, 1] > -109.2) & (pn[:, 2] > -2.6) & (pn[:, 2] < 5.0)
    return ((in_ch & contains_xy(route, pn[:, 1], pn[:, 2])) | (in_tpu & contains_xy(RR["back"].buffer(1.0), pn[:, 1], pn[:, 2]))
            | in_slot | in_pocket_zone(pn))


def nail_root(parts, hard, soft, edge_depth=1.0, reach=3.0):
    """The nail root, where over the laminate's width the film-covered bend takes the place of the root's
    corner and the slit runs up beside the insert. A fine ray scan from the object side (+y) over the whole
    nail face, stock vs this finger. Over the laminate's width, rays whose stock surface lies within
    `edge_depth` of the nail plane see the root's edge; the others go into the slit, compared at its mouth
    (either surface within `reach` of the nail plane). Over the whole face: how far behind the nail plane a ray
    first meets bare laminate, and how far the laminate or the film lies outside the stock frame (3D, the nail
    end of the route, s >= s_stack)."""
    gx0, gx1 = sorted(E.x_n_to_g(x) for x in T.P["CHANNEL_X"])
    xs = np.arange(-11.5, 11.5 + 1e-9, 0.25)                            # the whole nail face
    zs = np.arange(-99.0 + E.CZ, -94.5 + E.CZ, 0.05)
    a = EC.depth_map([hard, soft], xs, zs)
    names = ("core", "tpu", "film", "flex")
    each = np.stack([EC.depth_map([parts[k]], xs, zs) for k in names])
    b = np.nanmin(np.where(np.isnan(each), np.inf, each), axis=0)
    first = np.argmin(np.where(np.isnan(each), np.inf, each), axis=0)
    b[np.isinf(b)] = np.nan
    pl = D["nail_plane_g"]
    o, n = np.array(pl["origin"]), np.array(pl["normal"])
    X, Z = np.meshgrid(xs, zs)
    y_plane = o[1] - ((X - o[0]) * n[0] + (Z - o[2]) * n[2]) / n[1]
    both = ~np.isnan(a) & ~np.isnan(b)
    depth_stock, depth_new, diff = a - y_plane, b - y_plane, b - a          # diff + : further from the object than stock
    lam = (X > gx0 + 0.3 - 1e-9) & (X < gx1 - 0.3 + 1e-9)               # over the laminate (the channel less 0.2 a side)
    edge = both & lam & (depth_stock < edge_depth)
    mouth = both & lam & (depth_stock >= edge_depth) & (np.minimum(depth_stock, depth_new) < reach)
    bare = (first == names.index("flex")) & ~np.isnan(b)

    def ext(m, f):
        return round(float(f(diff[m])), 3) if m.any() else 0.0
    # where the film ends on the laminate in the slit (s_bend0, the top of the bend): above it the laminate's own
    # coverlay lines the slit's root side; its depth behind the nail plane
    C = RT["C"]
    p0, p1 = np.array(C.interpolate(D["s_bend0"]).coords[0]), np.array(C.interpolate(D["s_bend0"] + 0.01).coords[0])
    t = (p1 - p0) / np.linalg.norm(p1 - p0)
    end = p0 + T.P["FLEX_T"] * np.array([-t[1], t[0]])                  # the laminate's free face, on the free (left) side
    w_end = E.native_to_plane([[T.P["X_PROFILE"], end[0], end[1]]])[0, 2]
    out = dict(rays=int(both.sum()), edge_rays=int(edge.sum()), mouth_rays=int(mouth.sum()),
               edge_max_deeper_mm=ext(edge, np.max), edge_max_nearer_mm=max(0.0, -ext(edge, np.min)),
               mouth_max_deeper_mm=ext(mouth, np.max), mouth_max_nearer_mm=max(0.0, -ext(mouth, np.min)),
               bare_laminate_min_depth_mm=round(float(depth_new[bare].min()), 2) if bare.any() else None,
               film_end_depth_mm=round(float(-w_end), 2))
    # 3D: laminate and film round the nail root (both sheets stacked, and the film) vs the stock frame
    pts = np.vstack([trimesh.sample.sample_surface(parts[k], m, seed=7)[0] for k, m in (("flex", 60000), ("film", 30000))])
    pn = E.g2n(pts)
    near = pn[:, 1] < -90.0
    s = np.array([C.project(Point(y, z)) for y, z in pn[near][:, 1:]])
    pts = pts[near][s >= D["s_stack"]]
    sd = np.concatenate([trimesh.proximity.signed_distance(hard, pts[i:i + 2000]) for i in range(0, len(pts), 2000)])
    k = int(np.argmin(sd))                                                   # trimesh: + inside the mesh
    out["laminate_outside_stock_frame_mm"] = dict(max=round(max(0.0, float(-sd[k])), 3), n=int(len(pts)),
                                                  at_native_yz=np.round(E.g2n(pts[k:k + 1])[0, 1:], 2).tolist())
    return out


def shape(parts):
    """The contact side as an approaching object sees it (all of this finger's parts, the laminate
    included), compared with stock ENPIRE; then the core against the stock frame both ways, away from
    the zones changed on purpose; and the film against the nail plane."""
    src = ES.load(T.P["DZ"])
    hard, soft = src["hard"], src["soft"]
    out = {}
    xs = np.arange(-10.75, 10.76, 0.5)
    zs = np.arange(E.Zf - 0.5, -193.6, -0.5)
    a = EC.depth_map([hard, soft], xs, zs)
    names = ("core", "tpu", "film", "flex")
    each = np.stack([EC.depth_map([parts[k]], xs, zs) for k in names])
    b = np.nanmin(np.where(np.isnan(each), np.inf, each), axis=0)
    b[np.isinf(b)] = np.nan
    first = np.argmin(np.where(np.isnan(each), np.inf, each), axis=0)          # which part an object meets first
    X, Z = np.meshgrid(xs, zs)
    zn = Z - E.CZ
    both = ~np.isnan(a) & ~np.isnan(b)
    diff = np.where(both, b - a, np.nan)                    # + = surface further from the object than stock
    zones = dict(cradle=(zn <= -14.5) & (zn >= -92.0) & (np.abs(X + 0.46) <= 7.0),
                 transition=(zn < -92.0) & (zn > -96.9) & (np.abs(X + 0.46) <= 7.0),
                 nail=(zn <= -96.9),
                 sides=(zn <= -14.5) & (zn > -96.9) & (np.abs(X + 0.46) > 7.0))
    for k, msk in zones.items():
        v = np.abs(diff[msk & both])
        out[f"depth_map_{k}_mm"] = dict(n=int(v.size), p50=round(float(np.median(v)), 4),
                                        p95=round(float(np.percentile(v, 95)), 4), max=round(float(v.max()), 4))
    out["depth_map_coverage_change"] = int((np.isnan(a) != np.isnan(b)).sum())
    # bare laminate (no film) as first hit, away from the nail root, which nail_root() scans finely
    root = (zn < -88.0) & (zn > -99.5)
    out["laminate_exposed_rays_outside_root"] = int(((first == names.index("flex")) & ~np.isnan(b) & ~root).sum())
    out["nail_root"] = nail_root(parts, hard, soft)
    np.savez_compressed(os.path.join(CHK, "depth_maps.npz"), xs=xs, zs=zs, enpire=a, enpire_tip=b, first_part=first)
    # the stock frame's surface -> the new core (finds removed material), and the new core's surface -> the
    # stock frame (finds added material), both away from the changed zones, the flange and the thumbscrews
    def keep_of(pts):
        pn = E.g2n(pts)
        thumb = np.min([np.hypot(pts[:, 0] - tx, pts[:, 1] - ty) for tx, ty in E.FP["THUMB_XY"]], axis=0) < 5.6
        return (pts[:, 2] < E.Zf - 6.0) & ~changed_zone(pn) & ~(thumb & (pts[:, 2] > E.Zf - 5.5))
    for key, src_m, dst_m, seed in (("core_vs_hard_frame_mm", hard, parts["core"], 2), ("hard_frame_vs_core_mm", parts["core"], hard, 3)):
        pts = trimesh.sample.sample_surface(src_m, 14000, seed=seed)[0]
        keep = keep_of(pts)
        d = EC.dist(dst_m, pts[keep])
        out[key] = dict(n=int(keep.sum()), p50=round(float(np.median(d)), 4), p99=round(float(np.percentile(d, 99)), 4),
                        max=round(float(d.max()), 4))
    pl = D["nail_plane_g"]
    dev = (parts["film"].vertices - np.array(pl["origin"])) @ np.array(pl["normal"])
    flat = E.native_to_plane(E.g2n(parts["film"].vertices))[:, 1] >= NR["v_pb"] + 0.01     # the flat part, not the wrap
    out["film_vs_nail_plane_mm"] = dict(max_abs=round(float(np.abs(dev[flat & (dev > -0.05)]).max()), 4))
    return out


# ----------------------------------------------------------------------------------------------
def lam_thickness(s):
    """What lies on the bonding face at arc length s: one tail, both sheets, or both sheets and the film."""
    return np.where(s >= D["s_bend0"], T.POCKET_D, np.where(s >= D["s_stack"], T.P["FLEX_T"], T.P["TAIL_T"]))


US = np.linspace(-4.6, 3.7, 9)                      # gripper x across the laminate (both bands)


def behind(core, s_lo, s_hi, step=0.4):
    """Thinnest material right behind the laminate's bonding face (toward the core) over an s range. A
    bonding-face point with no material behind it counts as 0."""
    best = (np.inf, None)
    for s in np.arange(s_lo, s_hi + 1e-9, step):
        for u in US:
            g, n = FPATH.point_g(u, s, lift=0.0)
            n = n[0] / np.linalg.norm(n[0])
            o = g[0] - n * 0.02
            t = EC.first_wall(core, o, -n, start=0.0) if core.contains(o[None])[0] else 0.0
            if t < best[0]:
                best = (t, (round(float(s), 2), round(float(u), 2)))
    return dict(t=round(best[0], 3), at_s_u=best[1])


def free_side(core, s_lo, s_hi, reach=2.0, step=0.4):
    """Nothing of the core in front of the laminate's free face (or the film over it) within `reach`:
    no bridge, membrane or lip left over it anywhere along the route."""
    best = (np.inf, None)
    for s in np.arange(s_lo, s_hi + 1e-9, step):
        for u in US:
            g, n = FPATH.point_g(u, s, lift=float(lam_thickness(s)) + 0.02)
            n = n[0] / np.linalg.norm(n[0])
            t = EC.first_wall(core, g[0], n, start=0.0)
            if t < best[0]:
                best = (t, (round(float(s), 2), round(float(u), 2)))
    return dict(min_mm=round(min(best[0], reach), 3) if np.isfinite(best[0]) else f">{reach}", at_s_u=best[1] if best[0] < reach else None)


def walls(parts):
    core = parts["core"]
    out = {}
    fl = NR["flex"]
    best = (np.inf, None)
    nrm = (E.n2g(-E.NN[None]) - E.n2g(np.zeros((1, 3))))[0]
    for u in np.arange(fl.bounds[0], fl.bounds[2], 0.5):
        for v in np.arange(max(fl.bounds[1], NR["v_pb"] + 0.2), fl.bounds[3], 0.5):       # where the laminate lies on the floor
            if fl.contains(Point(u, v)):
                t = EC.first_wall(core, E.n2g(E.plane_to_native(u, v, -T.POCKET_D - 0.01))[0], nrm)
                if t < best[0]:
                    best = (t, (round(u, 2), round(v, 2)))
    out["nail_behind_pocket_min_mm"] = dict(t=round(best[0], 3), at_uv=best[1])
    v_prox = NR["face"].bounds[1] + 0.6                 # the neck runs through the proximal edge on purpose
    out["nail_lip_pocket_to_groove_mm"] = round(NR["pocket"].distance(NR["groove"]), 3)
    out["nail_lip_pocket_to_face_edge_mm"] = round(min(NR["face"].exterior.distance(Point(c))
                                                       for g in getattr(NR["pocket"], "geoms", [NR["pocket"]])
                                                       for c in g.exterior.coords if NR["face"].contains(Point(c)) and c[1] > v_prox), 3)
    # behind the laminate, segment by segment from below the flange slot (where the tails float) to the
    # nail floor: S-curve (back block), spine top, top fillet, diagonal, fillet into the slit, slit, bend;
    # and in front of it, nothing of the core
    (A0, _), (A1, B1), (A2, B2), (A3, B3), (A4, B4) = RT["tangents"]
    sC = lambda p: float(RT["C"].project(Point(p)))      # noqa: E731
    s0 = sC((E.g2n(np.array([[0.0, 0.0, E.Zf - 3.6]]))[0, 1] - 0.3, T.P["Z_RISE"])) + 0.3
    cuts = dict(s_curve=(s0, sC(B1)), top=(sC(B1), sC(A2)), top_fillet=(sC(A2), sC(B2)), diagonal=(sC(B2), sC(A3)),
                slit_fillet=(sC(A3), sC(B3)), slit=(sC(B3), sC(A4)), bend=(sC(A4), D["s_nail0"]))
    for k, (a, b) in cuts.items():
        out[f"behind_laminate_{k}_mm"] = behind(core, a, b)
    out["free_side_clear_mm"] = free_side(core, s0, D["s_nail0"] + 1.0)
    # flange: dock holes, cavity floor, the walls round the tails' slot at the back
    import measure as M
    zs = np.linspace(E.Zf + 0.3, E.Zs - 0.3, 7)
    for (tx, ty) in E.FP["THUMB_XY"]:
        out[f"wall_thumbscrew_{'L' if tx < 0 else 'R'}_mm"] = round(M.wall_around_hole(core, tx, ty, E.FP["M3_CLEAR"] / 2, zs), 3)
    zd = np.linspace(E.Zs - E.FP["DOWEL_HOLE_DEPTH"] + 0.2, E.Zs - 0.7, 4)
    for (dx, dy) in E.FP["DOWEL_XY"]:
        out[f"wall_dowel_{'L' if dx < 0 else 'R'}_mm"] = round(M.wall_around_hole(core, dx, dy, (E.FP["DOWEL_D"] + 0.05) / 2, zd), 3)
    cav, pcb = E.P["CAVITY"], E.P["PCB"]
    zfl = E.Zs - pcb["recess"] - pcb["t"] - cav["depth"]
    zone = E.pcb_outline(cav["inset"] + 0.5)
    y_bond = T.P["Z_RISE"] + 2.87
    x0, x1 = T.P["SLOT_X"]
    best = np.inf
    for x in np.linspace(zone.bounds[0], zone.bounds[2], 13):
        for y in np.linspace(zone.bounds[1], zone.bounds[3], 13):
            if zone.contains(Point(x, y)) and not (x0 - 0.5 < x < x1 + 0.5 and y > y_bond - 0.8):
                best = min(best, EC.first_wall(core, (x, y, zfl - 0.01), (0, 0, -1)))
    out["cavity_floor_min_mm"] = round(best, 3)
    best = dict(back=np.inf, front=np.inf, sides=np.inf)
    for z in np.linspace(E.Zf - 3.3, zfl - 0.3, 8):
        for x in np.linspace(x0 + 0.3, x1 - 0.3, 9):
            best["back"] = min(best["back"], EC.first_wall(core, (x, y_bond + 0.16, z), (0, 1, 0)))
            best["front"] = min(best["front"], EC.first_wall(core, (x, y_bond - T.SLOT_FRONT - 0.01, z), (0, -1, 0)))
        for x, dx in ((x0 - 0.01, -1), (x1 + 0.01, 1)):
            best["sides"] = min(best["sides"], EC.first_wall(core, (x, y_bond - 0.1, z), (dx, 0, 0)))
    out["tail_slot_walls_mm"] = {k: round(v, 3) for k, v in best.items()}
    return out


# ----------------------------------------------------------------------------------------------
def measure(parts, chk):
    src = ES.load(T.P["DZ"])
    new, old = [parts["core"], parts["film"], parts["tpu"]], [src["hard"], src["soft"]]
    import enpire_measure as EM
    tip_z = D["tip_g"][2]
    out = dict(tip_profile=[])
    for d in (0.5, 1.7, 3.0, 5.0, 10.0):
        z = tip_z + d
        out["tip_profile"].append(dict(from_tip_mm=d, thickness_mm=round(EM.span_y(new, -3.5, z), 3),
                                       stock_thickness_mm=round(EM.span_y(old, -3.5, z), 3),
                                       width_mm=round(EM.width_x(new, z), 3), stock_width_mm=round(EM.width_x(old, z), 3)))
    fpc = json.load(open(os.path.join(T.OUT, "fpc_pcb", "drc.json")))
    pin = json.load(open(os.path.join(T.OUT, "fpc_pcb", "pinmap.json")))
    tm = json.load(open(os.path.join(T.OUT, "taxel_map.json")))
    core = parts["core"]
    h = T.P["NAIL_PITCH"] / 2
    import enpire_tip_fpc as TF
    cells = [TF.flat_to_plane_pt(*t["flat_mm"]) for t in tm["taxels"]]
    v_tip = float(E.native_to_plane(E.g2n(np.array([D["tip_g"]])))[0, 1])          # the TCP tip (the nail's end point)
    out.update(
        tip_below_carriage_mm=D["tip_below_carriage_mm"], finger_root_to_tip_mm=round(float(E.Zs - tip_z), 2),
        laminate_length_mm=D["C_length"], tail_length_mm=pin["tail_length_mm"],
        core_volume_cm3=round(core.volume / 1000, 2), core_mass_g_pa12_mjf=round(core.volume / 1000 * 1.01, 1),
        tpu_insert_mass_g=round(src["soft"].volume / 1000 * 1.21, 1),
        stock_enpire_mass_g_solid_estimate=round((src["hard"].volume * 1.27 + src["soft"].volume * 1.21) / 1000, 1),
        nail_pocket_depth_mm=T.POCKET_D, taxels=fpc["taxels"], lines=fpc["lines"], pitch_mm=T.P["NAIL_PITCH"],
        sensing_area_mm2=round(len(cells) * T.P["NAIL_PITCH"] ** 2, 1), nail_face_area_mm2=round(NR["face"].area, 1),
        distal_taxel_edge_from_tip_mm=round(float(v_tip - (max(v for _, v in cells) + h)), 2),
        proximal_taxel_edge_from_nail_root_mm=round(float(min(v for _, v in cells) - h - NR["face"].bounds[1]), 2),
        sheets_part_at_s_mm=fpc["sheets_part_at_s_mm"], laminate_min_bend_radius=fpc["laminate_min_bend_radius"],
        pcb_free_mm2=fpc["pcb_free_mm2"], q_touch_mm=chk["contact"]["q_touch_mm"], stock_q_touch_mm=chk["contact"]["stock_q_touch_mm"],
        route_gap_to_tpu_mm=chk["route_gap_to_tpu_mm"], walls=chk["walls"], tail_room_mm=fpc["tail_room_mm"],
        shape={k: v for k, v in chk["shape"].items() if k.startswith(("depth_map", "core_vs", "hard_frame_vs", "film_vs", "nail_root",
                                                                      "laminate_exposed"))})
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cf.set_i2rt(sys.argv[1])
    os.makedirs(CHK, exist_ok=True)
    parts = load_parts()
    rep = dict(internal=internal(parts), route_gap_to_tpu_mm=route_gaps(parts), contact=first_contact(parts),
               shape=shape(parts), walls=walls(parts))
    rep["clearance_sweep"] = EC.fit(parts, names=("socket", "core", "tpu", "ph_thumbscrews"))
    json.dump(rep, open(os.path.join(CHK, "checks.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k != "clearance_sweep"}, indent=1))
    print("== clearance sweep, minimum over q in [0, 47.5] mm:")
    for part in ("socket", "core", "tpu", "ph_thumbscrews"):
        rr = [r for r in rep["clearance_sweep"] if r["part"] == part]
        h = min(rr, key=lambda r: r["vs_housing"]); o = min(rr, key=lambda r: r["vs_opposite_carriage"])
        print(f"   {part:16s} vs housing {h['vs_housing']:6.3f} (q={h['q_mm']})  vs opposite carriage {o['vs_opposite_carriage']:6.3f} "
              f"(q={o['q_mm']})  overlap {max(r['vol_x_housing'] + r['vol_x_opposite'] for r in rr)}")
    m = measure(parts, rep)
    json.dump(m, open(os.path.join(CHK, "measurements.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in m.items() if k not in ("walls", "shape")}, indent=1))
