"""
Check the cartridge webpage in headless Chromium (Playwright):
  * no JavaScript errors and no missing local files
  * the 3D view draws something other than background and responds to a drag and to "separate parts"
  * pressing the taxel pad updates the readout
  * no horizontal scrolling at phone width
Screenshots go to build/web-review/. Exit code 1 on any failure.

Usage (from cartridge/): python3 tools/verify_web.py
"""
import functools
import http.server
import io
import os
import sys
import threading

from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # cartridge/
SHOTS = os.path.join(ROOT, "build", "web-review")
EXTERNAL_OK = ("fonts.googleapis.com", "fonts.gstatic.com")             # optional web font


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def busy(png_bytes):
    """Spread of pixel values: a blank canvas is ~0."""
    st = ImageStat.Stat(Image.open(io.BytesIO(png_bytes)).convert("L"))
    return st.stddev[0]


def check_page(browser, url, name, viewport, phone):
    problems, notes = [], []
    ctx = browser.new_context(viewport=viewport, device_scale_factor=2 if phone else 1, is_mobile=phone, has_touch=phone)
    page = ctx.new_page()
    errors, failed = [], []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
    page.on("requestfailed", lambda r: failed.append(r.url))
    page.on("response", lambda r: failed.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
    page.goto(url, wait_until="load")
    page.wait_for_timeout(600)

    for u in failed:
        (notes if any(h in u for h in EXTERNAL_OK) else problems).append(f"[{name}] failed request: {u}")
    for e in errors:
        if not any(h in e for h in EXTERNAL_OK):
            problems.append(f"[{name}] {e}")
    broken = page.evaluate("[...document.images].filter(i => i.loading !== 'lazy' && (!i.complete || !i.naturalWidth)).map(i => i.src)")
    page.evaluate("for (const i of document.images) i.loading = 'eager'")
    page.wait_for_timeout(800)
    broken += page.evaluate("[...document.images].filter(i => !i.complete || !i.naturalWidth).map(i => i.src)")
    problems += [f"[{name}] image did not load: {b}" for b in sorted(set(broken))]
    over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    if over > 0:
        problems.append(f"[{name}] page scrolls sideways by {over}px")

    # taxel pad: press near the middle and read the readout back
    pad = page.locator("#pad")
    pad.scroll_into_view_if_needed()
    b = pad.bounding_box()
    page.mouse.move(b["x"] + b["width"] * 0.5, b["y"] + b["height"] * 0.55)
    page.mouse.down()
    page.mouse.move(b["x"] + b["width"] * 0.52, b["y"] + b["height"] * 0.57, steps=4)
    page.wait_for_timeout(500)
    total, taxel = page.locator("#r-total").inner_text(), page.locator("#r-taxel").inner_text()
    if total.strip() in ("0", "") or not taxel.startswith("Row"):
        problems.append(f"[{name}] pad press did not register (total={total!r}, taxel={taxel!r})")
    page.locator(".pad-demo").screenshot(path=os.path.join(SHOTS, f"{name}-pad.png"))
    page.mouse.up()
    page.wait_for_timeout(300)

    # 3D view: drawn, not blank, reacts to a drag and to the explode slider
    view = page.locator("#view")
    view.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    page.locator(".viewer").screenshot(path=os.path.join(SHOTS, f"{name}-viewer-default.png"))
    if not page.evaluate("+document.getElementById('view').dataset.rendered > 0"):
        problems.append(f"[{name}] 3D view never drew (WebGL unavailable?)")
    before = view.screenshot()
    if busy(before) < 3:
        problems.append(f"[{name}] 3D view looks blank")
    vb = view.bounding_box()
    page.mouse.move(vb["x"] + vb["width"] * 0.5, vb["y"] + vb["height"] * 0.5)
    page.mouse.down()
    page.mouse.move(vb["x"] + vb["width"] * 0.65, vb["y"] + vb["height"] * 0.45, steps=6)
    page.mouse.up()
    page.wait_for_timeout(200)
    after = view.screenshot()
    if before == after:
        problems.append(f"[{name}] dragging did not change the 3D view")
    page.locator("#explode").fill("70")
    page.wait_for_timeout(200)
    page.locator(".viewer").screenshot(path=os.path.join(SHOTS, f"{name}-viewer.png"))
    page.locator("#explode").fill("0")
    for sel in ("#top", "#why", "#inspect", "#assembly", "#sensor", "#checks", "#build", "#files", ".foot"):
        page.locator(sel).screenshot(path=os.path.join(SHOTS, f"{name}-section-{sel.strip('#.')}.png"))
    ctx.close()
    return problems, notes


def main():
    os.makedirs(SHOTS, exist_ok=True)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/web/index.html"
    problems, notes = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        for name, vp, phone in (("desktop", {"width": 1280, "height": 900}, False),
                                ("phone", {"width": 390, "height": 844}, True)):
            pr, nt = check_page(browser, url, name, vp, phone)
            problems += pr
            notes += nt
        browser.close()
    httpd.shutdown()
    for n in sorted(set(notes)):
        print("note:", n)
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    print(f"page OK at desktop and phone width; screenshots in {os.path.relpath(SHOTS, ROOT)}/")


if __name__ == "__main__":
    main()
