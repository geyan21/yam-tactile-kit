"""Shaded offscreen renders (VTK/EGL) and an annotated section of ENPIRE-T Tip.
Usage (from cartridge/): python3 cad/enpire_tip_render.py [i2rt_repo_root]  -> out/enpire_tip/renders/"""
import json
import os
import sys
import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_fit as cf          # noqa: E402
import enpire_finger as E       # noqa: E402
import enpire_source as ES      # noqa: E402
import enpire_tip as T          # noqa: E402
import render_vtk as RV         # noqa: E402

OUT = os.path.join(T.OUT, "renders")
os.makedirs(OUT, exist_ok=True)
RV.OUT = OUT
C = dict(socket=(0.36, 0.37, 0.40), core=(0.22, 0.42, 0.66), tpu=(0.95, 0.60, 0.22), film=(0.16, 0.60, 0.56),
         flex=(0.86, 0.70, 0.22), ph_finger_pcb=(0.10, 0.48, 0.22), ph_finger_pcb_parts=(0.15, 0.15, 0.15),
         ph_socket_pcb=(0.10, 0.48, 0.22), ph_pogo_pins=(0.85, 0.72, 0.25), ph_thumbscrews=(0.72, 0.72, 0.74),
         ph_dowels=(0.72, 0.72, 0.74), housing=(0.55, 0.57, 0.58), carriage=(0.72, 0.74, 0.76), taxel=(0.80, 0.30, 0.10),
         enpire_hard=(0.25, 0.25, 0.27), enpire_soft=(0.93, 0.62, 0.25))
TM = json.load(open(os.path.join(T.OUT, "taxel_map.json")))
TPU = T.tpu_stock()


def parts(q=0.0, side=1):
    out = {k: trimesh.load(os.path.join(T.OUT, k + ".stl")) for k in ("core", "film", "flex", "ph_finger_pcb", "ph_finger_pcb_parts")}
    out["tpu"] = TPU.copy()
    for k in ("socket", "ph_socket_pcb", "ph_pogo_pins", "ph_thumbscrews", "ph_dowels"):
        out[k] = trimesh.load(os.path.join(E.F.OUT, k + ".stl"))
    for m in out.values():
        m.apply_translation([0, q * 1000, 0])
        if side < 0:
            m.apply_transform(np.diag([-1, -1, 1, 1.0]))
    return out


def taxel_tiles(offset=(0, 0, 0)):
    pts = np.array(TM["fingers"]["right"]["sensor_q0"]) * 1000
    nrm = np.array(TM["fingers"]["right"]["normal_toward_object"])
    tiles = []
    a = T.P["NAIL_PITCH"] - 0.25
    for p, n in zip(pts, nrm):
        b = trimesh.creation.box((a, 0.08, a))
        e1 = np.array([1.0, 0, 0]); e2 = n / np.linalg.norm(n); e1 -= e2 * (e1 @ e2); e1 /= np.linalg.norm(e1)
        M = np.eye(4); M[:3, :3] = np.c_[e1, e2, np.cross(e1, e2)]; M[:3, 3] = p + n * 0.25 + np.array(offset)
        b.apply_transform(M)
        tiles.append(b)
    return trimesh.util.concatenate(tiles)


def hero():
    q = 0.024
    G, CL, CR, _, _ = cf.yam_meshes(q)
    R, L = parts(q, 1), parts(q, -1)
    def fn(ren):
        RV.add(ren, G, C["housing"]); RV.add(ren, CL, C["carriage"]); RV.add(ren, CR, C["carriage"])
        for f in (R, L):
            for k in ("socket", "core", "tpu", "film", "ph_thumbscrews"):
                RV.add(ren, f[k], C[k])
    RV.render(fn, "hero.png", pos=(-300, -390, -10), focal=(0, 0, -112), size=(1300, 1300))


def exploded():
    f = parts()
    off = dict(socket=(0, 0, 44), ph_socket_pcb=(0, 0, 32), ph_pogo_pins=(0, 0, 32), ph_dowels=(0, 0, 44),
               ph_finger_pcb=(0, 0, 18), ph_finger_pcb_parts=(0, 0, 18), core=(0, 0, 0), ph_thumbscrews=(0, 0, -16),
               flex=(0, -12, 0), tpu=(0, -30, 0), film=(0, -22, 0))
    tiles = taxel_tiles(offset=(0, -12, 0))
    def fn(ren):
        for k, m in f.items():
            mm = m.copy(); mm.apply_translation(off.get(k, (0, 0, 0)))
            RV.add(ren, mm, C[k])
        RV.add(ren, tiles, C["taxel"], edges=False)
    RV.render(fn, "exploded.png", pos=(-290, -300, -20), focal=(0, -10, -132), size=(1300, 1300))


def contact_face():
    f = parts()
    tiles = taxel_tiles()
    def fn(ren):
        for k in ("socket", "core", "tpu", "ph_thumbscrews"):
            RV.add(ren, f[k], C[k])
        RV.add(ren, tiles, C["taxel"], edges=False)
        RV.add(ren, f["film"], C["film"], opacity=0.33, edges=False)
    RV.render(fn, "contact_face.png", pos=(-150, -250, -150), focal=(0, 8, -138), size=(1100, 1300))


def nail_closeup():
    f = parts()
    tiles = taxel_tiles()
    def fn(ren):
        RV.add(ren, f["core"], C["core"])
        RV.add(ren, tiles, C["taxel"], edges=False)
        RV.add(ren, f["film"], C["film"], opacity=0.35, edges=False)
        RV.add(ren, f["tpu"], C["tpu"])
        RV.add(ren, f["flex"], C["flex"])
    RV.render(fn, "nail_closeup.png", pos=(-40, -82, -212), focal=(0, -1, -183.5), size=(1100, 1000))


def route_view():
    """The laminate's way from the nail to the flange: core see-through, insert hidden."""
    f = parts()
    def fn(ren):
        RV.add(ren, f["flex"], C["flex"])
        RV.add(ren, taxel_tiles(), C["taxel"], edges=False)
        RV.add(ren, f["ph_finger_pcb"], C["ph_finger_pcb"])
        RV.add(ren, f["core"], C["core"], opacity=0.28, edges=False)
        RV.add(ren, f["socket"], C["socket"], opacity=0.5, edges=False)
    RV.render(fn, "route_view.png", pos=(260, -120, -60), focal=(0, 12, -136), size=(1100, 1300))


def compare():
    """Stock ENPIRE (as mounted, left) next to ENPIRE-T Tip on its socket (right), same scale."""
    src = ES.load(0.0)
    f = parts()
    def fn(ren):
        h, s = src["hard"].copy(), src["soft"].copy()
        for m in (h, s):
            m.apply_translation((-45, 0, 0))
        RV.add(ren, h, C["enpire_hard"]); RV.add(ren, s, C["enpire_soft"])
        for k in ("socket", "core", "tpu", "film", "ph_thumbscrews"):
            RV.add(ren, f[k], C[k])
    RV.render(fn, "compare.png", pos=(-60, -380, -110), focal=(-22, 0, -132), size=(1300, 1100))


def back_view():
    f = parts()
    def fn(ren):
        for k in ("socket", "core", "tpu", "ph_thumbscrews"):
            RV.add(ren, f[k], C[k])
    RV.render(fn, "back_view.png", pos=(190, 280, -90), focal=(0, 10, -132), size=(1100, 1300))


def section():
    """Annotated mid-plane section: core, TPU insert, laminate, film, PCB, socket (matplotlib)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from shapely.geometry import Polygon
    f = parts()
    col = dict(core="#3a6aa8", tpu="#f2a33a", flex="#d9b232", film="#2aa198", ph_finger_pcb="#2e7d4f",
               ph_finger_pcb_parts="#333333", socket="#5c5f66", ph_socket_pcb="#2e7d4f", ph_pogo_pins="#d8b43c")
    x0 = -4.0                          # through the rows tail and a prong of the pad (the centre is the groove)
    fig, ax = plt.subplots(figsize=(17, 6.6))
    for k, c in col.items():
        s = f[k].section(plane_origin=[x0, 0, 0], plane_normal=[1, 0, 0])
        if s is None:
            continue
        geom = None
        for e in s.discrete:
            p = Polygon(e[:, [2, 1]]).buffer(0)
            geom = p if geom is None else geom.symmetric_difference(p)
        for g in getattr(geom, "geoms", [geom]):
            if g.is_empty:
                continue
            x, y = g.exterior.xy; ax.fill(x, y, fc=c, ec="#222", lw=0.3)
            for r in g.interiors:
                x, y = r.xy; ax.fill(x, y, fc="white", ec="#222", lw=0.2)
    rt = T.build_route()
    fp = E.FlexPath(dict(C=rt["C"]))
    at = lambda s: fp.point_g(x0, s, lift=0.1)[0][0]     # noqa: E731  (gripper x, y, z on the laminate)
    D = T.derived(rt, T.nail_regions(rt))
    kw = dict(fontsize=10, color="#1f2328", arrowprops=dict(arrowstyle="-", color="#5b6470", lw=0.8))
    ax.annotate("socket (v0.2, stays on the YAM)", xy=(-75, 18), xytext=(-74, 36), **kw)
    ax.annotate("finger PCB + readout in the flange", xy=(-83.2, 20), xytext=(-96, 33), **kw)
    p = at(25.0)
    ax.annotate("laminate tails, one sheet thick, in a 0.2 mm recess behind the insert", xy=(p[2], p[1]), xytext=(-104, 38.5), **kw)
    ax.annotate("stock TPU insert, unchanged", xy=(-125, 3.0), xytext=(-118, -8), **kw)
    p = at(D["s_stack"] + 1.0)
    ax.annotate("both sheets round the nail root, parting in the slit", xy=(p[2], p[1]), xytext=(-150, -8), **kw)
    ax.annotate(f"flush nail pad ({TM['counts']['nail']} taxels) under a {T.P['FILM_T']:g} mm film", xy=(-184, -0.9), xytext=(-170, -14), **kw)
    p = at(1.0)
    ax.annotate("tails rise into the flange at the back", xy=(p[2], p[1]), xytext=(-79, -3), **kw)
    ax.set_xlim(-72, -197); ax.set_ylim(-17, 41); ax.set_aspect("equal")
    ax.set_xlabel("gripper z (mm)"); ax.set_ylabel("gripper y (mm), object side at the bottom")
    ax.set_title(f"ENPIRE-T Tip, section beside the finger centre (x = {x0:g} mm)", loc="left")
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "section.png"), dpi=90); plt.close()


def contact_sheet():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.image as mpimg
    items = [("hero.png", "YAM Linear 4310 with two ENPIRE-T Tip fingers on the shared socket"),
             ("compare.png", "stock ENPIRE (left) and ENPIRE-T Tip on its socket (right)"),
             ("route_view.png", f"the laminate: {len(TM['taxels'])} taxels on the nail, tails behind the insert"),
             ("contact_face.png", "taxels under the film; the stock TPU cradle stays as it is")]
    fig, axs = plt.subplots(2, 2, figsize=(16, 15))
    for ax, (fn, t) in zip(axs.ravel(), items):
        ax.imshow(mpimg.imread(os.path.join(OUT, fn))); ax.set_title(t, fontsize=12); ax.axis("off")
    plt.tight_layout(); plt.savefig(os.path.join(OUT, "overview_sheet.png"), dpi=80); plt.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cf.set_i2rt(sys.argv[1])
    hero(); exploded(); contact_face(); nail_closeup(); route_view(); compare(); back_view(); section(); contact_sheet()
    print("renders in", OUT)
