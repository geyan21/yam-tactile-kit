#!/usr/bin/python3
"""Render O1's two wiring/placement cards and check their SVG text bounds."""

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--visuals", type=Path, required=True)
    args = parser.parse_args()
    source = args.visuals.resolve()
    if not source.is_relative_to(ROOT/"build") or not args.browser.is_file():
        parser.error("Use generated O1 visuals and an explicit installed browser")
    folder = ROOT/"build/engineering/prototypes/optical/diagram_reviews"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Render O1's two local wiring/placement cards in fresh browser profiles; preserve canvas checks and images for visual review") as record:
        folder.mkdir(parents=True)
        results = []
        with tempfile.TemporaryDirectory(prefix="o1-diagram-") as temporary:
            for name in ("o1_wiring", "o1_led_assembly"):
                path = source/(name+".svg")
                _, _, width, height = map(float, ET.parse(path).getroot().attrib["viewBox"].split())
                page = folder/(name+".html")
                script = """<script>addEventListener('load',()=>{const s=document.querySelector('svg'),v=s.viewBox.baseVal;
const outside=[...s.querySelectorAll('text')].filter(t=>{const b=t.getBBox();return b.x<0||b.y<0||b.x+b.width>v.width||b.y+b.height>v.height;}).map(t=>t.textContent);
document.querySelector('pre').textContent=JSON.stringify({passed:outside.length===0,outside});});</script>"""
                page.write_text('<!doctype html><meta charset="utf-8"><style>body{margin:0}svg{display:block}pre{display:none}</style>'
                                +path.read_text()+'<pre id="checks"></pre>'+script)
                command = [str(args.browser), "--headless", "--disable-background-networking", "--disable-extensions",
                           "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--force-device-scale-factor=1",
                           "--user-data-dir="+str(Path(temporary)/name), f"--window-size={int(width)},{int(height)+90}",
                           "--virtual-time-budget=1200", "--dump-dom", "--screenshot="+str(folder/(name+".png")), page.as_uri()]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                entry = {"argv": command, "pid": process.pid}; record.setdefault("browser_runs", []).append(entry)
                try:
                    stdout, stderr = process.communicate(timeout=40)
                except subprocess.TimeoutExpired:
                    entry["intentional_stop"] = "40 second limit on this owned local browser"
                    process.kill(); stdout, stderr = process.communicate()
                entry["returncode"] = process.returncode
                (folder/(name+".stderr.txt")).write_text(stderr); (folder/(name+".dom.html")).write_text(stdout)
                if process.returncode or entry.get("intentional_stop"):
                    raise RuntimeError("Diagram browser failed; retained logs identify the command")
                match = re.search(r'<pre id="checks"[^>]*>(.*?)</pre>', stdout, re.S)
                if not match:
                    raise ValueError("Missing SVG text-bound result")
                verdict = json.loads(html.unescape(match.group(1)))
                results.append({"source": str(path.relative_to(ROOT)), "source_sha256": digest(path), **verdict})
        report = {"schema": "yam-o1-diagram-review/1", "physical_specimens_tested": 0, "diagrams": results,
                  "passed_canvas_bounds": all(row["passed"] for row in results),
                  "limits": ["Canvas bounds do not establish internal readability; inspect the saved images."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))
        if not report["passed_canvas_bounds"]:
            raise ValueError("Diagram text exceeds its canvas")


if __name__ == "__main__":
    main()
