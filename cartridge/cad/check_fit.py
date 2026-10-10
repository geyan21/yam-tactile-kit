"""
Fit / interference checks of the tactile finger against the i2rt YAM Linear-4310 meshes.

Usage (from cartridge/): python3 cad/check_fit.py [i2rt_repo_root]
The i2rt checkout defaults to $I2RT_ROOT, else cartridge/third_party/i2rt (`make i2rt` fetches it).
Writes a JSON report to out/check/.
"""
import json
import os
import sys
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation as R

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # cartridge/
OUT = os.path.join(ROOT, "out")
CHK = os.path.join(OUT, "check")
os.makedirs(CHK, exist_ok=True)
I2RT = os.environ.get("I2RT_ROOT") or os.path.join(ROOT, "third_party", "i2rt")
I2RT_COMMIT = "120c3c81400171174604e503943f8d1ebc891058"   # meshes measured at this commit


def set_i2rt(path):
    global I2RT
    I2RT = path


def assets_dir():
    a = os.path.join(I2RT, "i2rt/robot_models/gripper/linear_4310/assets/")
    if not os.path.isdir(a):
        raise SystemExit(f"i2rt meshes not found at {a}\n"
                         f"Run `make i2rt` in cartridge/, or set I2RT_ROOT to an i2rt checkout ({I2RT_COMMIT[:7]}).")
    return a
P = json.load(open(os.path.join(OUT, "params.json")))
D = P["derived"]
Z_CAR = P["params"]["Z_CARRIAGE"]


def quat(w):
    return R.from_quat([w[1], w[2], w[3], w[0]]).as_matrix()


def place(mesh, gpos, gq, bpos=(0, 0, 0), bq=(1, 0, 0, 0), axis=(0, 0, 1), q=0.0):
    m = mesh.copy()
    T = np.eye(4); T[:3, :3] = quat(gq); T[:3, 3] = gpos
    B = np.eye(4); B[:3, :3] = quat(bq); B[:3, 3] = np.array(bpos) + quat(bq) @ (np.array(axis) * q)
    m.apply_transform(B @ T)
    m.apply_scale(1000.0)
    return m


def yam_meshes(q):
    A = assets_dir()
    g = trimesh.load(A + "gripper.stl")
    tl = trimesh.load(A + "tip_left.stl")
    tr = trimesh.load(A + "tip_right.stl")
    G = place(g, (-0.014, -0.0463995, 0.0731), (1, 0, 0, 0))
    L = place(tl, (0.129783, 0.00999321, -0.0914614), (0.499998, 0.5, 0.500002, 0.5),
              (-0.0238981, 0.0450619, -0.0545599), (0.499998, -0.5, -0.5, -0.500002), (0, 0, -1), q)
    Rr = place(tr, (-0.0379932, 0.129783, 0.00133753), (0.707105, -0.707108, 0, 0),
               (0.0238981, -0.0450619, -0.0545599), (0.707105, 0.707108, 0, 0), (0, 0, -1), q)
    # keep only the carriage (everything above the finger mounting face, cut exactly at the face so
    # near-contacts with OUR parts show up as ~0 clearance instead of being trimmed away)
    def carriage(m):
        parts = sorted(m.split(only_watertight=False), key=lambda p: -p.area)
        body = parts[0]
        return body.slice_plane([0, 0, Z_CAR], [0, 0, 1], cap=True)
    return G, carriage(L), carriage(Rr), L, Rr


def finger(q, side):
    """Our parts for one side at gripper opening q (m). side = +1 right, -1 left."""
    names = ["socket", "cartridge", "skin", "ph_pad", "ph_finger_pcb", "ph_finger_pcb_parts",
             "ph_socket_pcb", "ph_pogo_pins", "ph_thumbscrews", "ph_dowels"]
    out = {}
    for n in names:
        m = trimesh.load(os.path.join(OUT, n + ".stl"))
        m.apply_translation([0, q * 1000, 0])           # right finger opens toward +y
        if side < 0:
            m.apply_transform(np.diag([-1, -1, 1, 1.0]))  # left = right rotated 180 deg about z
        out[n] = m
    return out


def ivol(a, b):
    try:
        i = trimesh.boolean.intersection([a, b], engine="manifold")
        return float(abs(i.volume)) if i is not None and len(i.faces) else 0.0
    except Exception as e:  # noqa
        return float("nan")


def _near(points, mesh, margin):
    lo, hi = mesh.bounds[0] - margin, mesh.bounds[1] + margin
    return points[np.all((points >= lo) & (points <= hi), axis=1)]


def _min_dist(points, mesh, chunk=4000):
    best = np.inf
    for i in range(0, len(points), chunk):
        d = trimesh.proximity.closest_point(mesh, points[i:i + chunk])[1]
        best = min(best, float(d.min()))
    return best


def clearance(a, b, n=20000, seed=0, margin=6.0):
    """Min distance (mm) between meshes a and b (0 if touching/intersecting). Samples both surfaces,
    keeps only points within `margin` of the other mesh's bounding box, and runs in chunks."""
    rng = np.random.default_rng(seed)
    pa = np.vstack([a.vertices, trimesh.sample.sample_surface(a, n, seed=int(rng.integers(1 << 31)))[0]])
    pb = np.vstack([b.vertices, trimesh.sample.sample_surface(b, n, seed=int(rng.integers(1 << 31)))[0]])
    pa, pb = _near(pa, b, margin), _near(pb, a, margin)
    if len(pa) == 0 and len(pb) == 0:
        return float(margin)          # farther apart than the margin
    d = np.inf
    if len(pa):
        d = min(d, _min_dist(pa, b))
    if len(pb):
        d = min(d, _min_dist(pb, a))
    return round(min(d, margin), 3)


def sweep(qs=np.linspace(0.0, 0.0475, 9)):
    """Clearance of our moving parts vs the housing and the OPPOSITE carriage over the stroke."""
    rows = []
    for q in qs:
        G, CL, CR, _, _ = yam_meshes(q)
        Rf = finger(q, +1)
        for nm in ("socket", "cartridge", "skin", "ph_thumbscrews"):
            m = Rf[nm]
            rows.append(dict(q_mm=round(q * 1000, 2), part=nm,
                             vs_housing=round(clearance(m, G), 3),
                             vs_opposite_carriage=round(clearance(m, CL), 3),
                             vol_x_housing=round(ivol(m, G), 3), vol_x_opposite=round(ivol(m, CL), 3)))
    return rows


def report():
    rep = {}
    for q in (0.0, 0.0475):
        G, CL, CR, TL, TR = yam_meshes(q)
        Rf = finger(q, +1)
        Lf = finger(q, -1)
        r = {}
        mine_R = {k: v for k, v in Rf.items()}
        mine_L = {k: v for k, v in Lf.items()}
        # vs housing and both carriages
        for nm, m in mine_R.items():
            r[f"R.{nm} x housing"] = ivol(m, G)
            r[f"R.{nm} x left carriage"] = ivol(m, CL)
            r[f"R.{nm} x own carriage"] = ivol(m, CR)
        # right vs left parts (skins are expected to overlap slightly at q=0 by design)
        for a in ("socket", "cartridge", "skin", "ph_thumbscrews"):
            for b in ("socket", "cartridge", "skin", "ph_thumbscrews"):
                r[f"R.{a} x L.{b}"] = ivol(mine_R[a], mine_L[b])
        # internal: pad / pcb / pogos / dowels / screw inside the right finger
        pairs = [("ph_pad", "cartridge"), ("ph_pad", "skin"), ("ph_finger_pcb", "cartridge"),
                 ("ph_finger_pcb_parts", "cartridge"), ("ph_socket_pcb", "socket"), ("ph_pogo_pins", "socket"),
                 ("ph_pogo_pins", "ph_finger_pcb"), ("ph_pogo_pins", "cartridge"), ("ph_thumbscrews", "cartridge"),
                 ("ph_thumbscrews", "socket"), ("ph_dowels", "cartridge"), ("ph_dowels", "socket"),
                 ("socket", "cartridge"), ("skin", "cartridge"), ("ph_finger_pcb_parts", "socket")]
        for a, b in pairs:
            r[f"R.{a} x R.{b}"] = ivol(mine_R[a], mine_R[b])
        rep[f"q={q}"] = {k: round(v, 3) for k, v in r.items()}
    return rep


if __name__ == "__main__":
    if len(sys.argv) > 1:
        set_i2rt(sys.argv[1])
    rep = report()
    sw = sweep()
    rep["clearance_sweep"] = sw
    json.dump(rep, open(os.path.join(CHK, "interference.json"), "w"), indent=1)
    for q, r in rep.items():
        if q == "clearance_sweep":
            continue
        print("==", q)
        for k, v in r.items():
            if v != 0.0:
                print(f"   {k:45s} {v}")
    print("== clearance sweep (mm), minimum over q in [0, 47.5] mm:")
    for part in ("socket", "cartridge", "skin", "ph_thumbscrews"):
        rr = [r for r in sw if r["part"] == part]
        h = min(rr, key=lambda r: r["vs_housing"]); o = min(rr, key=lambda r: r["vs_opposite_carriage"])
        print(f"   {part:16s} vs housing {h['vs_housing']:6.3f} (q={h['q_mm']})   vs opposite carriage "
              f"{o['vs_opposite_carriage']:6.3f} (q={o['q_mm']})   overlap vol {max(r['vol_x_housing'] + r['vol_x_opposite'] for r in rr)}")
