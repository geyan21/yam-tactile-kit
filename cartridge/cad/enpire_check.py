"""
Checks for the ENPIRE-T cartridge against the i2rt YAM Linear-4310 meshes and the original ENPIRE.

  fit       clearance of socket / core / skin / thumbscrews to the housing and the opposite carriage
            over the full stroke, overlap volumes, and the first finger-to-finger contact (q_touch)
  internal  overlap volumes between the parts of one finger (core, skin, flex, film, PCB, socket ...)
  shape     how far the new outer surfaces sit from the original ENPIRE ones (skin vs TPU front,
            core vs hard frame, film vs nail plane)
  walls     thinnest material under the nail pocket, around the dock holes, beside the groove ...

Usage (from cartridge/): python3 cad/enpire_check.py [i2rt_repo_root]  -> out/enpire/check/*.json
"""
import json
import os
import sys
import numpy as np
import trimesh
from shapely.geometry import box as sbox
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_fit as cf          # noqa: E402
import enpire_finger as E       # noqa: E402
import enpire_source as ES      # noqa: E402

OUT = E.OUT
CHK = os.path.join(OUT, "check")
V02 = E.F.OUT                   # shared socket-side parts come from the v0.2 build
SOCKET_SIDE = ("socket", "ph_socket_pcb", "ph_pogo_pins", "ph_thumbscrews", "ph_dowels")


def load_parts():
    out = {k: trimesh.load(os.path.join(OUT, k + ".stl")) for k in E.PART_NAMES}
    for k in SOCKET_SIDE:
        out[k] = trimesh.load(os.path.join(V02, k + ".stl"))
    return out


def dist(mesh, pts, chunk=1500):
    """Unsigned distance from points to a mesh surface, in chunks (keeps memory bounded)."""
    out = []
    for i in range(0, len(pts), chunk):
        out.append(trimesh.proximity.closest_point(mesh, pts[i:i + chunk])[1])
    return np.concatenate(out) if out else np.zeros(0)


def clearance(a, b, n=8000, seed=0, margin=6.0):
    """Min distance (mm) between meshes a and b, like check_fit.clearance but with small chunks."""
    rng = np.random.default_rng(seed)
    pa = np.vstack([a.vertices, trimesh.sample.sample_surface(a, n, seed=int(rng.integers(1 << 31)))[0]])
    pb = np.vstack([b.vertices, trimesh.sample.sample_surface(b, n, seed=int(rng.integers(1 << 31)))[0]])
    pa, pb = cf._near(pa, b, margin), cf._near(pb, a, margin)
    d = margin
    if len(pa):
        d = min(d, float(dist(b, pa, 800).min()))
    if len(pb):
        d = min(d, float(dist(a, pb, 800).min()))
    return round(d, 3)


def placed(parts, q, side):
    out = {}
    for k, m in parts.items():
        mm = m.copy()
        mm.apply_translation([0, q * 1000, 0])
        if side < 0:
            mm.apply_transform(np.diag([-1, -1, 1, 1.0]))
        out[k] = mm
    return out


# ----------------------------------------------------------------------------------------------
def fit(parts, qs=np.linspace(0.0, 0.0475, 9)):
    rows = []
    for q in qs:
        G, CL, CR, _, _ = cf.yam_meshes(q)
        Rf = placed(parts, q, +1)
        for nm in ("socket", "core", "skin", "ph_thumbscrews"):
            m = Rf[nm]
            rows.append(dict(q_mm=round(q * 1000, 2), part=nm, vs_housing=clearance(m, G),
                             vs_opposite_carriage=clearance(m, CL), vs_own_carriage_overlap=round(cf.ivol(m, CR), 3),
                             vol_x_housing=round(cf.ivol(m, G), 3), vol_x_opposite=round(cf.ivol(m, CL), 3)))
    return rows


def touch_q(meshes):
    """Smallest per-jaw opening q (m) at which two such fingers (right, and left = right turned 180
    deg about z) stop overlapping: where they meet when the gripper closes on nothing."""
    keys = list(meshes)
    def overlap(q):
        R, L = placed(meshes, q, 1), placed(meshes, q, -1)
        return max(cf.ivol(R[a], L[b]) for a in keys for b in keys)
    lo, hi = 0.0, 0.004
    assert overlap(hi) == 0, "fingers still overlap at 4 mm opening"
    for _ in range(18):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if overlap(mid) > 0 else (lo, mid)
    return hi


def first_contact(parts):
    """q_touch for ENPIRE-T and for the stock ENPIRE (same placement), and which surfaces meet."""
    q = touch_q({k: parts[k] for k in ("core", "skin", "film")})
    src = ES.load(E.P["DZ"])
    q_stock = touch_q({"hard": src["hard"], "soft": src["soft"]})
    R, L = placed(parts, q + 0.00005, 1), placed(parts, q + 0.00005, -1)
    pairs = {}
    for a in ("core", "skin", "film", "flex", "socket", "ph_thumbscrews"):
        for b in ("core", "skin", "film", "flex", "socket", "ph_thumbscrews"):
            if a <= b:
                pairs[f"{a}-{b}"] = clearance(R[a], L[b], n=3000, margin=3.0)
    # where they touch: lowest-y points of the right finger
    pts = np.vstack([R["film"].vertices, R["core"].vertices])
    touch = pts[pts[:, 1] < pts[:, 1].min() + 0.02]
    return dict(q_touch_mm=round(q * 1000, 3), stock_q_touch_mm=round(q_stock * 1000, 3), gap_by_pair_at_touch_mm=pairs,
                touch_z_range=[round(float(touch[:, 2].min()), 2), round(float(touch[:, 2].max()), 2)])


def internal(parts):
    R = parts
    pairs = [("core", "skin"), ("core", "flex"), ("core", "film"), ("skin", "flex"), ("skin", "film"), ("flex", "film"),
             ("core", "ph_finger_pcb"), ("core", "ph_finger_pcb_parts"), ("flex", "ph_finger_pcb_parts"),
             ("core", "socket"), ("skin", "socket"), ("core", "ph_thumbscrews"), ("core", "ph_dowels"),
             ("core", "ph_pogo_pins"), ("ph_finger_pcb", "ph_pogo_pins"), ("ph_finger_pcb_parts", "socket"),
             ("ph_finger_pcb", "socket"), ("flex", "socket")]
    return {f"{a} x {b}": round(cf.ivol(R[a], R[b]), 4) for a, b in pairs}


# ----------------------------------------------------------------------------------------------
def depth_map(meshes, xs, zs, y0=-25.0):
    """First surface hit seen from the object side (+y rays) on an (x, z) grid; nan = no hit."""
    m = trimesh.util.concatenate(meshes)
    X, Z = np.meshgrid(xs, zs)
    o = np.c_[X.ravel(), np.full(X.size, y0), Z.ravel()]
    d = np.tile([0, 1.0, 0], (X.size, 1))
    loc, idx, _ = m.ray.intersects_location(o, d, multiple_hits=False)
    out = np.full(X.size, np.nan)
    out[idx] = loc[:, 1]
    return out.reshape(X.shape)


def shape(parts):
    """Contact-side shape vs the original ENPIRE (both placed identically): the depth map seen by an
    approaching object, plus the core vs the original frame away from the modified zones."""
    src = ES.load(E.P["DZ"])
    hard, soft = src["hard"], src["soft"]
    out = {}
    xs = np.arange(-10.75, 10.76, 0.5)              # offset grid: no ray lands in the 0.05 mm skin-rail gap
    zs = np.arange(E.Zf - 0.5, -193.6, -0.5)
    a = depth_map([hard, soft], xs, zs)
    b = depth_map([parts["core"], parts["skin"], parts["film"]], xs, zs)
    X, Z = np.meshgrid(xs, zs)
    zn = Z - E.CZ                                           # native y of each row
    both = ~np.isnan(a) & ~np.isnan(b)
    diff = np.where(both, b - a, np.nan)                    # + = ENPIRE-T surface further from the object
    zones = dict(cradle=(zn <= -14.5) & (zn >= -92.0) & (np.abs(X + 0.46) <= 7.0),
                 transition=(zn < -92.0) & (zn > -96.9) & (np.abs(X + 0.46) <= 7.0),
                 nail=(zn <= -96.9),
                 sides=(zn <= -14.5) & (zn > -96.9) & (np.abs(X + 0.46) > 7.0))
    for k, msk in zones.items():
        v = np.abs(diff[msk & both])
        out[f"depth_map_{k}_mm"] = dict(n=int(v.size), p50=round(float(np.median(v)), 4),
                                        p95=round(float(np.percentile(v, 95)), 4), max=round(float(v.max()), 4))
    out["depth_map_coverage_change"] = int((np.isnan(a) != np.isnan(b)).sum())
    # the one change to the outside: the V-notch where ENPIRE's TPU insert meets the nail is filled
    # flush, because the laminate passes through it (diff < 0: ENPIRE-T surface nearer the object)
    filled = zones["transition"] & both & (diff < -0.1)
    rows = np.where(filled.any(axis=1))[0]
    depth = -diff[filled & (a < 5.0)]                       # a >= 5: ray went into the slit at the notch root
    out["transition_notch_filled"] = dict(
        z_range_mm=[round(float(Z[rows, 0].max()), 2), round(float(Z[rows, 0].min()), 2)] if rows.size else None,
        height_mm=round(0.5 * rows.size, 1),                # grid rows (0.5 mm) where the surfaces differ by > 0.1 mm
        max_depth_mm=round(float(depth.max()), 2) if depth.size else 0.0,
        slit_at_root=bool((filled & (a >= 5.0)).any()))
    np.savez_compressed(os.path.join(CHK, "depth_maps.npz"), xs=xs, zs=zs, enpire=a, enpire_t=b)
    # core vs hard frame, away from the modified zones (flange, slot fill, pocket, relief cuts)
    pts = trimesh.sample.sample_surface(hard, 12000, seed=2)[0]
    keep = pts[:, 2] < E.Zf - 6.0
    pn = E.g2n(pts)
    in_slot = (pn[:, 1] < -96.8) & (pn[:, 1] > -109.2) & (pn[:, 2] > -2.6) & (pn[:, 2] < 5.0)
    near_face = np.abs((pn - E.NO) @ E.NN) < 1.2
    # surfaces that touched the TPU insert, or sat in the notch / under the flange that the core now
    # fills, are inside the new core; the rest of the frame, back included, must be unchanged
    from shapely import contains_xy
    pr0 = E.build_profile()
    filled_2d = unary_union([pr0["tpu"].buffer(1.0), sbox(-97.7, -4.5, -92.9, 3.7), sbox(-18.1, E.P["Z_SLOT"] - 1.5, -13.0, 13.0)])
    near_tpu = (pn[:, 0] > -15.6) & (pn[:, 0] < 0.6) & contains_xy(filled_2d, pn[:, 1], pn[:, 2])
    thumb = np.min([np.hypot(pts[:, 0] - tx, pts[:, 1] - ty) for tx, ty in E.FP["THUMB_XY"]], axis=0) < 5.6
    keep &= ~in_slot & ~near_face & ~near_tpu & ~(thumb & (pts[:, 2] > E.Zf - 5.5))
    d = dist(parts["core"], pts[keep])
    out["core_vs_hard_frame_mm"] = dict(n=int(keep.sum()), p50=round(float(np.median(d)), 4),
                                        p99=round(float(np.percentile(d, 99)), 4), max=round(float(d.max()), 4))
    # film outer surface vs the original nail plane (the nail face must not move)
    pr = E.build_profile()
    pl = E.derived(pr, E.nail_regions(pr))["nail_plane_g"]
    f = parts["film"]
    dev = (f.vertices - np.array(pl["origin"])) @ np.array(pl["normal"])
    top = dev[dev > -0.05]
    out["film_vs_nail_plane_mm"] = dict(max_abs=round(float(np.abs(top).max()), 4))
    return out


# ----------------------------------------------------------------------------------------------
def first_wall(mesh, origin, direction, start=0.02):
    """Material thickness from `origin` (just inside a surface) along `direction`."""
    loc, _, _ = mesh.ray.intersects_location(np.array([origin], float), np.array([direction], float), multiple_hits=True)
    if len(loc) == 0:
        return np.inf
    d = np.sort(np.linalg.norm(loc - origin, axis=1))
    d = d[d > start]
    return float(d[0]) if len(d) else np.inf


def walls(parts):
    core = parts["core"]
    pr = E.build_profile()
    N = E.nail_regions(pr)
    out = {}
    # nail: material behind the pocket floor, along -normal, over the flex outline
    from shapely.geometry import Point
    fl = N["flex"]
    us = np.arange(fl.bounds[0], fl.bounds[2], 0.5)
    vs = np.arange(max(fl.bounds[1], N["face"].bounds[1] + 0.5), fl.bounds[3], 0.5)
    best = (np.inf, None)
    for u in us:
        for v in vs:
            if not fl.contains(Point(u, v)):
                continue
            o = E.n2g(E.plane_to_native(u, v, -E.POCKET_D - 0.01))[0]
            nrm = E.n2g(-E.NN[None]) - E.n2g(np.zeros((1, 3)))
            t = first_wall(core, o, nrm[0])
            if t < best[0]:
                best = (t, (round(u, 2), round(v, 2)))
    out["nail_behind_pocket_min_mm"] = dict(t=round(best[0], 3), at_uv=best[1])
    # lips between the pocket and the groove / the face edge (in-plane)
    lip_g = N["pocket"].distance(N["groove"])
    face_edge = N["face"].exterior
    v_prox = N["face"].bounds[1] + 0.6            # the neck runs through the proximal edge on purpose
    lip_e = min(face_edge.distance(Point(c)) for g in getattr(N["pocket"], "geoms", [N["pocket"]])
                for c in g.exterior.coords if N["face"].contains(Point(c)) and c[1] > v_prox)
    out["nail_lip_pocket_to_groove_mm"] = round(lip_g, 3)
    out["nail_lip_pocket_to_face_edge_mm"] = round(lip_e, 3)
    # flange: around the dock holes (reuse the v0.2 ray method)
    import measure as M
    zs = np.linspace(E.Zf + 0.3, E.Zs - 0.3, 7)
    for (tx, ty) in E.FP["THUMB_XY"]:
        out[f"wall_thumbscrew_{'L' if tx < 0 else 'R'}_mm"] = round(M.wall_around_hole(core, tx, ty, E.FP["M3_CLEAR"] / 2, zs), 3)
    zd = np.linspace(E.Zs - E.FP["DOWEL_HOLE_DEPTH"] + 0.2, E.Zs - 0.7, 4)
    for (dx, dy) in E.FP["DOWEL_XY"]:
        out[f"wall_dowel_{'L' if dx < 0 else 'R'}_mm"] = round(M.wall_around_hole(core, dx, dy, (E.FP["DOWEL_D"] + 0.05) / 2, zd), 3)
    # cavity floor (between the component cavity and the flange bottom / the core below)
    cav, pcb = E.P["CAVITY"], E.P["PCB"]
    zfl = E.Zs - pcb["recess"] - pcb["t"] - cav["depth"]
    zone = E.pcb_outline(cav["inset"] + 0.5)
    best = np.inf
    for x in np.linspace(zone.bounds[0], zone.bounds[2], 11):
        for y in np.linspace(zone.bounds[1], zone.bounds[3], 11):
            if zone.contains(Point(x, y)):
                best = min(best, first_wall(core, (x, y, zfl - 0.01), (0, 0, -1)))
    out["cavity_floor_min_mm"] = round(best, 3)
    # front wall of the tail slot (flange front face -> slot)
    y_slot0 = E.P["Z_SLOT"] - E.P["FLEX_T"] - 0.25 + 2.87
    best = np.inf
    for x in np.linspace(-7.0, 6.0, 9):
        for z in np.linspace(E.Zf + 0.3, zfl - 0.3, 4):
            best = min(best, first_wall(core, (x, y_slot0 - 0.01, z), (0, -1, 0)))
    out["tail_slot_front_wall_mm"] = round(best, 3)
    # skin: thinnest point over the flex (normal direction), excluding the feather end
    fp = E.FlexPath(pr)
    s0, s1 = fp.s_at_y(-15.0), fp.s_at_y(E.P["SKIN_END_Y"] + 2.0)
    best = (np.inf, None)
    for s in np.linspace(s0, s1, 160):
        for u in (-6.5, -0.46, 5.5):
            g, n = fp.point_g(u, s, lift=E.P["FLEX_T"] + 0.01)
            t = first_wall(parts["skin"], g[0], n[0])
            if t < best[0]:
                best = (t, round(float(s), 2))
    out["skin_over_flex_min_mm"] = dict(t=round(best[0], 3), at_s=best[1])
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cf.set_i2rt(sys.argv[1])
    os.makedirs(CHK, exist_ok=True)
    parts = load_parts()
    rep = dict(internal=internal(parts), contact=first_contact(parts), shape=shape(parts), walls=walls(parts))
    rep["clearance_sweep"] = fit(parts)
    json.dump(rep, open(os.path.join(CHK, "checks.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k != "clearance_sweep"}, indent=1))
    print("== clearance sweep, minimum over q in [0, 47.5] mm:")
    for part in ("socket", "core", "skin", "ph_thumbscrews"):
        rr = [r for r in rep["clearance_sweep"] if r["part"] == part]
        h = min(rr, key=lambda r: r["vs_housing"]); o = min(rr, key=lambda r: r["vs_opposite_carriage"])
        print(f"   {part:16s} vs housing {h['vs_housing']:6.3f} (q={h['q_mm']})  vs opposite carriage {o['vs_opposite_carriage']:6.3f} "
              f"(q={o['q_mm']})  overlap {max(r['vol_x_housing'] + r['vol_x_opposite'] for r in rr)}")
