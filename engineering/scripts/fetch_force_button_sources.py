#!/usr/bin/python3
"""Cache selected public Honeywell documentation and discover its public CAD links."""

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

CATALOG = "https://automation.honeywell.com/us/en/products/sensing-solutions/sensors/force-sensors/fma-series-microforce-sensor"
DATASHEET = "https://prod-edam.honeywell.com/content/dam/honeywell-edam/sps/siot/fr-ca/products/sensors/force-sensors/microforce-fma-series/documents/hon-ia-hss-force-fma-series-datasheet-32347833-ciid-181799.pdf"
HOSTS = {"automation.honeywell.com", "prod-edam.honeywell.com"}


def fetch(url, maximum):
    if urlsplit(url).hostname not in HOSTS or urlsplit(url).scheme != "https":
        raise ValueError("Use the selected manufacturer's public hosts")
    with urlopen(Request(url, headers={"User-Agent": "yam-force-button-document-review"}), timeout=25) as response:
        if urlsplit(response.url).hostname not in HOSTS or urlsplit(response.url).scheme != "https":
            raise ValueError("Unexpected document redirect")
        data = response.read(maximum+1)
        final = response.url
    if len(data) > maximum:
        raise ValueError("Document exceeds the scoped download size")
    return data, final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", default=[])
    args = parser.parse_args()
    folder = ROOT / "build/engineering/prototypes/force_button/sources" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Read public manufacturer force-sensor documents and CAD-link metadata; no account access, ordering or execution of downloaded content") as record:
        folder.mkdir(parents=True, exist_ok=False)
        requests = args.url or [CATALOG, DATASHEET]
        documents, discovered = [], set()
        for index, url in enumerate(requests):
            data, final = fetch(url, 16*1024*1024)
            suffix = ".pdf" if data.startswith(b"%PDF") else ".zip" if data.startswith(b"PK") else ".html"
            path = folder / (f"document_{index}"+suffix)
            path.write_bytes(data)
            documents.append({"url": url, "final_url": final, "file": path.name, "bytes": len(data),
                              "sha256": hashlib.sha256(data).hexdigest()})
            if suffix == ".html":
                text = html.unescape(data.decode("utf-8").replace("\\/", "/"))
                for value in re.findall(r'(?:https://prod-edam\.honeywell\.com)?/content/dam/[^"<>\\\s]+', text):
                    value = value.rstrip(",;")
                    if re.search(r"\.(?:pdf|zip)(?:\?|$)", value, flags=re.I):
                        discovered.add(value if value.startswith("https://") else "https://prod-edam.honeywell.com"+value)
        report = {"documents": documents, "public_asset_links": sorted(discovered),
                  "scope": "Working reference cache; publish links and derived designs, not full copyrighted documents"}
        (folder / "collection.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
