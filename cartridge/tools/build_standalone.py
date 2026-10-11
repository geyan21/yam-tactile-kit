"""
Package web/ as a standalone page that can be hosted anywhere (it is what the published preview
page is built from):

  <out>/index.html   page content without the html/head/body wrapper (hosts add their own)
  <out>/assets/      style.css, viewer.js, app.js, data.js, data_enpire.js, data_enpire_tip.js, fonts/
  <out>/img/         the renders and section images the page shows

Download links point at the files on GitHub (branch from export_web.py), because sandboxed hosts
block direct downloads.

Usage (from cartridge/): python3 tools/build_standalone.py [out_dir]     default build/standalone
"""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # cartridge/
WEB = os.path.join(ROOT, "web")
sys.path.insert(0, os.path.join(ROOT, "cad"))


def main(out):
    # REPO / BRANCH live in export_web.py; read them without importing CadQuery
    src = open(os.path.join(ROOT, "cad", "export_web.py")).read()
    repo = re.search(r'^REPO = "([^"]+)"', src, re.M).group(1)
    branch = re.search(r'^BRANCH = "([^"]+)"', src, re.M).group(1)
    blob = f"https://github.com/{repo}/blob/{branch}/cartridge/out/"

    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "assets", "fonts"))
    html = open(os.path.join(WEB, "index.html")).read()

    drop = (r"<!doctype html>", r'<html lang="en">', r"</html>", r"<head>", r"</head>", r"<body>", r"</body>",
            r'<meta charset="utf-8">', r'<meta name="viewport"[^>]*>', r'<meta name="theme-color"[^>]*>',
            r'<meta name="description"[^>]*>')
    for pat in drop:
        html = re.sub(r"^\s*" + pat + r"\s*\n", "", html, flags=re.M | re.I)

    for name in ("style.css", "data.js", "viewer.js", "app.js"):
        html = html.replace(f'"{name}"', f'"assets/{name}"')
        shutil.copy(os.path.join(WEB, name), os.path.join(out, "assets", name))
    # loaded by app.js on demand, from next to data.js
    for name in ("data_enpire.js", "data_enpire_tip.js"):
        shutil.copy(os.path.join(WEB, name), os.path.join(out, "assets", name))
    html = html.replace('href="fonts/', 'href="assets/fonts/')
    for f in os.listdir(os.path.join(WEB, "fonts")):
        shutil.copy(os.path.join(WEB, "fonts", f), os.path.join(out, "assets", "fonts", f))

    # downloads -> GitHub (no download attribute: sandboxed hosts block page-started downloads)
    html = re.sub(r'href="\.\./out/([^"]+)" download', lambda m: f'href="{blob}{m.group(1)}"', html)
    images = set()

    def img(m):
        images.add(m.group(2))
        return f'{m.group(1)}="img/{m.group(2)}"'
    html = re.sub(r'(src|data-fallback(?:-[a-z]+)*)="\.\./out/([^"]+)"', img, html)
    if "../out/" in html:
        raise SystemExit("unconverted ../out/ reference left in the page")
    for rel in sorted(images):
        dst = os.path.join(out, "img", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(os.path.join(ROOT, "out", rel), dst)
    open(os.path.join(out, "index.html"), "w").write(html)
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(out) for f in fs)
    print(f"standalone page in {out}: {len(images)} images, {size / 1048576:.1f} MB")


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "standalone")))
