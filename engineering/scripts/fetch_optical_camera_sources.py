#!/usr/bin/python3
"""Read named official camera documents for the O1 integration."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import gzip
import io
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution

SOURCES = {
    "camera3_product": "https://www.raspberrypi.com/products/camera-module-3/",
    "camera3_brief": "https://datasheets.raspberrypi.com/camera/camera-module-3-product-brief.pdf",
    "camera3_wide_mechanical": "https://datasheets.raspberrypi.com/camera/camera-module-3-wide-mechanical-drawing.pdf",
    "picamera2_manual": "https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf",
}


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts, self.links = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "a":
            value = dict(attrs).get("href")
            if value:
                self.links.append(value)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden-1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def fetch(name, url, folder):
    with urlopen(Request(url, headers={"User-Agent": "yam-tactile-kit-research/1.0"}), timeout=30) as response:
        data = response.read(24*1024*1024+1)
        resolved = response.url
        content_encoding = response.headers.get("Content-Encoding")
    if len(data) > 24*1024*1024:
        raise ValueError("Document exceeds the review size bound")
    wire_sha256 = hashlib.sha256(data).hexdigest()
    if data.startswith(b"\x1f\x8b"):
        (folder/(name+".wire.gz")).write_bytes(data)
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            data = stream.read(24*1024*1024+1)
        if len(data) > 24*1024*1024:
            raise ValueError("Decoded document exceeds the review size bound")
    is_pdf = data.startswith(b"%PDF")
    source = folder/(name+(".pdf" if is_pdf else ".html"))
    source.write_bytes(data)
    if is_pdf:
        command = ["/usr/bin/pdftotext", "-layout", str(source), str(folder/(name+".txt"))]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=30)
        (folder/(name+".conversion.log")).write_text(stdout+stderr)
        if process.returncode:
            raise ValueError("PDF text conversion failed")
        conversion = {"command": command, "pid": process.pid, "returncode": process.returncode}
    else:
        parser = Text()
        parser.feed(data.decode("utf-8", errors="replace"))
        (folder/(name+".txt")).write_text("\n".join(parser.parts)+"\n")
        (folder/(name+".links.json")).write_text(json.dumps(sorted(set(parser.links)), indent=2)+"\n")
        conversion = None
    return {"name": name, "url": url, "resolved_url": resolved, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "file": source.name, "conversion": conversion,
            "wire_sha256": wire_sha256, "content_encoding": content_encoding}


def main():
    folder = ROOT/"build/engineering/prototypes/optical/camera_sources"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Read four named official Raspberry Pi documents to select a supported O1 camera and verify its mechanical and capture interfaces") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        sources, errors = [], []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [(name, pool.submit(fetch, name, url, folder)) for name, url in SOURCES.items()]
            for name, future in futures:
                try:
                    sources.append(future.result())
                except Exception as error:
                    errors.append({"name": name, "error": str(error)})
        receipt = {"sources": sources, "errors": errors,
                   "scope": "Local primary-source review; do not republish the complete proprietary documents as kit artwork."}
        (folder/"receipt.json").write_text(json.dumps(receipt, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **receipt}
        print(json.dumps(record["result"], indent=2))
        if errors:
            raise ValueError("Some candidate URLs failed; successful documents are preserved")


if __name__ == "__main__":
    main()
