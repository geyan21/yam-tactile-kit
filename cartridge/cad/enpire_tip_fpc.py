"""
ENPIRE-T Tip flex circuit: the nail pad's flat pattern, electrodes, leads, tails, DRC, pin maps,
taxel map and finger PCB.

Same construction as ENPIRE-T (cad/enpire_fpc.py): two 2-layer FPC sheets with Velostat between them,
rows on the seat side, columns on the object side, 0.1/0.3 mm laser microvias, 0.1 mm lines. The flat
pattern is exact in (u, s): u = gripper x of the right finger, s = arc length along the laminate's
bonding face from the flange face (s = 0) toward the tip; the tails run to negative s.

Only the nail senses. The pad is a 1.25 mm grid around the groove. The two sheets run stacked from the
pad round the bend into the slit and part there; from the slit up, their tails run side by side (rows
sheet on the low-u side, cols sheet on the high-u side), so the route behind the TPU insert is one sheet
thick. The cols sheet goes round the bend outside the rows sheet, so its neck is drawn longer by one sheet
thickness times the bend's turn (COLS_EXTRA). In the flange the cols tail goes to connector A (near the
back wall), the rows tail along the cavity floor under A into connector B.

Outputs (out/enpire_tip/fpc_pcb/): rows_sheet_fab.dxf, cols_sheet_fab.dxf, film_cut.dxf, finger_pcb_outline.dxf,
flex_preview_full.png, flex_preview_nail.png, flex_preview_tails.png, pcb_preview.png, pinmap.json,
drc.json; and out/enpire_tip/taxel_map.json. Exits 1 if the DRC or the PCB checks find anything.
Run (from cartridge/): python3 cad/enpire_tip_fpc.py
"""
import itertools
import json
import os
import sys
import numpy as np
import ezdxf
from shapely.geometry import box as sbox, LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely import affinity
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enpire_finger as E     # noqa: E402
import enpire_tip as T        # noqa: E402
import enpire_fpc as EF       # noqa: E402  (shared drawing / routing helpers)
from enpire_fpc import rect, path, via, staircase, assign_lanes, _fill, add_geom, DXF_LAYERS, LAYER_COL, SHEETS  # noqa: E402

OUT = os.path.join(T.OUT, "fpc_pcb")
os.makedirs(OUT, exist_ok=True)
L = dict(EF.L)
L.update(NAIL_PITCH=T.P["NAIL_PITCH"], NAIL_EW=T.P["NAIL_EW"], NAIL_ACTIVE_EDGE=T.P["NAIL_ACTIVE_EDGE"],
         BAND_GAP=0.6, BAND_WALL_MIN=0.3,
         A_EXTRA=0.8)            # connector A this much further from the rising tails than the bare minimum: room for the cols fan-out

RT = T.build_route()
NR = T.nail_regions(RT)
D = T.derived(RT, NR)
FPATH = E.FlexPath(dict(C=RT["C"]))
S_N0, V_N0 = D["s_nail0"], D["v_nail0"]
CH_LO, CH_HI = D["channel_u"]                       # gripper x of the tails' channel
U_LO, U_HI = CH_LO + 0.2, CH_HI - 0.2               # laminate edges in the channel


# Round the nail root the cols sheet runs outside the rows sheet, one sheet further out, so between the pad
# and the parting point it needs that much more length times the bend's turn. Its flat pattern gets it as a
# straight stretch of neck just above the parting step; everything of the cols sheet below that sits this much
# further down in flat s than where it lands on the route.
COLS_EXTRA = T.P["SHEET_T"] * np.radians(D["stack_bend_turn_deg"])


def insert_length(g, s_x, d):
    """g with everything below s = s_x moved down by d and its cross-section at s_x drawn out over the gap
    (exact where g runs straight along s at s_x)."""
    if g.is_empty:
        return g
    above = g.intersection(rect(-100, 100, s_x, 1000))
    below = affinity.translate(g.intersection(rect(-100, 100, -1000, s_x)), yoff=-d)
    cut = g.intersection(LineString([(-100, s_x), (100, s_x)]))
    fill = [rect(c.bounds[0], c.bounds[2], s_x - d, s_x) for c in getattr(cut, "geoms", [cut])
            if c.geom_type == "LineString" and c.length > 1e-9]
    return unary_union([above, below] + fill)


def plane_to_flat(g):
    g = affinity.scale(g, xfact=-1.0, yfact=1.0, origin=(0, 0))
    return affinity.translate(g, xoff=-(E.NO[0] + 7.96), yoff=S_N0 - V_N0)


def flat_to_plane_pt(u, s):
    return -(u + E.NO[0] + 7.96), s - (S_N0 - V_N0)


def P2F(u_p, v):
    return plane_to_flat(Point(u_p, v)).coords[0]


# ----------------------------------------------------------------------------------------------
def nail_layout():
    """Densest grid of NAIL_PITCH cells inside the pad (plane coords), columns on each side of the groove
    with their own offset, rows common; rows that would pass the groove's closed end too closely become
    separate left and right lines. Of the densest grids, the one furthest toward the tip: it leaves the most
    flat floor between the bend round the nail root and the first row."""
    p, h = L["NAIL_PITCH"], L["NAIL_PITCH"] / 2
    A = NR["pad"].buffer(-L["NAIL_ACTIVE_EDGE"], join_style=2)
    Ap, b = prep(A), A.bounds
    step = p / 10
    best = (0, -1.0)
    for uL, uR, v0 in itertools.product(np.arange(0, p, step), np.arange(0, p, step), np.arange(0, p, p / 20)):
        colsL = [-(uL + h) - j * p for j in range(20) if -(uL + h) - j * p > b[0] - p]
        colsR = [(uR + h) + j * p for j in range(20) if (uR + h) + j * p < b[2] + p]
        if not colsL or not colsR or min(colsR) - max(colsL) < p - 1e-9:
            continue
        rows = [b[1] + v0 + h + k * p for k in range(40) if b[1] + v0 + h + k * p < b[3]]
        cells = [(u, v) for v in rows for u in colsL + colsR if Ap.contains(sbox(u - h, v - h, u + h, v + h))]
        if (len(cells), v0) > best[:2]:
            best = (len(cells), v0, cells)
    cells = sorted(best[2], key=lambda c: (c[1], c[0]))
    us = sorted(set(round(c[0], 6) for c in cells))
    vs = sorted(set(round(c[1], 6) for c in cells))
    v_notch = NR["groove"].bounds[1] - T.P["GROOVE_CLR"]
    cols = []
    for u in us:
        cv = [c[1] for c in cells if abs(c[0] - u) < 1e-6]
        cols.append(dict(u=u, v0=min(cv), v1=max(cv)))
    rows = []
    for v in vs:
        cu = sorted(c[0] for c in cells if abs(c[1] - v) < 1e-6)
        left, right = [u for u in cu if u < 0], [u for u in cu if u > 0]
        split = bool(left and right) and (v + L["NAIL_EW"] / 2 > v_notch - L["EDGE_CU"] - 0.05)
        segs = [(min(left), max(left)), (min(right), max(right))] if split else [(min(cu), max(cu))]
        rows.append(dict(v=v, segs=segs, split=split))
    return dict(cells=cells, cols=cols, rows=rows, active=A)


def bands(n_rows, n_cols):
    """Side-by-side tail bands in the channel (flat u): rows sheet low-u, cols sheet high-u, the pair
    centred in the channel."""
    lane, edge = L["LANE"], L["EDGE_CU_TAIL"] + L["TRACE_W"] / 2 + 0.05
    w_r, w_c = (n_rows - 1) * lane + 2 * edge, (n_cols - 1) * lane + 2 * edge
    wall = (CH_HI - CH_LO - (w_r + L["BAND_GAP"] + w_c)) / 2
    assert wall >= L["BAND_WALL_MIN"] - 1e-9, f"tails do not fit side by side in the channel ({wall:.2f} mm to its walls)"
    rows = (CH_LO + wall, CH_LO + wall + w_r)
    cols = (CH_HI - wall - w_c, CH_HI - wall)
    fin_r = [rows[0] + edge + lane * k for k in range(n_rows)]
    fin_c = [cols[0] + edge + lane * k for k in range(n_cols)]
    return rows, cols, fin_r, fin_c


def neck_cu():
    """Copper range (flat u) of the neck and the stacked route: the laminate less the pad edge clearance."""
    m = L["EDGE_CU"] + L["TRACE_W"] / 2 + 0.02
    return U_LO + m, U_HI - m


CLR_VIA = L["VIA_PAD"] / 2 + 0.1 + L["TRACE_W"] / 2     # via centre to a passing lead's centre line


def slots(vias, lo, hi, n, from_left=True):
    """n lane positions in [lo, hi] for leads that pass a row of vias: >= CLR_VIA from each via centre,
    >= one lane apart, packed from the left or from the right."""
    grid = np.arange(lo, hi + 1e-9, 0.005)
    out = []
    for x in (grid if from_left else grid[::-1]):
        if all(abs(x - v) >= CLR_VIA - 1e-9 for v in vias) and all(abs(x - q) >= L["LANE"] - 1e-9 for q in out):
            out.append(round(float(x), 4))
            if len(out) == n:
                break
    assert len(out) == n, "no room for the outer columns' leads between the inner vias"
    return sorted(out)


def build():
    """Electrodes, vias and leads. Leads are on L2 of each sheet and may pass under the other electrodes.
    cols sheet: vias in the first row gap; columns outside the neck arch over the inner vias (nearest
    column lowest) and come down between them. rows sheet: the prong halves' leads step in below the
    groove's closed end, the full rows' vias sit between them. Then each bus steps into its tail band;
    the two sheets stay stacked through the bend and part in the slit."""
    nl = nail_layout()
    tw, step, h, ew = L["TRACE_W"], L["LANE"], L["NAIL_PITCH"] / 2, L["NAIL_EW"]
    nets = {}

    def add(net, layer, g):
        nets.setdefault(net, {}).setdefault(layer, []).append(g)
    pad_flat = plane_to_flat(NR["flex"])
    cu_lo, cu_hi = pad_flat.bounds[0] + L["EDGE_CU"] + 0.2, pad_flat.bounds[2] - L["EDGE_CU"] - 0.2
    lo_n, hi_n = neck_cu()
    s_groove = plane_to_flat(NR["groove"].buffer(T.P["GROOVE_CLR"], join_style=2)).bounds[1]

    # ---- columns (cols sheet)
    cols = []
    for i, c in enumerate(sorted(nl["cols"], key=lambda c: -c["u"])):          # flat u = -u_p: ascending
        net = f"NCOL{i:02d}"
        (ua, sa), (_, sb) = P2F(c["u"], c["v0"] - h + 0.05), P2F(c["u"], c["v1"] + h - 0.05)
        add(net, "C1", rect(ua - ew / 2, ua + ew / 2, sa, sb))
        sv = P2F(c["u"], c["v0"] + h)[1]
        add(net, "CV", via(ua, sv))
        cols.append(dict(net=net, u=ua, s_via=sv, s0=sa, s1=sb))
    sv0 = cols[0]["s_via"]
    assert all(abs(c["s_via"] - sv0) < 1e-6 and c["s1"] > sv0 + 0.5 for c in cols), "column vias are not in one row gap"
    inner = [c for c in cols if lo_n <= c["u"] <= hi_n]
    left = sorted([c for c in cols if c["u"] < lo_n], key=lambda c: -c["u"])     # nearest first
    right = sorted([c for c in cols if c["u"] > hi_n], key=lambda c: c["u"])
    vin = [c["u"] for c in inner]
    sl_l = slots(vin, lo_n, hi_n, len(left), True) if left else []
    sl_r = slots(vin, lo_n, hi_n, len(right), False)[::-1] if right else []          # nearest -> rightmost
    assert not (sl_l and sl_r) or max(sl_l) + step <= min(sl_r) + 1e-9, "outer columns' slots overlap"
    for c in inner:
        c["bus"], c["path"] = c["u"], [(c["u"], sv0)]
    for group, sl in ((left, sl_l), (right, sl_r)):
        for k, c in enumerate(group):
            hk = sv0 + CLR_VIA + step * k
            assert c["s1"] >= hk + 0.3, f"{c['net']}: column too short for its arch"
            c["bus"], c["path"] = sl[k], [(c["u"], sv0), (c["u"], hk), (sl[k], hk)]
    col_gaps = sorted({round((a["u"] + b["u"]) / 2, 4) for a, b in zip(cols, cols[1:])
                       if abs(a["u"] - b["u"]) < L["NAIL_PITCH"] * 1.01})

    # ---- rows (rows sheet): full rows F, split rows as halves L / R on the prongs
    lines = []
    for r, row in enumerate(sorted(nl["rows"], key=lambda r: r["v"])):
        for (u0p, u1p) in row["segs"]:
            (ua, s), (ub, _) = P2F(u0p - h + 0.05, row["v"]), P2F(u1p + h - 0.05, row["v"])
            ua, ub = sorted((ua, ub))
            kind = "F" if not row["split"] else ("L" if (ua + ub) / 2 < (lo_n + hi_n) / 2 else "R")
            net = f"NROW{r:02d}" + ("" if kind == "F" else kind)
            add(net, "R1", rect(ua, ub, s - ew / 2, s + ew / 2))
            lines.append(dict(net=net, s=s, u0=ua, u1=ub, kind=kind))
    pr = [ln for ln in lines if ln["kind"] != "F"]
    for ln, u in zip(pr, assign_lanes([(ln["u0"] + 0.2, ln["u1"] - 0.2) for ln in pr], cu_lo + 0.1, cu_hi - 0.1,
                                      gap=0.32, prefer=col_gaps)):
        ln["lane"] = u
    Ls = sorted([ln for ln in pr if ln["kind"] == "L"], key=lambda ln: ln["lane"])
    Rs = sorted([ln for ln in pr if ln["kind"] == "R"], key=lambda ln: ln["lane"])
    tgt_l = [lo_n + step * k for k in range(len(Ls))]
    tgt_r = [hi_n - step * (len(Rs) - 1 - k) for k in range(len(Rs))]
    Fs = [ln for ln in lines if ln["kind"] == "F"]
    f_lo = (tgt_l[-1] if Ls else lo_n - step) + CLR_VIA + 0.02
    f_hi = (tgt_r[0] if Rs else hi_n + step) - CLR_VIA - 0.02
    for ln, u in zip(Fs, assign_lanes([(max(ln["u0"] + 0.2, f_lo), min(ln["u1"] - 0.2, f_hi)) for ln in Fs], f_lo, f_hi,
                                      gap=0.32, prefer=col_gaps)):
        ln["lane"] = u
    for ln in lines:
        add(ln["net"], "RV", via(ln["lane"], ln["s"]))
    # the prong leads step in below the groove's closed end
    s_hi = min(min([ln["s"] for ln in pr], default=np.inf) - CLR_VIA, s_groove - L["EDGE_CU"] - tw / 2 - 0.02)
    s_top_r = (min(ln["s"] for ln in Fs) if Fs else s_hi - step * len(pr)) - CLR_VIA
    assert s_top_r <= s_hi - step * max(len(Ls), len(Rs)), "no room for the prong leads to step in"
    for grp, tgt in ((Ls, tgt_l), (Rs, tgt_r)):
        if grp:
            for ln, pts in zip(grp, staircase([ln["lane"] for ln in grp], tgt, s_hi, step, s_end=s_top_r)):
                ln["bus"], ln["path"] = pts[-1][0], [(ln["lane"], ln["s"])] + pts
    for ln in Fs:
        ln["bus"], ln["path"] = ln["lane"], [(ln["lane"], ln["s"])]

    # ---- each bus into its tail band
    rband, cband, fin_r, fin_c = bands(len(lines), len(cols))
    bus_r, bus_c = sorted(lines, key=lambda x: x["bus"]), sorted(cols, key=lambda x: x["bus"])
    for bus in (bus_r, bus_c):
        gaps = np.diff([x["bus"] for x in bus])
        assert gaps.min() >= step - 1e-6, "leads closer than one lane before the band staircase"
    st_r = staircase([x["bus"] for x in bus_r], fin_r, s_top_r, step, s_end=0.0)
    st_c = staircase([x["bus"] for x in bus_c], fin_c, sv0 - CLR_VIA, step, s_end=0.0)
    for bus, fin, st, layer in ((bus_r, fin_r, st_r, "R2"), (bus_c, fin_c, st_c, "C2")):
        for x, f, pts in zip(bus, fin, st):
            add(x["net"], layer, path(x["path"] + pts, tw))
            x["final"] = f
    lowest = min(p[1][1] for p in st_r + st_c)
    s_part = min(lowest - 0.6, D["s_bend0"] - 0.5)                  # the sheets part in the slit
    assert s_part >= D["s_stack"] + 0.3, f"sheets part at s {s_part:.2f}, above the stacked channel (s {D['s_stack']:.2f})"
    # outlines (s >= 0): pad + neck, both sheets full width down to s_part, then each sheet's band
    neck = rect(U_LO, U_HI, s_part, S_N0 + 0.6)
    pad_out = unary_union([pad_flat, neck]).buffer(0.3, join_style=1).buffer(-0.3, join_style=1)

    def sheet_outline(band):     # the step where a sheet narrows to its band gets 0.5 mm fillets (no tear starter)
        step = unary_union([rect(U_LO, U_HI, s_part, s_part + 1.5), rect(band[0], band[1], s_part - 1.5, s_part + 0.01)])
        step = step.buffer(0.5, join_style=1).buffer(-0.5, join_style=1)
        # snap away the micron-scale jogs the union leaves where the fillets meet the neck's straight edges
        return unary_union([pad_out, step, rect(band[0], band[1], 0.0, s_part + 0.01)]).simplify(0.002)
    outline = dict(rows=sheet_outline(rband), cols=sheet_outline(cband))
    # the cols sheet's extra length round the nail root, as straight neck between the parting step and the
    # lowest step of its leads (both its copper and its outline run straight along s there)
    s_x = s_part + 0.3
    assert s_x <= min(p[1][1] for p in st_c) - 0.05, "no straight stretch of the cols sheet's neck above the parting step"
    outline["cols"] = insert_length(outline["cols"], s_x, COLS_EXTRA)
    for net in [c["net"] for c in cols]:
        for layer, gs in nets[net].items():
            nets[net][layer] = [insert_length(g, s_x, COLS_EXTRA) for g in gs]
    return dict(nets=nets, nail=nl, nail_rows=lines, nail_cols=cols, outline=outline, pad_out=pad_out,
                bands=dict(rows=rband, cols=cband), s_part=s_part, lowest_step=lowest, cols_extra=COLS_EXTRA, cols_extra_at=s_x)


# ----------------------------------------------------------------------------------------------
# tails (s < 0): up the slot at the back of the cavity; cols -> A (near), rows -> under A -> B (far)
# ----------------------------------------------------------------------------------------------
def tail_geometry():
    """Both tails in the cavity, from explicit centrelines (enpire_fpc.cavity_tail): lengths, connector
    entries, where each tail may widen, and the rows tail's room under connector A. Gripper frame; the
    tails rise at the back of the cavity and run forward (-y)."""
    cav_floor = E.Zs - E.P["PCB"]["recess"] - E.P["PCB"]["t"] - E.P["CAVITY"]["depth"]
    slot = cav_floor - E.Zf
    rb = L["BEND_R"] + 0.1
    y_rise = D["y_rise_g"] - T.P["TAIL_T"] / 2
    z_contact = E.Zs - E.P["PCB"]["recess"] - E.P["PCB"]["t"] - 0.5
    out_len = L["STIFF_L"] - L["FINGER_L"]
    a_entry = y_rise - rb - out_len - 0.3 - L["A_EXTRA"]                    # A faces the back wall (+y)
    a_front = a_entry - L["CONN_DEPTH"]
    y_s = a_front - 0.3                                                     # the rows tail S-bends up just past A
    b_entry = y_s - 2 * rb - out_len - 0.3
    cols, seg_c = EF.cavity_tail("up", E.Zf, cav_floor, z_contact, y_rise, a_entry, rb)
    rows, seg_r = EF.cavity_tail("floor", E.Zf, cav_floor, z_contact, y_rise, b_entry, rb, y_s=y_s)
    # each tail keeps its band width until it is clear of the other: the rows tail until it lies on the
    # floor past its first bend; the cols tail from the slot exit, as its fan-out stays clear of the rows
    # band in x (tail() places it so)
    wide = dict(rows=slot + np.pi / 2 * rb + 0.3, cols=slot + 0.3)
    under_a = (z_contact + 0.5 - L["CONN_H"]) - (cav_floor + rb + T.P["TAIL_T"] / 2)
    return dict(slot=round(slot, 2), cols=round(cols + EF.TAIL_SLACK, 2), rows=round(rows + EF.TAIL_SLACK, 2),
                slack=EF.TAIL_SLACK, a_entry=round(a_entry, 2), b_entry=round(b_entry, 2), y_rise=round(y_rise, 3),
                widen_from={k: round(v, 2) for k, v in wide.items()}, rows_under_a_mm=round(under_a, 2),
                segments=dict(cols=np.round(seg_c, 3).tolist(), rows=np.round(seg_r, 3).tolist()), bend_r=rb)


def tail(b, sheet):
    TG = tail_geometry()
    p, fw, tw = L["TAIL_PITCH"], L["FINGER_W"], L["TRACE_W"]
    s_end = -TG[sheet]
    band = b["bands"][sheet]
    if sheet == "rows":
        leads, layer = [(r["net"], r["final"]) for r in b["nail_rows"]], "R2"
    else:
        leads, layer = [(c["net"], c["final"]) for c in b["nail_cols"]], "C2"
    leads = sorted(leads, key=lambda t: t[1])
    n = len(leads) + L["N_GND"]
    width = (n + 1) * p
    uc = (band[0] + band[1]) / 2
    if sheet == "cols":          # widens at the slot exit, beside the rows tail: keep its fan clear of the rows band
        uc = max(uc, b["bands"]["rows"][1] + 0.3 + width / 2)
    fingers_u = [uc + (k - (n - 1) / 2) * p for k in range(n)]
    sig_u = fingers_u[1:-1]
    s_w = -TG["widen_from"][sheet]                     # the outline widens from here, the fan starts 0.7 mm on
    s_fan0 = s_w - 0.7
    stairs = staircase([u for _, u in leads], sig_u, s_fan0, L["LANE"], s_end=s_end + L["FINGER_EDGE"])
    s_fan_end = min(p[1][1] for p in stairs) - 0.4
    assert s_fan_end - 0.8 >= s_end + L["FINGER_EDGE"] + L["FINGER_L"] + 0.3, f"{sheet} tail: fan-out runs into the fingers"
    x0, x1 = T.P["SLOT_X"]
    assert x0 + 0.2 <= uc - width / 2 and uc + width / 2 <= x1 - 0.2, f"{sheet} tail: its stiffened end does not pass the slot"
    out = []
    for (net, u0), uf, pts in zip(leads, sig_u, stairs):
        out.append((net, layer, path([(u0, 0.0)] + pts, tw)))
        out.append((net, layer, rect(uf - fw / 2, uf + fw / 2, s_end + L["FINGER_EDGE"], s_end + L["FINGER_EDGE"] + L["FINGER_L"])))
    for ug in (fingers_u[0], fingers_u[-1]):
        out.append(("GND", layer, rect(ug - fw / 2, ug + fw / 2, s_end + L["FINGER_EDGE"], s_end + L["FINGER_EDGE"] + L["FINGER_L"])))
    lo_f, hi_f = uc - width / 2, uc + width / 2
    lo_z, hi_z = min(band[0], lo_f), max(band[1], hi_f)
    outline = unary_union([rect(band[0], band[1], 0.5, s_w),
                           Polygon([(band[0], s_w), (band[1], s_w), (hi_z, s_w - 0.5), (lo_z, s_w - 0.5)]),
                           rect(lo_z, hi_z, s_w - 0.49, s_fan_end),
                           Polygon([(lo_z, s_fan_end + 0.01), (hi_z, s_fan_end + 0.01), (hi_f, s_fan_end - 0.8), (lo_f, s_fan_end - 0.8)]),
                           rect(lo_f, hi_f, s_fan_end - 0.79, s_end)]).buffer(0.2, join_style=1).buffer(-0.2, join_style=1).simplify(0.002)
    stiff = rect(uc - width / 2, uc + width / 2, s_end, s_end + L["STIFF_L"])
    gang = rect(min(fingers_u) - fw / 2 - 0.2, max(fingers_u) + fw / 2 + 0.2, s_end - 0.3, s_end + L["FINGER_EDGE"] + L["FINGER_L"] + 0.2)
    pins = [dict(pin=1, signal="GND", u=round(fingers_u[0], 3))] + \
           [dict(pin=k + 2, signal=net, u=round(u, 3)) for k, ((net, _), u) in enumerate(zip(leads, sig_u))] + \
           [dict(pin=n, signal="GND", u=round(fingers_u[-1], 3))]
    zone = rect(uc - width / 2 - 1, uc + width / 2 + 1, s_end - 1, s_end + L["FINGER_EDGE"] + L["FINGER_L"] + 0.3)
    # so far in route s; the cols sheet's tail sits COLS_EXTRA further down in its flat pattern
    dy = -b["cols_extra"] if sheet == "cols" else 0.0
    mv = lambda g: affinity.translate(g, yoff=dy)          # noqa: E731
    return dict(copper=[(net, ly, mv(g)) for net, ly, g in out], outline=mv(outline), stiffener=mv(stiff), gang=mv(gang), pins=pins,
                n=n, width=width, s_end=s_end + dy, uc=uc, finger_zone=mv(zone))


def velostat(b):
    h = L["NAIL_PITCH"] / 2
    cells = unary_union([plane_to_flat(sbox(u - h, v - h, u + h, v + h)) for (u, v) in b["nail"]["cells"]])
    return [cells.buffer(L["VELO_MARGIN"], join_style=2).intersection(b["pad_out"].buffer(-0.15))]


def full_outline(b, t, sheet):
    """A sheet's whole outline: pad, neck and band from build(), the tail from tail(), joined and cleaned."""
    return unary_union([b["outline"][sheet], t["outline"]]).simplify(0.002)


def sheet_geoms(b, sheet):
    layers = SHEETS[sheet]
    out = {ln: {} for ln in layers}
    for net, lay in b["nets"].items():
        for ln in layers:
            if ln in lay:
                out[ln][net] = unary_union([out[ln].get(net, Polygon())] + lay[ln])
    t = tail(b, sheet)
    for net, ln, g in t["copper"]:
        out[ln][net] = unary_union([out[ln].get(net, Polygon()), g])
    for net, g in out[layers[2]].items():
        for ln in layers[:2]:
            out[ln][net] = unary_union([out[ln].get(net, Polygon()), g])
    return out, t


def drc(b):
    """Copper spacing >= 0.1 mm on each layer; copper >= 0.35 mm from the outline on the pad and the
    stacked neck, >= 0.25 mm on the tails (the route behind the insert: nothing senses there), which
    start 0.4 mm above the step where each sheet narrows to its band."""
    from shapely.strtree import STRtree
    issues, stats = [], {}
    for sheet in ("rows", "cols"):
        cu, t = sheet_geoms(b, sheet)
        outline = full_outline(b, t, sheet)
        s_rule = b["s_part"] + 0.4 - (b["cols_extra"] if sheet == "cols" else 0.0)       # 0.4 mm above the sheet's parting step
        pad_zone = rect(-40, 40, s_rule, 300)
        for ln in [k for k in cu if not k.endswith("V")]:
            nets = {k: v for k, v in cu[ln].items() if not v.is_empty}
            names = sorted(nets)
            geoms = [nets[k] for k in names]
            tree = STRtree(geoms)
            gmin = np.inf
            for i, g in enumerate(geoms):
                for j in tree.query(g.buffer(0.2)):
                    if j <= i:
                        continue
                    d = g.distance(geoms[j])
                    gmin = min(gmin, d)
                    if d < 0.1 - 1e-6:
                        issues.append(f"{sheet}/{ln}: {names[i]} - {names[j]} gap {d:.3f} mm")
            allcu = unary_union(geoms)
            for zone, clr, tag in ((pad_zone, L["EDGE_CU"], "pad"), (rect(-40, 40, -60, s_rule), L["EDGE_CU_TAIL"], "tail")):
                cuz = allcu.intersection(zone).difference(t["finger_zone"])
                bad = cuz.difference(outline.buffer(-clr + 1e-4))
                if bad.area > 1e-4:
                    issues.append(f"{sheet}/{ln}: copper within {clr} mm of the outline ({tag}), {bad.area:.4f} mm2 at {np.round(bad.centroid.coords[0], 2).tolist()}")
            stats[f"{sheet}/{ln}_min_gap_mm"] = round(gmin, 3) if np.isfinite(gmin) else ">0.2"
    return issues, stats


def preview(b, fname, s_range=None, title=""):
    tall = s_range is None
    if tall:
        TG = tail_geometry()
        s_range = (-max(TG["rows"], TG["cols"]) - 1.0, D["C_length"] + 1.0)
    fig, axs = plt.subplots(1, 2, figsize=(12, 30) if tall else (16, 9))
    velo = velostat(b)
    for ax, sheet in zip(axs, ("rows", "cols")):
        cu, t = sheet_geoms(b, sheet)
        _fill(ax, full_outline(b, t, sheet), fc="#f6e7c8", ec="k", lw=0.6)
        for g in velo:
            _fill(ax, g, fc="none", ec="#555", lw=0.6, ls="--")
        for ln in SHEETS[sheet]:
            for net, g in cu[ln].items():
                _fill(ax, g, fc=LAYER_COL[ln], ec="none", alpha=0.9)
        _fill(ax, t["stiffener"], fc="#999", ec="none", alpha=0.3)
        ax.set_aspect("equal"); ax.grid(True, lw=0.3)
        ax.set_title({"rows": "rows sheet (core side): L1 rows (orange), L2 leads (blue)",
                      "cols": "cols sheet (object side): L1 columns (red), L2 leads (purple)"}[sheet], fontsize=11)
        ax.set_xlabel("u = gripper x of the right finger (mm)"); ax.set_ylabel("s along the laminate from the flange face (mm)")
        ax.set_ylim(s_range[1], s_range[0])                      # tails at the top
    fig.suptitle(title, fontsize=13)
    plt.tight_layout(rect=(0, 0, 1, 0.985 if tall else 0.96)); plt.savefig(os.path.join(OUT, fname), dpi=72 if tall else 80); plt.close()


def write_sheet_dxf(b, sheet):
    doc = ezdxf.new("R2010", setup=True); doc.units = ezdxf.units.MM
    for n, c in DXF_LAYERS.items():
        doc.layers.add(n, color=c)
    msp = doc.modelspace()
    cu, t = sheet_geoms(b, sheet)
    l1, l2, lv = SHEETS[sheet]
    add_geom(msp, full_outline(b, t, sheet), "OUTLINE")
    for net, g in cu[l1].items():
        add_geom(msp, g, "CU_L1")
    for net, g in cu[l2].items():
        add_geom(msp, g, "CU_L2")
    for net, g in cu[lv].items():
        for gg in getattr(g, "geoms", [g]):
            c = gg.centroid
            msp.add_circle((c.x, c.y), L["VIA_DRILL"] / 2, dxfattribs=dict(layer="VIA"))
    elec = [g for net, g in cu[l1].items() if net.startswith(("NROW", "NCOL"))]
    add_geom(msp, unary_union(elec).intersection(rect(-40, 40, b["s_part"], 300)).buffer(-0.05), "COVERLAY_OPEN_L1")
    add_geom(msp, t["gang"], "COVERLAY_OPEN_L2")
    for g in velostat(b):
        add_geom(msp, g, "VELOSTAT")
    add_geom(msp, t["stiffener"], "STIFFENER")
    note = {"rows": "ENPIRE-T TIP ROWS SHEET, the sheet against the core. Drawn looking from the core toward the object (x = gripper x "
                    "of the right finger, tip up), so this is its L2 side: mirror it for fab, with L1 as the top layer. L1 = row electrodes "
                    "(face the Velostat), L2 = leads + tail fingers. 2-layer flex, 12.5 um PI core, 1/3 oz Cu, laser microvias 0.1/0.3 "
                    "filled+capped, ENIG. Coverlay windows: COVERLAY_OPEN_L1 over the electrodes, COVERLAY_OPEN_L2 over the fingers; "
                    "stiffener to 0.2 mm on the L1 face, behind the fingers.",
            "cols": "ENPIRE-T TIP COLS SHEET, the sheet on the object side. Drawn looking from the core toward the object (x = gripper x "
                    "of the right finger, tip up), so this is its L1 side: fab it as drawn, with L1 as the top layer. L1 = column electrodes "
                    "(face the Velostat), L2 = leads + tail fingers. Same stack, coverlay layers and stiffener as the rows sheet."}[sheet]
    msp.add_text(note, height=0.5, dxfattribs=dict(layer="NOTE")).set_placement((U_LO, t["s_end"] - 3))
    doc.saveas(os.path.join(OUT, f"{sheet}_sheet_fab.dxf"))


def film_cut():
    """The PU film's flat cut outline, in the laminate's flat frame: the part over the nail pocket as it lies,
    and below the floor's proximal end (s < s_nail0) the strip that wraps round the nail root over the
    laminate's bend, drawn at the film's own length there (it runs round outside the laminate)."""
    flat = plane_to_flat(NR["film"].intersection(sbox(-30, NR["v_pb"], 30, 30)))
    lift = T.P["FLEX_T"] + T.P["FLEX_CLR"] + T.P["FILM_T"] / 2               # the film's mid-plane off the bonding face (as in film.stl)
    wrap_len = (T.P["R_BEND"] + lift) * np.radians(D["stack_bend_turn_deg"])
    cx0, cx1 = T.P["CHANNEL_X"]
    u0, u1 = sorted((E.x_n_to_g(cx0 + 0.1), E.x_n_to_g(cx1 - 0.1)))           # the wrap's width, as film.stl
    outline = unary_union([flat, rect(u0, u1, S_N0 - wrap_len, S_N0 + 0.01)]).simplify(0.002)
    doc = ezdxf.new("R2010", setup=True); doc.units = ezdxf.units.MM
    for n, c in DXF_LAYERS.items():
        doc.layers.add(n, color=c)
    msp = doc.modelspace()
    add_geom(msp, outline, "OUTLINE")
    msp.add_line((u0 - 1.0, S_N0), (u1 + 1.0, S_N0), dxfattribs=dict(layer="NOTE"))
    msp.add_text("ENPIRE-T TIP PU FILM (3M 8562, 0.20 mm), cut outline seen from its adhesive side (x = gripper x of the right finger, "
                 "tip up). Above the line it covers the nail pocket; below it, the strip wraps round the nail root over the laminate's bend "
                 "to the foot of the slit.",
                 height=0.5, dxfattribs=dict(layer="NOTE")).set_placement((u0, S_N0 - wrap_len - 2.0))
    doc.saveas(os.path.join(OUT, "film_cut.dxf"))
    b = outline.bounds
    return dict(width_mm=round(b[2] - b[0], 2), length_mm=round(b[3] - b[1], 2), wrap_strip_mm=round(wrap_len, 2),
                wrap_strip_width_mm=round(u1 - u0, 2))


def taxel_map(b):
    """Taxel centres + normals in the i2rt gripper frame at q = 0 (metres), both fingers, at the sensing
    layer and on the film's outer face (the original nail plane), plus flat (u, s)."""
    nl = b["nail"]
    lift_sense = T.P["FLEX_T"] / 2
    nail_rows_by = {}
    for ln in b["nail_rows"]:
        nail_rows_by.setdefault(round(ln["s"], 4), []).append(ln)
    col_by_u = {round(c["u"], 4): c["net"] for c in b["nail_cols"]}
    taxels = []
    for (up, v) in nl["cells"]:
        uf, sf = plane_to_flat(Point(up, v)).coords[0]
        rn = [ln for ln in nail_rows_by[round(sf, 4)] if ln["u0"] - 1e-6 <= uf <= ln["u1"] + 1e-6][0]["net"]
        cn = col_by_u[min(col_by_u, key=lambda k: abs(k - uf))]
        taxels.append(dict(region="nail", u=uf, s=sf, row_net=rn, col_net=cn))
    taxels.sort(key=lambda t: (t["s"], t["u"]))
    out = dict(frame="i2rt linear_4310 gripper body frame (MJCF body 'gripper'), q = 0", units="m",
               index="flat index = position in 'taxels': nail rows from the proximal end, then across u",
               counts=dict(nail=len(taxels)), fingers={})
    for side, sgn, joint in (("right", 1, "joint8"), ("left", -1, "joint7")):
        pts_s, pts_c, nrm = [], [], []
        for t in taxels:
            g, n = FPATH.point_g(t["u"], t["s"], lift=lift_sense)
            gc, _ = FPATH.point_g(t["u"], t["s"], lift=T.POCKET_D)
            M = np.diag([sgn, sgn, 1.0])
            pts_s.append((M @ g[0] / 1000).round(6).tolist())
            pts_c.append((M @ gc[0] / 1000).round(6).tolist())
            nrm.append((M @ (n[0] / np.linalg.norm(n[0]))).round(6).tolist())
        out["fingers"][side] = dict(joint=joint, slide_dir=[0.0, float(sgn), 0.0], sensor_q0=pts_s, surface_q0=pts_c,
                                    normal_toward_object=nrm)
    out["taxels"] = [dict(i=i, region=t["region"], row_net=t["row_net"], col_net=t["col_net"],
                          flat_mm=[round(t["u"], 3), round(t["s"], 3)]) for i, t in enumerate(taxels)]
    out["laminate_min_bend_radius"] = dict(single_sheet=D["route_min_bend_radius"], stacked=D["stack_min_bend_radius"])
    return out


def finger_pcb(b):
    """Same board and pogo targets as ENPIRE-T; connectors at the back of the cavity, where the tails rise."""
    TG = tail_geometry()
    board = E.pcb_outline(0.1)
    pogo = [sbox(x - 0.8, E.FP["POGO_Y"] - 1.1, x + 0.8, E.FP["POGO_Y"] + 1.1)
            for x in [(i - (E.FP["POGO_N"] - 1) / 2) * E.FP["POGO_PITCH"] for i in range(E.FP["POGO_N"])]]
    tr, tc = tail(b, "rows"), tail(b, "cols")

    def conn(n, u, y_entry):
        w = (n - 1) * L["TAIL_PITCH"] + L["CONN_BODY_EXTRA"]
        return sbox(u - w / 2, y_entry - L["CONN_DEPTH"], u + w / 2, y_entry)
    conn_a, conn_b = conn(tc["n"], tc["uc"], TG["a_entry"]), conn(tr["n"], tr["uc"], TG["b_entry"])
    zone = E.pcb_outline(E.P["CAVITY"]["inset"] + 0.4)
    slot = sbox(T.P["SLOT_X"][0], TG["y_rise"] - 0.3, T.P["SLOT_X"][1], TG["y_rise"] + 0.3)
    tails_corr = sbox(min(tr["uc"] - tr["width"] / 2, tc["uc"] - tc["width"] / 2) - 0.3, conn_b.bounds[1],
                      max(tr["uc"] + tr["width"] / 2, tc["uc"] + tc["width"] / 2) + 0.3, TG["y_rise"] + 0.5)
    free = zone.difference(unary_union([conn_a.buffer(0.3), conn_b.buffer(0.3), tails_corr]))
    issues = []
    for k, c in (("conn_a", conn_a), ("conn_b", conn_b)):
        if not zone.buffer(1e-6).contains(c):
            issues.append(f"{k} leaves the component zone")
    # straight run each tail has between its last bend and the stiffener in front of its connector, and the
    # rows tail's clearance under A (from the centrelines in tail_geometry)
    out_len = L["STIFF_L"] - L["FINGER_L"]
    room = dict(cols_before_A=round(TG["segments"]["cols"][2] - out_len, 2), rows_before_B=round(TG["segments"]["rows"][6] - out_len, 2),
                rows_under_A=TG["rows_under_a_mm"])
    for k, v in room.items():
        if v < 0.2:
            issues.append(f"tail room {k} is {v:.2f} mm")
    if conn_b.bounds[1] < zone.bounds[1]:
        issues.append("connector B runs past the front of the component zone")
    return dict(board=board, pogo=pogo, conn_a=conn_a, conn_b=conn_b, zone=zone, tails=tails_corr, free=free, slot=slot,
                free_mm2=round(free.area, 0), tail_room_mm=room, issues=issues)


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
    msp.add_text("ENPIRE-T TIP FINGER PCB, top view (+z). Top: 5 pogo targets (as v0.2). Bottom (NOTE): cols connector A "
                 "(near the back wall), rows connector B, free area for the readout; keep the tail corridor clear. Parts <= 2.2 mm.",
                 height=0.5, dxfattribs=dict(layer="NOTE")).set_placement((-14.5, 1.0))
    doc.saveas(os.path.join(OUT, "finger_pcb_outline.dxf"))
    fig, ax = plt.subplots(figsize=(10, 8))
    _fill(ax, fp["board"], fc="#2e7d4f", ec="k")
    _fill(ax, fp["free"], fc="#7fbf8e", ec="none", alpha=0.55)
    _fill(ax, fp["tails"], fc="#f6e7c8", ec="k", alpha=0.5)
    for k, c, lab in (("conn_a", "#cccccc", "A: cols"), ("conn_b", "#bbbbbb", "B: rows")):
        _fill(ax, fp[k], fc=c, ec="k", alpha=0.85)
        cx, cy = fp[k].centroid.xy; ax.text(cx[0], cy[0], lab, ha="center", va="center", fontsize=8)
    for p, sname in zip(fp["pogo"], ["GND", "D-", "D+", "VBUS", "GND"]):
        _fill(ax, p, fc="#e3b23c", ec="k"); cx, cy = p.centroid.xy; ax.text(cx[0], cy[0] + 1.4, sname, ha="center", fontsize=7, color="w")
    ax.text(-12.6, 6.2, f"free for the readout\n{fp['free_mm2']:.0f} mm²", fontsize=8, color="w", va="center")
    bb = fp["board"].bounds
    ax.set_title(f"ENPIRE-T Tip finger PCB {bb[2] - bb[0]:.1f} x {bb[3] - bb[1]:.1f} mm (top view; pogo pads on top, rest on the bottom)")
    ax.set_aspect("equal"); ax.grid(True, lw=0.3); ax.set_xlim(-16, 16); ax.set_ylim(2, 27)
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "pcb_preview.png"), dpi=80); plt.close()


def main():
    b = build()
    issues, stats = drc(b)
    TG = tail_geometry()
    tr, tc = tail(b, "rows"), tail(b, "cols")
    fp = finger_pcb(b)
    for sheet in ("rows", "cols"):
        write_sheet_dxf(b, sheet)
    write_pcb(fp)
    preview(b, "flex_preview_full.png", None, "ENPIRE-T Tip laminate, flat pattern (s = 0 at the flange face; tails above)")
    preview(b, "flex_preview_nail.png", (S_N0 - 4, D["C_length"] + 1), "nail end")
    preview(b, "flex_preview_tails.png", (-26, 8), "tails")
    tm = taxel_map(b)
    json.dump(tm, open(os.path.join(T.OUT, "taxel_map.json"), "w"))
    pin = dict(rows_tail=tr["pins"], cols_tail=tc["pins"], rows_tail_pins=tr["n"], cols_tail_pins=tc["n"],
               pitch_mm=L["TAIL_PITCH"], fpc_width_mm=dict(rows=round(tr["width"], 2), cols=round(tc["width"], 2)),
               tail_length_mm={k: TG[k] for k in ("slot", "cols", "rows", "slack")},
               connectors=dict(a_entry_y=TG["a_entry"], b_entry_y=TG["b_entry"]),
               scan=dict(row_lines=[r["net"] for r in b["nail_rows"]], col_lines=[c["net"] for c in b["nail_cols"]]),
               pogo=[dict(pin=i + 1, signal=s) for i, s in enumerate(["GND", "D-", "D+", "VBUS", "GND"])],
               connector_contacts=dict(A="contacts on the side away from the PCB (top contact): the cols fingers face down",
                                       B="contacts on the PCB side (bottom contact): the rows fingers face the board"),
               notes=["cols tail -> connector A (near the cavity's back wall, entry facing +y)",
                      "rows tail -> along the cavity floor under A -> connector B",
                      "both tails carry their fingers on L2; after their bends the rows fingers face the PCB and the cols fingers face away",
                      "thread the rows tail's stiffened end up through the flange slot first, then the cols tail's; latch both with "
                      "the PCB held above the flange before anything is bonded",
                      "the two tails run side by side behind the TPU insert (rows sheet on the -x side of the channel)",
                      f"the cols sheet's neck is {COLS_EXTRA:.2f} mm longer than the rows sheet's: it goes round the nail root outside it"])
    json.dump(pin, open(os.path.join(OUT, "pinmap.json"), "w"), indent=1)
    film = film_cut()
    rep = dict(drc_issues=issues, drc_stats=stats, pcb_issues=fp["issues"], pcb_free_mm2=fp["free_mm2"], tail_room_mm=fp["tail_room_mm"],
               taxels=tm["counts"], lines=dict(rows=len(pin["scan"]["row_lines"]), cols=len(pin["scan"]["col_lines"])),
               sheets_part_at_s_mm=round(b["s_part"], 2), laminate_min_bend_radius=tm["laminate_min_bend_radius"],
               cols_neck_extra_mm=round(COLS_EXTRA, 3), film_cut=film)
    json.dump(rep, open(os.path.join(OUT, "drc.json"), "w"), indent=1)
    print(json.dumps(rep, indent=1))
    if issues or fp["issues"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
