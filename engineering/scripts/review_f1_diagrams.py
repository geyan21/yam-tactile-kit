#!/usr/bin/python3
"""Rasterize the two local F1 diagrams and check that text stays inside each canvas."""

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path, required=True)
    args = parser.parse_args()
    if not args.browser.is_file():
        parser.error("Select an explicit installed browser")
    folder = ROOT / "build/engineering/prototypes/f1/diagram_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Render only the two repository-owned F1 diagrams in isolated local browser profiles; check SVG text bounds and save review images") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        record["browser_runs"] = []
        results = []
        with tempfile.TemporaryDirectory(prefix="f1-diagram-review-") as temporary:
            for name, height in (("f1_stack", 830), ("f1_wiring", 800)):
                source = ROOT / "engineering/web" / (name+".svg")
                page = folder / (name+".html")
                script = """<script>addEventListener('load',()=>{const s=document.querySelector('svg'),v=s.viewBox.baseVal;
const bad=[...s.querySelectorAll('text')].map(t=>({text:t.textContent,box:t.getBBox()}))
.filter(t=>t.box.x<0||t.box.y<0||t.box.x+t.box.width>v.width||t.box.y+t.box.height>v.height)
.map(t=>t.text);document.getElementById('checks').textContent=JSON.stringify({passed:bad.length===0,outside:bad});});</script>"""
                page.write_text('<!doctype html><meta charset="utf-8"><style>body{margin:0}svg{display:block}pre{display:none}</style>'
                                +source.read_text()+'<pre id="checks"></pre>'+script)
                command = [str(args.browser), "--headless", "--disable-background-networking",
                           "--disable-extensions", "--no-first-run", "--no-default-browser-check",
                           "--hide-scrollbars", "--force-device-scale-factor=1",
                           "--user-data-dir="+str(Path(temporary)/name), "--window-size=1160,"+str(height+100),
                           "--virtual-time-budget=1200", "--dump-dom",
                           "--screenshot="+str(folder/(name+".png")), page.as_uri()]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                entry = {"command": command, "pid": process.pid}
                record["browser_runs"].append(entry)
                try:
                    stdout, stderr = process.communicate(timeout=40)
                except subprocess.TimeoutExpired:
                    record["intentional_stop_requests"].append(f"Stop owned diagram browser PID {process.pid}: 40-second timeout")
                    process.kill()
                    stdout, stderr = process.communicate()
                    entry["timeout_s"] = 40
                entry["exit_code"] = process.returncode
                (folder/(name+".stderr.txt")).write_text(stderr)
                (folder/(name+".dom.html")).write_text(stdout)
                if process.returncode or entry.get("timeout_s"):
                    raise RuntimeError("Diagram browser failed; inspect retained stderr")
                match = re.search(r'<pre id="checks"[^>]*>(.*?)</pre>', stdout, re.S)
                if not match:
                    raise ValueError("Missing SVG text-bound check")
                result = json.loads(html.unescape(match.group(1)))
                results.append({"diagram": name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), **result})
        report = {"schema": "yam-f1-diagram-review/1", "physical_specimens_tested": 0, "diagrams": results,
                  "passed_canvas_bounds": all(row["passed"] for row in results),
                  "limits": ["Canvas-bound checks do not prove internal label spacing; inspect the rendered images."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))
        if not report["passed_canvas_bounds"]:
            raise ValueError("Diagram text extends beyond its canvas")


if __name__ == "__main__":
    main()
