"""
ENPIRE-T flex circuit: flat pattern, electrodes, routing, DRC, pin maps, taxel map and finger PCB.

The laminate lies on one extruded profile (cradle seat -> ramp -> nail plane), so its flat pattern
is exact in (u, s): u = gripper x of the right finger, s = arc length along the laminate bottom
from the flange face (s = 0) toward the tip; the tails run to negative s.

Two two-layer FPC sheets with Velostat between them (FlexiTac-style):
  rows sheet (seat side)   L1 row electrodes: strip rows across u; nail rows across u, where rows
                           that would pass the groove's closed end too closely become separate
                           left and right lines. L2 leads: strip-row vias in the left margin,
                           one via per nail-row line on its own electrode at its own lane, then a
                           staircase jog to lanes right of the strip leads, so no L2 leads cross.
  cols sheet (object side) L1 column electrodes (6 strip columns run straight into the tail; nail
                           columns along the nail), L2 leads of the nail columns (staircase to the centre).
Vias are 0.1/0.3 mm laser microvias, filled and capped, since some sit under a taxel.
Strip: 6 x 41 taxels at 2.0 mm on the cradle seat. Nail: a 1.5 mm grid around the groove.

Outputs (out/enpire/fpc_pcb/): rows_sheet_fab.dxf, cols_sheet_fab.dxf, finger_pcb_outline.dxf,
flex_preview_full.png, flex_preview_nail.png, flex_preview_tails.png, pcb_preview.png, pinmap.json,
drc.json; and out/enpire/taxel_map.json. Exits 1 if the DRC or the PCB zone check finds anything.
DXF layers: OUTLINE, CU_L1, CU_L2, VIA, COVERLAY_OPEN, VELOSTAT, STIFFENER, NOTE. Units mm.
Run (from cartridge/): python3 cad/enpire_fpc.py
"""
import itertools
import json
import os
import sys
import numpy as np
import ezdxf
from shapely.geometry import box as sbox, LineString, Point, Polygon
from shapely.ops import unary_union
from shapely import affinity
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enpire_finger as E     # noqa: E402

OUT = os.path.join(E.OUT, "fpc_pcb")
os.makedirs(OUT, exist_ok=True)

L = dict(
    STRIP_PITCH=2.0, STRIP_EW=1.4, STRIP_COLS=6, STRIP_ACTIVE_W=12.0,
    NAIL_PITCH=1.5, NAIL_EW=1.0, NAIL_ACTIVE_EDGE=0.6,
    TRACE_W=0.10, LANE=0.20, VIA_PAD=0.30, VIA_DRILL=0.10,     # laser microvias, filled + capped (via-in-pad)
    EDGE_CU=0.35, EDGE_CU_TAIL=0.25,
    VELO_MARGIN=0.3,
    TAIL_PITCH=0.3, FINGER_W=0.18, FINGER_L=2.5, FINGER_EDGE=0.3, STIFF_L=3.5, N_GND=2,
    CONN_BODY_EXTRA=3.4, CONN_DEPTH=4.3, CONN_H=1.0,
    CONN_A_Y=10.8, CONN_B_Y=18.6,         # FPC entry edge of the cols (A, near) and rows (B, far) connectors: far
                                          # enough from the slot for each tail's bend plus 1 mm of stiffener
    BEND_R=0.8,
)


# ----------------------------------------------------------------------------------------------
# geometry from the CAD
# ----------------------------------------------------------------------------------------------
PR = E.build_profile()
NR = E.nail_regions(PR)
D = E.derived(PR, NR)
FPATH = E.FlexPath(PR)
S_N0, V_N0 = D["s_nail0"], D["v_nail0"]
U_LO, U_HI = sorted(D["strip_u"])                      # laminate band on the cradle: -7.46 .. 6.54
U_C = (U_LO + U_HI) / 2


def plane_to_flat(g):
    """nail-plane (u_p, v) -> flat (u, s): u = gripper x = -u_p - 0.0532, s = s_nail0 + (v - v_nail0)."""
    g = affinity.scale(g, xfact=-1.0, yfact=1.0, origin=(0, 0))
    return affinity.translate(g, xoff=-(E.NO[0] + 7.96), yoff=S_N0 - V_N0)


def flat_to_plane_pt(u, s):
    return -(u + E.NO[0] + 7.96), s - (S_N0 - V_N0)


# ----------------------------------------------------------------------------------------------
# layout
# ----------------------------------------------------------------------------------------------
def strip_layout():
    p = L["STRIP_PITCH"]
    s0, s1 = D["s_strip"]
    n_rows = int((s1 - s0) // p)
    sr0 = s0 + ((s1 - s0) - n_rows * p) / 2
    cols_u = [U_C + (j - (L["STRIP_COLS"] - 1) / 2) * p for j in range(L["STRIP_COLS"])]
    rows_s = [sr0 + p * (k + 0.5) for k in range(n_rows)]
    act = (cols_u[0] - p / 2, cols_u[-1] + p / 2, sr0, sr0 + n_rows * p)
    return dict(cols_u=cols_u, rows_s=rows_s, active=act)


def nail_layout():
    """Best 1.5 mm grid on the nail pad (plane coords), columns split by the groove with their own
    offsets, rows common. Returns cells, columns (with v-extent) and row segments."""
    p, h = L["NAIL_PITCH"], L["NAIL_PITCH"] / 2
    A = NR["pad"].buffer(-L["NAIL_ACTIVE_EDGE"], join_style=2)
    best = (0,)
    for uL, uR, v0 in itertools.product(np.arange(0, p, 0.1), np.arange(0, p, 0.1), np.arange(0, p, 0.1)):
        colsL = [-(uL + h) - j * p for j in range(12)]
        colsR = [(uR + h) + j * p for j in range(12)]
        if min(colsR) - max(colsL) < p - 1e-9:
            continue
        rows = [A.bounds[1] + v0 + h + k * p for k in range(20)]
        cells = [(u, v) for v in rows for u in colsL + colsR if A.contains(sbox(u - h, v - h, u + h, v + h))]
        if len(cells) > best[0]:
            best = (len(cells), cells)
    cells = sorted(best[1], key=lambda c: (c[1], c[0]))
    us = sorted(set(round(c[0], 6) for c in cells))
    vs = sorted(set(round(c[1], 6) for c in cells))
    gro = NR["groove"].bounds
    v_notch = gro[1] - E.P["GROOVE_CLR"]
    cols = []
    for u in us:
        cv = [c[1] for c in cells if abs(c[0] - u) < 1e-6]
        cols.append(dict(u=u, v0=min(cv), v1=max(cv)))
    rows = []
    for v in vs:
        cu = sorted(c[0] for c in cells if abs(c[1] - v) < 1e-6)
        left = [u for u in cu if u < 0]
        right = [u for u in cu if u > 0]
        # split when the full-width electrode would pass the notch end closer than the edge clearance
        split = bool(left and right) and (v + L["NAIL_EW"] / 2 > v_notch - L["EDGE_CU"] - 0.05)
        if split:
            rows.append(dict(v=v, segs=[(min(left), max(left)), (min(right), max(right))], split=True))
        else:
            rows.append(dict(v=v, segs=[(min(cu), max(cu))], split=False))
    return dict(cells=cells, cols=cols, rows=rows, active=A, v_notch=v_notch, groove=NR["groove"])


def rect(u0, u1, s0, s1):
    return sbox(min(u0, u1), min(s0, s1), max(u0, u1), max(s0, s1))


def path(pts, w):
    return LineString(pts).buffer(w / 2, cap_style=2, join_style=2)


def via(u, s):
    return Point(u, s).buffer(L["VIA_PAD"] / 2, resolution=12)


def staircase(starts, finals, s_top, step, s_end=0.0):
    """Planar jog of a bus of leads from x-positions `starts` (at s_top) to `finals`, both sorted
    the same way: each lead drops to its own level, runs sideways, then continues down to s_end.
    Leads moving right turn first if they are right-most (and mirrored for leads moving left)."""
    paths = []
    order = np.argsort(starts)
    starts, finals = np.asarray(starts)[order], np.asarray(finals)[order]
    right = [i for i in range(len(starts)) if finals[i] >= starts[i]]
    left = [i for i in range(len(starts)) if finals[i] < starts[i]]
    levels = {}
    for rank, i in enumerate(sorted(right, key=lambda i: -starts[i])):
        levels[i] = s_top - step * rank
    for rank, i in enumerate(sorted(left, key=lambda i: starts[i])):
        levels[i] = s_top - step * rank
    out = [None] * len(starts)
    for i in range(len(starts)):
        sh = levels[i]
        out[order[i]] = [(starts[i], s_top + 0.001), (starts[i], sh), (finals[i], sh), (finals[i], s_end)]
    return out


def assign_lanes(extents, lo, hi, gap, prefer=None):
    """One lane per extent (u0, u1) inside [lo, hi], all lanes >= gap apart. Greedy by right end
    (optimal for points-in-intervals with a spacing rule); a column gap (no taxel under the via)
    is taken when it is within 0.3 mm of the earliest feasible position."""
    order = sorted(range(len(extents)), key=lambda k: (min(extents[k][1], hi), extents[k][1] - extents[k][0]))
    lanes = {}
    prefer = sorted(prefer or [])
    for k in order:
        u0, u1 = max(extents[k][0], lo), min(extents[k][1], hi)
        free = [x for x in np.arange(u0, u1 + 1e-9, 0.02) if all(abs(x - v) >= gap - 1e-9 for v in lanes.values())]
        if not free:
            raise RuntimeError(f"no lane for extent {extents[k]}")
        x = free[0]
        g = [q for q in prefer if x - 1e-9 <= q <= min(u1, x + 0.3) and all(abs(q - v) >= gap - 1e-9 for v in lanes.values())]
        lanes[k] = g[0] if g else x
    return [lanes[k] for k in range(len(extents))]


def build():
    st, nl = strip_layout(), nail_layout()
    tw, lane_p = L["TRACE_W"], L["LANE"]
    nets = {}
    def add(net, layer, g):
        nets.setdefault(net, {}).setdefault(layer, []).append(g)
    def P2F(u_p, v):
        return plane_to_flat(Point(u_p, v)).coords[0]

    band = rect(U_LO, U_HI, 0.0, S_N0 + 0.6)
    outline_sense = unary_union([band, plane_to_flat(NR["flex"])]).buffer(0.3, join_style=1).buffer(-0.3, join_style=1)
    cu_lo, cu_hi = U_LO + L["EDGE_CU"] + tw / 2 + 0.01, U_HI - L["EDGE_CU"] - tw / 2 - 0.01

    # ---- strip: columns on C1 straight into the tail, rows on R1 with left-margin vias ------------
    au0, au1, as0, as1 = st["active"]
    for j, u in enumerate(st["cols_u"]):
        add(f"SCOL{j}", "C1", rect(u - L["STRIP_EW"] / 2, u + L["STRIP_EW"] / 2, as0 + 0.05, as1 - 0.05))
        add(f"SCOL{j}", "C1", path([(u, as0 + 0.1), (u, 0.0)], 0.3))
    via_u = U_LO + L["EDGE_CU"] + L["VIA_PAD"] / 2 + 0.01
    lane0 = via_u + L["VIA_PAD"] / 2 + 0.1 + tw / 2
    strip_rows = []
    for k, s in enumerate(st["rows_s"]):
        net = f"SROW{k:02d}"
        add(net, "R1", rect(au0, au1, s - L["STRIP_EW"] / 2, s + L["STRIP_EW"] / 2))
        add(net, "R1", path([(via_u, s), (au0 + 0.2, s)], 0.3))
        add(net, "RV", via(via_u, s))
        lane = lane0 + lane_p * k
        add(net, "R2", path([(via_u, s), (lane, s), (lane, 0.0)], tw))
        strip_rows.append(dict(net=net, s=s, lane=lane))
    strip_lane_max = lane0 + lane_p * (len(strip_rows) - 1)

    # ---- nail columns (C1) + their leads (C2) ------------------------------------------------------
    h = L["NAIL_PITCH"] / 2
    rows_v = sorted(set(r["v"] for r in nl["rows"]))
    nail_cols = []
    for i, c in enumerate(sorted(nl["cols"], key=lambda c: -c["u"])):      # flat u = -u_p: sort by flat u
        net = f"NCOL{i:02d}"
        (ua, sa), (_, sb) = P2F(c["u"], c["v0"] - h + 0.05), P2F(c["u"], c["v1"] + h - 0.05)
        add(net, "C1", rect(ua - L["NAIL_EW"] / 2, ua + L["NAIL_EW"] / 2, sa, sb))
        # via in the row gap after the column's first cell (no taxel under it)
        v_gap = c["v0"] + h
        sv = P2F(c["u"], v_gap)[1] if (c["v1"] - c["v0"]) > 1e-6 else sa + 0.2
        add(net, "CV", via(ua, sv))
        nail_cols.append(dict(net=net, u=ua, s_via=sv, s0=sa, s1=sb))
    col_finals = [U_C + (i - (len(nail_cols) - 1) / 2) * lane_p for i in range(len(nail_cols))]
    s_top_c = min(c["s_via"] for c in nail_cols) - L["VIA_PAD"] / 2 - 0.12     # turn between the vias and the outline step
    for c, pts in zip(nail_cols, staircase([c["u"] for c in nail_cols], col_finals, s_top_c, lane_p)):
        add(c["net"], "C2", path([(c["u"], c["s_via"])] + pts, tw))

    # ---- nail rows (R1): band rows whole, prong rows as separate halves; vias on the electrodes ----
    col_gaps = sorted({round((a["u"] + b["u"]) / 2, 4) for a, b in zip(nail_cols, nail_cols[1:])
                       if abs(a["u"] - b["u"]) < L["NAIL_PITCH"] * 1.01})
    lines = []
    for r, row in enumerate(sorted(nl["rows"], key=lambda r: r["v"])):
        halves = row["segs"]
        tags = ["L", "R"] if row["split"] else [""]
        for (u0p, u1p), tag in zip(halves, tags):
            (ua, s), (ub, _) = P2F(u0p - h + 0.05, row["v"]), P2F(u1p + h - 0.05, row["v"])
            ua, ub = sorted((ua, ub))
            if row["split"]:      # flat u is mirrored: name halves by side in the flat pattern
                tag = "L" if (ua + ub) / 2 < U_C else "R"
            net = f"NROW{r:02d}{tag}"
            add(net, "R1", rect(ua, ub, s - L["NAIL_EW"] / 2, s + L["NAIL_EW"] / 2))
            lines.append(dict(net=net, s=s, u0=ua, u1=ub))
    ext = [(ln["u0"] + 0.2, ln["u1"] - 0.2) for ln in lines]
    lanes = assign_lanes(ext, cu_lo + 0.1, cu_hi - 0.1, gap=0.32, prefer=col_gaps)
    for ln, u in zip(lines, lanes):
        ln["lane"] = u
        add(ln["net"], "RV", via(u, ln["s"]))
    s_top_r = S_N0 - 0.8
    n_n = len(lines)
    finals = [cu_hi - lane_p * (n_n - 1 - i) for i in range(n_n)]
    order = np.argsort([ln["lane"] for ln in lines])
    fin_of = {lines[k]["net"]: finals[i] for i, k in enumerate(order)}
    assert min(finals) - strip_lane_max >= lane_p - 1e-9, "nail lanes run into the strip lanes"
    pts_all = staircase([ln["lane"] for ln in lines], [fin_of[ln["net"]] for ln in lines], s_top_r, lane_p)
    for ln, pts in zip(lines, pts_all):
        add(ln["net"], "R2", path([(ln["lane"], ln["s"])] + pts, tw))
        ln["final"] = fin_of[ln["net"]]
    return dict(nets=nets, outline=outline_sense, strip=st, nail=nl, strip_rows=strip_rows, nail_rows=lines,
                nail_cols=nail_cols, col_finals=col_finals, via_u=via_u, cu=(cu_lo, cu_hi),
                strip_lanes=(lane0, strip_lane_max))


# ----------------------------------------------------------------------------------------------
# tails (s < 0): through the flange slot, bend, fan out to 0.3 mm fingers
# ----------------------------------------------------------------------------------------------
def tail_lengths():
    """Path length of each tail from the flange face (s = 0) to its connector stop, from the CAD."""
    cav_floor = E.Zs - E.P["PCB"]["recess"] - E.P["PCB"]["t"] - E.P["CAVITY"]["depth"]
    slot = cav_floor - E.Zf
    bend = np.pi / 2 * (L["BEND_R"] + 0.1)
    y_slot = E.P["Z_SLOT"] - E.P["FLEX_T"] / 2 + 2.87
    z_contact = E.Zs - E.P["PCB"]["recess"] - E.P["PCB"]["t"] - 0.5
    ins = 2.5
    cols = slot + (z_contact - cav_floor) + bend + (L["CONN_A_Y"] - y_slot) + ins            # up, turn, into A
    rows = slot + bend + (L["CONN_B_Y"] - 1.2 - y_slot) + 2 * bend + (z_contact - cav_floor - 0.4) + ins   # floor, under A, up into B
    return dict(slot=round(slot, 2), cols=round(cols + 1.0, 2), rows=round(rows + 1.0, 2), slack=1.0)


def tail(b, sheet):
    """Outline + copper for one sheet's tail. Fingers on L2 (rows) / C2 (cols)."""
    TL = tail_lengths()
    p, fw = L["TAIL_PITCH"], L["FINGER_W"]
    tw = L["TRACE_W"]
    s_end = -TL[sheet]
    s_fan0, s_fan1 = -TL["slot"] - 1.6, -TL["slot"] - 4.6           # fan-out region inside the cavity
    if sheet == "rows":
        leads = [(r["net"], r["lane"]) for r in b["strip_rows"]] + [(r["net"], r["final"]) for r in b["nail_rows"]]
        layer = "R2"
    else:
        cols = [(f"SCOL{j}", u) for j, u in enumerate(b["strip"]["cols_u"])]
        nleads = [(c["net"], f) for c, f in zip(b["nail_cols"], b["col_finals"])]
        leads = cols[:3] + nleads + cols[3:]
        layer = "C2"
    leads = sorted(leads, key=lambda t: t[1])
    n = len(leads) + L["N_GND"]
    width = (n + 1) * p
    uc = U_C
    fingers_u = [uc + (k - (n - 1) / 2) * p for k in range(n)]
    gnd_u = [fingers_u[0], fingers_u[-1]]
    sig_u = fingers_u[1:-1]
    geo = {}
    out = []
    s_fan0 = -TL["slot"] - 1.0
    starts = []
    for net, u0 in leads:
        if sheet == "cols" and net.startswith("SCOL"):
            # strip columns drop from C1 to C2 near the flange face, clear of the nail-column bus
            j = int(net[4:])
            bus_lo = min(f for f in b["col_finals"]) - 0.6
            bus_hi = max(f for f in b["col_finals"]) + 0.6
            u_v = min(u0, bus_lo) if u0 < U_C else max(u0, bus_hi)
            out.append((net, "C1", path([(u0, 0.2), (u0, -1.1), (u_v, -1.4), (u_v, -1.6)], 0.3)))
            out.append((net, "CV", via(u_v, -1.6)))         # in the straight slot, 1.6 mm from the exit bend
            starts.append((net, u_v, -1.6))
        else:
            starts.append((net, u0, 0.0))
    stairs = staircase([u for _, u, _ in starts], sig_u, s_fan0, L["LANE"], s_end=s_end + L["FINGER_EDGE"])
    n_lev = max(1, len(starts) // 2 + 1)
    s_fan_end = s_fan0 - L["LANE"] * n_lev - 0.4
    for (net, u0, s0), uf, pts in zip(starts, sig_u, stairs):
        out.append((net, layer, path([(u0, s0)] + pts, L["TRACE_W"])))
        out.append((net, layer, rect(uf - fw / 2, uf + fw / 2, s_end + L["FINGER_EDGE"], s_end + L["FINGER_EDGE"] + L["FINGER_L"])))
    for ug in gnd_u:                         # shield/ground fingers at both ends (tied on the PCB)
        out.append(("GND", layer, rect(ug - fw / 2, ug + fw / 2, s_end + L["FINGER_EDGE"], s_end + L["FINGER_EDGE"] + L["FINGER_L"])))
    w_end = width
    lo_f, hi_f = uc - w_end / 2, uc + w_end / 2
    lo_z, hi_z = min(U_LO, lo_f), max(U_HI, hi_f)
    outline = unary_union([rect(U_LO, U_HI, 0.5, -TL["slot"] - 0.3),
                           Polygon([(U_LO, -TL["slot"] - 0.3), (U_HI, -TL["slot"] - 0.3), (hi_z, -TL["slot"] - 0.8), (lo_z, -TL["slot"] - 0.8)]),
                           rect(lo_z, hi_z, -TL["slot"] - 0.79, s_fan_end),
                           Polygon([(lo_z, s_fan_end + 0.01), (hi_z, s_fan_end + 0.01), (hi_f, s_fan_end - 0.8), (lo_f, s_fan_end - 0.8)]),
                           rect(lo_f, hi_f, s_fan_end - 0.79, s_end)]).buffer(0.2, join_style=1).buffer(-0.2, join_style=1)
    stiff = rect(uc - width / 2, uc + width / 2, s_end, s_end + L["STIFF_L"])
    gang = rect(min(fingers_u) - fw / 2 - 0.2, max(fingers_u) + fw / 2 + 0.2, s_end - 0.3,
                s_end + L["FINGER_EDGE"] + L["FINGER_L"] + 0.2)
    pins = [dict(pin=1, signal="GND", u=round(fingers_u[0], 3))] + \
           [dict(pin=k + 2, signal=net, u=round(u, 3)) for k, ((net, _), u) in enumerate(zip(leads, sig_u))] + \
           [dict(pin=n, signal="GND", u=round(fingers_u[-1], 3))]
    return dict(copper=out, outline=outline, stiffener=stiff, gang=gang, pins=pins, n=n, width=width, s_end=s_end,
                finger_zone=rect(uc - width / 2 - 1, uc + width / 2 + 1, s_end - 1, s_end + L["FINGER_EDGE"] + L["FINGER_L"] + 0.3))


def velostat(b):
    st = b["strip"]["active"]
    strip = rect(st[0] - L["VELO_MARGIN"], st[1] + L["VELO_MARGIN"], st[2] - L["VELO_MARGIN"], st[3] + L["VELO_MARGIN"])
    h = L["NAIL_PITCH"] / 2
    cells = unary_union([plane_to_flat(sbox(u - h, v - h, u + h, v + h)) for (u, v) in b["nail"]["cells"]])
    nail = cells.buffer(L["VELO_MARGIN"], join_style=2).intersection(b["outline"].buffer(-0.15))
    return strip, nail


def sheet_geoms(b, sheet):
    """All copper of one sheet: {layer: {net: geom}}."""
    layers = ("R1", "R2", "RV") if sheet == "rows" else ("C1", "C2", "CV")
    out = {ln: {} for ln in layers}
    for net, lay in b["nets"].items():
        for ln in layers:
            if ln in lay:
                out[ln][net] = unary_union([out[ln].get(net, Polygon())] + lay[ln])
    t = tail(b, sheet)
    for net, ln, g in t["copper"]:
        out[ln][net] = unary_union([out[ln].get(net, Polygon()), g])
    # vias exist on both copper layers of their sheet
    vl = layers[2]
    for net, g in out[vl].items():
        for ln in layers[:2]:
            out[ln][net] = unary_union([out[ln].get(net, Polygon()), g])
    return out, t


def drc(b):
    issues, stats = [], {}
    for sheet in ("rows", "cols"):
        cu, t = sheet_geoms(b, sheet)
        outline = unary_union([b["outline"], t["outline"]])
        sense_zone = rect(-40, 40, 0.0, 200)
        for ln in [k for k in cu if not k.endswith("V")]:
            nets = {k: v for k, v in cu[ln].items() if not v.is_empty}
            names = sorted(nets)
            gmin = np.inf
            from shapely.strtree import STRtree
            geoms = [nets[k] for k in names]
            tree = STRtree(geoms)
            for i, g in enumerate(geoms):
                for j in tree.query(g.buffer(0.2)):
                    if j <= i:
                        continue
                    d = g.distance(geoms[j])
                    gmin = min(gmin, d)
                    if d < 0.1 - 1e-6:
                        issues.append(f"{sheet}/{ln}: {names[i]} - {names[j]} gap {d:.3f} mm")
            allcu = unary_union(geoms)
            for zone, clr, tag in ((sense_zone, L["EDGE_CU"], "sensing area"), (rect(-40, 40, -60, 0.0), L["EDGE_CU_TAIL"], "tail")):
                cuz = allcu.intersection(zone).difference(t["finger_zone"])
                bad = cuz.difference(outline.buffer(-clr + 1e-4))
                if bad.area > 1e-4:
                    issues.append(f"{sheet}/{ln}: copper within {clr} mm of the outline ({tag}), {bad.area:.4f} mm2 at {np.round(bad.centroid.coords[0], 2).tolist()}")
            stats[f"{sheet}/{ln}_min_gap_mm"] = round(gmin, 3) if np.isfinite(gmin) else ">0.2"
    return issues, stats


# ----------------------------------------------------------------------------------------------
# outputs: previews, DXF, pin map, taxel map, finger PCB
# ----------------------------------------------------------------------------------------------
LAYER_COL = dict(R1="#c47a2c", R2="#2f6fb3", RV="#111111", C1="#c0392b", C2="#7d3c98", CV="#111111")
SHEETS = dict(rows=("R1", "R2", "RV"), cols=("C1", "C2", "CV"))


def _fill(ax, g, **kw):
    for gg in getattr(g, "geoms", [g]):
        if gg.is_empty or not hasattr(gg, "exterior"):
            continue
        x, y = gg.exterior.xy
        ax.fill(x, y, **kw)


def preview(b, fname, s_range=None, title=""):
    tall = s_range is None
    fig, axs = plt.subplots(1, 2, figsize=(14, 30) if tall else (16, 9))
    velo = velostat(b)
    for ax, sheet in zip(axs, ("rows", "cols")):
        cu, t = sheet_geoms(b, sheet)
        _fill(ax, unary_union([b["outline"], t["outline"]]), fc="#f6e7c8", ec="k", lw=0.6)
        for g in velo:
            _fill(ax, g, fc="none", ec="#555", lw=0.6, ls="--")
        for ln in SHEETS[sheet]:
            for net, g in cu[ln].items():
                _fill(ax, g, fc=LAYER_COL[ln], ec="none", alpha=0.9)
        _fill(ax, t["stiffener"], fc="#999", ec="none", alpha=0.3)
        ax.set_aspect("equal"); ax.grid(True, lw=0.3)
        ax.set_title({"rows": "rows sheet (seat side): L1 rows (orange), L2 leads (blue)",
                      "cols": "cols sheet (object side): L1 columns (red), L2 leads (purple)"}[sheet], fontsize=11)
        ax.set_xlabel("u = gripper x of the right finger (mm)"); ax.set_ylabel("s along the laminate from the flange face (mm)")
        if s_range:
            ax.set_ylim(*s_range)
        ax.invert_yaxis()
    fig.suptitle(title, fontsize=13)
    plt.tight_layout(); plt.savefig(os.path.join(OUT, fname), dpi=72 if tall else 80); plt.close()


DXF_LAYERS = dict(OUTLINE=7, CU_L1=1, CU_L2=5, VIA=6, COVERLAY_OPEN=3, VELOSTAT=2, STIFFENER=8, NOTE=8)


def add_geom(msp, geom, layer):
    for g in getattr(geom, "geoms", [geom]):
        if g.is_empty or not hasattr(g, "exterior"):
            continue
        for r in [g.exterior] + list(g.interiors):
            msp.add_lwpolyline(list(r.coords), close=True, dxfattribs=dict(layer=layer))


def write_sheet_dxf(b, sheet):
    doc = ezdxf.new("R2010", setup=True); doc.units = ezdxf.units.MM
    for n, c in DXF_LAYERS.items():
        doc.layers.add(n, color=c)
    msp = doc.modelspace()
    cu, t = sheet_geoms(b, sheet)
    l1, l2, lv = SHEETS[sheet]
    add_geom(msp, unary_union([b["outline"], t["outline"]]), "OUTLINE")
    for net, g in cu[l1].items():
        add_geom(msp, g, "CU_L1")
    for net, g in cu[l2].items():
        add_geom(msp, g, "CU_L2")
    for net, g in cu[lv].items():
        for gg in getattr(g, "geoms", [g]):
            c = gg.centroid
            msp.add_circle((c.x, c.y), L["VIA_DRILL"] / 2, dxfattribs=dict(layer="VIA"))
    # coverlay openings: electrode faces toward the Velostat, and the finger row
    elec = [g for net, g in cu[l1].items() if net.startswith(("SROW", "NROW", "SCOL", "NCOL"))]
    sense = rect(-40, 40, 0.0, 200)
    add_geom(msp, unary_union(elec).intersection(sense).buffer(-0.05), "COVERLAY_OPEN")
    add_geom(msp, t["gang"], "COVERLAY_OPEN")
    for g in velostat(b):
        add_geom(msp, g, "VELOSTAT")
    add_geom(msp, t["stiffener"], "STIFFENER")
    note = {"rows": "ROWS SHEET (seat side), seen from the contact side. L1 = row electrodes (face the Velostat), "
                    "L2 = leads + tail fingers. 2-layer flex, 12.5 um PI core, 1/3 oz Cu, laser microvias 0.1/0.3 filled+capped, ENIG, "
                    "stiffener to 0.2 mm at the fingers.",
            "cols": "COLS SHEET (object side), seen from the contact side (fab: mirror). L1 = column electrodes (face the Velostat), "
                    "L2 = nail-column leads + tail fingers. Same stack as the rows sheet."}[sheet]
    msp.add_text(note, height=0.5, dxfattribs=dict(layer="NOTE")).set_placement((U_LO, -tail_lengths()[sheet] - 3))
    doc.saveas(os.path.join(OUT, f"{sheet}_sheet_fab.dxf"))


def taxel_map(b):
    """Taxel centres + normals in the i2rt gripper frame at q = 0 (metres), both fingers, at the
    sensing layer and at the contact surface (skin outer / nail film), plus flat (u, s)."""
    st, nl = b["strip"], b["nail"]
    F = FPATH
    lift_sense = E.P["FLEX_T"] / 2
    taxels = []
    for k, sr in enumerate(st["rows_s"]):
        for j, u in enumerate(st["cols_u"]):
            taxels.append(dict(region="strip", row=k, col=j, u=u, s=sr, row_net=f"SROW{k:02d}", col_net=f"SCOL{j}",
                               lift_surface=E.P["FLEX_T"] + E.P["SKIN_T"]))
    h = L["NAIL_PITCH"] / 2
    row_v = {round(r["v"], 6): r for r in nl["rows"]}
    nail_rows_by = {}
    for ln in b["nail_rows"]:
        nail_rows_by.setdefault(round(ln["s"], 4), []).append(ln)
    col_by_u = {round(c["u"], 4): c["net"] for c in b["nail_cols"]}
    for (up, v) in nl["cells"]:
        uf, sf = plane_to_flat(Point(up, v)).coords[0]
        rn = [ln for ln in nail_rows_by[round(sf, 4)] if ln["u0"] - 1e-6 <= uf <= ln["u1"] + 1e-6][0]["net"]
        cn = col_by_u[min(col_by_u, key=lambda k: abs(k - uf))]
        taxels.append(dict(region="nail", row=None, col=None, u=uf, s=sf, row_net=rn, col_net=cn, lift_surface=E.POCKET_D))
    out = dict(frame="i2rt linear_4310 gripper body frame (MJCF body 'gripper'), q = 0", units="m",
               index="flat index = position in 'taxels'; strip first (row-major from the flange end), then nail",
               counts=dict(strip=sum(t["region"] == "strip" for t in taxels), nail=sum(t["region"] == "nail" for t in taxels)),
               fingers={})
    for side, sgn, joint in (("right", 1, "joint8"), ("left", -1, "joint7")):
        pts_s, pts_c, nrm = [], [], []
        for t in taxels:
            g, n = F.point_g(t["u"], t["s"], lift=lift_sense)
            gc, _ = F.point_g(t["u"], t["s"], lift=t["lift_surface"])
            M = np.diag([sgn, sgn, 1.0])
            pts_s.append((M @ g[0] / 1000).round(6).tolist())
            pts_c.append((M @ gc[0] / 1000).round(6).tolist())
            nrm.append((M @ (n[0] / np.linalg.norm(n[0]))).round(6).tolist())
        out["fingers"][side] = dict(joint=joint, slide_dir=[0.0, float(sgn), 0.0], sensor_q0=pts_s, surface_q0=pts_c,
                                    normal_toward_object=nrm)
    out["taxels"] = [dict(i=i, region=t["region"], row=t["row"], col=t["col"], row_net=t["row_net"], col_net=t["col_net"],
                          flat_mm=[round(t["u"], 3), round(t["s"], 3)]) for i, t in enumerate(taxels)]
    # bend radius of the seat under each strip row (Velostat preload depends on it)
    rr, R = E.curvature_radius(PR["C"])
    sr = np.r_[0, np.cumsum(np.linalg.norm(np.diff(rr, axis=0), axis=1))]
    out["strip_row_min_bend_radius_mm"] = [round(float(np.min(R[(sr > s - 1) & (sr < s + 1)])), 2) for s in st["rows_s"]]
    i = int(np.argmin(R))                       # tightest bend anywhere on the laminate (the flange exit, no taxels)
    out["laminate_min_bend_radius"] = dict(mm=round(float(R[i]), 2), at_s_mm=round(float(sr[i]), 2))
    return out


def finger_pcb(b):
    """Finger PCB (same seat and pogo targets as v0.2, larger board): outline, pogo pads (top),
    connector keep-outs and component zones (bottom)."""
    board = E.pcb_outline(0.1)
    pogo = [sbox(x - 0.8, E.FP["POGO_Y"] - 1.1, x + 0.8, E.FP["POGO_Y"] + 1.1)
            for x in [(i - (E.FP["POGO_N"] - 1) / 2) * E.FP["POGO_PITCH"] for i in range(E.FP["POGO_N"])]]
    tr, tc = tail(b, "rows"), tail(b, "cols")
    def conn(n, y0):
        w = (n - 1) * L["TAIL_PITCH"] + L["CONN_BODY_EXTRA"]
        return sbox(U_C - w / 2, y0, U_C + w / 2, y0 + L["CONN_DEPTH"])
    conn_a, conn_b = conn(tc["n"], L["CONN_A_Y"]), conn(tr["n"], L["CONN_B_Y"])
    zone = E.pcb_outline(E.P["CAVITY"]["inset"] + 0.4)
    slot = sbox(-8.0, E.P["Z_SLOT"] - E.P["FLEX_T"] - 0.25 + 2.87, 7.1, E.P["Z_SLOT"] + 0.25 + 2.87)
    tails_corr = sbox(-8.2, slot.bounds[1], 7.3, conn_b.bounds[1])             # where the tails run (keep clear)
    free = zone.difference(unary_union([conn_a.buffer(0.3), conn_b.buffer(0.3), tails_corr]))
    fp = dict(board=board, pogo=pogo, conn_a=conn_a, conn_b=conn_b, zone=zone, tails=tails_corr, free=free, slot=slot)
    issues = []
    for k in ("conn_a", "conn_b"):
        if not zone.buffer(1e-6).contains(fp[k]):
            issues.append(f"{k} leaves the component zone")
    # tail routes in the y-z plane (the 3D tails are stubs): each tail bends 90 deg (R = BEND_R + its
    # thickness) and needs STIFF_L - FINGER_L of straight stiffener in front of its connector
    rb, out_len = L["BEND_R"] + 0.1, L["STIFF_L"] - L["FINGER_L"]
    y_cols = E.P["Z_SLOT"] - E.P["FLEX_T"] + 2.87 + 0.06                     # cols sheet (front) rising through the slot
    room_a = L["CONN_A_Y"] - out_len - (y_cols + rb)
    a_back = L["CONN_A_Y"] + L["CONN_DEPTH"]                                   # rows tail runs under A, then S-bends up into B
    room_b = L["CONN_B_Y"] - out_len - (a_back + 0.3 + 2 * rb)
    fp["tail_room_mm"] = dict(cols_before_A=round(room_a, 2), rows_before_B=round(room_b, 2))
    if room_a < 0.2:
        issues.append(f"cols tail: {room_a:.2f} mm between its bend and the stiffener in front of connector A")
    if room_b < 0.2:
        issues.append(f"rows tail: {room_b:.2f} mm for the S-bend between connector A and the stiffener at B")
    fp["free_mm2"] = round(free.area, 0)
    fp["issues"] = issues
    return fp


def write_pcb(fp):
    doc = ezdxf.new("R2010", setup=True); doc.units = ezdxf.units.MM
    for n, c in DXF_LAYERS.items():
        doc.layers.add(n, color=c)
    msp = doc.modelspace()
    add_geom(msp, fp["board"], "OUTLINE")
    for p in fp["pogo"]:
        add_geom(msp, p, "CU_L1")
    for k in ("conn_a", "conn_b", "zone", "tails", "free"):
        add_geom(msp, fp[k], "NOTE")
    msp.add_text("ENPIRE-T FINGER PCB, top view (+z). Top: 5 pogo targets (ENIG, same places as v0.2). Bottom (NOTE): "
                 "cols connector A (near), rows connector B (far), free area for the readout; keep the tail corridor clear. "
                 "Parts <= 2.2 mm.", height=0.5, dxfattribs=dict(layer="NOTE")).set_placement((-14.5, 1.0))
    doc.saveas(os.path.join(OUT, "finger_pcb_outline.dxf"))
    fig, ax = plt.subplots(figsize=(10, 8))
    _fill(ax, fp["board"], fc="#2e7d4f", ec="k")
    _fill(ax, fp["zone"], fc="none", ec="w", ls="--")
    _fill(ax, fp["free"], fc="#7fbf8e", ec="none", alpha=0.55)
    _fill(ax, fp["tails"], fc="#f6e7c8", ec="k", alpha=0.5)
    for k, c, lab in (("conn_a", "#cccccc", "A: cols FPC conn"), ("conn_b", "#bbbbbb", "B: rows FPC conn")):
        _fill(ax, fp[k], fc=c, ec="k", alpha=0.85)
        cx, cy = fp[k].centroid.xy; ax.text(cx[0], cy[0], lab, ha="center", va="center", fontsize=8, color="k")
    ax.text(-12.6, 6.2, f"free for the readout\n{fp['free_mm2']:.0f} mm²", fontsize=8, color="w", va="center")
    for p, sname in zip(fp["pogo"], ["GND", "D-", "D+", "VBUS", "GND"]):
        _fill(ax, p, fc="#e3b23c", ec="k"); cx, cy = p.centroid.xy; ax.text(cx[0], cy[0] + 1.4, sname, ha="center", fontsize=7, color="w")
    bb = fp["board"].bounds
    ax.set_title(f"ENPIRE-T finger PCB {bb[2] - bb[0]:.1f} x {bb[3] - bb[1]:.1f} mm (top view; pogo pads on top, rest on the bottom)")
    ax.set_aspect("equal"); ax.grid(True, lw=0.3); ax.set_xlim(-16, 16); ax.set_ylim(2, 27)
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "pcb_preview.png"), dpi=80); plt.close()


def main():
    b = build()
    issues, stats = drc(b)
    TL = tail_lengths()
    tr, tc = tail(b, "rows"), tail(b, "cols")
    fp = finger_pcb(b)
    for sheet in ("rows", "cols"):
        write_sheet_dxf(b, sheet)
    write_pcb(fp)
    preview(b, "flex_preview_full.png", None, "ENPIRE-T laminate, flat pattern (s = 0 at the flange face; tails above)")
    preview(b, "flex_preview_nail.png", (88, 121), "nail end")
    preview(b, "flex_preview_tails.png", (-22, 14), "tails")
    tm = taxel_map(b)
    json.dump(tm, open(os.path.join(E.OUT, "taxel_map.json"), "w"))
    pin = dict(rows_tail=tr["pins"], cols_tail=tc["pins"], rows_tail_pins=tr["n"], cols_tail_pins=tc["n"],
               pitch_mm=L["TAIL_PITCH"], fpc_width_mm=dict(rows=round(tr["width"], 2), cols=round(tc["width"], 2)),
               tail_length_mm=TL, scan=dict(row_lines=[r["net"] for r in b["strip_rows"]] + [r["net"] for r in b["nail_rows"]],
                                            col_lines=[f"SCOL{j}" for j in range(len(b["strip"]["cols_u"]))] + [c["net"] for c in b["nail_cols"]]),
               pogo=[dict(pin=i + 1, signal=sname) for i, sname in enumerate(["GND", "D-", "D+", "VBUS", "GND"])],
               notes=["rows tail -> connector B (far), runs along the cavity floor under connector A",
                      "cols tail -> connector A (near); both tails pass the flange slot stacked (cols sheet in front)",
                      "fingers on L2 of each sheet: pick top- or bottom-contact 0.3 mm FPC connectors to match the bend direction"])
    json.dump(pin, open(os.path.join(OUT, "pinmap.json"), "w"), indent=1)
    rep = dict(drc_issues=issues, drc_stats=stats, pcb_issues=fp["issues"], pcb_free_mm2=fp["free_mm2"],
               tail_room_mm=fp["tail_room_mm"], taxels=tm["counts"],
               lines=dict(rows=len(pin["scan"]["row_lines"]), cols=len(pin["scan"]["col_lines"])),
               min_seat_bend_radius_under_taxels_mm=min(tm["strip_row_min_bend_radius_mm"]),
               laminate_min_bend_radius=tm["laminate_min_bend_radius"])
    json.dump(rep, open(os.path.join(OUT, "drc.json"), "w"), indent=1)
    print(json.dumps(rep, indent=1))
    if issues or fp["issues"]:
        sys.exit(1)


if __name__ == "__main__" and "--preview" not in sys.argv:
    main()
