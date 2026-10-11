"""
ENPIRE-T Tip: the ENPIRE finger with tactile sensing on the nail only.

The stock compliant TPU cradle stays as it is (print it from the original STL); only the nail senses.
Same shared socket dock as ENPIRE-T and the v0.2 cartridge.

  nail    cross-slot filled; flush 0.70 mm pocket for a 1.25 mm-pitch pad around the groove, under PU tape
  route   both sheets wrap round the nail root together (under the PU tape, which follows them round) and
          run up the slit between the TPU insert's lower end and the nail root, where they part. Their tails
          run side by side, one sheet thick, in a 0.2 mm recess along the back spine's inner face behind the
          insert, cross behind the insert's top corner and rise through a slot into the flange cavity. Every
          surface on the way is an extrusion across the finger or the nail plane, so the flat pattern is
          exact in (u, s).
  back    the open gap between the root block and the spine bar is closed, and a 1 mm ledge backs the tails
          wherever the frame has a window behind them.
  flange  the ENPIRE-T dock; the tails come up at the back of the cavity.

Frames as enpire_finger.py: profiles in native ENPIRE (y, z), 3D parts in the i2rt gripper frame, right
finger at q = 0, mm. Run (from cartridge/): python3 cad/enpire_tip.py --build  -> out/enpire_tip/
"""
import json
import os
import sys
import numpy as np
import trimesh
from shapely.geometry import LineString, Point, Polygon, box as sbox
from shapely.ops import substring, unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enpire_finger as E      # noqa: E402  (frames, booleans, flange, dock, nail plane)
import enpire_source as ES     # noqa: E402

OUT = os.path.join(E.F.OUT, "enpire_tip")
P = dict(
    DZ=E.P["DZ"],                 # same placement as ENPIRE-T (shared socket + flange)
    TPU_X=E.P["TPU_X"], X_PROFILE=E.P["X_PROFILE"],
    # nail pad (only sensor): stack and pocket as ENPIRE-T, finer pitch
    FLEX_T=0.45, FLEX_CLR=0.05, FILM_T=0.20,
    TIP_BARE=3.0, PAD_EDGE=1.0, GROOVE_CLR=1.0, POCKET_CLR=0.15,
    NAIL_PITCH=1.25, NAIL_EW=0.85, NAIL_ACTIVE_EDGE=0.45,
    # tail route: one sheet thick (two tails side by side) + PSA
    TAIL_T=0.17, TAIL_CLR=0.05,
    SHEET_T=0.14,                 # one 2-layer sheet with its coverlays (TAIL_T less the PSA under it)
    RECESS=0.20,                  # tails sit this deep in the spine's inner face (TPU gap there is only 0.2 mm)
    Z_RISE=21.0,                  # native z where the tails rise into the flange (inside the cavity footprint)
    # native y of the bonding face in the slit beside the nail root, and the stacked bend from the slit onto the
    # nail floor (radius at the bonding face, the rows sheet's inner face): together they keep the film-covered
    # bend inside the stock root's corner (flush at most) and its end on the floor short of the pad's Velostat
    Y_SLIT=-96.6, R_BEND=1.6,
    STACK_Z=1.5,                  # native z in the slit below which both sheets run stacked (they part above the bend)
    R_S=4.0, R_TOP=4.0, R_DS=2.0,                 # bend radii of the single-sheet route (mm, at the bonding face)
    S_MID=(-20.3, 60.0),          # S-curve behind the insert's top corner: centre y, slope of its middle (deg)
    CHANNEL_X=(-12.1, -2.9),      # native x band of the tails' channel (9.2 mm: the spine's waist at the slit)
    BACK_Z=28.28,                 # finger back face (spine outer face) at the top
    SLOT_X=(-6.2, 5.5),           # gripper x of the flange slot: each stiffened tail end passes beside the other tail
    CUT_EXTRA=0.15,               # the tails' channel is cut this far past the tails' free face (no membranes)
    LEDGE_T=1.0,                  # material kept behind the tails' bonding face all along the route
)
Zs, Zf, CZ = E.Zs, E.Zf, E.CZ
TPU_TOP_Y = E.TPU_TOP_Y
POCKET_D = P["FLEX_T"] + P["FLEX_CLR"] + P["FILM_T"]
SLOT_FRONT = P["TAIL_T"] + P["TAIL_CLR"] + P["CUT_EXTRA"]      # the flange slot's front face, in front of the tails' bonding face
NO, NN, NU, NV = E.NO, E.NN, E.NU, E.NV


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def fillet(p0, t0, p1, t1, R, n=48):
    """Tangent arc of radius R from line (p0, t0) onto line (p1, t1), both travelled along their t.
    Returns the tangent points A (first line), B (second line) and the arc samples A..B."""
    t0, t1 = unit(t0), unit(t1)
    a, _ = np.linalg.solve(np.c_[t0, -t1], np.asarray(p1, float) - np.asarray(p0, float))
    X = np.asarray(p0, float) + a * t0
    phi = np.arccos(np.clip(t0 @ t1, -1.0, 1.0))
    d = R * np.tan(phi / 2)
    A, B = X - d * t0, X + d * t1
    turn = np.sign(t0[0] * t1[1] - t0[1] * t1[0])            # + : counter-clockwise
    Cc = A + R * turn * np.array([-t0[1], t0[0]])
    a0, a1 = np.arctan2(*(A - Cc)[::-1]), np.arctan2(*(B - Cc)[::-1])
    da = (a1 - a0 + np.pi) % (2 * np.pi) - np.pi
    ang = a0 + np.linspace(0.0, 1.0, n) * da
    return A, B, np.c_[Cc[0] + R * np.cos(ang), Cc[1] + R * np.sin(ang)]


def spine_lines():
    """The back spine's inner face behind the insert, from the stock frame: the top line (constant z)
    and the diagonal down to the nail root, as (point, direction) in native (y, z)."""
    hard = E.src_native()["hard"]
    H = E.section_yz(hard, P["X_PROFILE"])
    ys, zs = [], []
    for y in np.arange(-62.0, -88.0, -1.0):
        seg = H.intersection(LineString([(y, 5.0), (y, 40.0)]))
        lows = [min(c[1] for c in g.coords) for g in getattr(seg, "geoms", [seg]) if not g.is_empty]
        if lows:
            ys.append(y); zs.append(min(lows))
    k, b = np.polyfit(ys, zs, 1)
    resid = np.abs(np.polyval([k, b], ys) - zs).max()
    assert resid < 0.02, f"spine diagonal is not straight here ({resid:.3f} mm)"
    seg = H.intersection(LineString([(-40.0, 20.0), (-40.0, 40.0)]))
    z_top = min(min(c[1] for c in g.coords) for g in getattr(seg, "geoms", [seg]) if not g.is_empty)
    t_diag = unit([-1.0, -k])                                 # toward the tip (y decreasing)
    return dict(z_top=z_top, diag_p=np.array([-75.0, k * -75.0 + b]), diag_t=t_diag)


def build_route():
    """Flex path C (laminate bonding face), flange face -> nail pad end, native (y, z)."""
    sp = spine_lines()
    r = P["RECESS"]
    n_diag = np.array([-sp["diag_t"][1], sp["diag_t"][0]])
    if n_diag[1] < 0:
        n_diag = -n_diag                                      # into the spine (+z side)
    L_rise = (np.array([TPU_TOP_Y, P["Z_RISE"]]), np.array([-1.0, 0.0]))
    ym, ang = P["S_MID"]
    L_mid = (np.array([ym, (P["Z_RISE"] + sp["z_top"] + r) / 2]), unit([-np.cos(np.radians(ang)), np.sin(np.radians(ang))]))
    L_top = (np.array([-40.0, sp["z_top"] + r]), np.array([-1.0, 0.0]))
    L_diag = (sp["diag_p"] + r * n_diag, sp["diag_t"])
    L_slit = (np.array([P["Y_SLIT"], 0.0]), np.array([0.0, -1.0]))
    p_floor = E.plane_to_native(0.0, 0.0, -POCKET_D)[0]
    L_floor = (np.array([p_floor[1], p_floor[2]]), unit([NV[1], NV[2]]))
    lines = [L_rise, L_mid, L_top, L_diag, L_slit, L_floor]
    radii = [P["R_S"], P["R_S"], P["R_TOP"], P["R_DS"], P["R_BEND"]]
    pts = [L_rise[0]]
    tangent_pts = []
    for (pa, ta), (pb, tb), R in zip(lines[:-1], lines[1:], radii):
        A, B, arc = fillet(pa, ta, pb, tb, R)
        tangent_pts.append((A, B))
        pts += [A] + list(arc[1:-1]) + [B]
    # straight runs must have non-negative length between consecutive fillets
    for (_, B), (A2, _), (_, t) in zip(tangent_pts[:-1], tangent_pts[1:], lines[1:-1]):
        assert (A2 - B) @ t > -1e-6, "route fillets overlap: radii too large for the segment"
    assert (tangent_pts[0][0] - L_rise[0]) @ L_rise[1] > 0, "S-curve starts above the flange face"
    pb = tangent_pts[-1][1]                                   # end of the bend onto the nail floor
    v_tip = E.native_to_plane([[NO[0], -117.45, E.nail_face_z(-117.45)]])[0, 1]
    v_end = v_tip - P["TIP_BARE"] + 0.5
    p_end = E.plane_to_native(0.0, v_end, -POCKET_D)[0]
    pts.append(np.array([p_end[1], p_end[2]]))
    C = LineString(np.array(pts)).simplify(0.001)
    return dict(C=C, pb=pb, v_tip=v_tip, v_end=v_end, spine=sp, lines=lines, tangents=tangent_pts)


def side_band(C, d0, d1, free=True):
    """Region beside C at a distance in [d0, d1]: on the free side (toward the insert / the object,
    left of the travel direction) or the bonded side (the core)."""
    s = 1.0 if free else -1.0
    reg = C.buffer(s * d1, single_sided=True, join_style=1)
    if d0 > 0:
        reg = reg.difference(C.buffer(s * d0, single_sided=True, join_style=1))
    return reg.buffer(0)


def nail_regions(rt):
    """Pad, groove, neck and pocket on the nail plane (u, v), as ENPIRE-T but with the neck as wide as
    the tails' channel and running out through the face's proximal edge. pad is the region the taxel grid may
    use; flex, the laminate's outline, leaves the floor only along the neck."""
    face = E.nail_face_polygon()
    hull = face.convex_hull.difference(face)
    groove = max(getattr(hull, "geoms", [hull]), key=lambda g: g.bounds[3] - g.bounds[1] if abs((g.bounds[0] + g.bounds[2]) / 2) < 2 else 0)
    groove = sbox(groove.bounds[0], groove.bounds[1], groove.bounds[2], groove.bounds[3] + 5)
    v_max = rt["v_tip"] - P["TIP_BARE"]
    pad = face.buffer(-P["PAD_EDGE"], join_style=2).difference(groove.buffer(P["GROOVE_CLR"], join_style=2))
    pad = pad.intersection(sbox(-30, -30, 30, v_max))
    x0, x1 = P["CHANNEL_X"]
    u0, u1 = x0 - NO[0] + 0.2, x1 - NO[0] - 0.2
    v_pb = E.native_to_plane([[NO[0], rt["pb"][0], rt["pb"][1]]])[0, 1]
    # the neck runs out through the face's proximal edge, so no lip of the face is left over the laminate
    # where it turns round the nail root
    neck = sbox(u0, face.bounds[1] - 0.6, u1, face.bounds[1] + 2.5)
    # outside the neck the laminate stays on the flat floor: its proximal edge there sits 0.3 mm past the bend's
    # end, so the 0.3 mm fillets where it meets the neck end where the bend starts (the grid still uses all of pad)
    pad_flat = pad.intersection(sbox(-30, v_pb + 0.3, 30, 30))
    flex = unary_union([pad_flat, neck]).buffer(0.3, join_style=1).buffer(-0.3, join_style=1)
    pocket = flex.buffer(P["POCKET_CLR"], join_style=1)
    # the film lies flat from where the laminate leaves the floor; round the bend it follows the laminate. Both
    # flat parts start 0.03 mm into the bend, so each joins its wrap as one body
    film = flex.buffer(0.1, join_style=2).intersection(sbox(-30, v_pb - 0.03, 30, v_max + 0.5))
    flex_floor = flex.intersection(sbox(-30, v_pb - 0.03, 30, 30))      # the part of the laminate lying on the floor
    return dict(face=face, groove=groove, pad=pad, neck=neck, flex=flex, flex_floor=flex_floor, pocket=pocket, film=film,
                v_pb=v_pb, v_max=v_max, u_channel=(u0, u1))


def route_regions(rt):
    """2D regions (native y, z): the back block, slit fill and ledge (added to the core), the laminate's
    channel (cut from it), the laminate placeholder and the film where it wraps round the nail root."""
    C = rt["C"]
    band = P["TAIL_T"] + P["TAIL_CLR"]
    # back block: closes the gap between the root and the spine bar, behind the S-curve, up to the back face
    yb0, yb1 = -24.6, TPU_TOP_Y + 0.3
    back = side_band(C, 0.0, 12.0, free=False).intersection(sbox(yb0, P["Z_RISE"] - 0.5, yb1, P["BACK_Z"]))
    # slit fill: material up to C along the nail root (fills where the stock face is behind C)
    slit_zone = sbox(-97.8, -3.6, -94.2, 10.0)
    slit_fill = side_band(C, 0.0, 1.0, free=False).intersection(slit_zone)
    # ledge: LEDGE_T of material behind the bonding face from the flange to the slit. Inside the frame it
    # changes nothing; where the frame has a window behind the tails it backs them
    ledge = side_band(substring(C, 0.0, C.project(Point(rt["tangents"][3][1]))), 0.0, P["LEDGE_T"], free=False)
    # channel for the tails: from the flange face down to where the pad pocket takes over
    pb = rt["pb"]
    s_pb = C.project(Point(pb))
    route = substring(C, 0.0, s_pb)
    # open the slit toward the insert: the stock root face lies up to 1.15 mm in front of the bonding face (it
    # bulges to within 0.6 mm of the insert), so a channel only as deep as the tails would leave a skin over them
    slit_open = side_band(route, 0.0, 1.5, free=True).intersection(sbox(-97.8, -1.5, -94.2, 10.0))
    # the two sheets stay stacked from the pad round the bend and part in the slit: a full-stack band there
    s_stack = C.project(Point(P["Y_SLIT"], P["STACK_Z"]))
    stacked = substring(C, s_stack, s_pb)
    # room for both sheets and the PU film round the bend, and nothing of the root's corner left in front of it
    stack_cut = side_band(stacked, 0.0, POCKET_D + 0.05, free=True)
    corner = side_band(stacked, 0.0, 3.0, free=True).intersection(sbox(P["Y_SLIT"] - 3.0, -6.0, P["Y_SLIT"] + 0.9, -1.0))
    stack_cut = unary_union([stack_cut, corner])
    s_bend0 = C.project(Point(rt["tangents"][4][0]))
    film_wrap = side_band(substring(C, s_bend0, s_pb), P["FLEX_T"] + P["FLEX_CLR"], POCKET_D, free=True)
    channel = unary_union([side_band(route, 0.0, band + P["CUT_EXTRA"], free=True), slit_open, stack_cut]).buffer(0).simplify(0.001)
    e = 0.005                                    # placeholder 5 um off the core: no coincident faces in overlap checks
    tail = unary_union([side_band(substring(C, 0.0, s_stack), e, P["TAIL_T"] + e, free=True),
                        side_band(stacked, e, P["FLEX_T"] + e, free=True)]).buffer(0)
    clean = lambda g: g.simplify(0.001)          # noqa: E731  (drops near-duplicate vertices that break extrusion)
    return dict(back=clean(back), slit_fill=clean(slit_fill), ledge=clean(ledge), channel=channel, tail=tail,
                film_wrap=clean(film_wrap), s_pb=s_pb, s_stack=s_stack)


def dock_cuts_tip():
    """The ENPIRE-T dock cuts without its front tail slot, plus this finger's slot at the back of the
    cavity (gripper y of the tails rising into the flange)."""
    cuts = E.dock_cuts(None)[:-1]                              # last one is ENPIRE-T's front slot
    y_bond = P["Z_RISE"] + 2.87                                # tails' bonding face (back side)
    pcb, cav = E.P["PCB"], E.P["CAVITY"]
    seat_z = Zs - pcb["recess"] - pcb["t"]
    x0, x1 = P["SLOT_X"]
    # down through the flange floor and the stock root block below it (native y -13.5 .. -17.4), so the
    # stiffened tail ends pass straight up from the open space behind the insert's top corner
    cuts.append(E.gbox(x0, x1, y_bond - SLOT_FRONT, y_bond + 0.15, Zf - 3.6, seat_z - cav["depth"] + 0.02))
    return cuts


def tpu_stock():
    return ES.load(P["DZ"])["soft"]


def build_all(verbose=True):
    rt = build_route()
    RR = route_regions(rt)
    N = nail_regions(rt)
    xs = P["TPU_X"]
    cx0, cx1 = P["CHANNEL_X"]
    frame = ES.load(P["DZ"])["hard"]
    frame = E.diff(frame, [E.gbox(-60, 60, -60, 80, Zf + 0.3, 0)])
    flange, _ = E.make_flange()
    adds = [frame, flange, E.make_slot_fill(),
            E.extrude_yz(RR["back"], xs[0] - 0.02, xs[1] + 0.02),
            E.extrude_yz(RR["slit_fill"], cx0 - 0.3, cx1 + 0.3),
            E.extrude_yz(RR["ledge"], cx0 - 0.3, cx1 + 0.3)]
    core = E.union(adds)
    cuts = dock_cuts_tip()
    cuts.append(E.extrude_yz(RR["channel"], cx0, cx1))
    # the pocket floor at exactly the laminate's bonding face: the bend round the nail root runs onto it tangent
    cuts.append(E.extrude_plane(N["pocket"], -POCKET_D, 1.5))
    core = E.diff(core, cuts)
    # laminate placeholder (5 um off the core, as the route band): route band + pad + the tails' stub in the flange slot
    seat_z = Zs - E.P["PCB"]["recess"] - E.P["PCB"]["t"]
    y_bond = P["Z_RISE"] + 2.87
    tx0, tx1 = sorted((E.x_n_to_g(cx0 + 0.2), E.x_n_to_g(cx1 - 0.2)))
    e = 0.005
    flex = E.union([E.extrude_yz(RR["tail"], cx0 + 0.2, cx1 - 0.2),
                    E.extrude_plane(N["flex_floor"], -POCKET_D + e, -POCKET_D + P["FLEX_T"] + e),
                    E.gbox(tx0, tx1, y_bond - P["TAIL_T"], y_bond, Zf - 0.05, seat_z - E.P["CAVITY"]["depth"] + 1.0)])
    film = E.union([E.extrude_plane(N["film"], -P["FILM_T"], 0.0), E.extrude_yz(RR["film_wrap"], cx0 + 0.1, cx1 - 0.1)])
    parts = dict(core=core, flex=flex, film=film)
    ph = E.placeholders()
    # the readout's parts keep clear of the tails, which rise at the back of the cavity
    ph["ph_finger_pcb_parts"] = E.diff(ph["ph_finger_pcb_parts"], [E.gbox(P["SLOT_X"][0] - 0.3, P["SLOT_X"][1] + 0.3, y_bond - 1.6, 40.0,
                                                                         seat_z - 10.0, seat_z + 1.0)])
    parts.update(ph)
    if verbose:
        for k, m in parts.items():
            print(f"{k:20s} watertight {m.is_watertight!s:5s} vol {m.volume:10.1f}  bounds {np.round(m.bounds, 2).tolist()}")
    return parts, rt, RR, N


def derived(rt, N):
    fp = E.FlexPath(dict(C=rt["C"]))
    s_nail0 = float(rt["C"].project(Point(rt["pb"])))
    tip_n = np.array([NO[0], -117.647, E.nail_face_z(-117.647)])
    tip_g = E.n2g(tip_n)[0]
    C = rt["C"]
    (_, slit_top), (bend0, _) = rt["tangents"][3], rt["tangents"][4]
    s_stack = float(C.project(Point(P["Y_SLIT"], P["STACK_Z"])))
    # each bend's radius at the laminate's inner face: the bonding face where the bend turns toward the core,
    # the free face (bonding face radius less the laminate) where it turns toward the free side
    bends = []
    names = ("S-curve, lower", "S-curve, upper", "spine top to diagonal", "diagonal into the slit", "round the nail root")
    radii = [P["R_S"], P["R_S"], P["R_TOP"], P["R_DS"], P["R_BEND"]]
    for k, ((_, ta), (_, tb), R, (A, B)) in enumerate(zip(rt["lines"][:-1], rt["lines"][1:], radii, rt["tangents"])):
        t_lam = P["FLEX_T"] if k == 4 else P["TAIL_T"]
        toward_free = (ta[0] * tb[1] - ta[1] * tb[0]) > 0          # counter-clockwise: centre on the free (left) side
        turn = np.degrees(np.arccos(np.clip(unit(ta) @ unit(tb), -1.0, 1.0)))
        bends.append(dict(bend=names[k], at_s_mm=round(float(C.project(Point(A))), 2), radius_mm=R,
                          inner_face_mm=round(R - t_lam if toward_free else R, 2), turn_deg=round(float(turn), 2),
                          sheets=2 if k == 4 else 1))
    single = min((b for b in bends if b["sheets"] == 1), key=lambda b: b["inner_face_mm"])
    stacked = [b for b in bends if b["sheets"] == 2][0]
    return dict(Zs=Zs, Zf=Zf, DZ=P["DZ"], POCKET_D=POCKET_D, C_length=round(float(fp.length), 3),
                s_nail0=round(s_nail0, 3), v_nail0=round(float(N["v_pb"]), 3), v_pad_max=round(float(N["v_max"]), 3),
                s_slit_top=round(float(C.project(Point(slit_top))), 3), s_bend0=round(float(C.project(Point(bend0))), 3),
                s_stack=round(s_stack, 3),
                tip_g=tip_g.round(3).tolist(), tip_below_carriage_mm=round(float(E.FP["Z_CARRIAGE"] - tip_g[2]), 2),
                channel_u=sorted([round(E.x_n_to_g(P["CHANNEL_X"][0]), 3), round(E.x_n_to_g(P["CHANNEL_X"][1]), 3)]),
                route_min_bend_radius=dict(mm=single["inner_face_mm"], at_s_mm=single["at_s_mm"], bend=single["bend"]),
                stack_min_bend_radius=dict(mm=stacked["inner_face_mm"], at_s_mm=stacked["at_s_mm"], bend=stacked["bend"]),
                stack_bend_turn_deg=stacked["turn_deg"],
                laminate_bends=bends,
                y_rise_g=round(P["Z_RISE"] + 2.87, 3),
                nail_plane_g=dict(origin=E.n2g(NO)[0].round(4).tolist(),
                                  normal=(E.n2g(NN[None]) - E.n2g(np.zeros((1, 3))))[0].round(6).tolist(),
                                  u=(E.n2g(NU[None]) - E.n2g(np.zeros((1, 3))))[0].round(6).tolist(),
                                  v=(E.n2g(NV[None]) - E.n2g(np.zeros((1, 3))))[0].round(6).tolist()))


PART_NAMES = ("core", "flex", "film", "ph_finger_pcb", "ph_finger_pcb_parts")
ATTRIBUTION = ES.ATTRIBUTION.split(" Modified:")[0] + (
    " Modified (ENPIRE-T Tip): filled nail slot, nail sensor pocket, plug-in dock flange, a laminate channel"
    " round the nail root (its corner cleared there) and along the back spine, a ledge behind that channel"
    " at the frame's windows, and a closed back between the root block and the spine bar. The TPU"
    " insert is used unchanged.")


def export(parts, rt, RR, N):
    os.makedirs(OUT, exist_ok=True)
    for k in PART_NAMES:
        parts[k] = E.clean(parts[k])
        parts[k].export(os.path.join(OUT, f"{k}.stl"))
        back = trimesh.load(os.path.join(OUT, f"{k}.stl"))
        assert back.is_watertight and back.is_volume, f"{k}.stl is not a closed volume after export"
    D = derived(rt, N)
    json.dump(dict(params=P, derived=D, source=dict(commit=ES.COMMIT, files={k: v[1] for k, v in ES.FILES.items()},
                                                   attribution=ATTRIBUTION)),
              open(os.path.join(OUT, "params.json"), "w"), indent=1)
    json.dump(dict(frame="native ENPIRE (y, z), mm", note="C: laminate bonding face, flange face -> nail pad end",
                   C=np.round(np.asarray(rt["C"].coords), 4).tolist(),
                   nail_flex_uv=[list(map(list, g.exterior.coords)) for g in getattr(N["flex"], "geoms", [N["flex"]])]),
              open(os.path.join(OUT, "profile.json"), "w"))
    open(os.path.join(OUT, "NOTICE.txt"), "w").write(
        "ENPIRE-T Tip parts in this folder are a modified version of the ENPIRE gripper finger.\n" + ATTRIBUTION +
        "\nLicence: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ . Changes are listed above and in docs/ENPIRE_T_TIP.md.\n"
        "The cradle is the original TPU insert (I2RT_UCG_Soft.stl), unchanged: print it from the original file, which\n"
        "cad/enpire_source.py fetches. The sim model (sim/assets/tpu_*.stl) and the web viewer carry copies of it placed\n"
        "on the finger, under the same licence.\n")
    return D


if __name__ == "__main__" and "--build" in sys.argv:
    parts, rt, RR, N = build_all()
    D = export(parts, rt, RR, N)
    print({k: v for k, v in D.items() if k != "nail_plane_g"})

if __name__ == "__main__" and "--profile" in sys.argv:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rt = build_route()
    RR = route_regions(rt)
    S = E.src_native()
    H, T = E.section_yz(S["hard"], P["X_PROFILE"]), E.section_yz(S["soft"], P["X_PROFILE"])
    fig, axs = plt.subplots(3, 1, figsize=(20, 24))
    views = (((-10, -120), (-6, 31)), ((-86, -100), (-5, 12)), ((-10, -58), (17, 30)))
    for ax, (xl, yl) in zip(axs, views):
        for g0, c in ((H, "#8d99ab"), (T, "#f2b35b")):
            for g in getattr(g0, "geoms", [g0]):
                x, y = g.exterior.xy; ax.fill(x, y, fc=c, ec="k", lw=0.4, alpha=0.6)
                for rr in g.interiors:
                    x, y = rr.xy; ax.fill(x, y, fc="white", ec="k", lw=0.3)
        for k, c in (("back", "#3a6aa8"), ("slit_fill", "#2e7d4f"), ("channel", "#d9b232")):
            for g in getattr(RR[k], "geoms", [RR[k]]):
                if not g.is_empty:
                    x, y = g.exterior.xy; ax.fill(x, y, fc=c, ec="none", alpha=0.6)
        x, y = rt["C"].xy; ax.plot(x, y, "r-", lw=1.0)
        ax.set_xlim(*xl); ax.set_ylim(*yl); ax.set_aspect("equal"); ax.grid(alpha=.3)
    plt.tight_layout(); plt.savefig(sys.argv[-1], dpi=60)
    print("C length", round(rt["C"].length, 2), "pb", np.round(rt["pb"], 3))
