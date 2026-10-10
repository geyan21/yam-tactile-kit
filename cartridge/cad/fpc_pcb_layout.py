"""
Generate the FPC pad (two layers, FlexiTac-style sandwich), the finger-PCB / socket-PCB outlines,
pin maps and the taxel map, all derived from the cartridge parameters.

Outputs (./out/fpc_pcb/):
  fpc_stack_view.dxf        all layers aligned as assembled, seen from the contact side (u = x)
  fpc_rows_bottom_fab.dxf   bottom FPC (16 row electrodes), copper-side view  -> fab
  fpc_cols_top_fab.dxf      top FPC (8 column electrodes), copper-side view (mirrored) -> fab
  finger_pcb_outline.dxf    27.0 x 13.8 mm board: outline, pogo target pads, ZIF/keep-out zones
  socket_pcb_outline.dxf    pogo carrier board
  pinmap.json, taxel_map.json, fpc_preview.png, pcb_preview.png
DXF layers: OUTLINE, CU_ELECTRODE, CU_TRACE, COVERLAY_OPEN, SLOT, STIFFENER, VELOSTAT, NOTE.
Units mm. Stack-view coordinates: u = finger x, v = distance from the pad's distal edge toward the
base (v = z - PAD_DIST_Z).
"""
import json
import math
import os
import sys
import numpy as np
import ezdxf
from shapely.geometry import box as sbox, LineString, Polygon
from shapely.ops import unary_union
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yam_tactile_finger as F  # noqa: E402

P, D = F.P, F.DERIVED
OUT = os.path.join(F.OUT, "fpc_pcb")
os.makedirs(OUT, exist_ok=True)

NR, NC, PITCH, EW = P["N_ROWS"], P["N_COLS"], P["PITCH"], P["ELECTRODE_W"]
PH = D["PAD_HALF_X"]
L_PAD = D["PAD_PROX_Z"] - D["PAD_DIST_Z"]
V0 = P["MARGIN_DIST"]                 # active area starts here (v)
V1 = V0 + D["ACT_L"]                  # active area ends here
AW2 = D["ACT_W"] / 2
TRACE_W, LANE = 0.10, 0.20            # margin routing: 0.1 mm traces on a 0.2 mm grid
TAIL_TRACE_W, TP = 0.25, P["TAIL_PITCH"]
FINGER_W, FINGER_L, FINGER_EDGE = 0.30, 3.0, 0.3
STIFF_L = 4.5
SLOT_W = 0.2                          # laser-cut compliance slots between electrodes
SLOT_CU_MIN = 0.2                     # slot edge -> copper
EDGE_CU_PAD, EDGE_CU_TAIL = 0.4, 0.3  # outline -> copper: pad (laminate seal) / tail
ZIF = dict(body_extra=5.0, depth=5.5, gap_min=1.0)   # keep-out: width = (n-1)*0.5 + body_extra


# ----------------------------------------------------------------------------------------------
# tail length from the CAD path (pad proximal edge -> ZIF stop)
# ----------------------------------------------------------------------------------------------
def tail_length():
    g, R = F.TAIL_GROOVE, P["BEND_R"]
    nz = D["Zs"] - P["NOTCH_FLOOR"]
    s1 = P["INCLINE_END_Z"] - D["PAD_PROX_Z"]
    s2 = math.hypot(P["Y_IN"] - D["Y_FACE"], D["Zf"] - P["INCLINE_END_Z"])
    s3 = (nz - R) - D["Zf"]
    bend = math.pi / 2 * (R + 0.1)
    zif_front = P["CAVITY"]["y"][0] + 0.2
    s4 = (zif_front + P["ZIF_DEPTH"]) - (P["Y_IN"] + g + R)
    total = s1 + s2 + s3 + bend + s4
    return dict(bay=s1, incline=s2, flange=s3, bend=bend, into_zif=s4, total=total, slack=1.0,
                cut_length=round(total + 1.0, 2))


TL = tail_length()
L_TAIL = TL["cut_length"]
V_END = L_PAD + L_TAIL


def rrect(u0, u1, v0, v1, r):
    return sbox(u0 + r, v0 + r, u1 - r, v1 - r).buffer(r, resolution=16) if r > 0 else sbox(u0, v0, u1, v1)


def path(pts, w):
    return LineString(pts).buffer(w / 2, cap_style=2, join_style=2)


def tail_slots(u_lo, u_hi, n):
    c = (u_lo + u_hi) / 2
    return [c + (i - (n - 1) / 2) * TP for i in range(n)]


# ----------------------------------------------------------------------------------------------
# bottom FPC: 16 row electrodes (copper faces the Velostat = toward the contact side)
# ----------------------------------------------------------------------------------------------
def rows_layer():
    rows_v = [V0 + PITCH * (k + 0.5) for k in range(NR)]
    slots_u = tail_slots(*P["TAIL_ROWS_U"], NR)
    electrodes, traces, pinmap = [], [], []
    half = NR // 2
    for k in range(NR):
        v = rows_v[k]
        electrodes.append(sbox(-AW2, v - EW / 2, AW2, v + EW / 2))
        if k < half:          # distal rows -> left margin; inner lane = most proximal row
            idx = half - 1 - k
            lane = -AW2 - 0.35 - LANE * idx
            h = V1 + 0.25 + LANE * idx
            s = k
            pts = [(-AW2 + 0.2, v), (lane, v), (lane, h), (slots_u[s], h), (slots_u[s], L_PAD + 0.2)]
        else:                 # proximal rows -> right margin
            idx = NR - 1 - k
            lane = AW2 + 0.35 + LANE * idx
            h = V1 + 0.25 + LANE * idx
            s = half + idx
            pts = [(AW2 - 0.2, v), (lane, v), (lane, h), (slots_u[s], h), (slots_u[s], L_PAD + 0.2)]
        traces.append(path(pts, TRACE_W))
        traces.append(path([(slots_u[s], L_PAD), (slots_u[s], V_END - FINGER_EDGE)], TAIL_TRACE_W))
        pinmap.append(dict(signal=f"ROW{k:02d}", tail_pin=s + 1, u=round(slots_u[s], 3)))
    slots = [sbox(-AW2 + 0.4, rows_v[k] + PITCH / 2 - SLOT_W / 2, AW2 - 0.4, rows_v[k] + PITCH / 2 + SLOT_W / 2)
             for k in range(NR - 1)]
    fingers = [sbox(u - FINGER_W / 2, V_END - FINGER_EDGE - FINGER_L, u + FINGER_W / 2, V_END - FINGER_EDGE)
               for u in slots_u]
    fingers_by_net = [None] * NR
    for d_ in pinmap:
        fingers_by_net[int(d_["signal"][3:])] = fingers[d_["tail_pin"] - 1]
    outline = unary_union([rrect(-PH, PH, 0, L_PAD, P["PAD_R"]),
                           sbox(P["TAIL_ROWS_U"][0], L_PAD - 1, P["TAIL_ROWS_U"][1], V_END)])
    outline = outline.buffer(0.5, resolution=16).buffer(-0.5, resolution=16)   # round the tail root
    stiff = sbox(P["TAIL_ROWS_U"][0], V_END - STIFF_L, P["TAIL_ROWS_U"][1], V_END)
    return dict(outline=outline, electrodes=electrodes, traces=traces, slots=slots, fingers=fingers,
                fingers_by_net=fingers_by_net, stiffener=stiff, gang=gang_opening(slots_u),
                pinmap=sorted(pinmap, key=lambda d: d["tail_pin"]))


# ----------------------------------------------------------------------------------------------
# top FPC: 8 column electrodes (copper faces the Velostat = away from the contact side)
# ----------------------------------------------------------------------------------------------
def cols_layer():
    cols_u = [-AW2 + PITCH * (j + 0.5) for j in range(NC)]
    slots_u = tail_slots(*P["TAIL_COLS_U"], NC)
    electrodes, traces, pinmap = [], [], []
    for j in range(NC):
        u = cols_u[j]
        electrodes.append(sbox(u - EW / 2, V0, u + EW / 2, V1))
        g = V1 + 0.3 + LANE * (NC - 1 - j)          # column nearest the tail turns first
        pts = [(u, V1 - 0.2), (u, g), (slots_u[j], g), (slots_u[j], L_PAD + 0.2)]
        traces.append(path(pts, TRACE_W))
        traces.append(path([(slots_u[j], L_PAD), (slots_u[j], V_END - FINGER_EDGE)], TAIL_TRACE_W))
        pinmap.append(dict(signal=f"COL{j}", tail_pin=j + 1, u=round(slots_u[j], 3)))
    slots = [sbox(cols_u[j] + PITCH / 2 - SLOT_W / 2, V0 + 0.4, cols_u[j] + PITCH / 2 + SLOT_W / 2, V1 - 0.4)
             for j in range(NC - 1)]
    fingers = [sbox(u - FINGER_W / 2, V_END - FINGER_EDGE - FINGER_L, u + FINGER_W / 2, V_END - FINGER_EDGE)
               for u in slots_u]
    outline = unary_union([rrect(-PH, PH, 0, L_PAD, P["PAD_R"]),
                           sbox(P["TAIL_COLS_U"][0], L_PAD - 1, P["TAIL_COLS_U"][1], V_END)])
    outline = outline.buffer(0.5, resolution=16).buffer(-0.5, resolution=16)
    stiff = sbox(P["TAIL_COLS_U"][0], V_END - STIFF_L, P["TAIL_COLS_U"][1], V_END)
    return dict(outline=outline, electrodes=electrodes, traces=traces, slots=slots, fingers=fingers,
                fingers_by_net=fingers, stiffener=stiff, gang=gang_opening(slots_u), pinmap=pinmap)


def gang_opening(slots_u):
    """One coverlay opening over all contact fingers (no 0.1 mm webs)."""
    return sbox(min(slots_u) - FINGER_W / 2 - 0.25, V_END - FINGER_EDGE - FINGER_L - 0.3,
                max(slots_u) + FINGER_W / 2 + 0.25, V_END + 0.5)


def velostat():
    return sbox(-AW2 - 0.5, V0 - 0.5, AW2 + 0.5, V1 + 0.5)


# ----------------------------------------------------------------------------------------------
# checks
# ----------------------------------------------------------------------------------------------
def drc(layer, name, n_pins, tail_u):
    issues = []
    allcu = unary_union(layer["electrodes"] + layer["traces"] + layer["fingers"])
    allcu = allcu.difference(sbox(-50, V_END - STIFF_L, 50, V_END + 1))   # contact fingers run to the edge
    pad_zone = sbox(-50, -1, 50, L_PAD)
    for zone, clr, tag in ((pad_zone, EDGE_CU_PAD, "pad"), (sbox(-50, L_PAD, 50, V_END + 1), EDGE_CU_TAIL, "tail")):
        cu = allcu.intersection(zone)
        if not layer["outline"].buffer(-clr).buffer(1e-6).contains(cu):
            issues.append(f"{name}: copper within {clr} mm of the outline ({tag}), "
                          f"area {cu.difference(layer['outline'].buffer(-clr)).area:.4f} mm2")
    per_net = [unary_union([e, layer["traces"][2 * i], layer["traces"][2 * i + 1], layer["fingers_by_net"][i]])
               for i, e in enumerate(layer["electrodes"])]
    min_gap = min(per_net[i].distance(per_net[j]) for i in range(len(per_net)) for j in range(i + 1, len(per_net)))
    if min_gap < 0.08:
        issues.append(f"{name}: min copper gap between nets {min_gap:.3f} mm < 0.08")
    sl = unary_union(layer["slots"])
    slot_gap = sl.distance(unary_union(layer["electrodes"] + layer["traces"]))
    if slot_gap < SLOT_CU_MIN - 1e-6:
        issues.append(f"{name}: slot-to-copper {slot_gap:.3f} mm < {SLOT_CU_MIN}")
    w_need = (n_pins + 1) * TP
    w = tail_u[1] - tail_u[0]
    if abs(w - w_need) > 0.05:
        issues.append(f"{name}: tail width {w:.2f} mm, a {n_pins}-pin 0.5 mm FFC needs {w_need:.2f} +-0.05")
    return issues, round(min_gap, 3), round(slot_gap, 3)


# ----------------------------------------------------------------------------------------------
# DXF / PNG output
# ----------------------------------------------------------------------------------------------
LAYERS = dict(OUTLINE=7, CU_ELECTRODE=1, CU_TRACE=1, COVERLAY_OPEN=3, SLOT=5, STIFFENER=6, VELOSTAT=2, NOTE=8)


def add_geom(msp, geom, layer, mirror=False):
    geoms = getattr(geom, "geoms", [geom])
    for g in geoms:
        rings = [g.exterior] + list(g.interiors) if isinstance(g, Polygon) else [g]
        for r in rings:
            pts = [(-x if mirror else x, y) for x, y in r.coords]
            msp.add_lwpolyline(pts, close=True, dxfattribs=dict(layer=layer))


def new_doc():
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    for n, c in LAYERS.items():
        doc.layers.add(n, color=c)
    return doc


def write_layer_dxf(layer, fname, mirror, title):
    doc = new_doc(); msp = doc.modelspace()
    add_geom(msp, layer["outline"], "OUTLINE", mirror)
    for e in layer["electrodes"]:
        add_geom(msp, e, "CU_ELECTRODE", mirror)
        add_geom(msp, e.buffer(-0.05), "COVERLAY_OPEN", mirror)
    for t in layer["traces"]:
        add_geom(msp, t, "CU_TRACE", mirror)
    for f in layer["fingers"]:
        add_geom(msp, f, "CU_ELECTRODE", mirror)
    add_geom(msp, layer["gang"].intersection(layer["outline"].buffer(0.5)), "COVERLAY_OPEN", mirror)
    for s in layer["slots"]:
        add_geom(msp, s, "SLOT", mirror)
    add_geom(msp, layer["stiffener"], "STIFFENER", mirror)
    msp.add_text(title, height=1.0, dxfattribs=dict(layer="NOTE")).set_placement((-PH, -4))
    doc.saveas(os.path.join(OUT, fname))


def write_stack_dxf(rows, cols):
    doc = new_doc(); msp = doc.modelspace()
    for layer, tag in ((rows, "B"), (cols, "T")):
        add_geom(msp, layer["outline"], "OUTLINE")
        for e in layer["electrodes"]:
            add_geom(msp, e, "CU_ELECTRODE")
    add_geom(msp, velostat(), "VELOSTAT")
    msp.add_text("STACK VIEW from the contact side: top FPC (cols, copper down) / Velostat / bottom FPC (rows, copper up)",
                 height=0.8, dxfattribs=dict(layer="NOTE")).set_placement((-PH, -4))
    doc.saveas(os.path.join(OUT, "fpc_stack_view.dxf"))


def preview(rows, cols):
    fig, axs = plt.subplots(1, 3, figsize=(17, 13))
    def draw(ax, layer, title, extra=None):
        def fill(geom, **kw):
            for g in getattr(geom, "geoms", [geom]):
                x, y = g.exterior.xy; ax.fill(x, y, **kw)
        fill(layer["outline"], fc="#f3d9a4", ec="k", lw=0.6)
        fill(layer["stiffener"], fc="#c9a46a", ec="none", alpha=0.5)
        for e in layer["electrodes"]: fill(e, fc="#c47a2c", ec="none")
        for t in layer["traces"]: fill(t, fc="#c47a2c", ec="none")
        for f in layer["fingers"]: fill(f, fc="#e3b23c", ec="none")
        for s in layer["slots"]: fill(s, fc="white", ec="none")
        if extra: extra(ax)
        ax.set_aspect("equal"); ax.set_title(title, fontsize=11); ax.grid(True, lw=0.3)
        ax.set_xlim(-PH - 1, PH + 1); ax.set_ylim(-1, V_END + 1)
    draw(axs[0], rows, "bottom FPC: 16 rows (copper side)")
    draw(axs[1], cols, "top FPC: 8 cols (stack view, copper faces away)")
    ax = axs[2]
    for layer, c in ((rows, "#2f6fb3"), (cols, "#d04a3a")):
        for g in getattr(layer["outline"], "geoms", [layer["outline"]]):
            x, y = g.exterior.xy; ax.plot(x, y, c, lw=0.8)
        for e in layer["electrodes"]:
            x, y = e.exterior.xy; ax.fill(x, y, fc=c, alpha=0.35, ec="none")
    x, y = velostat().exterior.xy; ax.plot(x, y, "k--", lw=0.8)
    ax.set_aspect("equal"); ax.set_title("stack view: 128 taxels (overlaps), Velostat dashed", fontsize=11)
    ax.set_xlim(-PH - 1, PH + 1); ax.set_ylim(-1, V_END + 1); ax.grid(True, lw=0.3)
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "fpc_preview.png"), dpi=85); plt.close()


# ----------------------------------------------------------------------------------------------
# finger PCB + socket PCB
# ----------------------------------------------------------------------------------------------
POGO_SIGNALS = ["GND", "D-", "D+", "VBUS", "GND"]


def pogo_x():
    n = P["POGO_N"]
    return [(i - (n - 1) / 2) * P["POGO_PITCH"] for i in range(n)]


def finger_pcb():
    pcb, cav = P["PCB"], P["CAVITY"]
    bx0, bx1, by0, by1 = -pcb["x"] + 0.1, pcb["x"] - 0.1, pcb["y"][0] + 0.1, pcb["y"][1] - 0.1
    board = sbox(bx0, by0, bx1, by1)
    pads = [sbox(x - 0.8, P["POGO_Y"] - 1.1, x + 0.8, P["POGO_Y"] + 1.1) for x in pogo_x()]
    comp_zone = sbox(-cav["x"] + 0.4, cav["y"][0] + 0.2, cav["x"] - 0.4, cav["y"][1] - 0.4)
    zif_y0 = cav["y"][0] + 0.2
    ru, cu = P["TAIL_ROWS_U"], P["TAIL_COLS_U"]
    rc, cc = (ru[0] + ru[1]) / 2, (cu[0] + cu[1]) / 2
    wr = (NR - 1) * TP + ZIF["body_extra"]                          # FH12-type 0.5 mm back-flip keep-outs
    wc = (NC - 1) * TP + ZIF["body_extra"]
    zif_rows = sbox(rc - wr / 2, zif_y0, rc + wr / 2, zif_y0 + ZIF["depth"])
    zif_cols = sbox(cc - wc / 2, zif_y0, cc + wc / 2, zif_y0 + ZIF["depth"])
    mcu = sbox(-11.6, 13.0, -6.6, 18.0)                            # QFN32 5x5 suggestion
    swd = [sbox(x - 0.4, 17.6 - 0.4, x + 0.4, 17.6 + 0.4) for x in (1.0, 2.6, 4.2, 5.8, 7.4)]
    fp = dict(board=board, pads=pads, comp_zone=comp_zone, zif_rows=zif_rows, zif_cols=zif_cols, mcu=mcu, swd=swd)
    gap = zif_rows.distance(zif_cols)
    assert gap >= ZIF["gap_min"], f"ZIF keep-outs only {gap:.2f} mm apart"
    for k in ("zif_rows", "zif_cols", "mcu"):
        assert comp_zone.buffer(1e-6).contains(fp[k]), f"{k} leaves the component zone"
    assert mcu.distance(zif_rows) > 0.5 and mcu.distance(zif_cols) > 0.5, "MCU overlaps a ZIF keep-out"
    fp["zif_gap"] = round(gap, 2)
    return fp


def socket_pcb():
    b = sbox(-P["SPCB_X"] + 0.15, P["SPCB_Y"][0] + 0.15, P["SPCB_X"] - 0.15, P["SPCB_Y"][1] - 0.15)
    pins = [sbox(x - 0.75, P["POGO_Y"] - 0.75, x + 0.75, P["POGO_Y"] + 0.75) for x in pogo_x()]
    wires = [sbox(x - 0.45, 11.6, x + 0.45, 12.6) for x in np.linspace(1.6, 6.6, 5)]
    return dict(board=b, pogo=pins, wire_pads=wires)


def write_pcb_dxf(fp, sp):
    doc = new_doc(); msp = doc.modelspace()
    add_geom(msp, fp["board"], "OUTLINE")
    for p in fp["pads"]:
        add_geom(msp, p, "CU_ELECTRODE")
    for k in ("comp_zone", "zif_rows", "zif_cols", "mcu"):
        add_geom(msp, fp[k], "NOTE")
    for p in fp["swd"]:
        add_geom(msp, p, "CU_TRACE")
    msp.add_text("FINGER PCB, top view (+z). Top: pogo targets (ENIG). Bottom (NOTE layer): ZIFs, MCU, comp zone <= 2.1 mm",
                 height=0.6, dxfattribs=dict(layer="NOTE")).set_placement((-13.5, 3.5))
    doc.saveas(os.path.join(OUT, "finger_pcb_outline.dxf"))
    doc = new_doc(); msp = doc.modelspace()
    add_geom(msp, sp["board"], "OUTLINE")
    for p in sp["pogo"]:
        add_geom(msp, p, "CU_ELECTRODE")
    for p in sp["wire_pads"]:
        add_geom(msp, p, "CU_TRACE")
    msp.add_text("SOCKET PCB, top view (+z). Pogo pins on the BOTTOM side (pointing -z), wire pads on top",
                 height=0.5, dxfattribs=dict(layer="NOTE")).set_placement((-9, 6.8))
    doc.saveas(os.path.join(OUT, "socket_pcb_outline.dxf"))


def pcb_preview(fp, sp):
    fig, axs = plt.subplots(1, 2, figsize=(15, 5.5))
    def fill(ax, g, **kw):
        x, y = g.exterior.xy; ax.fill(x, y, **kw)
    ax = axs[0]
    fill(ax, fp["board"], fc="#2e7d4f", ec="k")
    fill(ax, fp["comp_zone"], fc="none", ec="w", ls="--")
    for k, c in (("zif_rows", "#cccccc"), ("zif_cols", "#cccccc"), ("mcu", "#333333")):
        fill(ax, fp[k], fc=c, ec="k", alpha=0.6)
    for p, s in zip(fp["pads"], POGO_SIGNALS):
        fill(ax, p, fc="#e3b23c", ec="k"); cx, cy = p.centroid.xy
        ax.text(cx[0], cy[0] + 1.5, s, ha="center", fontsize=8, color="w")
    for p in fp["swd"]:
        fill(ax, p, fc="#e3b23c", ec="k")
    for k, label in (("zif_rows", "ZIF 16p (rows)"), ("zif_cols", "ZIF 8p (cols)")):
        cx, cy = fp[k].centroid.xy
        ax.text(cx[0], fp[k].bounds[1] + 0.8, label, ha="center", fontsize=8)
    ax.text(-9.1, 15.4, "MCU", ha="center", fontsize=8, color="w")
    ax.text(4.2, 18.4, "SWD test pads", ha="center", fontsize=7, color="w")
    b = fp["board"].bounds
    ax.set_title(f"finger PCB {b[2] - b[0]:.1f} x {b[3] - b[1]:.1f} mm (top view; grey = bottom side)", fontsize=11)
    ax.set_aspect("equal"); ax.set_xlim(-15, 15); ax.set_ylim(4, 21); ax.grid(True, lw=0.3)
    ax = axs[1]
    fill(ax, sp["board"], fc="#2e7d4f", ec="k")
    for p, s in zip(sp["pogo"], POGO_SIGNALS):
        fill(ax, p, fc="#e3b23c", ec="k"); cx, cy = p.centroid.xy
        ax.text(cx[0], cy[0] - 1.6, s, ha="center", fontsize=8)
    for p in sp["wire_pads"]:
        fill(ax, p, fc="#bbbbbb", ec="k")
    b = sp["board"].bounds
    ax.set_title(f"socket PCB {b[2] - b[0]:.1f} x {b[3] - b[1]:.1f} mm (pogo pins on bottom; GND pins longer)", fontsize=11)
    ax.set_aspect("equal"); ax.set_xlim(-10, 10); ax.set_ylim(6, 15); ax.grid(True, lw=0.3)
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "pcb_preview.png"), dpi=90); plt.close()


# ----------------------------------------------------------------------------------------------
# taxel map
# ----------------------------------------------------------------------------------------------
def taxel_map():
    """Taxel centres in the i2rt linear_4310 gripper body frame at q = 0 (closed), metres.
    Right finger (tip_right / joint8): moves +y with q.  Left (tip_left / joint7): rotated 180 deg
    about z, moves -y with q.  Row 0 = distal (nearest the fingertip), col 0 = -x on the right finger."""
    out = dict(frame="i2rt linear_4310 gripper body frame (MJCF body 'gripper')", units="m",
               layout=dict(rows=NR, cols=NC, pitch_m=PITCH / 1000, index="flat = row * cols + col"),
               fingers={})
    for side, sgn, joint in (("right", 1, "joint8"), ("left", -1, "joint7")):
        pts = []
        for r in range(NR):
            for c in range(NC):
                x = -AW2 + PITCH * (c + 0.5)
                z = D["ACT_Z0"] + PITCH * (r + 0.5)
                pts.append([round(sgn * x / 1000, 6), round(sgn * P["CONTACT_Y"] / 1000, 6), round(z / 1000, 6)])
        out["fingers"][side] = dict(joint=joint, slide_dir=[0.0, float(sgn), 0.0], normal_toward_object=[0.0, float(-sgn), 0.0],
                                    taxels_q0=pts)
    return out


if __name__ == "__main__":
    rows, cols = rows_layer(), cols_layer()
    issues = []
    for layer, name, n, tu in ((rows, "rows", NR, P["TAIL_ROWS_U"]), (cols, "cols", NC, P["TAIL_COLS_U"])):
        iss, gap, sgap = drc(layer, name, n, tu)
        issues += iss
        print(f"{name}: min net gap {gap} mm, slot-to-copper {sgap} mm, tail width {tu[1] - tu[0]:.2f} mm")
    print("tail:", {k: round(v, 2) for k, v in TL.items()})
    print("DRC:", issues or "clean")
    write_layer_dxf(rows, "fpc_rows_bottom_fab.dxf", False, "BOTTOM FPC rows, copper side up, 0.2 mm flex, ENIG, stiffener 0.3 mm total at fingers")
    write_layer_dxf(cols, "fpc_cols_top_fab.dxf", True, "TOP FPC cols, copper side up (mirrored from stack view), 0.2 mm flex, ENIG")
    write_stack_dxf(rows, cols)
    preview(rows, cols)
    fp, sp = finger_pcb(), socket_pcb()
    write_pcb_dxf(fp, sp); pcb_preview(fp, sp)
    print("finger PCB:", [round(v, 2) for v in fp["board"].bounds], "ZIF keep-out gap", fp["zif_gap"], "mm;",
          "socket PCB:", [round(v, 2) for v in sp["board"].bounds])
    pinmap = dict(rows_tail_16p=rows["pinmap"], cols_tail_8p=cols["pinmap"],
                  pogo=[dict(pin=i + 1, x_mm=round(x, 2), signal=s, length="long (mates first)" if s == "GND" else "standard")
                        for i, (x, s) in enumerate(zip(pogo_x(), POGO_SIGNALS))],
                  rows_readout_order=[next(d["tail_pin"] - 1 for d in rows["pinmap"] if d["signal"] == f"ROW{k:02d}") for k in range(NR)],
                  tail=TL, notes=["rows tail copper faces the finger PCB at the ZIF (PCB-side contacts)",
                                  "cols tail copper faces away from the finger PCB (far-side contacts) - or use dual-contact ZIFs"])
    json.dump(pinmap, open(os.path.join(OUT, "pinmap.json"), "w"), indent=1)
    json.dump(taxel_map(), open(os.path.join(F.OUT, "taxel_map.json"), "w"), indent=1)
    print("written to", OUT)
