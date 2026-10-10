"""
MuJoCo model of the i2rt YAM Linear-4310 gripper with the tactile cartridges and 2 x 128 touch
sensors (one box site per taxel on the skin surface).

Usage (from cartridge/): python3 cad/make_sim_model.py [i2rt_repo_root]
Writes ./out/sim/linear_4310_tactile.xml + assets/, then self-tests it: closes the gripper on a
block and checks that the touch sensors respond on both fingers.
Drop-in idea: point your arm MJCF at this file instead of i2rt's linear_4310.xml (same body,
joint and site names: gripper, tip_left/joint7, tip_right/joint8, tcp_site, grasp_site).
"""
import json
import os
import shutil
import sys
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation as R

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_fit as cf          # noqa: E402
import yam_tactile_finger as F  # noqa: E402

P, D = F.P, F.DERIVED
SIM = os.path.join(F.OUT, "sim")
ASSETS = os.path.join(SIM, "assets")
os.makedirs(ASSETS, exist_ok=True)

BODY = {   # from i2rt/robot_models/gripper/linear_4310/linear_4310.xml
    "left": dict(pos=(-0.0238981, 0.0450619, -0.0545599), quat=(0.499998, -0.5, -0.5, -0.500002), joint="joint7", sgn=-1,
                 inertial='pos="-0.0224716 0.0143408 -0.0426253" quat="0.498899 0.455348 -0.0576406 0.735143" mass="0.0710042" '
                           'diaginertia="6.24193e-05 6.01079e-05 2.83591e-05"'),
    "right": dict(pos=(0.0238981, -0.0450619, -0.0545599), quat=(0.707105, 0.707108, 0, 0), joint="joint8", sgn=+1,
                  inertial='pos="-0.0143408 -0.0224716 -0.0426253" quat="0.281222 0.8726 0.16705 -0.362738" mass="0.0710042" '
                            'diaginertia="6.24193e-05 6.01079e-05 2.83591e-05"'),
}


def rotm(wxyz):
    return R.from_quat([wxyz[1], wxyz[2], wxyz[3], wxyz[0]]).as_matrix()


def to_body(points_m, side):
    b = BODY[side]
    return (points_m - np.array(b["pos"])) @ rotm(b["quat"])      # = R^T (x - t), row vectors


def body_quat_of_gripper_axes(side):
    """Quaternion (wxyz) of an object aligned with the gripper axes, expressed in the body frame."""
    q = R.from_matrix(rotm(BODY[side]["quat"]).T).as_quat()
    return (q[3], q[0], q[1], q[2])


def fmt(v):
    return " ".join(f"{x:.6g}" for x in v)


def collision_boxes(n_beam=6):
    """Boxes (centre, half-size) in mm, right-finger gripper frame, that stay inside the real
    socket + cartridge: socket block, flange, and a stack of beam slices behind the taxel layer."""
    Zs, Zf = D["Zs"], D["Zf"]
    zt = P["Z_CARRIAGE"]
    out = []
    # socket (own-carriage part only; the relieved wing is left out)
    x0, x1 = P["CARRIAGE_X"][0], P["DOCK_HALF_X"]
    out.append((((x0 + x1) / 2, (P["Y_IN"] + P["Y_OUT"]) / 2, (Zs + zt) / 2), ((x1 - x0) / 2, (P["Y_OUT"] - P["Y_IN"]) / 2, (zt - Zs) / 2)))
    # flange
    hx = P["DOCK_HALF_X"] - 1.0
    out.append(((0, (P["Y_IN"] + P["Y_OUT"]) / 2, (Zs + Zf) / 2), (hx, (P["Y_OUT"] - P["Y_IN"]) / 2 - 0.5, (Zs - Zf) / 2)))
    # beam slices: y from just behind the skin (taxel boxes handle the face) to the back face
    zs = np.linspace(Zf, D["Z_END"] + 1.0, n_beam + 1)
    y0 = D["Y_FACE"] + 0.2
    for za, zb in zip(zs[:-1], zs[1:]):
        zlo, zhi = min(za, zb), max(za, zb)
        yb = F.y_back(zlo) - 0.3                     # back face is lowest at the slice's low end
        if zhi > P["INCLINE_END_Z"]:                 # inner face rises with z: use the slice's high end
            y_in = D["Y_FACE"] + (zhi - P["INCLINE_END_Z"]) * (P["Y_IN"] - D["Y_FACE"]) / (Zf - P["INCLINE_END_Z"])
            y0s = max(y0, y_in + 0.2)
        else:
            y0s = y0
        if yb <= y0s + 0.5:
            continue
        hxs = P["SENSE_HALF_X"] - 0.3
        out.append(((0, (y0s + yb) / 2, (za + zb) / 2), (hxs, (yb - y0s) / 2, abs(za - zb) / 2)))
    return out


def build():
    _, CL, CR, _, _ = cf.yam_meshes(0.0)
    carriages = {"left": CL, "right": CR}
    out_meshes = {}
    for side in ("left", "right"):
        parts = cf.finger(0.0, BODY[side]["sgn"])
        for name, key in (("socket", "socket"), ("cartridge", "cartridge"), ("skin", "skin")):
            m = parts[key].copy()
            m.vertices = to_body(m.vertices / 1000.0, side)
            fn = f"{name}_{side}.stl"; m.export(os.path.join(ASSETS, fn)); out_meshes[(name, side)] = fn
        c = carriages[side].copy()
        c.vertices = to_body(c.vertices / 1000.0, side)
        fn = f"carriage_{side}.stl"; c.export(os.path.join(ASSETS, fn)); out_meshes[("carriage", side)] = fn
    shutil.copy(os.path.join(cf.assets_dir(), "gripper.stl"), os.path.join(ASSETS, "gripper.stl"))

    tmap = json.load(open(os.path.join(F.OUT, "taxel_map.json")))
    hx = P["SENSE_HALF_X"] + P["SKIN_SIDE_T"]
    pad_half = np.array([hx, (P["SKIN_T"] - 0.4) / 2, (P["SKIN_TOP_Z"] - P["TCP_Z"]) / 2]) / 1000   # backing, recessed 0.4
    taxel_half = np.array([P["PITCH"] / 2 - 0.05, P["SKIN_T"] / 2, P["PITCH"] / 2 - 0.05]) / 1000
    site_half = np.array([P["PITCH"] / 2 - 0.02, 0.3, P["PITCH"] / 2 - 0.02]) / 1000

    L = ['<mujoco model="linear_4310_tactile">',
         '  <!-- generated by make_sim_model.py: i2rt linear_4310 + tactile cartridges, 2 x 128 touch sensors -->',
         '  <compiler angle="radian" meshdir="assets"/>',
         '  <default><default class="tac_vis"><geom contype="0" conaffinity="0" group="2"/></default></default>',
         '  <asset>', '    <mesh name="gripper" file="gripper.stl"/>']
    for (name, side), fn in out_meshes.items():
        L.append(f'    <mesh name="{name}_{side}" file="{fn}"/>')
    L += ['  </asset>', '  <worldbody>',
          '    <body name="gripper" pos="0 0 0" quat="0 0.70711 0.70711 0">',
          '      <inertial pos="-3.57066e-05 0.000249371 -0.0293133" quat="0.667981 0.744113 -0.00433092 0.00882801" mass="0.553219" diaginertia="0.000409686 0.000369758 0.000324415"/>',
          '      <geom pos="-0.014 -0.0463995 0.0731" type="mesh" rgba="0.11 0.29 0.012 1" mesh="gripper" contype="0" conaffinity="0"/>',
          '      <site name="tcp_site" pos="0 0 0" quat="0 1 0 0" size="0.005" rgba="1 0 0 1"/>',
          f'      <site name="grasp_site" pos="0 0 {P["TCP_Z"] / 1000:.6g}" quat="0 1 0 0" size="0.005" rgba="0 1 0 1"/>']
    sensors = []
    for side in ("left", "right"):
        b = BODY[side]
        s = b["sgn"]
        gq = body_quat_of_gripper_axes(side)
        pad_c = np.array([0.0, s * (P["CONTACT_Y"] + 0.4 + D["Y_FACE"]) / 2, (P["TCP_Z"] + P["SKIN_TOP_Z"]) / 2]) / 1000
        pad_c_b = to_body(pad_c[None], side)[0]
        L += [f'      <body name="tip_{side}" pos="{fmt(b["pos"])}" quat="{fmt(b["quat"])}">',
              f'        <inertial {b["inertial"]}/>',
              f'        <joint name="{b["joint"]}" pos="0 0 0" type="slide" axis="0 0 -1" range="0 0.0475"/>',
              f'        <geom class="tac_vis" type="mesh" mesh="carriage_{side}" rgba="0.6 0.79 0.92 1"/>',
              f'        <geom class="tac_vis" type="mesh" mesh="skin_{side}" rgba="0.95 0.55 0.15 1"/>',
              f'        <geom class="tac_vis" type="mesh" mesh="socket_{side}" rgba="0.35 0.35 0.38 1"/>',
              f'        <geom class="tac_vis" type="mesh" mesh="cartridge_{side}" rgba="0.15 0.45 0.75 1"/>',
              f'        <geom name="skin_contact_{side}" type="box" pos="{fmt(pad_c_b)}" quat="{fmt(gq)}" size="{fmt(pad_half)}" '
              f'friction="1.2 0.02 0.001" solref="0.004 1" solimp="0.9 0.97 0.001" rgba="0.95 0.55 0.15 0"/>']
        for k, (c_g, h_g) in enumerate(collision_boxes()):
            c_b = to_body((np.array(c_g) * s * np.array([1, 1, 0]) + np.array(c_g) * np.array([0, 0, 1]))[None] / 1000, side)[0]
            L.append(f'        <geom name="col_{side}_{k}" type="box" pos="{fmt(c_b)}" quat="{fmt(gq)}" size="{fmt(np.array(h_g) / 1000)}" '
                     f'rgba="0.15 0.45 0.75 0" friction="0.6 0.01 0.001"/>')
        tax = np.array(tmap["fingers"][side]["taxels_q0"])
        inward = np.array([0.0, s * P["SKIN_T"] / 2000, 0.0])          # taxel box centre behind the surface
        tax_b = to_body(tax + inward, side)
        site_b = to_body(tax, side)
        for i, (p, ps) in enumerate(zip(tax_b, site_b)):
            r, c = divmod(i, P["N_COLS"])
            nm = f"tax_{side[0].upper()}_r{r:02d}_c{c}"
            # one collision box per taxel: box-box contacts land on each taxel's own face, so the
            # per-taxel touch sensors see a distributed pressure map instead of a few corner points
            L.append(f'        <geom name="{nm}" type="box" pos="{fmt(p)}" quat="{fmt(gq)}" size="{fmt(taxel_half)}" '
                     f'friction="1.2 0.02 0.001" solref="0.004 1" solimp="0.9 0.97 0.001" rgba="1 0.6 0.2 0.0"/>')
            L.append(f'        <site name="{nm}" type="box" pos="{fmt(ps)}" quat="{fmt(gq)}" size="{fmt(site_half)}" rgba="0.2 1 0.2 0.25" group="4"/>')
            sensors.append(f'    <touch name="{nm}" site="{nm}"/>')
        L.append('      </body>')
    L += ['    </body>', '  </worldbody>',
          '  <equality><joint joint1="joint7" joint2="joint8" polycoef="0 1 0 0 0"/></equality>',
          '  <contact>', '    <exclude body1="gripper" body2="tip_left"/>', '    <exclude body1="gripper" body2="tip_right"/>',
          '    <exclude body1="tip_left" body2="tip_right"/>', '  </contact>', '  <sensor>'] + sensors + ['  </sensor>', '</mujoco>']
    path = os.path.join(SIM, "linear_4310_tactile.xml")
    open(path, "w").write("\n".join(L) + "\n")
    return path


def self_test(path):
    import mujoco
    m = mujoco.MjModel.from_xml_path(path)
    # wrapper: gripper at the world origin. Its body quat (0 .707 .707 0) maps gripper x->world y,
    # y->world x, z->world -z, so fingers point to world +z and close along world x. A fixed
    # 24 x 30 x 20 mm block sits in the jaws at gripper z = -125 mm; both slide joints are driven
    # closed with 15 N each, i.e. a 15 N grip (each jaw presses 15 N on the block).
    wrap = f"""<mujoco>
      <option gravity="0 0 0" timestep="0.0002"/>
      <include file="{os.path.basename(path)}"/>
      <worldbody>
        <body name="block" pos="0 0 0.125"><geom type="box" size="0.012 0.015 0.010" rgba="0.8 0.2 0.2 1"/></body>
      </worldbody>
      <actuator><motor joint="joint7" gear="-1" ctrlrange="-60 60"/><motor joint="joint8" gear="-1" ctrlrange="-60 60"/></actuator>
    </mujoco>"""
    wp = os.path.join(SIM, "_selftest.xml")
    open(wp, "w").write(wrap)
    m = mujoco.MjModel.from_xml_path(wp)
    d = mujoco.MjData(m)
    j7 = m.joint("joint7").qposadr[0]; j8 = m.joint("joint8").qposadr[0]
    d.qpos[j7] = d.qpos[j8] = 0.0135          # start 1.5 mm from contact (the stock joints have no
    steps = int(0.6 / m.opt.timestep)            # armature/damping, so a fast approach would tunnel)
    for step in range(steps):
        d.ctrl[:] = 15.0 * min(1.0, step / (0.3 / m.opt.timestep))   # ramp to a 15 N grip
        d.qvel[:] *= 0.995                                            # light numerical damping
        mujoco.mj_step(m, d)
    vals = np.array(d.sensordata).reshape(2, P["N_ROWS"], P["N_COLS"])
    res = dict(nsensor=m.nsensor, q_open_per_finger_mm=round(float(d.qpos[j7]) * 1000, 2),
               left_sum_N=round(float(vals[0].sum()), 2), right_sum_N=round(float(vals[1].sum()), 2),
               left_active=int((vals[0] > 1e-3).sum()), right_active=int((vals[1] > 1e-3).sum()),
               left_rows_active=[int(r) for r in np.where(vals[0].sum(1) > 1e-3)[0]])
    os.remove(wp)
    return res, vals


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cf.set_i2rt(sys.argv[1])
    p = build()
    print("wrote", p)
    res, vals = self_test(p)
    res["block_mm"] = [24, 30, 20]
    res["grip_N"] = 15.0
    json.dump(res, open(os.path.join(SIM, "selftest.json"), "w"), indent=1)
    print("self-test:", res)
    np.set_printoptions(precision=1, suppress=True, linewidth=140)
    print("left finger touch map (N), rows 0=distal:\n", vals[0])
