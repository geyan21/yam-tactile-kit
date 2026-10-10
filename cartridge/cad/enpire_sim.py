"""
MuJoCo model of the YAM Linear-4310 gripper with two ENPIRE-T fingers and 2 x 302 touch sensors.

Contact surfaces are tiled with small boxes whose outer faces sit on the real contact surface
(skin outside over the cradle strip, film outside on the nail): one box + one touch site per
taxel, plus plain boxes on the uncovered margins, the top corner, the ramp and the bare nail tip.
Meshes are visual only. Same body / joint / site names as i2rt's linear_4310.xml, so it drops in.

Self-tests: (1) nail pinch of a 3 mm pin, (2) cradle power grasp of a 32 mm rod; each checks
that the sensors on both fingers carry the grip force. (3) a flat plate held at the nail tips
records the nail's blind spot: the tips meet first, so the taxels see little of a rigid flat part.
Usage (from cartridge/): python3 cad/enpire_sim.py [i2rt_repo_root]  -> out/enpire/sim/
"""
import json
import os
import shutil
import sys
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation as Rot
from shapely.geometry import Point, box as sbox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_fit as cf          # noqa: E402
import enpire_finger as E       # noqa: E402
import make_sim_model as MS     # noqa: E402  (body frames / helpers shared with the v0.2 model)

SIM = os.path.join(E.OUT, "sim")
ASSETS = os.path.join(SIM, "assets")
TM = json.load(open(os.path.join(E.OUT, "taxel_map.json")))
PR = E.build_profile()
NR = E.nail_regions(PR)
FPATH = E.FlexPath(PR)
D = E.derived(PR, NR)


def frame_quat(n, side_sgn):
    """Box orientation: local x = gripper x, local y = surface normal (toward the object), z = x cross y."""
    e1 = np.array([1.0, 0, 0]) * side_sgn
    e2 = n / np.linalg.norm(n)
    e1 = e1 - e2 * (e1 @ e2); e1 /= np.linalg.norm(e1)
    e3 = np.cross(e1, e2)
    return np.c_[e1, e2, e3]


def to_body_rot(Rg, side):
    return MS.rotm(MS.BODY[side]["quat"]).T @ Rg


def quat_wxyz(Rm):
    q = Rot.from_matrix(Rm).as_quat()
    return (q[3], q[0], q[1], q[2])


def filler_points():
    """Plain (sensor-less) contact boxes: (u, s, lateral half, along-s half, lift to the surface)."""
    out = []
    st = TM["taxels"]
    lift_c = E.P["FLEX_T"] + E.P["SKIN_T"]
    # strip side margins (beside the 6 columns), every 2 mm along the strip
    s_rows = sorted({t["flat_mm"][1] for t in st if t["region"] == "strip"})
    u_lo, u_hi = sorted(D["strip_u"])
    act_lo, act_hi = -6.46, 5.54
    for s in s_rows:
        for a, b in ((u_lo - 0.45, act_lo), (act_hi, u_hi + 0.45)):
            out.append(((a + b) / 2, s, (b - a) / 2 - 0.02, 0.95, lift_c))
    # top corner and ramp (full width), 2 mm steps
    for s0, s1 in ((1.0, min(s_rows) - 1.0), (max(s_rows) + 1.0, D["s_nail0"] - 0.2)):
        for s in np.arange(s0 + 1.0, s1, 2.0):
            out.append(((u_lo + u_hi) / 2, s, (u_hi - u_lo) / 2 + 0.4, 0.95, lift_c))
    return out


def nail_fillers():
    """Plain boxes on the nail face around the taxels, the groove kept open: 1.5 mm grid cells of
    the planar face that are not taxels (margins and the bare tip)."""
    h = 0.75
    face = NR["face"].buffer(-0.05)
    taken = [sbox(u - h, v - h, u + h, v + h) for (u, v) in [E.native_to_plane([[0, 0, 0]])[0][:2]]][:0]
    cells = []
    tax_flat = [tuple(t["flat_mm"]) for t in TM["taxels"] if t["region"] == "nail"]
    import enpire_fpc as FP
    tax_plane = [FP.flat_to_plane_pt(u, s) for (u, s) in tax_flat]
    tax_boxes = [sbox(u - h, v - h, u + h, v + h) for (u, v) in tax_plane]
    from shapely.ops import unary_union
    covered = unary_union(tax_boxes)
    b = face.bounds
    for v in np.arange(b[1] + h, b[3], 2 * h):
        for u in np.arange(b[0] + h, b[2], 2 * h):
            c = sbox(u - h, v - h, u + h, v + h)
            part = c.intersection(face).difference(covered)
            if part.area > 0.6:
                cells.append(part.envelope.intersection(face).envelope)
    return cells


def build():
    os.makedirs(ASSETS, exist_ok=True)
    _, CL, CR, _, _ = cf.yam_meshes(0.0)
    car = {"left": CL, "right": CR}
    meshes = {}
    for side in ("left", "right"):
        sgn = MS.BODY[side]["sgn"]
        for name in ("core", "skin", "film"):
            m = trimesh.load(os.path.join(E.OUT, f"{name}.stl"))
            if sgn < 0:
                m.apply_transform(np.diag([-1, -1, 1, 1.0]))
            m.vertices = MS.to_body(m.vertices / 1000.0, side)
            fn = f"{name}_{side}.stl"; m.export(os.path.join(ASSETS, fn)); meshes[(name, side)] = fn
        s = trimesh.load(os.path.join(E.F.OUT, "socket.stl"))
        if sgn < 0:
            s.apply_transform(np.diag([-1, -1, 1, 1.0]))
        s.vertices = MS.to_body(s.vertices / 1000.0, side)
        fn = f"socket_{side}.stl"; s.export(os.path.join(ASSETS, fn)); meshes[("socket", side)] = fn
        c = car[side].copy(); c.vertices = MS.to_body(c.vertices / 1000.0, side)
        fn = f"carriage_{side}.stl"; c.export(os.path.join(ASSETS, fn)); meshes[("carriage", side)] = fn
    shutil.copy(os.path.join(cf.assets_dir(), "gripper.stl"), os.path.join(ASSETS, "gripper.stl"))
    open(os.path.join(SIM, "NOTICE.txt"), "w").write(
        "gripper.stl and carriage_*.stl are copied/derived from i2rt-robotics/i2rt\n"
        f"(i2rt/robot_models/gripper/linear_4310/assets, commit {cf.I2RT_COMMIT[:7]}), MIT License, Copyright (c) I2RT Robotics.\n"
        "See I2RT_LICENSE.\n\n"
        "core_*.stl, skin_*.stl and film_*.stl are a modified version of the ENPIRE gripper finger.\n" + E.ES.ATTRIBUTION +
        "\nLicence: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/\n")
    lic = os.path.join(cf.I2RT, "LICENSE")
    if os.path.isfile(lic):
        shutil.copy(lic, os.path.join(SIM, "I2RT_LICENSE"))

    contact = 'friction="1.2 0.02 0.001" solref="0.004 1" solimp="0.9 0.97 0.001"'
    L = ['<mujoco model="linear_4310_enpire_t">',
         f'  <!-- generated by enpire_sim.py: i2rt linear_4310 + ENPIRE-T tactile fingers, 2 x {len(TM["taxels"])} touch sensors -->',
         '  <compiler angle="radian" meshdir="assets"/>',
         '  <default><default class="vis"><geom contype="0" conaffinity="0" group="2"/></default></default>',
         '  <asset>', '    <mesh name="gripper" file="gripper.stl"/>']
    for (name, side), fn in meshes.items():
        L.append(f'    <mesh name="{name}_{side}" file="{fn}"/>')
    tip = np.array(D["tip_g"]) / 1000
    L += ['  </asset>', '  <worldbody>',
          '    <body name="gripper" pos="0 0 0" quat="0 0.70711 0.70711 0">',
          '      <inertial pos="-3.57066e-05 0.000249371 -0.0293133" quat="0.667981 0.744113 -0.00433092 0.00882801" mass="0.553219" diaginertia="0.000409686 0.000369758 0.000324415"/>',
          '      <geom class="vis" pos="-0.014 -0.0463995 0.0731" type="mesh" rgba="0.11 0.29 0.012 1" mesh="gripper"/>',
          '      <site name="tcp_site" pos="0 0 0" quat="0 1 0 0" size="0.005" rgba="1 0 0 1"/>',
          f'      <site name="grasp_site" pos="0 0 {tip[2]:.6g}" quat="0 1 0 0" size="0.005" rgba="0 1 0 1"/>']
    sensors = []
    fill = filler_points()
    nail_fill = nail_fillers()
    ntax = len(TM["taxels"])
    for side in ("left", "right"):
        b = MS.BODY[side]
        sgn = b["sgn"]
        L += [f'      <body name="tip_{side}" pos="{MS.fmt(b["pos"])}" quat="{MS.fmt(b["quat"])}">',
              f'        <inertial {b["inertial"]}/>',
              f'        <joint name="{b["joint"]}" pos="0 0 0" type="slide" axis="0 0 -1" range="0 0.0475"/>']
        for name, rgba in (("carriage", "0.6 0.79 0.92 1"), ("socket", "0.35 0.35 0.38 1"), ("core", "0.30 0.50 0.72 1"),
                           ("skin", "0.94 0.54 0.16 1"), ("film", "0.2 0.62 0.58 1")):
            L.append(f'        <geom class="vis" type="mesh" mesh="{name}_{side}" rgba="{rgba}"/>')
        surf = np.array(TM["fingers"][side]["surface_q0"]) * 1000
        nrm = np.array(TM["fingers"][side]["normal_toward_object"])
        for i, t in enumerate(TM["taxels"]):
            pitch = 2.0 if t["region"] == "strip" else 1.5
            thick = 1.4 if t["region"] == "strip" else 0.6
            c_g = surf[i] - nrm[i] * thick / 2
            Rg = frame_quat(nrm[i], sgn)
            pos = MS.to_body((c_g / 1000)[None], side)[0]
            q = quat_wxyz(to_body_rot(Rg, side))
            ds = 0.07 if t["region"] == "strip" else 0.03       # along s: the strip curves, see the site below
            half = np.array([pitch / 2 - 0.03, thick / 2, pitch / 2 - ds]) / 1000
            nm = f"tax_{side[0].upper()}_{i:03d}"
            L.append(f'        <geom name="{nm}" type="box" pos="{MS.fmt(pos)}" quat="{MS.fmt(q)}" size="{MS.fmt(half)}" {contact} rgba="1 0.6 0.2 0"/>')
            # touch site: a thin slab around the box's outer face, 0.02 mm longer than the box along s.
            # Where the cradle is concave, neighbouring tiles tilt into each other; a deeper or longer
            # site would also catch the neighbour's contacts and count them twice.
            sh = np.array([pitch / 2 - 0.01, 0.12, pitch / 2 - ds + 0.02]) / 1000
            spos = MS.to_body(((surf[i] - nrm[i] * 0.02) / 1000)[None], side)[0]
            L.append(f'        <site name="{nm}" type="box" pos="{MS.fmt(spos)}" quat="{MS.fmt(q)}" size="{MS.fmt(sh)}" rgba="0.2 1 0.2 0.25" group="4"/>')
            sensors.append(f'    <touch name="{nm}" site="{nm}"/>')
        k = 0
        for (u, s, hu, hs, lift) in fill:
            g, n = FPATH.point_g(u, s, lift=lift)
            n = n[0] / np.linalg.norm(n[0])
            c_g = np.diag([sgn, sgn, 1.0]) @ (g[0] - n * 0.7)
            n_s = np.diag([sgn, sgn, 1.0]) @ n
            pos = MS.to_body((c_g / 1000)[None], side)[0]
            q = quat_wxyz(to_body_rot(frame_quat(n_s, sgn), side))
            L.append(f'        <geom name="fill_{side}_{k}" type="box" pos="{MS.fmt(pos)}" quat="{MS.fmt(q)}" size="{MS.fmt(np.array([hu, 0.7, hs]) / 1000)}" {contact} rgba="0.3 0.5 0.7 0"/>')
            k += 1
        nn_g = (E.n2g(E.NN[None]) - E.n2g(np.zeros((1, 3))))[0]
        for cell in nail_fill:
            u0, v0, u1, v1 = cell.bounds
            c_n = E.plane_to_native((u0 + u1) / 2, (v0 + v1) / 2, -0.3)
            c_g = np.diag([sgn, sgn, 1.0]) @ E.n2g(c_n)[0]
            n_s = np.diag([sgn, sgn, 1.0]) @ nn_g
            # local z of the box = x cross normal; the plane's v axis maps onto it up to sign
            pos = MS.to_body((c_g / 1000)[None], side)[0]
            q = quat_wxyz(to_body_rot(frame_quat(n_s, sgn), side))
            L.append(f'        <geom name="fill_{side}_{k}" type="box" pos="{MS.fmt(pos)}" quat="{MS.fmt(q)}" '
                     f'size="{MS.fmt(np.array([(u1 - u0) / 2, 0.3, (v1 - v0) / 2]) / 1000)}" {contact} rgba="0.3 0.5 0.7 0"/>')
            k += 1
        L.append('      </body>')
    L += ['    </body>', '  </worldbody>',
          '  <equality><joint joint1="joint7" joint2="joint8" polycoef="0 1 0 0 0"/></equality>',
          '  <contact>', '    <exclude body1="gripper" body2="tip_left"/>', '    <exclude body1="gripper" body2="tip_right"/>',
          '    <exclude body1="tip_left" body2="tip_right"/>', '  </contact>', '  <sensor>'] + sensors + ['  </sensor>', '</mujoco>']
    path = os.path.join(SIM, "linear_4310_enpire_t.xml")
    open(path, "w").write("\n".join(L) + "\n")
    return path, ntax


def grasp(path, obj, z_obj, q0, grip=15.0, t_end=0.6):
    """Close both jaws with `grip` N each on a fixed object; return sensor readings (2 x ntax)."""
    import mujoco
    wrap = f"""<mujoco>
      <option gravity="0 0 0" timestep="0.0002"/>
      <include file="{os.path.basename(path)}"/>
      <worldbody><body name="obj" pos="0 0 {-z_obj / 1000:.6g}">{obj}</body></worldbody>
      <actuator><motor joint="joint7" gear="-1" ctrlrange="-60 60"/><motor joint="joint8" gear="-1" ctrlrange="-60 60"/></actuator>
    </mujoco>"""
    wp = os.path.join(SIM, "_selftest.xml")
    open(wp, "w").write(wrap)
    m = mujoco.MjModel.from_xml_path(wp)
    d = mujoco.MjData(m)
    j7, j8 = m.joint("joint7").qposadr[0], m.joint("joint8").qposadr[0]
    d.qpos[j7] = d.qpos[j8] = q0
    steps = int(t_end / m.opt.timestep)
    for k in range(steps):
        d.ctrl[:] = grip * min(1.0, k / (0.3 / m.opt.timestep))
        d.qvel[:] *= 0.995
        mujoco.mj_step(m, d)
    os.remove(wp)
    vals = np.array(d.sensordata).reshape(2, -1)
    # every contact normal force on the object, by finger and by what it lands on (taxel or plain box)
    obj, f6 = m.body("obj").id, np.zeros(6)
    forces = {(sd, kind): 0.0 for sd in ("L", "R") for kind in ("tax", "fill")}
    for i in range(d.ncon):
        c = d.contact[i]
        b1, b2 = m.geom_bodyid[c.geom1], m.geom_bodyid[c.geom2]
        if obj not in (b1, b2):
            continue
        other = c.geom2 if b1 == obj else c.geom1
        nm = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, other) or ""
        mujoco.mj_contactForce(m, d, i, f6)
        kind = "tax" if nm.startswith("tax_") else "fill"
        sd = "L" if ("_L_" in nm or "_left_" in nm) else "R"
        forces[(sd, kind)] += abs(f6[0])
    return vals, float(d.qpos[j7]) * 1000, m.nsensor, forces


def self_test(path):
    """Grasps of fixed test objects at a 15 N grip per jaw. The objects are frictionless (priority 1,
    condim 1), so each finger's contact normal forces carry exactly the grip along the closing axis,
    and the share of it that lands on taxels (rather than on margins, the groove or the bare tip) is a
    fair measure of what the sensor sees. With friction the split between normal and friction forces
    depends on the closing history, most of all in the deep cradle."""
    reg = np.array([t["region"] for t in TM["taxels"]])
    def share(F):                               # share of each finger's contact normal force that lands on taxels
        return [round(F[(sd, "tax")] / max(F[(sd, "tax")] + F[(sd, "fill")], 1e-9), 3) for sd in ("L", "R")]
    def match(v, F):                            # each contact is counted by exactly one touch sensor
        return bool(all(abs(v[k].sum() - F[(sd, "tax")]) <= 0.02 * max(F[(sd, "tax")], 1.0) for k, sd in ((0, "L"), (1, "R"))))
    res = {}
    # 1) nail pinch: a 3 mm pin across the nail (along gripper x = world y), on the middle band row.
    #    The wrapper maps gripper x -> world y, y -> world x (closing axis), z -> world -z.
    surf = np.array(TM["fingers"]["right"]["surface_q0"]) * 1000
    nz = np.unique(np.round(surf[reg == "nail"][:, 2], 2))
    band = [z for z in nz if np.sum(np.isclose(surf[reg == "nail"][:, 2], z, atol=0.02)) >= 8]
    pin_z = float(band[len(band) // 2])
    pin = '<geom type="cylinder" size="0.0015 0.006" quat="0.7071068 0.7071068 0 0" priority="1" condim="1" rgba="0.8 0.2 0.2 1"/>'
    vals, q, ns, F1 = grasp(path, pin, pin_z, q0=0.0030)
    res["nail_pinch"] = dict(pin_d_mm=3, pin_len_mm=12, z_mm=round(pin_z, 2), q_mm=round(q, 2), grip_N=15.0,
                             left_nail_N=round(float(vals[0][reg == "nail"].sum()), 2), right_nail_N=round(float(vals[1][reg == "nail"].sum()), 2),
                             left_strip_N=round(float(vals[0][reg == "strip"].sum()), 2), right_strip_N=round(float(vals[1][reg == "strip"].sum()), 2),
                             sensed_share=share(F1), sensors_match_contacts=match(vals, F1),
                             active_nail=[int((vals[0][reg == "nail"] > 1e-3).sum()), int((vals[1][reg == "nail"] > 1e-3).sum())])
    # 2) cradle power grasp: 32 mm rod across the finger (world y = gripper x) in the two arches.
    #    The arches face each other ~31 mm apart at q = 0, so they hold rods from about 30 mm up.
    arch_z = -121.5
    rod = '<geom type="cylinder" size="0.016 0.012" quat="0.7071068 0.7071068 0 0" priority="1" condim="1" rgba="0.2 0.4 0.8 1"/>'
    vals2, q2, _, F2 = grasp(path, rod, arch_z, q0=0.004)
    res["cradle_grasp"] = dict(rod_d_mm=32, z_mm=arch_z, q_mm=round(q2, 2), grip_N=15.0,
                               left_strip_N=round(float(vals2[0][reg == "strip"].sum()), 2), right_strip_N=round(float(vals2[1][reg == "strip"].sum()), 2),
                               sensed_share=share(F2), sensors_match_contacts=match(vals2, F2),
                               active_strip=[int((vals2[0][reg == "strip"] > 1e-3).sum()), int((vals2[1][reg == "strip"] > 1e-3).sum())])
    # 3) a flat plate held at the nail tips. The nail faces are tilted 2.9 deg, as on stock ENPIRE, so
    #    the tips meet first: a rigid flat part touches only the bare tip and the nail taxels miss it.
    tip_z = float(json.load(open(os.path.join(E.OUT, "params.json")))["derived"]["tip_g"][2])
    plate = '<geom type="box" size="0.001 0.010 0.0075" priority="1" condim="1" rgba="0.3 0.7 0.3 1"/>'
    vals3, q3, _, F3 = grasp(path, plate, tip_z + 0.5 + 7.5, q0=0.0030)
    res["flat_tip_pinch"] = dict(plate_mm=[2, 20, 15], bottom_above_tip_mm=0.5, q_mm=round(q3, 2), grip_N=15.0,
                                 contact_N_both_fingers=round(sum(F3.values()), 2), sensed_share=share(F3),
                                 left_nail_N=round(float(vals3[0][reg == "nail"].sum()), 2), right_nail_N=round(float(vals3[1][reg == "nail"].sum()), 2))
    res["nsensor"] = ns
    return res, vals, vals2


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cf.set_i2rt(sys.argv[1])
    path, ntax = build()
    print("wrote", path)
    res, v1, v2 = self_test(path)
    json.dump(res, open(os.path.join(SIM, "selftest.json"), "w"), indent=1)
    np.savez_compressed(os.path.join(SIM, "selftest_maps.npz"), nail_pinch=v1, cradle_grasp=v2)
    print(json.dumps(res, indent=1))
