"""Deterministic downloadable handoff packages with no self-nesting archives."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile


SELF_ARCHIVES = {"downloads/yam-tactile-complete.zip", "downloads/yam-tactile-site.zip"}


def write_zip(path: Path, prefix: str, files: dict[str, bytes]):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            item = zipfile.ZipInfo(prefix + name, date_time=(2026, 10, 10, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, data)


def file_map(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*")) if path.is_file()
    }


def standalone_guide(html: str, css: str, diagram: bytes, public_base: str) -> str:
    html = html.replace('<link rel="stylesheet" href="assets/style.css">', f"<style>{css}</style>")
    html = html.replace('<script src="assets/data.js" defer></script>', "")
    html = html.replace('<script src="assets/app.js" defer></script>', "")
    image = "data:image/svg+xml;base64," + base64.b64encode(diagram).decode("ascii")
    html = html.replace('src="assets/original-concept.svg"', f'src="{image}"')
    html = html.replace('href="guide.html#', 'href="#')
    html = html.replace('href="index.html', f'href="{public_base}index.html')
    html = html.replace('href="downloads/', f'href="{public_base}downloads/')
    return html


def make_packages(root: Path, output: Path, site: Path, design_files: dict[str, bytes], public_base: str) -> dict:
    downloads = site / "downloads"
    design_archive = downloads / "yam-tactile-designs.zip"
    write_zip(design_archive, "yam-tactile-designs/", design_files)
    docs = {
        "markdown/" + name: data for name, data in file_map(root / "docs").items()
    }
    docs["guide.html"] = standalone_guide(
        (site / "guide.html").read_text(encoding="utf-8"),
        (site / "assets/style.css").read_text(encoding="utf-8"),
        (site / "assets/original-concept.svg").read_bytes(),
        public_base,
    ).encode("utf-8")
    docs["README.txt"] = b"Open guide.html to read/print the complete documentation offline. Markdown sources are in markdown/.\n"
    docs_archive = downloads / "yam-tactile-docs.zip"
    write_zip(docs_archive, "yam-tactile-documentation/", docs)

    # These two archives are intentionally excluded from every website snapshot:
    # neither an offline website nor a complete kit can contain its own ZIP.
    website = {name: data for name, data in file_map(site).items() if name not in SELF_ARCHIVES}
    site_archive = output / "yam-tactile-site.zip"
    write_zip(site_archive, "yam-tactile-site/", website)

    complete = {"website/" + name: data for name, data in website.items()}
    complete.update({"design/" + name: data for name, data in design_files.items()})
    complete.update({"documentation/" + name: data for name, data in docs.items()})
    with zipfile.ZipFile(io.BytesIO((downloads / "yam-tactile-kit.zip").read_bytes())) as source:
        for name in source.namelist():
            if not name.startswith("yam-tactile-kit/") or ".." in Path(name).parts:
                raise ValueError("Unexpected path in source package")
            complete["source/" + name.removeprefix("yam-tactile-kit/")] = source.read(name)
    complete["README_FIRST.md"] = (
        "# YAM Tactile Kit — complete handoff\n\n"
        "1. Open `website/index.html` for all visualizations and instructions.\n"
        "2. Open `documentation/guide.html` for the printable offline guide.\n"
        "3. Inspect `design/README.md` before using any CAD or mesh file.\n"
        "4. From `source/`, run `/usr/bin/python3 scripts/reproduce.py` to rebuild everything.\n\n"
        "The design files are conceptual component envelopes, not fabrication-ready parts. "
        "The calibration example is synthetic. Actual hardware qualification remains outstanding.\n\n"
        "The website works offline. Links that download the complete/offline ZIP again point "
        "to the public website; those ZIPs cannot recursively include themselves. All underlying "
        "source, design, and documentation files are already present in this handoff.\n"
    ).encode("utf-8")
    manifest = {
        "scope": "Complete handoff files; this manifest does not hash itself.",
        "hardware_validated": False,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(complete.items())},
    }
    complete["HANDOFF_MANIFEST.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    complete_archive = output / "yam-tactile-complete.zip"
    write_zip(complete_archive, "yam-tactile-complete/", complete)
    (downloads / site_archive.name).write_bytes(site_archive.read_bytes())
    (downloads / complete_archive.name).write_bytes(complete_archive.read_bytes())
    return {
        "site_archive_sha256": hashlib.sha256(site_archive.read_bytes()).hexdigest(),
        "complete_archive_sha256": hashlib.sha256(complete_archive.read_bytes()).hexdigest(),
        "design_archive_sha256": hashlib.sha256(design_archive.read_bytes()).hexdigest(),
        "docs_archive_sha256": hashlib.sha256(docs_archive.read_bytes()).hexdigest(),
    }
