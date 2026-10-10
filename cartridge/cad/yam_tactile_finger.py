"""
YAM Linear-4310 tactile finger cartridge — parametric CAD (CadQuery).

One design serves BOTH fingers: the left finger is the right one rotated 180 deg about z, exactly
like the stock i2rt tips (verified on the i2rt meshes, max deviation 0.18 mm).

  socket     stays on the YAM carriage (stock 2x M3 points). Flat docking face, 2 press-fit dowels,
             2 M3 heat-set inserts for the thumbscrews, pocket for a small pogo-pin PCB, cable exit
             with strain-relief tab.
  cartridge  tool-less plug-in finger. Pushes straight up onto the dowels (pogo pins compress
             axially, no wiping), held by two captive M3 knurled thumbscrews under the flange
             wings. Flat 8x16 sensor bay, tail groove + notch into the finger-PCB cavity.
  skin       snap-on TPU 85A cap over the sensing region (face, nose, sides, back lips).

Frame: i2rt `linear_4310` gripper body frame, right finger (tip_right) at q = 0 (closed).
  x lateral, y = closing axis (+y points away from the object for the right finger),
  z along the gripper axis (fingertips toward -z). Units: mm.
Interface numbers were measured from i2rt/robot_models/gripper/linear_4310/assets/*.stl.

Run (from cartridge/):  python3 cad/yam_tactile_finger.py  -> STEP + STL + params.json in out/
"""
import json
import os
import numpy as np
import cadquery as cq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # cartridge/
OUT = os.path.join(ROOT, "out")

# ----------------------------------------------------------------------------------------------
# Parameters
# ----------------------------------------------------------------------------------------------
P = dict(
    # --- YAM Linear 4310 interface (measured from the i2rt meshes) ---
    Z_CARRIAGE=-70.38,              # carriage plate bottom face = stock tip mounting face
    MOUNT_HOLES=[(-8.25, 17.15), (12.75, 17.15)],   # stock M3 points (21.0 mm apart)
    # stock tips carry knurled M3 heat-set inserts (D 3.9-4.6 x 5 mm) right under the carriage face,
    # screwed from above through the carriage. The socket copies that: same inserts, same screws.
    MOUNT_INSERT_D=4.0, MOUNT_INSERT_DEPTH=6.0, SCREW_TIP_CLEAR=2.5,
    M3_CLEAR=3.4,
    SOCKET_H=10.5,                  # carriage face -> docking face
    CARRIAGE_X=(-12.6, 33.9),       # own carriage footprint; beyond -12.6 the OPPOSITE carriage's
    OPP_RELIEF=1.5,                 # rack slides over the socket -> drop the top 1.5 mm (as stock)
    TCP_Z=-144.65,                  # stock fingertip distal facet (grasp_site in the MJCF)
    CONTACT_Y=-0.25,                # skin surface at q=0 (stock rubber sits at -0.52)

    # --- docking interface (socket bottom face == cartridge top face) ---
    Y_IN=3.0, Y_OUT=25.5,           # inner / outer faces of socket + flange
    DOCK_HALF_X=22.5,
    THUMB_XY=[(-18.3, 14.0), (18.3, 14.0)],   # M3 knurled thumbscrews (heads under the wings)
    THUMB_HEAD_D=8.0, THUMB_HEAD_H=3.5,
    INSERT_D=4.0, INSERT_DEPTH=6.0,           # M3 brass heat-set inserts (e.g. M3 x 5.7)
    DOWEL_XY=[(-17.5, 22.0), (17.5, 22.0)], DOWEL_D=3.0, DOWEL_PRESS=2.95, DOWEL_LEN=8.0,
    DOWEL_IN_SOCKET=6.0, DOWEL_HOLE_DEPTH=2.6,
    POGO_Y=10.5, POGO_PITCH=2.54, POGO_N=5, POGO_PROTRUDE=1.4, POGO_H=3.5,
    SPCB_X=9.0, SPCB_Y=(8.0, 13.0), SPCB_T=0.8,          # socket PCB (pogo carrier) pocket
    CABLE_X=(1.0, 7.5), CABLE_Z=(1.5, 4.3),              # cable channel, z above the docking face

    # --- cartridge ---
    FLANGE_T=9.0,
    BEAM_ROOT_HALF_X=12.8,          # beam width under the flange (wings beyond carry thumbscrews)
    BEAM_PAR_Z=-108.0,              # beam is parallel (half-width SENSE_HALF_X) below this
    SENSE_HALF_X=12.0,
    NOSE_R_XZ=3.5,
    INCLINE_END_Z=-104.0,           # inner face: flat bay below, gentle incline up to the flange
    BACK_TOP_Y=21.0, BACK_LOW=(4.6, -138.0), BACK_END_Y=2.9,
    NOSE_R_IN=1.0, NOSE_R_BACK=0.8,   # y-z nose fillets (inner corner / back corner)
    PCB=dict(x=13.6, y=(5.4, 19.4), recess=0.7, t=0.8),  # finger PCB seat (27.0 x 13.8 board)
    CAVITY=dict(x=12.8, y=(6.2, 18.6), depth=3.2),        # bottom-side components
    TAIL_HALF_X=9.7, NOTCH_FLOOR=2.8, BEND_R=1.0,  # tail groove depth = PAD_T (no step at the pad)
    # tails side by side (stack view, u = x), standard 0.5 mm FFC widths: (n + 1) x 0.5 mm
    TAIL_ROWS_U=(-9.4, -0.9), TAIL_COLS_U=(4.6, 9.1), TAIL_PITCH=0.5, ZIF_DEPTH=3.3,
    # skin retention: rib on each skin side wall snaps into a groove across the core's side face
    SKIN_RIB=dict(z=-112.0, w=1.5, depth=0.5, y0=3.5, clear=0.05, y1=13.0),

    # --- sensor (FlexiTac-style piezoresistive pad, 2 mm pitch) ---
    N_COLS=8, N_ROWS=16, PITCH=2.0, ELECTRODE_W=1.4,
    PAD_T=0.8, SKIN_T=1.2, SKIN_SIDE_T=1.0, SKIN_LIP=0.8,
    MARGIN_SIDE=2.85,              # 8 return traces + seal on each lateral side
    MARGIN_DIST=1.5, MARGIN_PROX=2.2, PAD_R=1.5, POCKET_CLEAR=0.15,
    NOSE_GAP=1.8,                  # core distal end -> pad distal edge
    SKIN_TOP_Z=-101.5,
)

Zs = P["Z_CARRIAGE"] - P["SOCKET_H"]     # docking face
TAIL_GROOVE = P["PAD_T"]                 # groove floor == pocket floor
Zf = Zs - P["FLANGE_T"]                  # flange bottom
Z_END = P["TCP_Z"] + P["SKIN_T"]         # core distal end (skin wraps the nose)
Y_FACE = P["CONTACT_Y"] + P["SKIN_T"]    # core inner face over the bay
Y_POCKET = Y_FACE + P["PAD_T"]           # pad pocket floor
ACT_W = P["N_COLS"] * P["PITCH"]
ACT_L = P["N_ROWS"] * P["PITCH"]
PAD_DIST_Z = Z_END + P["NOSE_GAP"]
ACT_Z0 = PAD_DIST_Z + P["MARGIN_DIST"]   # active area, distal edge
ACT_Z1 = ACT_Z0 + ACT_L                  # active area, proximal edge
PAD_PROX_Z = ACT_Z1 + P["MARGIN_PROX"]
PAD_HALF_X = ACT_W / 2 + P["MARGIN_SIDE"]
DERIVED = dict(Zs=Zs, Zf=Zf, Z_END=Z_END, Y_FACE=Y_FACE, Y_POCKET=Y_POCKET, ACT_Z0=ACT_Z0, ACT_Z1=ACT_Z1,
               PAD_DIST_Z=PAD_DIST_Z, PAD_PROX_Z=PAD_PROX_Z, PAD_HALF_X=PAD_HALF_X, ACT_W=ACT_W, ACT_L=ACT_L)


# ----------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------
def rpoly(wp, pts, radii):
    """Closed polygon on workplane `wp` with a tangent fillet of radii[i] at vertex i."""
    Pn = [np.array(p, float) for p in pts]
    n = len(Pn)
    tp = []
    for i in range(n):
        p0, p1, p2 = Pn[i - 1], Pn[i], Pn[(i + 1) % n]
        r = radii[i]
        if r <= 0:
            tp.append((p1, None, p1))
            continue
        d1 = (p0 - p1) / np.linalg.norm(p0 - p1)
        d2 = (p2 - p1) / np.linalg.norm(p2 - p1)
        ang = np.arccos(np.clip(d1 @ d2, -1, 1))
        t = r / np.tan(ang / 2)
        a, b = p1 + d1 * t, p1 + d2 * t
        bis = (d1 + d2) / np.linalg.norm(d1 + d2)
        c = p1 + bis * (r / np.sin(ang / 2))
        tp.append((a, c - bis * r, b))
    for i in range(n):           # fillets on both ends of an edge must fit on that edge
        j = (i + 1) % n
        need = np.linalg.norm(tp[i][2] - Pn[i]) + np.linalg.norm(tp[j][0] - Pn[j])
        if need > np.linalg.norm(Pn[j] - Pn[i]) + 1e-9:
            raise ValueError(f"rpoly: fillets at vertices {i},{j} overlap on edge {Pn[i]}->{Pn[j]}")
    w = wp.moveTo(*tp[0][2])
    for i in list(range(1, n)) + [0]:
        a, m, b = tp[i]
        w = w.lineTo(*a)
        if m is not None:
            w = w.threePointArc(tuple(m), tuple(b))
    return w.close()


def box(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def cyl_z(x, y, d, z0, z1):
    return cq.Workplane("XY").circle(d / 2).extrude(z1 - z0).translate((x, y, z0))


def hex_z(x, y, af, z0, z1):
    return cq.Workplane("XY").polygon(6, af / np.cos(np.pi / 6)).extrude(z1 - z0).translate((x, y, z0))


def xz_extrude(pts, radii, y0, y1):
    """Profile in (x, z), extruded over y in [y0, y1] (the XZ workplane normal is -y)."""
    return rpoly(cq.Workplane("XZ"), pts, radii).extrude(y1 - y0).translate((0, y1, 0))


def yz_extrude(pts, radii, x0, x1):
    """Profile in (y, z), extruded over x in [x0, x1]."""
    return rpoly(cq.Workplane("YZ"), pts, radii).extrude(x1 - x0).translate((x0, 0, 0))


def y_back(z):
    (yl, zl) = P["BACK_LOW"]
    return P["BACK_TOP_Y"] + (z - Zf) * (yl - P["BACK_TOP_Y"]) / (zl - Zf)


# ----------------------------------------------------------------------------------------------
# Socket
# ----------------------------------------------------------------------------------------------
def spcb_bottom_z():
    return Zs + P["POGO_H"] - P["POGO_PROTRUDE"]


def make_socket():
    zt = P["Z_CARRIAGE"]
    x0, x1 = -P["DOCK_HALF_X"], P["CARRIAGE_X"][1]
    body = (cq.Workplane("XY").box(x1 - x0, P["Y_OUT"] - P["Y_IN"], zt - Zs, centered=False)
            .translate((x0, P["Y_IN"], Zs)).edges("|Z").fillet(2.0))
    # relief under the opposite carriage's rack (it slides over this region for q < ~23 mm)
    body = body.cut(box(-40, P["CARRIAGE_X"][0], 0, 40, zt - P["OPP_RELIEF"], zt + 1))
    # carriage interface: M3 heat-set inserts from the top (as in the stock tips) + blind screw-tip clearance
    for (hx, hy) in P["MOUNT_HOLES"]:
        zi = zt - P["MOUNT_INSERT_DEPTH"]
        body = body.cut(cyl_z(hx, hy, P["MOUNT_INSERT_D"], zi, zt + 1))
        body = body.cut(cyl_z(hx, hy, P["M3_CLEAR"], zi - P["SCREW_TIP_CLEAR"], zi + 0.01))
    for (tx, ty) in P["THUMB_XY"]:                      # heat-set inserts for the thumbscrews
        body = body.cut(cyl_z(tx, ty, P["INSERT_D"], Zs - 1, Zs + P["INSERT_DEPTH"]))
    for (dx, dy) in P["DOWEL_XY"]:                      # dowel press holes
        body = body.cut(cyl_z(dx, dy, P["DOWEL_PRESS"], Zs - 1, Zs + P["DOWEL_IN_SOCKET"]))
    sb = spcb_bottom_z()                                 # pogo PCB pocket (open at the bottom)
    body = body.cut(box(-P["SPCB_X"], P["SPCB_X"], *P["SPCB_Y"], Zs - 1, sb + P["SPCB_T"] + 0.1))
    cz0, cz1 = Zs + P["CABLE_Z"][0], Zs + P["CABLE_Z"][1]
    body = body.cut(box(*P["CABLE_X"], P["SPCB_Y"][0] + 1, P["Y_OUT"] + 1, cz0, cz1))
    # zip-tie tab above the cable exit; runs up to the carriage face so it prints from the bed
    tab = box(0.5, 8.0, P["Y_OUT"] - 0.5, P["Y_OUT"] + 4.0, cz1 + 0.6, zt)
    tab = tab.cut(box(2.0, 6.5, P["Y_OUT"] + 1.1, P["Y_OUT"] + 2.6, Zs, zt + 1))
    return body.union(tab)


# ----------------------------------------------------------------------------------------------
# Cartridge (finger)
# ----------------------------------------------------------------------------------------------
def cartridge_blank():
    hx, rx, sx = P["DOCK_HALF_X"], P["BEAM_ROOT_HALF_X"], P["SENSE_HALF_X"]
    xz = [(-hx, Zs), (hx, Zs), (hx, Zf), (rx, Zf), (sx, P["BEAM_PAR_Z"]), (sx, Z_END), (-sx, Z_END),
          (-sx, P["BEAM_PAR_Z"]), (-rx, Zf), (-hx, Zf)]
    xz_r = [1.0, 1.0, 1.0, 1.2, 12.0, P["NOSE_R_XZ"], P["NOSE_R_XZ"], 12.0, 1.2, 1.0]
    A = xz_extrude(xz, xz_r, -5, 40)
    yl, zl = P["BACK_LOW"]
    yz = [(P["Y_IN"], Zs), (P["Y_OUT"], Zs), (P["Y_OUT"], Zf), (P["BACK_TOP_Y"], Zf), (yl, zl),
          (P["BACK_END_Y"], Z_END), (Y_FACE, Z_END), (Y_FACE, P["INCLINE_END_Z"]), (P["Y_IN"], Zf)]
    yz_r = [0.4, 1.0, 0.5, 2.0, 3.0, P["NOSE_R_BACK"], P["NOSE_R_IN"], 0.0, 0.0]
    B = yz_extrude(yz, yz_r, -30, 30)
    return A.intersect(B)


def make_cartridge():
    c = cartridge_blank()
    # sensor bay pocket
    pc = P["POCKET_CLEAR"]
    hw = PAD_HALF_X + pc
    z0, z1 = PAD_DIST_Z - pc, PAD_PROX_Z + pc
    pocket = (rpoly(cq.Workplane("XZ"), [(-hw, z0), (hw, z0), (hw, z1), (-hw, z1)], [P["PAD_R"] + pc] * 4)
              .extrude(Y_POCKET - (Y_FACE - 1.0)).translate((0, Y_POCKET, 0)))
    c = c.cut(pocket)
    # tail groove following the inner face up to the notch (floor flush with the pocket floor)
    g, th = TAIL_GROOVE, P["TAIL_HALF_X"]
    nz = Zs - P["NOTCH_FLOOR"]
    groove = [(Y_FACE - 1.0, PAD_PROX_Z - 0.5), (Y_FACE + g, PAD_PROX_Z - 0.5), (Y_FACE + g, P["INCLINE_END_Z"]),
              (P["Y_IN"] + g, Zf), (P["Y_IN"] + g, nz + 0.01), (P["Y_IN"] - 1.0, nz + 0.01), (P["Y_IN"] - 1.0, Zf),
              (Y_FACE - 1.0, P["INCLINE_END_Z"])]
    c = c.cut(yz_extrude(groove, [0] * len(groove), -th, th))
    # notch (open to the docking face) from the inner face into the PCB cavity + rounded bend edge
    cav_y0 = P["CAVITY"]["y"][0]
    c = c.cut(box(-th, th, P["Y_IN"] - 1, cav_y0 + 0.4, nz, Zs + 1))
    R, yb = P["BEND_R"], P["Y_IN"] + g
    corner = box(-th, th, yb - 0.01, yb + R, nz - R, nz + 0.01)
    keep = cq.Workplane("YZ").circle(R).extrude(2 * th).translate((-th, yb + R, nz - R))
    c = c.cut(corner.cut(keep))
    # finger PCB seat + bottom-side component cavity
    pcb, cav = P["PCB"], P["CAVITY"]
    seat_z = Zs - pcb["recess"] - pcb["t"]
    c = c.cut(box(-pcb["x"], pcb["x"], *pcb["y"], seat_z, Zs + 1))
    c = c.cut(box(-cav["x"], cav["x"], *cav["y"], seat_z - cav["depth"], seat_z + 0.01))
    # dowel holes: round on -x, slot (along x) on +x, with lead-in chamfers
    (dx0, dy0), (dx1, dy1) = P["DOWEL_XY"]
    dd = P["DOWEL_D"] + 0.05
    c = c.cut(cyl_z(dx0, dy0, dd, Zs - P["DOWEL_HOLE_DEPTH"], Zs + 1))
    c = c.cut(cq.Workplane("XY").slot2D(dd + 1.2, dd).extrude(P["DOWEL_HOLE_DEPTH"] + 1)
              .translate((dx1, dy1, Zs - P["DOWEL_HOLE_DEPTH"])))
    for (dx, dy) in P["DOWEL_XY"]:
        c = c.cut(cq.Workplane("XY").circle(dd / 2).workplane(offset=0.6).circle(dd / 2 + 0.6)
                  .loft().translate((dx, dy, Zs - 0.6)))
    # thumbscrew clearance holes through the wings
    for (tx, ty) in P["THUMB_XY"]:
        c = c.cut(cyl_z(tx, ty, P["M3_CLEAR"], Zf - 1, Zs + 1))
    # skin-retention grooves across both side faces (closed toward the face, open at the back)
    rb = P["SKIN_RIB"]
    sx = P["SENSE_HALF_X"]
    for sgn in (-1, 1):
        xa, xb = sorted((sgn * (sx - rb["depth"]), sgn * (sx + 5)))
        c = c.cut(box(xa, xb, rb["y0"], 40, rb["z"] - rb["w"] / 2, rb["z"] + rb["w"] / 2))
    return c


# ----------------------------------------------------------------------------------------------
# Skin (TPU 85A snap-on cap)
# ----------------------------------------------------------------------------------------------
def make_skin(core_blank):
    t, ts, lip = P["SKIN_T"], P["SKIN_SIDE_T"], P["SKIN_LIP"]
    hx, rx, sx = P["DOCK_HALF_X"], P["BEAM_ROOT_HALF_X"], P["SENSE_HALF_X"]
    zt = P["SKIN_TOP_Z"]
    xz = [(-hx - ts, Zs), (hx + ts, Zs), (hx + ts, Zf), (rx + ts, Zf), (sx + ts, P["BEAM_PAR_Z"]),
          (sx + ts, P["TCP_Z"]), (-sx - ts, P["TCP_Z"]), (-sx - ts, P["BEAM_PAR_Z"]), (-rx - ts, Zf), (-hx - ts, Zf)]
    xz_r = [0, 0, 0, 0, 12.0 + ts, P["NOSE_R_XZ"] + ts, P["NOSE_R_XZ"] + ts, 12.0 + ts, 0, 0]
    A = xz_extrude(xz, xz_r, -10, 40)
    yl, zl = P["BACK_LOW"]
    zb = zt + 2
    yz = [(P["CONTACT_Y"], zb), (y_back(zb) + ts, zb), (yl + ts, zl), (P["BACK_END_Y"] + ts, P["TCP_Z"]),
          (P["CONTACT_Y"], P["TCP_Z"])]
    yz_r = [0, 0, 3.0, P["NOSE_R_BACK"] + ts, P["NOSE_R_IN"] + t]
    B = yz_extrude(yz, yz_r, -40, 40)
    outer = A.intersect(B).intersect(box(-40, 40, -10, 40, P["TCP_Z"] - 5, zt))
    # subtract the UNCUT core: pad + tails sit flush in pocket/groove, so the skin's inner surface
    # is one flat plane over the whole sensing area
    skin = outer.cut(core_blank)
    win = [(y_back(zb), zb), (40, zb), (40, P["TCP_Z"] - 5), (P["BACK_END_Y"] - 0.2, P["TCP_Z"] - 5),
           (P["BACK_END_Y"] - 0.2, Z_END + 1.6), (yl, zl)]
    skin = skin.cut(yz_extrude(win, [0] * len(win), -(sx - lip), sx - lip))   # open back, keep lips
    # retention ribs on the inside of both side walls (lead-in ramp at the front end)
    rb = P["SKIN_RIB"]
    h = rb["depth"] - rb["clear"]
    w = rb["w"] - 2 * rb["clear"]
    y0, y1 = rb["y0"] + rb["clear"] + 0.2, rb["y1"]
    for sgn in (-1, 1):
        pts = [(sgn * (sx + 0.01), y0), (sgn * (sx + 0.01), y1), (sgn * (sx - h), y1), (sgn * (sx - h), y0 + h)]
        if sgn < 0:
            pts = pts[::-1]
        rib = (cq.Workplane("XY").polyline(pts).close().extrude(w).translate((0, 0, rb["z"] - w / 2)))
        skin = skin.union(rib)
    return skin


# ----------------------------------------------------------------------------------------------
# Placeholders (fit checks + assembly STEP)
# ----------------------------------------------------------------------------------------------
def make_pad():
    hw = PAD_HALF_X
    return (rpoly(cq.Workplane("XZ"), [(-hw, PAD_DIST_Z), (hw, PAD_DIST_Z), (hw, PAD_PROX_Z), (-hw, PAD_PROX_Z)],
                  [P["PAD_R"]] * 4).extrude(P["PAD_T"]).translate((0, Y_POCKET, 0)))


def make_finger_pcb():
    pcb, cav = P["PCB"], P["CAVITY"]
    z1 = Zs - pcb["recess"]
    board = box(-pcb["x"] + 0.1, pcb["x"] - 0.1, pcb["y"][0] + 0.1, pcb["y"][1] - 0.1, z1 - pcb["t"], z1)
    comps = box(-cav["x"] + 0.4, cav["x"] - 0.4, cav["y"][0] + 0.2, cav["y"][1] - 0.4,
                z1 - pcb["t"] - 2.1, z1 - pcb["t"])
    return board, comps


def make_socket_pcb_and_pogos():
    sb = spcb_bottom_z()
    board = box(-P["SPCB_X"] + 0.15, P["SPCB_X"] - 0.15, P["SPCB_Y"][0] + 0.15, P["SPCB_Y"][1] - 0.15,
                sb, sb + P["SPCB_T"])
    pins = None
    for i in range(P["POGO_N"]):
        x = (i - (P["POGO_N"] - 1) / 2) * P["POGO_PITCH"]
        pin = cyl_z(x, P["POGO_Y"], 1.5, sb - P["POGO_H"], sb)
        pins = pin if pins is None else pins.union(pin)
    return board, pins


def make_hardware():
    screws = None
    for (tx, ty) in P["THUMB_XY"]:
        s = cyl_z(tx, ty, P["THUMB_HEAD_D"], Zf - P["THUMB_HEAD_H"], Zf).union(cyl_z(tx, ty, 3.0, Zf, Zs + 5.5))
        screws = s if screws is None else screws.union(s)
    dowels = None
    for (dx, dy) in P["DOWEL_XY"]:
        d = cyl_z(dx, dy, P["DOWEL_D"], Zs + P["DOWEL_IN_SOCKET"] - P["DOWEL_LEN"], Zs + P["DOWEL_IN_SOCKET"])
        dowels = d if dowels is None else dowels.union(d)
    return screws, dowels


def sanity(parts):
    bb = parts["cartridge"].val().BoundingBox()
    assert abs(bb.ymin - Y_FACE) < 1e-3 and bb.ymax <= P["Y_OUT"] + 1e-3, "cartridge y-extent wrong (profile failed?)"
    assert abs(bb.zmin - Z_END) < 1e-3 and abs(bb.zmax - Zs) < 1e-3, "cartridge z-extent wrong"
    sb = parts["skin"].val().BoundingBox()
    assert abs(sb.ymin - P["CONTACT_Y"]) < 1e-3 and abs(sb.zmin - P["TCP_Z"]) < 1e-3, "skin extent wrong"
    for k, v in parts.items():
        assert v.val().isValid(), f"{k} is not a valid solid"
    assert abs((Y_FACE + TAIL_GROOVE) - Y_POCKET) < 1e-9, "tail groove floor must be flush with the pocket floor"


def build_all():
    blank = cartridge_blank()
    parts = dict(socket=make_socket(), cartridge=make_cartridge(), skin=make_skin(blank), pad=make_pad())
    parts["finger_pcb"], parts["finger_pcb_parts"] = make_finger_pcb()
    parts["socket_pcb"], parts["pogo_pins"] = make_socket_pcb_and_pogos()
    parts["thumbscrews"], parts["dowels"] = make_hardware()
    sanity(parts)
    return parts


COLORS = dict(socket=(0.35, 0.35, 0.38), cartridge=(0.15, 0.45, 0.75), skin=(0.95, 0.55, 0.15),
              pad=(0.85, 0.7, 0.2), finger_pcb=(0.1, 0.5, 0.2), finger_pcb_parts=(0.2, 0.2, 0.2),
              socket_pcb=(0.1, 0.5, 0.2), pogo_pins=(0.85, 0.75, 0.3), thumbscrews=(0.7, 0.7, 0.7),
              dowels=(0.7, 0.7, 0.7))


def export(parts):
    os.makedirs(OUT, exist_ok=True)
    for name in ("socket", "cartridge", "skin"):
        cq.exporters.export(parts[name], os.path.join(OUT, f"{name}.step"))
        cq.exporters.export(parts[name], os.path.join(OUT, f"{name}.stl"), tolerance=0.02, angularTolerance=0.1)
    asm = cq.Assembly(name="yam_tactile_finger_right_q0")
    for k, v in parts.items():
        asm.add(v, name=k, color=cq.Color(*COLORS[k]))
    asm.export(os.path.join(OUT, "finger_assembly_right_q0.step"))
    for k in ("pad", "finger_pcb", "finger_pcb_parts", "socket_pcb", "pogo_pins", "thumbscrews", "dowels"):
        cq.exporters.export(parts[k], os.path.join(OUT, f"ph_{k}.stl"), tolerance=0.02)
    with open(os.path.join(OUT, "params.json"), "w") as f:
        json.dump(dict(params=P, derived=DERIVED), f, indent=1)


if __name__ == "__main__":
    parts = build_all()
    for k, v in parts.items():
        s = v.val()
        bb = s.BoundingBox()
        print(f"{k:18s} vol {s.Volume():9.1f} mm3  valid {s.isValid()}  x[{bb.xmin:7.2f},{bb.xmax:7.2f}] "
              f"y[{bb.ymin:7.2f},{bb.ymax:7.2f}] z[{bb.zmin:8.2f},{bb.zmax:8.2f}]")
    print({k: round(v, 3) for k, v in DERIVED.items()})
    export(parts)
    print("exported to", OUT)
