#!/usr/bin/python3
"""Render the P1 wiring and pin-one card locally, checking SVG text bounds."""

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
    parser.add_argument("--integration", type=Path, required=True)
    args = parser.parse_args()
    integration = args.integration.resolve()
    if not integration.is_relative_to(ROOT/"build") or not args.browser.is_file():
        parser.error("Use this checkout's integration review and an explicit browser")
    sources = [ROOT/"engineering/web/p1_wiring.svg", integration/"p1_pcb_orientation.svg"]
    folder = ROOT/"build/engineering/prototypes/pneumatic/diagram_reviews"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Render two repository-owned P1 diagrams in temporary local browser profiles and check canvas bounds; save images for manual layout review") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        results, runs = [], []
        record["browser_runs"] = runs
        with tempfile.TemporaryDirectory(prefix="p1-diagram-") as temporary:
            for source in sources:
                _, _, width, height = map(float, ET.parse(source).getroot().attrib["viewBox"].split())
                page = folder/(source.stem+".html")
                script = """<script>addEventListener('load',()=>{const s=document.querySelector('svg'),v=s.viewBox.baseVal;
const outside=[...s.querySelectorAll('text')].filter(t=>{const b=t.getBBox();return b.x<0||b.y<0||b.x+b.width>v.width||b.y+b.height>v.height;}).map(t=>t.textContent);
document.querySelector('pre').textContent=JSON.stringify({passed:outside.length===0,outside});});</script>"""
                page.write_text('<!doctype html><meta charset="utf-8"><style>body{margin:0}svg{display:block}pre{display:none}</style>'
                                +source.read_text()+'<pre id="checks"></pre>'+script)
                command = [str(args.browser), "--headless", "--disable-background-networking", "--disable-extensions",
                           "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
                           "--force-device-scale-factor=1", "--user-data-dir="+str(Path(temporary)/source.stem),
                           f"--window-size={int(width)},{int(height)+100}", "--virtual-time-budget=1200", "--dump-dom",
                           "--screenshot="+str(folder/(source.stem+".png")), page.as_uri()]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                entry = {"command": command, "pid": process.pid}
                runs.append(entry)
                try:
                    stdout, stderr = process.communicate(timeout=40)
                except subprocess.TimeoutExpired:
                    record["intentional_stop_requests"].append(f"Stop owned P1 browser {process.pid}: 40-second timeout")
                    process.kill()
                    stdout, stderr = process.communicate()
                    entry["timeout_s"] = 40
                entry["returncode"] = process.returncode
                (folder/(source.stem+".stderr.txt")).write_text(stderr)
                (folder/(source.stem+".dom.html")).write_text(stdout)
                if process.returncode or entry.get("timeout_s"):
                    raise RuntimeError("P1 diagram browser failed; retained logs identify the command")
                match = re.search(r'<pre id="checks"[^>]*>(.*?)</pre>', stdout, re.S)
                if not match:
                    raise ValueError("Missing browser SVG-bound result")
                verdict = json.loads(html.unescape(match.group(1)))
                results.append({"source": str(source.relative_to(ROOT)), "source_sha256": digest(source), **verdict})
        report = {"schema": "yam-p1-diagram-review/1", "physical_specimens_tested": 0, "diagrams": results,
                  "passed_canvas_bounds": all(row["passed"] for row in results),
                  "limits": ["Check the retained images for internal spacing; canvas bounds alone do not establish readability."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))
        if not report["passed_canvas_bounds"]:
            raise ValueError("P1 diagram text exceeds its canvas")


if __name__ == "__main__":
    main()
