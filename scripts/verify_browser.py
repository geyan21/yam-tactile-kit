#!/usr/bin/python3
"""Exercise the generated site with a local browser and save review screenshots."""

import argparse
from functools import partial
import html
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from threading import Thread

from _bootstrap import ROOT
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--site", type=Path, default=ROOT / "build/site")
    parser.add_argument("--output", type=Path, default=ROOT / "build/browser-review")
    args = parser.parse_args()
    if not args.browser.is_file() or not (args.site / "index.html").is_file():
        parser.error("An explicit browser executable and a built website are required")
    args.output.mkdir(parents=True, exist_ok=True)
    with execution(ROOT / "build/records", "Local browser interaction checks and desktop/mobile screenshots") as record:
        record["browser_runs"] = []
        record["http_requests"] = []

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, format, *values):
                record["http_requests"].append(format % values)

        with tempfile.TemporaryDirectory(prefix="yam-tactile-browser-") as temporary:
            temporary = Path(temporary)
            webroot = temporary / "site"
            shutil.copytree(args.site, webroot)
            shutil.copyfile(ROOT / "tests/browser-check.html", webroot / "qa.html")
            # Some desktop Chrome builds clamp top-level CSS viewports to 500 px.
            # An iframe gives a real 390 px viewport without a debugging port.
            (webroot / "mobile-review.html").write_text(
                '<!doctype html><html><head><meta charset="utf-8">'
                '<title>390 px mobile review</title></head>'
                '<body style="margin:0;background:#dce5d7;display:flex;justify-content:center">'
                '<iframe title="390 px website viewport" src="index.html" '
                'style="width:390px;height:2200px;border:0;flex-shrink:0"></iframe>'
                '</body></html>', encoding="utf-8"
            )
            # Isolate the real force component in the initial viewport. This
            # avoids compositor timing differences when CLI screenshots scroll.
            force_review = (webroot / "index.html").read_text(encoding="utf-8").replace(
                "</head>",
                "<style>.site-header,.hero,.scope-strip,#get-kit,#design,#cad{display:none!important}"
                "#force{padding-top:28px}</style></head>",
            )
            (webroot / "force-review.html").write_text(force_review, encoding="utf-8")
            cad_review = (webroot / "index.html").read_text(encoding="utf-8").replace(
                "</head>",
                "<style>.site-header,.hero,.scope-strip,#get-kit,#design{display:none!important}"
                "#cad{padding-top:28px}</style></head>",
            )
            (webroot / "cad-review.html").write_text(cad_review, encoding="utf-8")
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(webroot)))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            record["http_bind"] = f"127.0.0.1:{server.server_port}"
            base = f"http://127.0.0.1:{server.server_port}/"

            def browser(name, arguments):
                profile = temporary / f"profile-{name}"
                command = [
                    str(args.browser), "--headless", "--disable-background-networking",
                    "--disable-extensions", "--no-first-run", "--no-default-browser-check",
                    "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--user-data-dir={profile}", *arguments,
                ]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                entry = {"name": name, "command": command, "pid": process.pid}
                record["browser_runs"].append(entry)
                try:
                    stdout, stderr = process.communicate(timeout=40)
                except subprocess.TimeoutExpired:
                    record["intentional_stop_requests"].append(f"Timeout: stop owned browser process {process.pid}")
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise RuntimeError("Local browser review timed out")
                entry.update({"exit_code": process.returncode, "stderr": stderr[-2500:]})
                if process.returncode:
                    raise RuntimeError(f"Browser failed: {stderr[-1500:]}")
                return stdout

            try:
                document = browser("checks", ["--window-size=1440,1140", "--virtual-time-budget=7000", "--dump-dom", base + "qa.html"])
                match = re.search(r'<pre id="qa-results"[^>]*>([\s\S]*?)</pre>', document)
                if not match:
                    raise RuntimeError("Browser check result not found in returned document")
                result = json.loads(html.unescape(match.group(1)))
                (args.output / "checks.json").write_text(json.dumps(result, indent=2) + "\n")
                record["checks"] = result
                if not result["passed"]:
                    failed = [item["name"] for item in result["checks"] if not item["passed"]]
                    raise RuntimeError(f"Browser checks failed: {', '.join(failed)}")
                for name, size, page in (
                    ("desktop", "1440,1180", "index.html"),
                    ("cad", "1440,1180", "cad-review.html"),
                    ("force", "1440,1180", "force-review.html"),
                    ("mobile", "500,1550", "mobile-review.html"),
                    ("guide", "1280,1100", "guide.html"),
                ):
                    image = (args.output / f"{name}.png").resolve()
                    browser(name, [f"--window-size={size}", "--virtual-time-budget=1200", f"--screenshot={image}", base + page])
                    if not image.is_file():
                        raise RuntimeError(f"Screenshot missing: {name}")
                print(json.dumps({"passed": True, "checks": len(result["checks"]), "screenshots": str(args.output)}, indent=2))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                record["intentional_stop_requests"].append("Closed this verifier's owned temporary HTTP server")


if __name__ == "__main__":
    main()
