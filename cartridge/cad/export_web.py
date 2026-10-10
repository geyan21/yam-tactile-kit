"""
Build the cartridge webpage data from the pipeline outputs.

  web/data.js     compact meshes (0.01 mm integers) + feature edges for the WebGL viewer, the taxel
                  layout, pin maps, measurements and the file list
  web/index.html  web/index.template.html with every {{placeholder}} filled from the same numbers,
                  so the page reads correctly even without JavaScript

Usage (from cartridge/): python3 cad/export_web.py      (run after the other pipeline steps)
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


def file_list():
    rows = []
    for base, _, names in os.walk(OUT):
        for n in sorted(names):
            p = os.path.join(base, n)
            rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
            rows.append(dict(path=rel, bytes=os.path.getsize(p)))
    return sorted(rows, key=lambda r: r["path"])


def fmt(x, nd=2):
    return f"{x:.{nd}f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


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
    os.makedirs(WEB, exist_ok=True)
    js = "window.CARTRIDGE = " + json.dumps(data, separators=(",", ":")) + ";\n"
    open(os.path.join(WEB, "data.js"), "w").write(js)

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
    files_html = []
    groups = [("Printable parts", ("out/socket.", "out/cartridge.", "out/skin.")),
              ("Assembly", ("out/finger_assembly",)),
              ("FPC and PCBs", ("out/fpc_pcb/",)),
              ("Sim model", ("out/sim/linear_4310_tactile.xml", "out/sim/selftest.json")),
              ("Data contracts", ("out/taxel_map.json", "out/params.json")),
              ("Checks", ("out/check/interference.json", "out/check/measurements.json"))]
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
