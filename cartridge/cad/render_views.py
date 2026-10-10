"""Render overview / exploded / section images of the tactile finger (matplotlib, headless)."""
import json
import os
import sys
import numpy as np
import trimesh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from matplotlib.patches import Polygon as MPoly

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_fit as cf  # noqa: E402
import yam_tactile_finger as F  # noqa: E402

OUT = cf.OUT
CHK = cf.CHK
COL = dict(socket="#6b6f78", cartridge="#2f6fb3", skin="#f08a24", ph_pad="#d9b23a", ph_finger_pcb="#1f7a3a",
           ph_finger_pcb_parts="#333333", ph_socket_pcb="#1f7a3a", ph_pogo_pins="#c9a227", ph_thumbscrews="#b0b0b0",
           ph_dowels="#b0b0b0", housing="#9a9a9a", carriage="#b8b8b8")


def shade(m, base, light=np.array([0.35, -0.55, 0.75])):
    n = m.face_normals
    light = light / np.linalg.norm(light)
    k = np.clip(n @ light, 0, 1) * 0.6 + 0.4
    rgb = np.array(matplotlib.colors.to_rgb(base))
    return np.clip(rgb[None] * k[:, None], 0, 1)


def draw(ax, items, el, az, lims, title, alpha=1.0):
    for m, c in items:
        pc = Poly3DCollection(m.vertices[m.faces], facecolors=shade(m, c), edgecolors="none", linewidths=0, alpha=alpha)
        ax.add_collection3d(pc)
    (x0, x1), (y0, y1), (z0, z1) = lims
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_zlim(z0, z1)
    ax.set_box_aspect((x1 - x0, y1 - y0, z1 - z0))
    ax.view_init(elev=el, azim=az)
    ax.set_title(title, fontsize=11)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])
    ax.set_axis_off()


def overview():
    q = 0.022
    G, CL, CR, _, _ = cf.yam_meshes(q)
    Rf, Lf = cf.finger(q, +1), cf.finger(q, -1)
    items = [(G, COL["housing"]), (CL, COL["carriage"]), (CR, COL["carriage"])]
    for f in (Rf, Lf):
        for k in ("socket", "cartridge", "skin"):
            items.append((f[k], COL[k]))
    fig = plt.figure(figsize=(16, 8.5))
    lims = ((-60, 60), (-75, 75), (-150, 15))
    ax = fig.add_subplot(1, 2, 1, projection="3d"); draw(ax, items, 18, -55, lims, "YAM Linear 4310 + tactile cartridges (22 mm open)")
    ax = fig.add_subplot(1, 2, 2, projection="3d"); draw(ax, items, 0, 0, lims, "side view (along x)")
    plt.tight_layout(); plt.savefig(os.path.join(CHK, "overview.png"), dpi=90); plt.close()


def exploded():
    f = cf.finger(0.0, +1)
    off = dict(socket=(0, 0, 22), ph_socket_pcb=(0, 0, 30), ph_pogo_pins=(0, 0, 30), ph_dowels=(0, 0, 22),
               ph_finger_pcb=(0, 0, 9), ph_finger_pcb_parts=(0, 0, 9), cartridge=(0, 0, 0), ph_thumbscrews=(0, 0, -14),
               ph_pad=(0, -9, 0), skin=(0, -20, 0))
    items = []
    for k, m in f.items():
        mm = m.copy(); mm.apply_translation(off.get(k, (0, 0, 0)))
        items.append((mm, COL[k]))
    fig = plt.figure(figsize=(16, 9))
    lims = ((-30, 30), (-30, 45), (-150, -50))
    ax = fig.add_subplot(1, 2, 1, projection="3d"); draw(ax, items, 15, -35, lims, "exploded: socket / PCBs / cartridge / pad / skin")
    items2 = [(f[k], COL[k]) for k in ("socket", "cartridge", "skin", "ph_thumbscrews")]
    ax = fig.add_subplot(1, 2, 2, projection="3d"); draw(ax, items2, 20, 145, ((-30, 30), (-10, 45), (-150, -65)), "docked, from below/back (thumbscrews under the wings)")
    plt.tight_layout(); plt.savefig(os.path.join(CHK, "exploded.png"), dpi=90); plt.close()


def section(axis, value, fname, title, xlim, ylim):
    f = cf.finger(0.0, +1)
    ai = "xyz".index(axis)
    others = [i for i in range(3) if i != ai]
    fig, ax = plt.subplots(figsize=(9, 9 * (ylim[1] - ylim[0]) / (xlim[1] - xlim[0]) + 0.6))
    order = ["socket", "cartridge", "skin", "ph_pad", "ph_finger_pcb", "ph_finger_pcb_parts", "ph_socket_pcb",
             "ph_pogo_pins", "ph_thumbscrews", "ph_dowels"]
    for k in order:
        m = f[k]
        o = np.zeros(3); o[ai] = value
        nrm = np.zeros(3); nrm[ai] = 1
        s = m.section(plane_origin=o, plane_normal=nrm)
        if s is None:
            continue
        T = np.eye(4)
        # project to the two remaining axes
        pts3 = s.vertices
        for ent in s.entities:
            pts = pts3[ent.points][:, others]
            ax.add_patch(MPoly(pts, closed=True, facecolor=COL[k], edgecolor="k", lw=0.4, alpha=0.85))
    ax.set_xlim(*xlim); ax.set_ylim(*ylim); ax.set_aspect("equal")
    ax.grid(True, lw=0.3)
    ax.set_xlabel(f"{'xyz'[others[0]]} [mm]"); ax.set_ylabel(f"{'xyz'[others[1]]} [mm]")
    ax.set_title(title, fontsize=11)
    plt.tight_layout(); plt.savefig(os.path.join(CHK, fname), dpi=110); plt.close()


if __name__ == "__main__":
    which = sys.argv[1:] or ["overview", "exploded", "sections"]
    if "overview" in which:
        overview()
    if "exploded" in which:
        exploded()
    if "sections" in which:
        D = cf.D
        section("x", 0.0, "sec_x0.png", "section x = 0 (centre: tails, slot, PCB, pogo, thumbscrew)", (-3, 32), (-146, -68))
        section("x", 18.5, "sec_x18.png", "section x = 18.5 (thumbscrew + insert)", (-3, 32), (-100, -68))
        section("x", 10.0, "sec_x10.png", "section x = 10 (dowel, PCB, ZIF zone)", (-3, 32), (-100, -68))
        section("z", -124.0, "sec_z124.png", "section z = -124 (through the sensor bay)", (-20, 20), (-2, 16))
        section("z", D["Zs"] - 1.0, "sec_flange.png", "section 1 mm below the docking face", (-26, 36), (0, 31))
        section("z", F.P["SKIN_RIB"]["z"], "sec_skin_rib.png", "section through the skin retention ribs", (-15, 15), (-1, 15))
        section("x", -17.5, "sec_relief.png", "section x = -17.5 (relief under the opposite carriage, dowel)", (0, 28), (-92, -68))
