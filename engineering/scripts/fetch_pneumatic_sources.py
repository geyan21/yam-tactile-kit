#!/usr/bin/python3
"""Preserve the selected public pneumatic manufacturer document for local review."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def main():
    config = ROOT / "engineering/research/pneumatic_source_review.json"
    review = json.loads(config.read_text())
    url = review["manufacturer"]["url"]
    folder = ROOT / "build/engineering/prototypes/pneumatic/sources" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Download one public manufacturer PDF named in the pneumatic source review; preserve URL, bytes and checksum without browser/login workarounds") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        with urlopen(Request(url, headers={"User-Agent": "yam-tactile-kit-research/1.0"}), timeout=30) as response:
            data = response.read(16*1024*1024+1)
            content_type = response.headers.get("Content-Type")
            final_url = response.url
        if len(data) > 16*1024*1024 or not data.startswith(b"%PDF"):
            raise ValueError("Expected a PDF no larger than 16 MiB")
        path = folder / "all_sensors_DS-0375_rev_C.pdf"
        path.write_bytes(data)
        receipt = {"source_url": url, "resolved_url": final_url, "content_type": content_type,
                   "file": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                   "review_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
                   "scope": "Local source review. Do not republish the complete proprietary document as kit artwork."}
        (folder / "receipt.json").write_text(json.dumps(receipt, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **receipt}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
