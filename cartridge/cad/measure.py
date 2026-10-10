"""
Measure the numbers quoted in README.md from the exported geometry (so the README can't drift).
Usage (from cartridge/): python3 cad/measure.py [i2rt_repo_root]   -> prints a table, writes out/check/measurements.json
"""
import json
import os
import sys
import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_fit as cf          # noqa: E402
import yam_tactile_finger as F  # noqa: E402

P, D = F.P, F.DERIVED
OUT = F.OUT


def load(n):
    return trimesh.load(os.path.join(OUT, n + ".stl"))


def ray_span(mesh, origin, direction):
    loc, _, _ = mesh.ray.intersects_location(np.array([origin], float), np.array([direction], float), multiple_hits=True)
    return np.asarray(loc, float).reshape(-1, 3)


def thickness_y(mesh, x, z):
    """Material thickness along y at (x, z): sum of inside segments."""
    loc = ray_span(mesh, (x, -30.0, z), (0, 1, 0))
    ys = np.unique(np.round(loc[:, 1], 3))
    if len(ys) < 2:
        return 0.0
    return float(sum(ys[i + 1] - ys[i] for i in range(0, len(ys) - 1, 2)))


def outer_span_y(meshes, x, z):
    ys = []
    for m in meshes:
        loc = ray_span(m, (x, -30.0, z), (0, 1, 0))
        ys += list(loc[:, 1])
    return (max(ys) - min(ys)) if ys else 0.0


def width_x(meshes, z):
    xs = []
    for m in meshes:
        s = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if s is not None:
            xs += list(s.vertices[:, 0])
    return (max(xs) - min(xs)) if xs else 0.0


def wall_around_hole(mesh, cx, cy, r, zs, n_dir=72):
    """Min wall thickness around a vertical hole (any shape: round, slot, chamfered): cast radial
    rays from the hole axis; wall = 2nd hit - 1st hit (hole wall -> next surface)."""
    best = np.inf
    for z in zs:
        o = np.array([cx, cy, z])
        for t in np.linspace(0, 2 * np.pi, n_dir, endpoint=False):
            d = np.array([np.cos(t), np.sin(t), 0.0])
            loc = ray_span(mesh, o, d)
            dist = np.unique(np.round(np.linalg.norm(loc - o, axis=1), 3))   # drop duplicate edge hits
            if len(dist) >= 2:
                best = min(best, float(dist[1] - dist[0]))
    return round(best, 2)


def main():
    res = {}
    sock, cart, skin = load("socket"), load("cartridge"), load("skin")
    res["volume_cm3"] = {n: round(m.volume / 1000, 2) for n, m in (("socket", sock), ("cartridge", cart), ("skin", skin))}

    # --- fingertip size vs stock (right finger at q=0) ---
    _, _, _, _, TR = cf.yam_meshes(0.0)
    stock = sorted(TR.split(only_watertight=False), key=lambda p: -p.area)[0]
    tip = P["TCP_Z"]
    prof = []
    for dz in (0.5, 1.7, 3.0, 5.0, 10.0, 15.0):
        z = tip + dz
        prof.append(dict(from_tip_mm=dz,
                         ours_thick_centre=round(outer_span_y([cart, skin], 0.0, z), 2),
                         ours_thick_max=round(max(outer_span_y([cart, skin], x, z) for x in np.linspace(-13, 13, 53)), 2),
                         stock_thick_centre=round(outer_span_y([stock], 0.0, z), 2),
                         ours_width=round(width_x([cart, skin], z), 2),
                         stock_width=round(width_x([stock], z), 2)))
    res["tip_profile"] = prof

    # --- walls ---
    zpad = np.linspace(D["PAD_DIST_Z"] + 0.3, D["PAD_PROX_Z"] - 0.3, 40)
    xs = np.linspace(-10.5, 10.5, 15)
    res["wall_behind_pad_min_mm"] = round(min(thickness_y(cart, x, z) for x in xs for z in zpad), 2)
    sz = [D["Zs"] + 0.5, D["Zs"] + 2.5, D["Zs"] + 4.5]
    cz = [D["Zs"] - 0.3, D["Zs"] - 1.5, D["Zs"] - 2.4]
    res["socket_wall_around_dowel_mm"] = min(wall_around_hole(sock, x, y, P["DOWEL_PRESS"] / 2, sz) for x, y in P["DOWEL_XY"])
    res["cartridge_wall_around_dowel_mm"] = min(wall_around_hole(cart, x, y, P["DOWEL_D"] / 2 + 0.025, cz) for x, y in P["DOWEL_XY"])
    res["socket_wall_around_thumb_insert_mm"] = min(wall_around_hole(sock, x, y, P["INSERT_D"] / 2, sz) for x, y in P["THUMB_XY"])
    zi = [P["Z_CARRIAGE"] - 0.5 - P["OPP_RELIEF"] * 0, P["Z_CARRIAGE"] - 3.0, P["Z_CARRIAGE"] - 5.5]
    res["socket_wall_around_mount_insert_mm"] = min(wall_around_hole(sock, x, y, P["MOUNT_INSERT_D"] / 2, zi) for x, y in P["MOUNT_HOLES"])
    res["cartridge_wall_around_thumb_hole_mm"] = min(wall_around_hole(cart, x, y, P["M3_CLEAR"] / 2, [D["Zf"] + 1, D["Zf"] + 4.5, D["Zs"] - 1])
                                                     for x, y in P["THUMB_XY"])

    # --- clearances (from the fit check) ---
    rep = json.load(open(os.path.join(OUT, "check", "interference.json")))
    sw = rep["clearance_sweep"]
    res["min_clearance_vs_opposite_carriage_mm"] = min(r["vs_opposite_carriage"] for r in sw)
    res["min_clearance_vs_housing_mm"] = min(r["vs_housing"] for r in sw)
    res["intended_overlaps_q0_mm3"] = {k: v for k, v in rep["q=0.0"].items() if v != 0.0}

    # --- tail / pinmap / sim ---
    pin = json.load(open(os.path.join(OUT, "fpc_pcb", "pinmap.json")))
    res["tail_cut_length_mm"] = pin["tail"]["cut_length"]
    res["rows_readout_order"] = pin["rows_readout_order"]
    os.makedirs(os.path.join(OUT, "check"), exist_ok=True)
    json.dump(res, open(os.path.join(OUT, "check", "measurements.json"), "w"), indent=1)
    return res


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cf.set_i2rt(sys.argv[1])
    r = main()
    print(json.dumps({k: v for k, v in r.items() if k != "tip_profile"}, indent=1))
    print("tip profile (mm):")
    for p in r["tip_profile"]:
        print("  ", p)
