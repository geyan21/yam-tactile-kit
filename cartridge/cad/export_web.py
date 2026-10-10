"""
Build the cartridge webpage data from the pipeline outputs.

  web/data.js         compact meshes (0.01 mm integers) + feature edges for the WebGL viewer, the taxel
                      layout, pin maps, measurements and the file list
  web/data_enpire.js  the ENPIRE-T model for the same viewer (loaded only when someone picks it): its own
                      parts, decimated where that changes nothing visible, plus the socket parts it shares
  web/index.html      web/index.template.html with every {{placeholder}} filled from the same numbers,
                      so the page reads correctly even without JavaScript

Usage (from cartridge/): python3 cad/export_web.py      (run after the other pipeline steps, `make enpire` included)
"""
import json
import os
import re
import sys
import tempfile

import cadquery as cq
import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yam_tactile_finger as F  # noqa: E402

ROOT = F.ROOT
OUT = F.OUT
WEB = os.path.join(ROOT, "web")
REPO = "geyan21/yam-tactile-kit"
BRANCH = "tactile-cartridge"
VERSION = "0.2"

PARTS = {   # name: (label, colour, explode vector mm, group)
    "socket": ("Socket (stays on the carriage)", "#6b6f78", (0, 0, 34), "socket"),
    "dowels": ("Dowel pins", "#aeb4b9", (0, 0, 34), "socket"),
    "socket_pcb": ("Socket PCB", "#1f6b3f", (0, 0, 24), "electronics"),
    "pogo_pins": ("Pogo pins", "#c9a227", (0, 0, 24), "electronics"),
    "finger_pcb": ("Finger PCB", "#1f6b3f", (0, 0, 12), "electronics"),
    "finger_pcb_parts": ("Finger PCB components", "#2b3238", (0, 0, 12), "electronics"),
    "cartridge": ("Cartridge", "#2f6fb3", (0, 0, 0), "cartridge"),
    "thumbscrews": ("Thumbscrews", "#aeb4b9", (0, 0, -14), "cartridge"),
    "pad": ("Sensor pad", "#d9961e", (0, -12, 0), "pad"),
    "skin": ("TPU skin", "#e8873a", (0, -24, 0), "skin"),
}
ENPIRE = os.path.join(OUT, "enpire")
# ENPIRE-T in viewer order. A str entry reuses that v0.2 socket-side part with a new explode vector;
# a tuple is (stl in out/enpire, label, colour, explode vector mm, group, decimate to this fraction).
ENPIRE_PARTS = {
    "socket": (0, 0, 40), "dowels": (0, 0, 40), "socket_pcb": (0, 0, 28), "pogo_pins": (0, 0, 28),
    "finger_pcb": ("ph_finger_pcb", "Finger PCB", "#1f6b3f", (0, 0, 16), "electronics", 1.0),
    "finger_pcb_parts": ("ph_finger_pcb_parts", "Finger PCB components", "#2b3238", (0, 0, 16), "electronics", 1.0),
    "core": ("core", "Rigid core (ENPIRE frame)", "#2f6fb3", (0, 0, 0), "cartridge", 0.5),
    "thumbscrews": (0, 0, -14),
    "flex": ("flex", "Sensing laminate", "#d9961e", (0, -14, 0), "pad", 1.0),
    "film": ("film", "Nail film", "#2aa198", (0, -24, 0), "skin", 1.0),
    "skin": ("skin", "Silicone skin", "#e8873a", (0, -30, 0), "skin", 0.5),
}
GLASS = ("skin", "film")          # drawn see-through when "See through the skin" is on


def mesh_of(shape, tmp, name):
    path = os.path.join(tmp, name + ".stl")
    cq.exporters.export(shape, path, tolerance=0.08, angularTolerance=0.3)
    m = trimesh.load(path)
    m.merge_vertices()
    return m


def feature_edges(m, angle_deg=32):
    """Edges whose adjacent faces bend more than angle_deg, plus open boundary edges."""
    sharp = m.face_adjacency_edges[m.face_adjacency_angles > np.radians(angle_deg)]
    edges = trimesh.grouping.group_rows(m.edges_sorted, require_count=1)
    boundary = m.edges_sorted[edges]
    return np.vstack([sharp, boundary]) if len(boundary) else sharp


def pack(m):
    q = np.round(m.vertices * 100).astype(int)
    return dict(v=q.ravel().tolist(), f=m.faces.ravel().tolist(), e=feature_edges(m).ravel().tolist())


def decimate(m, keep):
    """Quadric decimation to `keep` of the faces (viewer only; at 0.5 it moves the core and the skin by
    < 0.05 mm, so the skin keeps its teeth)."""
    if keep >= 1.0:
        return m
    import fast_simplification
    v, f = fast_simplification.simplify(m.vertices.astype(np.float32), m.faces.astype(np.int32), target_reduction=1.0 - keep)
    return trimesh.Trimesh(v.astype(float), f, process=True)


def enpire_taxels():
    """One square per ENPIRE-T taxel (electrode width) on the laminate's outer face, right finger, q = 0."""
    tm = json.load(open(os.path.join(ENPIRE, "taxel_map.json")))
    lift = json.load(open(os.path.join(ENPIRE, "params.json")))["params"]["FLEX_T"] / 2 + 0.03
    R = tm["fingers"]["right"]
    v, f = [], []
    for t, p, n in zip(tm["taxels"], R["sensor_q0"], R["normal_toward_object"]):
        a = (1.4 if t["region"] == "strip" else 1.0) / 2
        n = np.asarray(n, float) / np.linalg.norm(n)
        e1 = np.array([1.0, 0, 0]) - n * n[0]
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(n, e1)
        c = np.asarray(p, float) * 1000 + n * lift
        b = len(v)
        v += [c + du * e1 + dv * e2 for du, dv in ((-a, -a), (a, -a), (a, a), (-a, a))]
        f += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
    return np.array(v), np.array(f), len(tm["taxels"])


def enpire_model():
    """The ENPIRE-T viewer model (web/data_enpire.js)."""
    parts = []
    for name, spec in ENPIRE_PARTS.items():
        if not isinstance(spec[0], str):                   # a v0.2 socket-side part, shared
            parts.append(dict(name=name, shared=True, explode=list(spec)))
            continue
        stl, label, colour, explode, group, keep = spec
        m = trimesh.load(os.path.join(ENPIRE, stl + ".stl"))
        m.merge_vertices()
        m = decimate(m, keep)
        parts.append(dict(name=name, label=label, color=colour, explode=list(explode), group=group, glass=name in GLASS, **pack(m)))
        if name == "flex":
            v, f, n = enpire_taxels()
            parts.append(dict(name="taxels", label="Taxels", color="#b0631f", explode=list(explode), group="pad", glass=False,
                              v=np.round(v * 100).astype(int).ravel().tolist(), f=f.ravel().tolist(), e=[]))
    meas = json.load(open(os.path.join(ENPIRE, "check", "measurements.json")))
    return dict(frame="as data.js; ENPIRE-T right finger at q = 0", parts=parts, measurements=meas)


def file_list():
    rows = []
    for base, _, names in os.walk(OUT):
        for n in sorted(names):
            p = os.path.join(base, n)
            rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
            rows.append(dict(path=rel, bytes=os.path.getsize(p)))
    return sorted(rows, key=lambda r: r["path"])


def fmt(x, nd=2):
    if not isinstance(x, float):
        return str(x)
    s = f"{x:.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s       # 10.0 at nd=0 stays "10"


def gap_band(tm):
    """Length along the finger (z) between the last strip row and the first nail row, mm."""
    sq = np.array(tm["fingers"]["right"]["surface_q0"]) * 1000
    reg = np.array([t["region"] for t in tm["taxels"]])
    return sq[reg == "strip"][:, 2].min() - sq[reg == "nail"][:, 2].max()


def enpire_values(em, n_e):
    """Template values for the ENPIRE-T section, from out/enpire/."""
    def J(rel):
        return json.load(open(os.path.join(ENPIRE, rel)))
    ec, es, ed, epm = J("check/checks.json"), J("sim/selftest.json"), J("fpc_pcb/drc.json"), J("fpc_pcb/pinmap.json")
    ep = J("params.json")["params"]
    sw = ec["clearance_sweep"]
    walls = em["walls"]
    rects = ep["PCB"]["rects"]
    pin, rod = es["nail_pinch"], es["cradle_grasp"]
    rows = []
    for r in em["tip_profile"]:
        if r["from_tip_mm"] in (0.5, 1.7, 5.0, 10.0):
            rows.append(f'          <tr><th scope="row">{fmt(r["from_tip_mm"], 1)} mm</th><td>{fmt(r["thickness_mm"])} mm</td>'
                        f'<td>{fmt(r["stock_thickness_mm"])} mm</td><td>{fmt(r["width_mm"], 1)} mm</td><td>{fmt(r["stock_width_mm"], 1)} mm</td></tr>')
    return {
        "e_taxels": str(n_e), "e_strip": str(em["taxels"]["strip"]), "e_nail": str(em["taxels"]["nail"]),
        "e_rows_lines": str(em["lines"]["rows"]), "e_cols_lines": str(em["lines"]["cols"]),
        "e_frame_bytes": str(16 + 2 * n_e),
        "e_tip_rows": "\n".join(rows),
        "e_tip_below": fmt(em["tip_below_carriage_mm"], 1),
        "e_longer": fmt(em["tip_below_carriage_mm"] - em["stock_tip_below_carriage_mm"], 1),
        "e_skin_t": fmt(ep["SKIN_T"], 1), "e_film_t": fmt(ep["FILM_T"], 2),
        "e_seat_set": fmt(em["seat_set_back_mm"], 1), "e_pocket": fmt(em["nail_pocket_depth_mm"], 2),
        "e_q_touch": fmt(em["q_touch_mm"], 3),
        "e_cradle_p95": fmt(em["shape"]["depth_map_cradle_mm"]["p95"], 3),
        "e_notch_depth": fmt(em["shape"]["transition_notch_filled"]["max_depth_mm"], 0),
        "e_clear_socket": fmt(min(r["vs_opposite_carriage"] for r in sw if r["part"] == "socket"), 1),
        "e_clear_finger": fmt(min(min(r["vs_opposite_carriage"], r["vs_housing"]) for r in sw
                                  if r["part"] in ("core", "skin", "ph_thumbscrews")), 1),
        "e_wall_nail": fmt(walls["nail_behind_pocket_min_mm"]["t"], 1),
        "e_wall_dowel": fmt(min(walls["wall_dowel_L_mm"], walls["wall_dowel_R_mm"]), 2),
        "e_wall_thumb": fmt(min(walls["wall_thumbscrew_L_mm"], walls["wall_thumbscrew_R_mm"]), 1),
        "e_bend_r": fmt(em["min_seat_bend_radius_under_taxels_mm"], 1),
        "e_grip": fmt(pin["grip_N"], 0), "e_pin_d": fmt(float(pin["pin_d_mm"]), 0),
        "e_pin_share": str(round(100 * min(pin["sensed_share"]))),
        "e_rod_share": "–".join(sorted({str(round(100 * x)) for x in rod["sensed_share"]}, key=int)),
        "e_flat_n": fmt(max(es["flat_tip_pinch"]["left_nail_N"], es["flat_tip_pinch"]["right_nail_N"]), 1),
        "e_gap_band": fmt(float(gap_band(J("taxel_map.json"))), 0),
        "e_tilt": fmt(float(np.degrees(np.arcsin(abs(ep["NAIL_N"][1])))), 1),
        "e_q_stock": fmt(ec["contact"]["stock_q_touch_mm"], 3),
        "e_free_mm2": fmt(ed["pcb_free_mm2"], 0),
        "e_lam_r": fmt(ed["laminate_min_bend_radius"]["mm"], 1),
        "e_pin_taxels": str(min(pin["active_nail"])),
        "e_rod_d": fmt(float(rod["rod_d_mm"]), 0), "e_rod_taxels": str(min(rod["active_strip"])),
        "e_drc_gap": fmt(min(v for v in ed["drc_stats"].values() if isinstance(v, (int, float))), 2),
        "e_pcb_w": fmt(max(r[1] for r in rects) - min(r[0] for r in rects) - 0.2, 1),
        "e_pcb_h": fmt(max(r[3] for r in rects) - min(r[2] for r in rects) - 0.2, 1),
        "e_rows_pins": str(epm["rows_tail_pins"]), "e_cols_pins": str(epm["cols_tail_pins"]),
        "e_doc_url": f"https://github.com/{REPO}/blob/{BRANCH}/cartridge/docs/ENPIRE_T.md",
    }


def main():
    P, D = F.P, F.DERIVED
    meas = json.load(open(os.path.join(OUT, "check", "measurements.json")))
    inter = json.load(open(os.path.join(OUT, "check", "interference.json")))
    pin = json.load(open(os.path.join(OUT, "fpc_pcb", "pinmap.json")))
    sim = json.load(open(os.path.join(OUT, "sim", "selftest.json")))

    parts = F.build_all()
    meshes = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, (label, colour, explode, group) in PARTS.items():
            m = mesh_of(parts[name], tmp, name)
            meshes[name] = dict(label=label, color=colour, explode=explode, group=group, **pack(m))

    tip = {round(r["from_tip_mm"], 1): r for r in meas["tip_profile"]}
    data = dict(
        version=VERSION,
        repo=REPO, branch=BRANCH,
        frame="i2rt linear_4310 gripper body frame, right finger at q = 0, millimetres (x lateral, y closing axis, z toward the wrist)",
        meshes=meshes,
        layout=dict(rows=P["N_ROWS"], cols=P["N_COLS"], pitch=P["PITCH"], electrode=P["ELECTRODE_W"],
                    act_z0=D["ACT_Z0"], act_w=D["ACT_W"], y_face=D["Y_FACE"], contact_y=P["CONTACT_Y"],
                    pad_half_x=D["PAD_HALF_X"], pad_z=[D["PAD_DIST_Z"], D["PAD_PROX_Z"]], tcp_z=P["TCP_Z"],
                    skin_top_z=P["SKIN_TOP_Z"], sense_half_x=P["SENSE_HALF_X"], skin_side=P["SKIN_SIDE_T"]),
        pinmap=dict(rows=pin["rows_tail_16p"], cols=pin["cols_tail_8p"], rows_readout_order=pin["rows_readout_order"],
                    pogo=pin["pogo"]),
        measurements=meas, selftest=sim,
        files=file_list(),
    )
    em = json.load(open(os.path.join(ENPIRE, "check", "measurements.json")))
    n_e = em["taxels"]["strip"] + em["taxels"]["nail"]
    data["models"] = dict(
        flat=dict(label="Flat cartridge", caption=f"Flat cartridge v{VERSION}: {P['N_ROWS'] * P['N_COLS']} taxels on one flat pad."),
        enpire=dict(label="ENPIRE-T", src="data_enpire.js", var="CARTRIDGE_ENPIRE",
                    caption=f"ENPIRE-T: {n_e} taxels, {em['taxels']['strip']} on the cradle and {em['taxels']['nail']} on the nail."))
    os.makedirs(WEB, exist_ok=True)
    js = "window.CARTRIDGE = " + json.dumps(data, separators=(",", ":")) + ";\n"
    open(os.path.join(WEB, "data.js"), "w").write(js)
    ejs = "window.CARTRIDGE_ENPIRE = " + json.dumps(enpire_model(), separators=(",", ":")) + ";\n"
    open(os.path.join(WEB, "data_enpire.js"), "w").write(ejs)

    sweep = inter["clearance_sweep"]
    values = {
        "version": VERSION,
        "repo": REPO, "branch": BRANCH,
        "zip_url": f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip",
        "tree_url": f"https://github.com/{REPO}/tree/{BRANCH}/cartridge",
        "clear_opp": fmt(min(r["vs_opposite_carriage"] for r in sweep), 1),
        "clear_housing": fmt(min(r["vs_housing"] for r in sweep), 0),
        "wall_pad": fmt(meas["wall_behind_pad_min_mm"], 1),
        "wall_min_hole": fmt(min(meas[k] for k in ("socket_wall_around_dowel_mm", "socket_wall_around_thumb_insert_mm",
                                                   "socket_wall_around_mount_insert_mm", "cartridge_wall_around_thumb_hole_mm")), 1),
        "wall_max_hole": fmt(max(meas[k] for k in ("socket_wall_around_dowel_mm", "socket_wall_around_thumb_insert_mm",
                                                   "socket_wall_around_mount_insert_mm", "cartridge_wall_around_thumb_hole_mm")), 1),
        "vol_socket": fmt(meas["volume_cm3"]["socket"], 1), "vol_cart": fmt(meas["volume_cm3"]["cartridge"], 1),
        "vol_skin": fmt(meas["volume_cm3"]["skin"], 1),
        "t17_ours": fmt(tip[1.7]["ours_thick_centre"]), "t17_max": fmt(tip[1.7]["ours_thick_max"]),
        "t17_stock": fmt(tip[1.7]["stock_thick_centre"]), "w17_ours": fmt(tip[1.7]["ours_width"], 1),
        "w17_stock": fmt(tip[1.7]["stock_width"], 1),
        "t5_ours": fmt(tip[5.0]["ours_thick_centre"]), "t5_max": fmt(tip[5.0]["ours_thick_max"]),
        "t5_stock": fmt(tip[5.0]["stock_thick_centre"]), "w5_ours": fmt(tip[5.0]["ours_width"], 1),
        "w5_stock": fmt(tip[5.0]["stock_width"], 1),
        "tail_len": fmt(meas["tail_cut_length_mm"], 1),
        "sim_left": fmt(sim["left_sum_N"], 1), "sim_right": fmt(sim["right_sum_N"], 1),
        "sim_taxels": str(sim["left_active"]), "sim_grip": fmt(sim["grip_N"], 0),
        "taxels": str(P["N_ROWS"] * P["N_COLS"]), "rows": str(P["N_ROWS"]), "cols": str(P["N_COLS"]),
        "pitch": fmt(float(P["PITCH"]), 0), "act_w": fmt(float(D["ACT_W"]), 0), "act_l": fmt(float(D["ACT_L"]), 0),
        "skin_t": fmt(P["SKIN_T"], 1), "pad_t": fmt(P["PAD_T"], 1),
        "relief": fmt(P["OPP_RELIEF"], 1),
        "squeeze": fmt(-P["CONTACT_Y"], 2),
        "tcp_z": fmt(P["TCP_Z"], 2),
    }
    values.update(enpire_values(em, n_e))
    files_html = []
    groups = [("Printable parts", ("out/socket.", "out/cartridge.", "out/skin.")),
              ("Assembly", ("out/finger_assembly",)),
              ("FPC and PCBs", ("out/fpc_pcb/",)),
              ("Sim model", ("out/sim/linear_4310_tactile.xml", "out/sim/selftest.json")),
              ("Data contracts", ("out/taxel_map.json", "out/params.json")),
              ("Checks", ("out/check/interference.json", "out/check/measurements.json")),
              ("ENPIRE-T parts", ("out/enpire/core.stl", "out/enpire/skin.", "out/enpire/skin_mold_", "out/enpire/film.stl")),
              ("ENPIRE-T laminate and PCB", ("out/enpire/fpc_pcb/",)),
              ("ENPIRE-T sim, data and checks", ("out/enpire/sim/linear_4310_enpire_t.xml", "out/enpire/sim/selftest.json",
                                                 "out/enpire/taxel_map.json", "out/enpire/params.json",
                                                 "out/enpire/check/checks.json", "out/enpire/check/measurements.json",
                                                 "out/enpire/NOTICE.txt"))]
    listed = set()
    for title, prefixes in groups:
        rows = [f for f in data["files"] if f["path"].startswith(prefixes) and not f["path"].endswith(".png")]
        if not rows:
            continue
        files_html.append(f'<tr class="group"><th colspan="2" scope="rowgroup">{title}</th></tr>')
        for f in rows:
            listed.add(f["path"])
            b = f["bytes"]
            size = f"{b / 1048576:.1f} MB" if b >= 1048576 else f"{b / 1024:.0f} KB" if b >= 1024 else f"{b} B"
            files_html.append(f'<tr><td><a href="../{f["path"]}" download><code>{f["path"][4:]}</code></a></td><td>{size}</td></tr>')
    values["files_rows"] = "\n".join(files_html)

    tpl = open(os.path.join(WEB, "index.template.html")).read()

    def sub(mt):
        key = mt.group(1)
        if key not in values:
            raise KeyError(f"index.template.html uses unknown placeholder {{{{{key}}}}}")
        return values[key]
    html = re.sub(r"\{\{([a-z0-9_]+)\}\}", sub, tpl)
    assert "{{" not in html, "unfilled placeholder"

    def size(mt):   # width/height attributes always match the image on disk (no layout shift)
        from PIL import Image
        w, h = Image.open(os.path.join(ROOT, mt.group(2))).size
        return f'{mt.group(1)}{mt.group(2)}"{mt.group(3)}width="{w}" height="{h}"'
    html = re.sub(r'(<img src="\.\./)(out/[^"]+)"([^>]*?)width="\d+" height="\d+"', size, html)
    open(os.path.join(WEB, "index.html"), "w").write(html)
    print(f"web/data.js {len(js) / 1024:.0f} KB, {sum(len(m['f']) // 3 for m in meshes.values())} triangles; "
          f"web/index.html written ({len(listed)} files listed)")


if __name__ == "__main__":
    main()
