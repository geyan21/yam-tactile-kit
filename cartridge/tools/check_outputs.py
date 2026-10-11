"""
Stdlib-only consistency check of the committed outputs (no CadQuery needed):
every file the page links exists, the page has no unfilled placeholders, data.js matches the
measurement files, the taxel and pin maps are self-consistent, and the key margins hold.

Usage (from cartridge/): python3 tools/check_outputs.py      exit code 1 on any failure
"""
import json
import math
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # cartridge/
OUT = os.path.join(ROOT, "out")
WEB = os.path.join(ROOT, "web")
REQUIRED = [
    "socket.step", "socket.stl", "cartridge.step", "cartridge.stl", "skin.step", "skin.stl",
    "finger_assembly_right_q0.step", "params.json", "taxel_map.json",
    "fpc_pcb/fpc_rows_bottom_fab.dxf", "fpc_pcb/fpc_cols_top_fab.dxf", "fpc_pcb/fpc_stack_view.dxf",
    "fpc_pcb/finger_pcb_outline.dxf", "fpc_pcb/socket_pcb_outline.dxf", "fpc_pcb/pinmap.json",
    "sim/linear_4310_tactile.xml", "sim/selftest.json", "sim/NOTICE.txt", "sim/I2RT_LICENSE",
    "check/interference.json", "check/measurements.json", "renders/overview_sheet.png",
]
problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)


def load(rel):
    with open(os.path.join(OUT, rel)) as f:
        return json.load(f)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets, self.ids = [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.targets += [a[k] for k in ("href", "src") if a.get(k)]
        if "id" in a:
            self.ids.add(a["id"])


def main():
    for rel in REQUIRED:
        check(os.path.isfile(os.path.join(OUT, rel)), f"missing out/{rel}")

    html = open(os.path.join(WEB, "index.html")).read()
    check("{{" not in html, "web/index.html has unfilled placeholders (run cad/export_web.py)")
    links = Links()
    links.feed(html)
    for t in links.targets:
        u = urlsplit(t)
        if u.scheme or t.startswith("//"):
            continue
        if not u.path:
            check(u.fragment in links.ids, f"web/index.html links to missing #{u.fragment}")
            continue
        check(os.path.isfile(os.path.normpath(os.path.join(WEB, u.path))), f"web/index.html links to missing {t}")

    js = open(os.path.join(WEB, "data.js")).read()
    m = re.fullmatch(r"window\.CARTRIDGE = (.*);\n", js, re.S)
    check(m is not None, "web/data.js has an unexpected format")
    data = json.loads(m.group(1)) if m else {}
    meas = load("check/measurements.json")
    check(data.get("measurements") == meas, "web/data.js is stale (measurements differ; run cad/export_web.py)")
    for name, mesh in data.get("meshes", {}).items():
        nv = len(mesh["v"]) // 3
        check(len(mesh["v"]) % 3 == 0 and len(mesh["f"]) % 3 == 0, f"mesh {name}: ragged arrays")
        check(max(mesh["f"] + mesh["e"], default=0) < nv, f"mesh {name}: index out of range")

    P = load("params.json")
    p, d = P["params"], P["derived"]
    tm = load("taxel_map.json")
    n = p["N_ROWS"] * p["N_COLS"]
    right, left = tm["fingers"]["right"]["taxels_q0"], tm["fingers"]["left"]["taxels_q0"]
    check(len(right) == n and len(left) == n, "taxel_map: wrong taxel count")
    check(all(abs(r[0] + l[0]) < 1e-9 and abs(r[1] + l[1]) < 1e-9 and abs(r[2] - l[2]) < 1e-9 for r, l in zip(right, left)),
          "taxel_map: left finger is not the right one rotated 180 deg about z")
    pitch = p["PITCH"] / 1000
    check(abs((right[1][0] - right[0][0]) - pitch) < 1e-9 and abs((right[p["N_COLS"]][2] - right[0][2]) - pitch) < 1e-9,
          "taxel_map: pitch mismatch")
    check(abs(d["Y_FACE"] + p["PAD_T"] - d["Y_POCKET"]) < 1e-9, "params: pad pocket depth != PAD_T")

    pin = load("fpc_pcb/pinmap.json")
    half = p["N_ROWS"] // 2
    check(pin["rows_readout_order"] == list(range(half)) + list(range(p["N_ROWS"] - 1, half - 1, -1)),
          "pinmap: unexpected rows readout order")
    for key, nn in (("TAIL_ROWS_U", p["N_ROWS"]), ("TAIL_COLS_U", p["N_COLS"])):
        w = p[key][1] - p[key][0]
        check(abs(w - (nn + 1) * 0.5) <= 0.05, f"params: {key} width {w:.2f} mm is not a {nn}-pin 0.5 mm FFC")
    check([q["signal"] for q in pin["pogo"]] == ["GND", "D-", "D+", "VBUS", "GND"], "pinmap: pogo order changed")

    sweep = load("check/interference.json")["clearance_sweep"]
    check(min(r["vs_opposite_carriage"] for r in sweep) >= 1.0, "clearance to the opposite carriage < 1.0 mm")
    check(min(r["vs_housing"] for r in sweep) >= 1.0, "clearance to the housing < 1.0 mm")
    check(max(r["vol_x_housing"] + r["vol_x_opposite"] for r in sweep) == 0, "parts intersect the YAM over the stroke")
    walls = [meas[k] for k in meas if k.endswith("_mm") and ("wall" in k)]
    check(min(walls) >= 1.3, f"a wall is thinner than 1.3 mm: {min(walls)}")
    st = load("sim/selftest.json")
    check(st["nsensor"] == 2 * n and abs(st["left_sum_N"] - st["grip_N"]) < 0.5 and abs(st["right_sum_N"] - st["grip_N"]) < 0.5,
          "sim self-test: touch sensors do not read the grip force")

    check_enpire()
    check_enpire_tip()
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    print(f"outputs OK: {len(REQUIRED)} + {len(ENPIRE_REQUIRED)} + {len(TIP_REQUIRED)} files, page links, data.js, taxel/pin maps, "
          f"margins, sim self-tests (v0.2, ENPIRE-T and ENPIRE-T Tip)")


ENPIRE_REQUIRED = [
    "core.stl", "skin.stl", "skin.step", "flex.stl", "film.stl", "skin_mold_core.stl", "skin_mold_shell.stl",
    "params.json", "profile.json", "taxel_map.json", "NOTICE.txt",
    "fpc_pcb/rows_sheet_fab.dxf", "fpc_pcb/cols_sheet_fab.dxf", "fpc_pcb/finger_pcb_outline.dxf", "fpc_pcb/pinmap.json",
    "fpc_pcb/drc.json", "check/checks.json", "check/measurements.json",
    "sim/linear_4310_enpire_t.xml", "sim/selftest.json", "sim/NOTICE.txt", "sim/I2RT_LICENSE",
    "renders/overview_sheet.png", "renders/section.png",
]


def check_enpire():
    """ENPIRE-T outputs: present, mutually consistent, and every check still passing."""
    base = os.path.join(OUT, "enpire")
    for rel in ENPIRE_REQUIRED:
        check(os.path.isfile(os.path.join(base, rel)), f"missing out/enpire/{rel}")
    if problems:
        return
    def J(rel):
        with open(os.path.join(base, rel)) as f:
            return json.load(f)
    tm, pin, drc = J("taxel_map.json"), J("fpc_pcb/pinmap.json"), J("fpc_pcb/drc.json")
    n = len(tm["taxels"])
    check(tm["counts"]["strip"] + tm["counts"]["nail"] == n, "enpire taxel_map: counts do not add up")
    R, L = tm["fingers"]["right"], tm["fingers"]["left"]
    for key in ("sensor_q0", "surface_q0"):
        check(len(R[key]) == n and all(abs(r[0] + l[0]) < 1e-9 and abs(r[1] + l[1]) < 1e-9 and abs(r[2] - l[2]) < 1e-9
                                         for r, l in zip(R[key], L[key])), f"enpire taxel_map {key}: left is not the right rotated 180 deg")
    rows, cols = set(pin["scan"]["row_lines"]), set(pin["scan"]["col_lines"])
    cross = [(t["row_net"], t["col_net"]) for t in tm["taxels"]]
    check(all(r in rows and c in cols for r, c in cross), "enpire: a taxel uses a line missing from the pin map")
    check(len(set(cross)) == n, "enpire: two taxels share a row/column crossing")
    for tail, key in (("rows_tail", "row_lines"), ("cols_tail", "col_lines")):
        sig = [p["signal"] for p in pin[tail] if p["signal"] != "GND"]
        check(sorted(sig) == sorted(pin["scan"][key]), f"enpire pinmap: {tail} does not carry exactly the {key}")
    check(not drc["drc_issues"] and not drc["pcb_issues"], "enpire: flex DRC or PCB placement issues")
    chk = J("check/checks.json")
    internal = {k: v for k, v in chk["internal"].items() if k != "ph_finger_pcb x ph_pogo_pins"}   # pogo stroke by design
    # parts that share a boundary (skin/flex on the laminate top) can leave a boolean sliver of ~1e-4 mm3
    check(all(v < 1e-3 for v in internal.values()), f"enpire: parts overlap inside one finger {[k for k, v in internal.items() if v >= 1e-3]}")
    sw = chk["clearance_sweep"]
    check(min(r["vs_housing"] for r in sw) >= 1.0 and min(r["vs_opposite_carriage"] for r in sw) >= 1.0,
          "enpire: clearance to the YAM < 1 mm over the stroke")
    check(max(r["vol_x_housing"] + r["vol_x_opposite"] for r in sw) == 0, "enpire: parts intersect the YAM over the stroke")
    ct = chk["contact"]
    check(abs(ct["q_touch_mm"] - ct["stock_q_touch_mm"]) < 0.02, "enpire: the fingers no longer meet at the stock ENPIRE opening")
    sh = chk["shape"]
    check(sh["depth_map_cradle_mm"]["p95"] < 0.05 and sh["depth_map_nail_mm"]["p95"] < 0.05 and sh["film_vs_nail_plane_mm"]["max_abs"] < 0.01,
          "enpire: the contact surface moved away from the original ENPIRE shape")
    w = chk["walls"]
    check(w["nail_behind_pocket_min_mm"]["t"] >= 2.0 and w["nail_lip_pocket_to_groove_mm"] >= 0.8 and
          min(w[k] for k in w if k.startswith("wall_")) >= 1.3 and w["cavity_floor_min_mm"] >= 2.0 and
          w["nail_lip_pocket_to_face_edge_mm"] >= 0.6, "enpire: a wall is too thin")
    check(min(drc["tail_room_mm"].values()) >= 0.2, "enpire: a tail has no room for its bend and stiffener")
    st = J("sim/selftest.json")
    check(st["nsensor"] == 2 * n, "enpire sim: sensor count")
    nail, cr, fl = st["nail_pinch"], st["cradle_grasp"], st["flat_tip_pinch"]
    check(min(nail["sensed_share"]) >= 0.75 and nail["sensors_match_contacts"], "enpire sim: nail taxels miss the pin")
    check(min(cr["sensed_share"]) >= 0.6 and cr["sensors_match_contacts"] and min(cr["active_strip"]) >= 10,
          "enpire sim: cradle taxels miss the rod")
    check(abs(fl["contact_N_both_fingers"] - 2 * fl["grip_N"]) < 1.0, "enpire sim: the flat plate was not gripped")

    # the page's ENPIRE-T model (web/data_enpire.js), loaded by app.js from next to data.js
    def page_data(name, var):
        with open(os.path.join(WEB, name)) as f:
            m = re.fullmatch(r"window\." + var + r" = (.*);\n", f.read(), re.S)
        check(m is not None, f"web/{name} has an unexpected format")
        return json.loads(m.group(1)) if m else {}
    data, edata = page_data("data.js", "CARTRIDGE"), page_data("data_enpire.js", "CARTRIDGE_ENPIRE")
    check(data.get("models", {}).get("enpire", {}).get("src") == "data_enpire.js", "web/data.js does not point at data_enpire.js")
    check(edata.get("measurements") == J("check/measurements.json"), "web/data_enpire.js is stale (run cad/export_web.py)")
    for p in edata.get("parts", []):
        if p.get("shared"):
            check(p["name"] in data.get("meshes", {}), f"web/data_enpire.js: shared part {p['name']} is not in data.js")
            continue
        nv = len(p["v"]) // 3
        check(len(p["v"]) % 3 == 0 and len(p["f"]) % 3 == 0, f"ENPIRE-T mesh {p['name']}: ragged arrays")
        check(max(p["f"] + p["e"], default=0) < nv, f"ENPIRE-T mesh {p['name']}: index out of range")
    tx = [p for p in edata.get("parts", []) if p["name"] == "taxels"]
    check(len(tx) == 1 and len(tx[0]["f"]) == 6 * n, "web/data_enpire.js: not one square per ENPIRE-T taxel")


TIP_REQUIRED = [
    "core.stl", "flex.stl", "film.stl", "params.json", "profile.json", "taxel_map.json", "NOTICE.txt",
    "fpc_pcb/rows_sheet_fab.dxf", "fpc_pcb/cols_sheet_fab.dxf", "fpc_pcb/film_cut.dxf", "fpc_pcb/finger_pcb_outline.dxf",
    "fpc_pcb/pinmap.json", "fpc_pcb/drc.json", "check/checks.json", "check/measurements.json",
    "sim/linear_4310_enpire_t_tip.xml", "sim/selftest.json", "sim/NOTICE.txt", "sim/I2RT_LICENSE",
    "renders/overview_sheet.png", "renders/section.png", "renders/route_view.png", "renders/hero.png", "renders/nail_closeup.png",
]


def check_enpire_tip():
    """ENPIRE-T Tip outputs: present, mutually consistent, and every check still passing."""
    base = os.path.join(OUT, "enpire_tip")
    for rel in TIP_REQUIRED:
        check(os.path.isfile(os.path.join(base, rel)), f"missing out/enpire_tip/{rel}")
    if problems:
        return
    def J(rel):
        with open(os.path.join(base, rel)) as f:
            return json.load(f)
    tm, pin, drc, meas = J("taxel_map.json"), J("fpc_pcb/pinmap.json"), J("fpc_pcb/drc.json"), J("check/measurements.json")
    n = len(tm["taxels"])
    check(tm["counts"]["nail"] == n == meas["taxels"]["nail"], "tip taxel_map: counts do not add up")
    R, L = tm["fingers"]["right"], tm["fingers"]["left"]
    for key in ("sensor_q0", "surface_q0"):
        check(len(R[key]) == n and all(abs(r[0] + l[0]) < 1e-9 and abs(r[1] + l[1]) < 1e-9 and abs(r[2] - l[2]) < 1e-9
                                         for r, l in zip(R[key], L[key])), f"tip taxel_map {key}: left is not the right rotated 180 deg")
    rows, cols = set(pin["scan"]["row_lines"]), set(pin["scan"]["col_lines"])
    cross = [(t["row_net"], t["col_net"]) for t in tm["taxels"]]
    check(all(r in rows and c in cols for r, c in cross), "tip: a taxel uses a line missing from the pin map")
    check(len(set(cross)) == n, "tip: two taxels share a row/column crossing")
    for tail, key in (("rows_tail", "row_lines"), ("cols_tail", "col_lines")):
        sig = [p["signal"] for p in pin[tail] if p["signal"] != "GND"]
        check(sorted(sig) == sorted(pin["scan"][key]), f"tip pinmap: {tail} does not carry exactly the {key}")
    check(not drc["drc_issues"] and not drc["pcb_issues"], "tip: flex DRC or PCB placement issues")
    check(min(drc["tail_room_mm"].values()) >= 0.2, "tip: a tail has no room for its bends and stiffener in the cavity")
    bend = drc["laminate_min_bend_radius"]
    check(bend["single_sheet"]["mm"] >= 1.8 and bend["stacked"]["mm"] >= 1.5, f"tip: laminate bends too tight {bend}")
    der = J("params.json")["derived"]
    sheet_t = J("params.json")["params"]["SHEET_T"]
    check(abs(drc["cols_neck_extra_mm"] - sheet_t * math.radians(der["stack_bend_turn_deg"])) < 0.002,
          "tip: the cols sheet's neck does not carry its extra length round the nail root")
    cx = J("params.json")["params"]["CHANNEL_X"]
    check(drc["film_cut"]["wrap_strip_mm"] > (der["s_nail0"] - der["s_bend0"]) and drc["film_cut"]["width_mm"] > 8.0
          and abs(drc["film_cut"]["wrap_strip_width_mm"] - (cx[1] - cx[0] - 0.2)) < 0.02,
          "tip: the film's cut outline does not reach round the nail root as film.stl does")
    check(der["s_slit_top"] < drc["sheets_part_at_s_mm"] < der["s_bend0"] and der["s_stack"] <= drc["sheets_part_at_s_mm"] - 0.3,
          "tip: the sheets no longer part in the slit, inside the stacked channel")
    for rel, words in (("NOTICE.txt", ("Wenli Xiao", "CC BY 4.0", "ENPIRE-T Tip")), ("sim/NOTICE.txt", ("Wenli Xiao", "ENPIRE-T Tip", "unchanged"))):
        with open(os.path.join(base, rel)) as f:
            txt = f.read()
        check(all(w in txt for w in words), f"out/enpire_tip/{rel} lacks the attribution")
    chk = J("check/checks.json")
    internal = {k: v for k, v in chk["internal"].items() if k != "ph_finger_pcb x ph_pogo_pins"}   # pogo stroke by design
    check(all(v < 1e-3 for v in internal.values()), f"tip: parts overlap inside one finger {[k for k, v in internal.items() if v >= 1e-3]}")
    check(chk["route_gap_to_tpu_mm"]["min_mm"] >= 0.2, "tip: the laminate comes within 0.2 mm of the TPU insert")
    sw = chk["clearance_sweep"]
    check(min(r["vs_housing"] for r in sw) >= 1.0 and min(r["vs_opposite_carriage"] for r in sw) >= 1.0,
          "tip: clearance to the YAM < 1 mm over the stroke")
    check(max(r["vol_x_housing"] + r["vol_x_opposite"] for r in sw) == 0, "tip: parts intersect the YAM over the stroke")
    ct = chk["contact"]
    check(abs(ct["q_touch_mm"] - ct["stock_q_touch_mm"]) < 0.02, "tip: the fingers no longer meet at the stock ENPIRE opening")
    sh = chk["shape"]
    check(sh["depth_map_cradle_mm"]["max"] < 0.01 and sh["depth_map_sides_mm"]["max"] < 0.01 and sh["depth_map_nail_mm"]["p95"] < 0.05
          and sh["film_vs_nail_plane_mm"]["max_abs"] < 0.01, "tip: the contact side moved away from the original ENPIRE shape")
    check(sh["core_vs_hard_frame_mm"]["max"] < 0.05 and sh["hard_frame_vs_core_mm"]["max"] < 0.05,
          "tip: the core differs from the stock frame outside the zones changed on purpose")
    root = sh["nail_root"]
    # the docs say: the film-covered bend lies within the stock corner (flush at most), the slit's mouth is no
    # narrower than stock, and bare laminate shows only deep in the slit
    check(root["laminate_outside_stock_frame_mm"]["max"] <= 0.02 and root["edge_max_nearer_mm"] <= 0.02 and root["mouth_max_nearer_mm"] <= 0.02,
          f"tip: the laminate or film stands proud of the stock nail root {root}")
    check(sh["laminate_exposed_rays_outside_root"] == 0 and (root["bare_laminate_min_depth_mm"] is None or root["bare_laminate_min_depth_mm"] >= 5.0)
          and root["film_end_depth_mm"] >= 2.0,
          "tip: bare laminate shows outside the slit, or nearer the nail face than the docs say")
    check(chk["route_gap_to_tpu_mm"]["slit_and_bend_mm"] >= chk["route_gap_to_tpu_mm"]["stock_root_face_to_tpu_mm"],
          "tip: the slit beside the insert is narrower than stock")
    w = chk["walls"]
    behind = {k: v["t"] for k, v in w.items() if k.startswith("behind_laminate_")}
    check(len(behind) == 7 and min(behind.values()) >= 0.8, f"tip: thin or missing material behind the laminate {behind}")
    fs = w["free_side_clear_mm"]["min_mm"]
    check(isinstance(fs, str) or fs >= 2.0, f"tip: core material in front of the laminate ({fs} mm)")
    check(w["nail_behind_pocket_min_mm"]["t"] >= 2.0 and w["nail_lip_pocket_to_groove_mm"] >= 0.8 and
          w["nail_lip_pocket_to_face_edge_mm"] >= 0.6 and min(w[k] for k in w if k.startswith("wall_")) >= 1.3 and
          w["cavity_floor_min_mm"] >= 2.0 and min(w["tail_slot_walls_mm"].values()) >= 1.0, "tip: a wall is too thin")
    st = J("sim/selftest.json")
    check(st["nsensor"] == 2 * n, "tip sim: sensor count")
    nail, cr, fl = st["nail_pinch"], st["cradle_grasp"], st["flat_tip_pinch"]
    check(nail["min_sensed_share"] >= 0.99 and nail["all_match_contacts"] and nail["max_touch_error"] <= 0.01
          and set(nail["max_touch_error_by_object"]) == {"pin", "rod", "bar_edge_on"},
          "tip sim: the nail taxels do not read the pin's, rod's and bar's force (the page says within 1%, all on taxels)")
    check(max(cr["sensed_share"]) == 0 and cr["contact_N_both_fingers"] > 2 * cr["grip_N"] - 1.0,
          "tip sim: the cradle grasp should load only the (unsensed) stock insert")
    check(abs(fl["contact_N_both_fingers"] - 2 * fl["grip_N"]) < 1.0 and max(fl["sensed_share"]) == 0,
          "tip sim: the flat plate at the tips should be gripped by the bare tips only (the page says so)")
    # the page's numbers come from these files: they must not have changed since web/index.html was written
    import hashlib
    with open(os.path.join(WEB, "page_inputs.json")) as f:
        inputs = json.load(f)
    stale = [r for r, h in inputs.items() if hashlib.sha256(open(os.path.join(ROOT, r), "rb").read()).hexdigest() != h]
    check(not stale, f"web/index.html is stale: {stale} changed since (run cad/export_web.py)")
    with open(os.path.join(WEB, "data.js")) as f:
        m = re.fullmatch(r"window\.CARTRIDGE = (.*);\n", f.read(), re.S)
    data = json.loads(m.group(1)) if m else {}
    check(data.get("models", {}).get("enpire_tip", {}).get("src") == "data_enpire_tip.js", "web/data.js does not point at data_enpire_tip.js")
    with open(os.path.join(WEB, "data_enpire_tip.js")) as f:
        m = re.fullmatch(r"window\.CARTRIDGE_ENPIRE_TIP = (.*);\n", f.read(), re.S)
    check(m is not None, "web/data_enpire_tip.js has an unexpected format")
    tdata = json.loads(m.group(1)) if m else {}
    check(tdata.get("measurements") == meas, "web/data_enpire_tip.js is stale (run cad/export_web.py)")
    for p in tdata.get("parts", []):
        if p.get("shared"):
            check(p["name"] in data.get("meshes", {}), f"web/data_enpire_tip.js: shared part {p['name']} is not in data.js")
            continue
        nv = len(p["v"]) // 3
        check(len(p["v"]) % 3 == 0 and len(p["f"]) % 3 == 0, f"ENPIRE-T Tip mesh {p['name']}: ragged arrays")
        check(max(p["f"] + p["e"], default=0) < nv, f"ENPIRE-T Tip mesh {p['name']}: index out of range")
    tx = [p for p in tdata.get("parts", []) if p["name"] == "taxels"]
    check(len(tx) == 1 and len(tx[0]["f"]) == 6 * n, "web/data_enpire_tip.js: not one square per taxel")


if __name__ == "__main__":
    main()
