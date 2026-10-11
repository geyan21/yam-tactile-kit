#!/usr/bin/python3
"""Check the engineering site and save desktop/mobile screenshots in an owned browser."""

import argparse
from datetime import datetime, timezone
from functools import partial
import html
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from threading import Thread

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser",type=Path,required=True)
    parser.add_argument("--checks-only",action="store_true")
    parser.add_argument("--views",nargs="+",choices=("desktop","design","build","mobile","root","guide","l1-assembly","l1-bench","contact","b1-assembly","b1-guide","sensors","sensor-map","architecture","b2-concept","c1-concept","magnetic-scaling","magnetic-gap","design-directory","r1-page","b1-page","b2-page","c1-page","nail-page","design-mobile","b2-assembly","b2-guide","b2-wiring","build-all","c1-assembly","c1-wiring","c1-gauges","c1-guide","c1-analysis","nail-assembly","nail-wiring","nail-gauges","nail-guide","nail-analysis","nail-mobile","recessed-page","recessed-mobile","recessed-assembly","recessed-wiring","recessed-placement","recessed-guide","recessed-analysis","f1-page","f1-mobile","f1-placement","f1-guide","f1-files"),
                        help="Capture only selected views after the functional checks")
    args=parser.parse_args()
    if not args.browser.is_file():parser.error("Select an explicit browser executable")
    output=ROOT/"build/engineering/browser"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output.mkdir(parents=True,exist_ok=False)
    with execution(ROOT/"build/records","Verify actual-mesh controls, downloads, report handling, and mobile layout using only a temporary loopback website") as record:
        record["browser_runs"]=[]
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
        with tempfile.TemporaryDirectory(prefix="enpire-browser-") as temporary:
            temporary=Path(temporary);site=temporary/"site"
            shutil.copytree(ROOT/"build/site",site)
            shutil.copyfile(ROOT/"engineering/tests/browser-check.html",site/"qa.html")
            shutil.copyfile(ROOT/"engineering/tests/design-pages-check.html",site/"design-qa.html")
            (site/"mobile.html").write_text('<!doctype html><html><body style="margin:0;background:#eef2ed"><iframe src="index.html" title="390px mobile website" style="width:390px;height:2400px;border:0"></iframe></body></html>')
            (site/"design-mobile.html").write_text('<!doctype html><html><body style="margin:0;background:#eef2ed"><iframe src="b2.html" title="390px mobile design page" style="width:390px;height:2500px;border:0"></iframe></body></html>')
            (site/"nail-mobile.html").write_text('<!doctype html><html><body style="margin:0;background:#eef2ed"><iframe src="rigid-nail.html" title="390px N1 design page" style="width:390px;height:2700px;border:0"></iframe></body></html>')
            (site/"recessed-mobile.html").write_text('<!doctype html><html><body style="margin:0;background:#eef2ed"><iframe src="recessed-magnetic.html" title="390px B3 design page" style="width:390px;height:2700px;border:0"></iframe></body></html>')
            (site/"f1-mobile.html").write_text('<!doctype html><html><body style="margin:0;background:#eef2ed"><iframe src="flexible-matrix.html" title="390px F1 design page" style="width:390px;height:3100px;border:0"></iframe></body></html>')
            index=(site/"index.html").read_text()
            for name,style in (
                ("design",".hero,.brief{display:none} #design{padding-top:25px}"),
                ("build",".hero,.brief,#design,#bending,#root-force{display:none} #build{padding-top:25px}"),
                ("root",".hero,.brief,#design,#bending{display:none} #root-force{padding-top:25px}"),
            ):
                (site/f"{name}-review.html").write_text(index.replace("</head>",f"<style>{style}</style></head>"))
            for name,model in (("l1-assembly","l1_assembly"),("l1-bench","l1_bench"),("b1-assembly","b1_assembly"),("b2-assembly","b2_assembly"),("c1-assembly","c1_assembly"),("nail-assembly","nail_assembly"),("recessed-assembly","recessed_assembly")):
                prepared=index.replace("</head>","<style>.hero,.brief{display:none} #design{padding-top:25px}</style></head>")
                script=(
                    "<script>window.addEventListener('load',()=>{"
                    "const s=document.getElementById('model-select');s.value="+json.dumps(model)+";"
                    "s.dispatchEvent(new Event('change'));});</script>"
                )
                (site/f"{name}-review.html").write_text(prepared.replace("</body>",script+"</body>"))
            server=ThreadingHTTPServer(("127.0.0.1",0),partial(Handler,directory=str(site)))
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            record["http_bind"]=f"127.0.0.1:{server.server_port}"
            base=f"http://127.0.0.1:{server.server_port}/"
            def browser(name,arguments):
                command=[str(args.browser),"--headless","--disable-background-networking","--disable-extensions",
                    "--no-first-run","--no-default-browser-check","--hide-scrollbars","--force-device-scale-factor=1",
                    f"--user-data-dir={temporary/f'profile-{name}'}",*arguments]
                process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                entry={"name":name,"command":command,"pid":process.pid};record["browser_runs"].append(entry)
                try:stdout,stderr=process.communicate(timeout=40)
                except subprocess.TimeoutExpired:
                    record["intentional_stop_requests"].append(f"Stop owned browser PID {process.pid}: timeout")
                    process.kill();process.communicate();raise RuntimeError("Browser verification timed out")
                entry.update({"exit_code":process.returncode,"stderr":stderr[-1200:]})
                if process.returncode:raise RuntimeError(f"Browser failed: {stderr[-1200:]}")
                return stdout
            try:
                document=browser("checks",["--window-size=1440,1000","--virtual-time-budget=7000","--dump-dom",base+"qa.html"])
                match=re.search(r'<pre id="qa-results"[^>]*>([\s\S]*?)</pre>',document)
                if not match:raise RuntimeError("No browser check output")
                result=json.loads(html.unescape(match.group(1)))
                (output/"checks.json").write_text(json.dumps(result,indent=2)+"\n")
                record["checks"]=result
                if not result["passed"]:raise RuntimeError(f"Browser checks failed: {result}")
                design_document=browser("design-checks",["--window-size=1440,1200","--virtual-time-budget=20000","--dump-dom",base+"design-qa.html"])
                design_match=re.search(r'<pre id="qa-results"[^>]*>([\s\S]*?)</pre>',design_document)
                if not design_match:raise RuntimeError("No design-page browser check output")
                design_result=json.loads(html.unescape(design_match.group(1)))
                (output/"design-checks.json").write_text(json.dumps(design_result,indent=2)+"\n")
                record["design_checks"]=design_result
                if not design_result["passed"]:raise RuntimeError(f"Design page checks failed: {design_result}")
                if args.checks_only:
                    print(json.dumps({"passed":True,"checks":len(result["checks"]),"design_checks":len(design_result["checks"]),"observations":design_result.get("observations")},indent=2))
                    return
                for name,size,page in (
                    ("desktop","1440,1140","index.html"),("design","1440,1100","design-review.html"),
                    ("build","1440,1100","build-review.html"),("mobile","500,1800","mobile.html"),
                    ("root","1440,1200","root-review.html"),("guide","1280,1100","l1-electronics.html"),
                    ("l1-assembly","1440,1100","l1-assembly-review.html"),("l1-bench","1440,1100","l1-bench-review.html"),
                    ("contact","1280,1250","contact.html"),
                    ("b1-assembly","1440,1100","b1-assembly-review.html"),("b1-guide","1280,1200","build-b1.html"),
                    ("sensors","1440,1600","sensors.html"),("sensor-map","1280,610","assets/sensor-placement.svg"),
                    ("architecture","1440,1450","architecture.html"),
                    ("b2-concept","1400,700","assets/concepts/b2_board_concept.svg"),
                    ("c1-concept","1400,700","assets/concepts/c1_concept.svg"),
                    ("magnetic-scaling","1400,650","assets/concepts/magnetic_scaling.svg"),
                    ("magnetic-gap","1400,650","assets/concepts/magnetic_gap.svg"),
                    ("design-directory","1440,1600","designs.html"),
                    ("r1-page","1440,1450","r1.html"),
                    ("b1-page","1440,1450","b1.html"),("b2-page","1440,1450","b2.html"),
                    ("c1-page","1440,1450","c1.html"),("nail-page","1440,1450","rigid-nail.html"),
                    ("design-mobile","500,2600","design-mobile.html"),
                    ("b2-assembly","1440,1150","b2-assembly-review.html"),
                    ("b2-guide","1280,1500","build-b2.html"),
                    ("b2-wiring","1280,850","assets/prototypes/b2/b2-wiring.svg"),
                    ("build-all","1440,1700","build-all.html"),
                    ("c1-assembly","1440,1150","c1-assembly-review.html"),
                    ("c1-wiring","1280,1000","assets/prototypes/c1/c1-wiring.svg"),
                    ("c1-gauges","1320,850","assets/prototypes/c1/c1_gauge_placement.svg"),
                    ("c1-guide","1440,1800","build-c1.html"),
                    ("c1-analysis","1440,1700","c1-analysis.html"),
                    ("nail-assembly","1440,1150","nail-assembly-review.html"),
                    ("nail-wiring","1280,1430","assets/prototypes/nail/nail-wiring.svg"),
                    ("nail-gauges","1400,700","assets/prototypes/nail/nail_gauge_placement.svg"),
                    ("nail-guide","1440,1800","build-nail.html"),
                    ("nail-analysis","1440,1700","nail-analysis.html"),
                    ("nail-mobile","500,2800","nail-mobile.html"),
                    ("recessed-page","1440,1550","recessed-magnetic.html"),
                    ("recessed-mobile","500,2800","recessed-mobile.html"),
                    ("recessed-assembly","1440,1150","recessed-assembly-review.html"),
                    ("recessed-wiring","1280,930","assets/prototypes/recessed/recessed-wiring.svg"),
                    ("recessed-placement","1400,760","assets/prototypes/recessed/recessed_placement.svg"),
                    ("recessed-guide","1440,1800","build-recessed.html"),
                    ("recessed-analysis","1440,1800","recessed-analysis.html"),
                    ("f1-page","1440,1700","flexible-matrix.html"),
                    ("f1-mobile","500,3200","f1-mobile.html"),
                    ("f1-placement","1440,1100","assets/development/f1/r3/visuals/sensor_placement.png"),
                    ("f1-guide","1440,1800","build-f1.html"),
                    ("f1-files","1440,1600","assets/development/f1/r3/file-index.html"),
                ):
                    if args.views and name not in args.views:continue
                    browser(name,[f"--window-size={size}","--virtual-time-budget=1800",f"--screenshot={output/f'{name}.png'}",base+page])
                print(json.dumps({"passed":True,"checks":len(result["checks"]),"design_checks":len(design_result["checks"]),"screenshots":str(output)},indent=2))
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)
                record["intentional_stop_requests"].append("Closed this verifier's owned loopback HTTP server")


if __name__=="__main__":
    main()
