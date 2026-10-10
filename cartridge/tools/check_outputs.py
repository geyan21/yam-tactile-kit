"""
Stdlib-only consistency check of the committed outputs (no CadQuery needed):
every file the page links exists, the page has no unfilled placeholders, data.js matches the
measurement files, the taxel and pin maps are self-consistent, and the key margins hold.

Usage (from cartridge/): python3 tools/check_outputs.py      exit code 1 on any failure
"""
import json
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

    if problems:
        print("\n".join(problems))
        sys.exit(1)
    print(f"outputs OK: {len(REQUIRED)} files, page links, data.js, taxel/pin maps, margins, sim self-test")


if __name__ == "__main__":
    main()
