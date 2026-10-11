"""
MuJoCo model of the YAM Linear-4310 gripper with two ENPIRE-T Tip fingers and 2 x 92 touch sensors.

Each nail taxel is a flat ellipsoid in its own body (welded to the finger) with a touch site: its top
touches the film's outer face at the taxel's centre, and neighbouring ellipsoids overlap below it, so the
pad has no edges or gaps for an object to catch on, whatever its shape (a box tiling reads a cylinder or a
bar's edge lying across a row gap far too high: edge contacts get inclined normals). A touch sensor counts
only its own body's contacts, so each contact is counted once. Plain boxes cover the nail's margins and
bare tip, and the front of the stock TPU insert (the cradle has no sensors in this version). The fingers'
contact geoms touch anything with MuJoCo's default contype and not each other. Meshes are visual only.
Same body / joint / site names as i2rt's linear_4310.xml, so it drops in.

Self-tests, 15 N grip per jaw on frictionless fixed objects as stiff as the fingers' contacts (every
contact force is then a normal force, and the share of it landing on taxels is what the sensor sees; on
inclined faces the normal forces add up to more than the grip):
  (1) nail pinch               - a 3 mm pin, a 3 mm rod and a 3 mm square bar edge-on, across the full rows
                                 near the nail root, on a row, between rows, near and on a row gap: the
                                 taxels read the nail's normal force, grip / cos(tilt)
  (2) cradle grasp, 32 mm rod  - the stock cradle takes it, nothing is sensed (by design)
  (3) a flat plate at the tips - the nail faces are tilted 2.9 deg, as on stock ENPIRE: the bare tips
                                 meet a rigid flat part first and the taxels miss it
Usage (from cartridge/): python3 cad/enpire_tip_sim.py [i2rt_repo_root]  -> out/enpire_tip/sim/
"""
import json
import os
import shutil
import sys
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation as Rot
from shapely.geometry import box as sbox
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_fit as cf          # noqa: E402
import enpire_finger as E       # noqa: E402
import enpire_tip as T          # noqa: E402
import make_sim_model as MS     # noqa: E402

SIM = os.path.join(T.OUT, "sim")
ASSETS = os.path.join(SIM, "assets")
TM = json.load(open(os.path.join(T.OUT, "taxel_map.json")))
PARAMS = json.load(open(os.path.join(T.OUT, "params.json")))["derived"]
PITCH = T.P["NAIL_PITCH"]
TAXEL_ELLIPSOID = (2.0, 0.6)  # in-plane and depth semi-axes (mm): at a cell's edge the top is 30 um down and 5.6 deg off flat


def frame_quat(n, side_sgn):
    """Box orientation: local x = gripper x, local y = surface normal (toward the object), z = x cross y."""
    e1 = np.array([1.0, 0, 0]) * side_sgn
    e2 = n / np.linalg.norm(n)
    e1 = e1 - e2 * (e1 @ e2); e1 /= np.linalg.norm(e1)
    return np.c_[e1, e2, np.cross(e1, e2)]


def to_body_rot(Rg, side):
    return MS.rotm(MS.BODY[side]["quat"]).T @ Rg


def quat_wxyz(Rm):
    q = Rot.from_matrix(Rm).as_quat()
    return (q[3], q[0], q[1], q[2])


def nail_fillers(cell=0.3):
    """Plain boxes on the nail face around the taxels, the groove kept open: a fine grid over the face
    less the taxels, merged into runs along u. No box overlaps a taxel."""
    import enpire_tip_fpc as TF
    rt = T.build_route()
    NR = T.nail_regions(rt)
    h = PITCH / 2
    face = NR["face"].buffer(-0.05)
    covered = unary_union([sbox(u - h, v - h, u + h, v + h) for (u, v) in (TF.flat_to_plane_pt(*t["flat_mm"]) for t in TM["taxels"])])
    free = face.difference(covered.buffer(0.03, join_style=2))
    b = free.bounds
    out = []
    for v in np.arange(b[1], b[3], cell):
        run = None
        for u in np.arange(b[0], b[2] + cell, cell):
            c = sbox(u, v, u + cell, v + cell)
            ok = free.contains(c.centroid) and c.intersection(covered).area < 1e-9
            if ok:
                run = [u, u + cell] if run is None else [run[0], u + cell]
            elif run is not None:
                out.append(sbox(run[0], v, run[1], v + cell)); run = None
        if run is not None:
            out.append(sbox(run[0], v, run[1], v + cell))
    return out


def cradle_fillers(step=1.0):
    """Plain boxes along the front of the stock TPU insert (native profile at the finger centre),
    outer faces on the tips of its ridges: (centre_g, normal_g, along-curve half length)."""
    S = E.src_native()
    sec = E.section_yz(S["soft"], T.P["X_PROFILE"])
    ys = np.arange(-94.4, -14.2, 0.1)
    zf = E.lower_envelope(sec, ys)
    ok = ~np.isnan(zf)
    ys, zf = ys[ok], zf[ok]
    out = []
    for y in np.arange(ys[0] + step / 2, ys[-1] - step / 2, step):
        m = np.abs(ys - y) <= step / 2
        z = zf[m].min()                                   # ridge tips in this window
        w = np.abs(ys - y) <= 2.0
        k = np.polyfit(ys[w], zf[w], 1)[0]                # local slope of the front
        t = np.array([1.0, k]) / np.hypot(1.0, k)
        n_n = np.array([t[1], -t[0]])                     # toward the object (-z native)
        if n_n[1] > 0:
            n_n = -n_n
        p = E.n2g(np.array([[T.P["X_PROFILE"], y, z]]))[0]
        n = (E.n2g(np.array([[0.0, n_n[0], n_n[1]]])) - E.n2g(np.zeros((1, 3))))[0]
        out.append((p, n / np.linalg.norm(n), step / 2 * np.hypot(1.0, k) - 0.02))   # boxes meet along the curve
    return out


def build():
    os.makedirs(ASSETS, exist_ok=True)
    _, CL, CR, _, _ = cf.yam_meshes(0.0)
    car = {"left": CL, "right": CR}
    meshes = {}
    tpu = T.tpu_stock()
    for side in ("left", "right"):
        sgn = MS.BODY[side]["sgn"]
        for name in ("core", "tpu", "film"):
            m = tpu.copy() if name == "tpu" else trimesh.load(os.path.join(T.OUT, f"{name}.stl"))
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
        "core_*.stl and film_*.stl are a modified version of the ENPIRE gripper finger; tpu_*.stl is the original\n"
        "ENPIRE TPU insert, unchanged, placed on each finger.\n" + T.ATTRIBUTION +
        "\nLicence: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/\n")
    lic = os.path.join(cf.I2RT, "LICENSE")
    if os.path.isfile(lic):
        shutil.copy(lic, os.path.join(SIM, "I2RT_LICENSE"))

    # the fingers' contact boxes touch anything with MuJoCo's default contype (1) but not each other
    contact = 'contype="2" conaffinity="1" friction="1.2 0.02 0.001" solref="0.004 1" solimp="0.9 0.97 0.001"'
    ntax = len(TM["taxels"])
    L = ['<mujoco model="linear_4310_enpire_t_tip">',
         f'  <!-- generated by enpire_tip_sim.py: i2rt linear_4310 + ENPIRE-T Tip fingers, 2 x {ntax} touch sensors -->',
         '  <compiler angle="radian" meshdir="assets"/>',
         '  <default><default class="vis"><geom contype="0" conaffinity="0" group="2"/></default></default>',
         '  <asset>', '    <mesh name="gripper" file="gripper.stl"/>']
    for (name, side), fn in meshes.items():
        L.append(f'    <mesh name="{name}_{side}" file="{fn}"/>')
    tip = np.array(PARAMS["tip_g"]) / 1000
    L += ['  </asset>', '  <worldbody>',
          '    <body name="gripper" pos="0 0 0" quat="0 0.70711 0.70711 0">',
          '      <inertial pos="-3.57066e-05 0.000249371 -0.0293133" quat="0.667981 0.744113 -0.00433092 0.00882801" mass="0.553219" diaginertia="0.000409686 0.000369758 0.000324415"/>',
          '      <geom class="vis" pos="-0.014 -0.0463995 0.0731" type="mesh" rgba="0.11 0.29 0.012 1" mesh="gripper"/>',
          '      <site name="tcp_site" pos="0 0 0" quat="0 1 0 0" size="0.005" rgba="1 0 0 1"/>',
          f'      <site name="grasp_site" pos="0 0 {tip[2]:.6g}" quat="0 1 0 0" size="0.005" rgba="0 1 0 1"/>']
    sensors = []
    nail_fill, cradle = nail_fillers(), cradle_fillers()
    pl = PARAMS["nail_plane_g"]
    for side in ("left", "right"):
        b = MS.BODY[side]
        sgn = b["sgn"]
        M = np.diag([sgn, sgn, 1.0])
        L += [f'      <body name="tip_{side}" pos="{MS.fmt(b["pos"])}" quat="{MS.fmt(b["quat"])}">',
              f'        <inertial {b["inertial"]}/>',
              f'        <joint name="{b["joint"]}" pos="0 0 0" type="slide" axis="0 0 -1" range="0 0.0475"/>']
        for name, rgba in (("carriage", "0.6 0.79 0.92 1"), ("socket", "0.35 0.35 0.38 1"), ("core", "0.30 0.50 0.72 1"),
                           ("tpu", "0.94 0.62 0.25 1"), ("film", "0.2 0.62 0.58 1")):
            L.append(f'        <geom class="vis" type="mesh" mesh="{name}_{side}" rgba="{rgba}"/>')
        surf = np.array(TM["fingers"][side]["surface_q0"]) * 1000
        nrm = np.array(TM["fingers"][side]["normal_toward_object"])
        # one body per taxel (welded to the finger): a touch sensor counts only its own body's contacts, so where
        # neighbouring ellipsoids overlap each contact is counted once, by the taxel it is on
        a, c = TAXEL_ELLIPSOID
        gsize, sh = np.array([a, c, a]) / 1000, np.array([a + 0.02, c + 0.02, a + 0.02]) / 1000
        for i in range(ntax):
            Rg = frame_quat(nrm[i], sgn)
            q = quat_wxyz(to_body_rot(Rg, side))
            pos = MS.to_body(((surf[i] - nrm[i] * c) / 1000)[None], side)[0]
            nm = f"tax_{side[0].upper()}_{i:03d}"
            L += [f'        <body name="{nm}" pos="{MS.fmt(pos)}" quat="{MS.fmt(q)}">',
                  f'          <geom name="{nm}" type="ellipsoid" size="{MS.fmt(gsize)}" {contact} rgba="1 0.6 0.2 0"/>',
                  f'          <site name="{nm}" type="box" size="{MS.fmt(sh)}" rgba="0.2 1 0.2 0.25" group="4"/>',
                  '        </body>']
            sensors.append(f'    <touch name="{nm}" site="{nm}"/>')
        k = 0
        n_s = M @ np.array(pl["normal"])
        qn = quat_wxyz(to_body_rot(frame_quat(n_s, sgn), side))
        for cell in nail_fill:
            u0, v0, u1, v1 = cell.bounds
            c_g = M @ E.n2g(E.plane_to_native((u0 + u1) / 2, (v0 + v1) / 2, -0.3))[0]
            pos = MS.to_body((c_g / 1000)[None], side)[0]
            L.append(f'        <geom name="fill_{side}_{k}" type="box" pos="{MS.fmt(pos)}" quat="{MS.fmt(qn)}" '
                     f'size="{MS.fmt(np.array([(u1 - u0) / 2, 0.3, (v1 - v0) / 2]) / 1000)}" {contact} rgba="0.3 0.5 0.7 0"/>')
            k += 1
        half_w = (T.P["TPU_X"][1] - T.P["TPU_X"][0]) / 2 - 0.3
        for (p, n, hl) in cradle:
            c_g = M @ (p - n * 0.7)
            q = quat_wxyz(to_body_rot(frame_quat(M @ n, sgn), side))
            pos = MS.to_body((c_g / 1000)[None], side)[0]
            L.append(f'        <geom name="fill_{side}_{k}" type="box" pos="{MS.fmt(pos)}" quat="{MS.fmt(q)}" '
                     f'size="{MS.fmt(np.array([half_w, 0.7, hl]) / 1000)}" {contact} rgba="0.9 0.6 0.3 0"/>')
            k += 1
        L.append('      </body>')
    L += ['    </body>', '  </worldbody>',
          '  <equality><joint joint1="joint7" joint2="joint8" polycoef="0 1 0 0 0"/></equality>',
          '  <contact>', '    <exclude body1="gripper" body2="tip_left"/>', '    <exclude body1="gripper" body2="tip_right"/>',
          '    <exclude body1="tip_left" body2="tip_right"/>', '  </contact>', '  <sensor>'] + sensors + ['  </sensor>', '</mujoco>']
    path = os.path.join(SIM, "linear_4310_enpire_t_tip.xml")
    open(path, "w").write("\n".join(L) + "\n")
    return path, ntax


def grasp(path, obj, z_obj, q0, grip=15.0, t_end=0.6):
    """Close both jaws with `grip` N each on a fixed object; sensor readings (2 x ntax), the jaw
    opening, and every contact normal force on the object by finger and by what it lands on."""
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
    def share(F):
        return [round(F[(sd, "tax")] / max(F[(sd, "tax")] + F[(sd, "fill")], 1e-9), 3) for sd in ("L", "R")]

    def match(v, F):
        return bool(all(abs(v[k].sum() - F[(sd, "tax")]) <= 0.02 * max(F[(sd, "tax")], 1.0) for k, sd in ((0, "L"), (1, "R"))))
    res = {}
    # 1) nail pinch: 3 mm objects across the nail (along gripper x = world y), centred on a full taxel row
    surf = np.array(TM["fingers"]["right"]["surface_q0"]) * 1000
    nz = np.unique(np.round(surf[:, 2], 2))
    band = [z for z in nz if np.sum(np.isclose(surf[:, 2], z, atol=0.02)) >= 10]
    pin_z = float(band[len(band) // 2])
    obj = 'priority="1" condim="1" solref="0.004 1" solimp="0.9 0.97 0.001"'
    shapes = dict(pin=f'<geom type="capsule" size="0.0015 0.0045" quat="0.7071068 0.7071068 0 0" {obj} rgba="0.8 0.2 0.2 1"/>',
                  rod=f'<geom type="cylinder" size="0.0015 0.006" quat="0.7071068 0.7071068 0 0" {obj} rgba="0.8 0.2 0.2 1"/>',
                  bar_edge_on=f'<geom type="box" size="0.0015 0.006 0.0015" quat="0.9238795 0 0.3826834 0" {obj} rgba="0.8 0.2 0.2 1"/>')
    # the nail plane is tilted, so each nail's normal force is the grip / cos(tilt); the taxels should read that
    expected = 15.0 / abs(PARAMS["nail_plane_g"]["normal"][1])
    runs, errs = [], {}
    for name, geom in shapes.items():
        for dz in (0.0, 0.3, 0.6, PITCH / 2):          # on a row, between rows, near and on the gap between two rows
            vals_k, q_k, ns, F_k = grasp(path, geom, pin_z + dz, q0=0.0030)
            touch = [round(float(vals_k[0].sum()), 2), round(float(vals_k[1].sum()), 2)]
            runs.append(dict(object=name, offset_mm=round(dz, 3), touch_N=touch, sensed_share=share(F_k),
                             sensors_match_contacts=match(vals_k, F_k), active=[int((vals_k[0] > 1e-3).sum()), int((vals_k[1] > 1e-3).sum())]))
            errs[name] = max(errs.get(name, 0.0), max(abs(t - expected) / expected for t in touch))
            if name == "pin" and dz == 0.0:
                vals, q, F1 = vals_k, q_k, F_k
    res["nail_pinch"] = dict(object_d_mm=3, object_len_mm=12, objects=dict(pin="capsule", rod="cylinder", bar_edge_on="square bar, edge first"),
                             z_mm=round(pin_z, 2), q_mm=round(q, 2), grip_N=15.0, expected_normal_N=round(expected, 2),
                             left_nail_N=round(float(vals[0].sum()), 2), right_nail_N=round(float(vals[1].sum()), 2),
                             sensed_share=share(F1), sensors_match_contacts=match(vals, F1),
                             active_nail=[int((vals[0] > 1e-3).sum()), int((vals[1] > 1e-3).sum())],
                             runs=runs, min_sensed_share=min(min(r["sensed_share"]) for r in runs),
                             all_match_contacts=all(r["sensors_match_contacts"] for r in runs),
                             max_touch_error_by_object={k: round(v, 4) for k, v in errs.items()},
                             max_touch_error=round(max(errs.values()), 4))
    # 2) cradle grasp: 32 mm rod in the arches of the stock TPU inserts
    arch_z = -121.5
    rod = '<geom type="cylinder" size="0.016 0.012" quat="0.7071068 0.7071068 0 0" priority="1" condim="1" solref="0.004 1" solimp="0.9 0.97 0.001" rgba="0.2 0.4 0.8 1"/>'
    vals2, q2, _, F2 = grasp(path, rod, arch_z, q0=0.004)
    res["cradle_grasp"] = dict(rod_d_mm=32, z_mm=arch_z, q_mm=round(q2, 2), grip_N=15.0,
                               contact_N_both_fingers=round(sum(F2.values()), 2), sensed_share=share(F2),
                               left_nail_N=round(float(vals2[0].sum()), 2), right_nail_N=round(float(vals2[1].sum()), 2))
    # 3) a flat plate held at the nail tips (the blind spot shared with ENPIRE-T and stock ENPIRE)
    tip_z = float(PARAMS["tip_g"][2])
    plate = '<geom type="box" size="0.001 0.010 0.0075" priority="1" condim="1" solref="0.004 1" solimp="0.9 0.97 0.001" rgba="0.3 0.7 0.3 1"/>'
    vals3, q3, _, F3 = grasp(path, plate, tip_z + 0.5 + 7.5, q0=0.0030)
    res["flat_tip_pinch"] = dict(plate_mm=[2, 20, 15], bottom_above_tip_mm=0.5, q_mm=round(q3, 2), grip_N=15.0,
                                 contact_N_both_fingers=round(sum(F3.values()), 2), sensed_share=share(F3),
                                 left_nail_N=round(float(vals3[0].sum()), 2), right_nail_N=round(float(vals3[1].sum()), 2))
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
