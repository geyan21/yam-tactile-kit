"""
ENPIRE finger source geometry: fetch, verify and place it on the YAM.

The original finger is Wenli Xiao's ENPIRE gripper finger (MakerWorld model 2984746, CC BY 4.0).
The original STLs are not committed here; this module downloads the copies from the community
Open-ENPIRE-Gripper repository at a pinned commit and checks their SHA-256 (the same files and
hashes as the engineering study on main). Files land in cartridge/third_party/enpire/ (ignored by git).
(ENPIRE-T Tip's sim model and the web viewer carry a placed copy of the unchanged TPU insert, under its
CC BY 4.0 licence, with attribution in out/enpire_tip/.)

Native ENPIRE axes: X across the insert width, -Y toward the tip, -Z out of the contact face.
Gripper frame (i2rt linear_4310 'gripper' body, right finger at q = 0, mm): x lateral, y closing
axis (+y away from the object for the right finger), z along the gripper axis (tips toward -z).

Placement: the two O4.6 insert bores sit on the YAM's M3 points (x -8.25 / 12.75, y 17.15), which
fixes x and y. The rotation is proper (det +1), so the STL is the right finger as is.

Usage (from cartridge/): python3 cad/enpire_source.py       downloads + verifies
"""
import hashlib
import os
import sys
import urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                                        # cartridge/
SRC_DIR = os.environ.get("ENPIRE_SRC") or os.path.join(ROOT, "third_party", "enpire")
COMMIT = "72cc833bfe1521132318db6a2724e7e9bbb8cd6e"
BASE = f"https://raw.githubusercontent.com/pgeedh/Open-ENPIRE-Gripper/{COMMIT}/grippers-stl/enpire_i2rt_yam_stl/"
FILES = {
    "hard": ("i2rt_UCG_Hard.stl", "b59f7e26b280cd31e73f2efeb19d02583ff504edd83d70e6e508f0ce976856df"),
    "soft": ("I2RT_UCG_Soft.stl", "6dc8c8ae8ebe5f4981e4bd097b95b36c9c98cac23020d237aed8418db9c0bbdc"),
}
ATTRIBUTION = ("Derived from the ENPIRE gripper finger by Wenli Xiao (NVIDIA GEAR ENPIRE), "
               "https://makerworld.com/en/models/2984746, licensed CC BY 4.0. Source STLs via "
               f"github.com/pgeedh/Open-ENPIRE-Gripper@{COMMIT[:7]}. Modified: rigid cradle with a sensor seat, "
               "filled nail slot, nail sensor pocket, plug-in dock flange, flex routing.")

# native -> gripper frame. Stock mount: the finger's top (the 5 mm rib above the 787 mm^2 root face)
# bears on the carriage face z = -70.38, which is the only seating the i2rt meshes allow (no slot
# for the rib is modelled in the carriage). If the real carriage has a slot for that rib, the stock
# finger sits 5.0 mm higher than this; the tactile finger does not depend on it (it docks on the socket).
R_NATIVE = np.array([[-1.0, 0, 0], [0, 0, 1.0], [0, 1.0, 0]])
T_STOCK = np.array([-7.96, 2.87, -67.61])


def fetch(force=False):
    os.makedirs(SRC_DIR, exist_ok=True)
    for key, (name, sha) in FILES.items():
        path = os.path.join(SRC_DIR, name)
        if force or not os.path.isfile(path):
            print("downloading", name)
            urllib.request.urlretrieve(BASE + name, path)
        got = hashlib.sha256(open(path, "rb").read()).hexdigest()
        if got != sha:
            raise SystemExit(f"{name}: SHA-256 {got} does not match the pinned {sha}")
    return {k: os.path.join(SRC_DIR, n) for k, (n, _) in FILES.items()}


def paths():
    p = {k: os.path.join(SRC_DIR, n) for k, (n, _) in FILES.items()}
    missing = [v for v in p.values() if not os.path.isfile(v)]
    if missing:
        raise SystemExit(f"ENPIRE source STLs missing ({', '.join(map(os.path.basename, missing))}).\n"
                         f"Run `make enpire-src` in cartridge/ (or python3 cad/enpire_source.py).")
    for k, (n, sha) in FILES.items():
        if hashlib.sha256(open(p[k], "rb").read()).hexdigest() != sha:
            raise SystemExit(f"{n} does not match its pinned SHA-256; re-run `make enpire-src`.")
    return p


def native_to_gripper(dz=0.0):
    """4x4 transform from native ENPIRE mm to the gripper frame (right finger, q = 0), with the
    finger lowered by -dz along z (dz < 0 moves it down)."""
    M = np.eye(4)
    M[:3, :3] = R_NATIVE
    M[:3, 3] = T_STOCK + np.array([0.0, 0.0, dz])
    return M


def to_gripper_pts(pts, dz=0.0):
    pts = np.atleast_2d(np.asarray(pts, float))
    return pts @ R_NATIVE.T + T_STOCK + np.array([0.0, 0.0, dz])


def to_native_pts(pts, dz=0.0):
    pts = np.atleast_2d(np.asarray(pts, float))
    return (pts - T_STOCK - np.array([0.0, 0.0, dz])) @ R_NATIVE


def load(dz=0.0):
    import trimesh
    p = paths()
    out = {}
    for k in ("hard", "soft"):
        m = trimesh.load(p[k], force="mesh")
        m.apply_transform(native_to_gripper(dz))
        out[k] = m
    return out


if __name__ == "__main__":
    p = fetch(force="--force" in sys.argv)
    for k, v in p.items():
        print(f"{k:5s} {v}  OK")
