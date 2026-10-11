#!/usr/bin/python3
"""Cache the selected official connector STEP for mating-geometry review."""

from datetime import datetime, timezone
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

URL = "https://www.hirose.com/en/product/p/CL0528-0030-8-98/documents?path=%2Fapi%2Fv1%2Fproducts%2FCL0528-0030-8-98%2Fdocuments%2Fmodel_3d_step%2Fcontent"
RESOLVED_URL = "https://www.hirose.com/en/product/p/CL0528-0030-8-98/documents?path=/api/v1/products/CL0528-0030-8-98/documents/model_3d_step/content"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolved-public-link", action="store_true",
                        help="Use the public site's unescaped path form and product-page Referer")
    args = parser.parse_args()
    url = RESOLVED_URL if args.resolved_public_link else URL
    folder = ROOT / "build/engineering/prototypes/f1/connector_sources" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Read the official FH12 six-position STEP archive to verify the mating plane and carrier clearances; do not execute or redistribute vendor source") as record:
        folder.mkdir(parents=True, exist_ok=False)
        headers = {"User-Agent": "yam-f1-connector-geometry-review"}
        if args.resolved_public_link:
            headers["Referer"] = "https://www.hirose.com/en/product/p/CL0528-0030-8-98"
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            final = urlsplit(response.url)
            if final.scheme != "https" or final.hostname != "www.hirose.com":
                raise ValueError("Unexpected connector-source redirect")
            data = response.read(10*1024*1024+1)
            final_url = response.url
        if len(data) > 10*1024*1024 or not data.startswith(b"PK"):
            raise ValueError("Expected the bounded official STEP ZIP")
        (folder / "vendor_archive.zip").write_bytes(data)
        files = []
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > 100 or sum(p.file_size for p in archive.infolist()) > 32*1024*1024:
                raise ValueError("Unexpected connector archive size")
            for member in archive.infolist():
                path = PurePosixPath(member.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Unexpected archive member path")
                if member.is_dir() or path.suffix.lower() not in (".step", ".stp"):
                    continue
                content = archive.read(member)
                if not content.lstrip().startswith(b"ISO-10303-21"):
                    raise ValueError("Unexpected STEP header")
                target = folder / Path(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                files.append({"path": str(target.relative_to(ROOT)), "sha256": hashlib.sha256(content).hexdigest(),
                              "bytes": len(content)})
        if not files:
            raise ValueError("Archive contains no STEP geometry")
        receipt = {"url": url, "final_url": final_url,
                   "archive_sha256": hashlib.sha256(data).hexdigest(), "files": files,
                   "physical_evidence": False,
                   "note": "Working source cache. Publish manufacturer links, dimensions and the kit's own integration geometry."}
        (folder / "collection.json").write_text(json.dumps(receipt, indent=2)+"\n")
        record["collection"] = receipt
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
