#!/usr/bin/python3
"""Cache selected public F1 manufacturer PDFs and the KiCad library license."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

DOCUMENTS = {
    "hirose_catalog_public_copy": "https://datasheet.lcsc.com/datasheet/pdf/b87be22e0cecc59ab77d96f3dce601d5.pdf?productCode=C597994",
    "hirose_drawing": "https://www.hirose.com/en/product/p/CL0528-0030-8-98/documents?path=%2Fapi%2Fv1%2Fproducts%2FCL0528-0030-8-98%2Fdocuments%2Fdrawing_2d%2Fcontent%3Flang%3DEN",
    "hirose_specification": "https://www.hirose.com/en/product/p/CL0528-0030-8-98/documents?path=%2Fapi%2Fv1%2Fproducts%2FCL0528-0030-8-98%2Fdocuments%2Fspec_sheet%2Fcontent%3Flang%3DEN",
    "opa392": "https://www.ti.com/lit/ds/symlink/opa2392.pdf",
    "adg706": "https://www.analog.com/media/en/technical-documentation/data-sheets/adg706_707.pdf",
    "mcp3208": "https://ww1.microchip.com/downloads/aemDocuments/documents/APID/ProductDocuments/DataSheets/21298e.pdf",
    "ads8866": "https://www.ti.com/lit/ds/symlink/ads8866.pdf",
    "opa320": "https://www.ti.com/lit/ds/symlink/opa320.pdf",
    "opa320_q1": "https://www.ti.com/lit/ds/symlink/opa320-q1.pdf",
    "ref60": "https://www.ti.com/lit/ds/symlink/ref60.pdf",
    "tmux1134": "https://www.ti.com/lit/ds/symlink/tmux1134.pdf",
    "tmux1112": "https://www.ti.com/lit/ds/symlink/tmux1112.pdf",
    "tmux1101": "https://www.ti.com/lit/ds/symlink/tmux1101.pdf",
    "molex_15166_spec": "https://www.molex.com/content/dam/molex/molex-dot-com/products/automated/en-us/productspecificationpdf/151/15166/PS-15166-001-001.pdf",
    "molex_15166_drawing": "https://www.molex.com/content/dam/molex/molex-dot-com/products/automated/en-us/salesdrawingpdf/151/15166/151660160_sd.pdf",
    "kicad_library_license": "https://raw.githubusercontent.com/KiCad/kicad-footprints/master/LICENSE.md",
}
ALLOWED = {urlsplit(url).hostname for url in DOCUMENTS.values()}


def fetch(name, folder):
    url = DOCUMENTS[name]
    request = Request(url, headers={"User-Agent": "yam-f1-manufacturer-document-review"})
    with urlopen(request, timeout=30) as response:
        final = response.url
        if urlsplit(final).scheme != "https" or urlsplit(final).hostname not in ALLOWED:
            raise ValueError("Manufacturer document redirected outside the selected source hosts")
        content = response.read(16 * 1024 * 1024 + 1)
    is_license = name == "kicad_library_license"
    valid = (b"CC-BY-SA" in content and b"KiCad" in content and len(content) < 20000) if is_license else content.startswith(b"%PDF")
    if len(content) > 16 * 1024 * 1024 or not valid:
        raise ValueError("Expected the selected bounded PDF or KiCad library license text")
    if is_license:
        content.decode("utf-8")
    path = folder / (name + (".md" if is_license else ".pdf"))
    path.write_bytes(content)
    return {"name": name, "url": url, "final_url": final,
            "path": str(path.relative_to(ROOT)), "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="+", choices=sorted(DOCUMENTS))
    args = parser.parse_args()
    folder = ROOT / "build/engineering/prototypes/f1/sources" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Read selected public F1 connector, amplifier, multiplexer and ADC PDFs; cache exact revisions for dimensional/electrical review") as record:
        folder.mkdir(parents=True, exist_ok=False)
        results = []; failures = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {name: pool.submit(fetch, name, folder) for name in dict.fromkeys(args.names)}
            for name, future in futures.items():
                try:
                    results.append(future.result())
                except Exception as error:
                    failures[name] = type(error).__name__ + ": " + str(error)
        receipt = {"documents": results, "failures": failures,
                   "note": "Working cache: publish manufacturer links and the kit's own design, not complete datasheets. The KiCad license is retained with redistributed footprint libraries."}
        (folder / "collection.json").write_text(json.dumps(receipt, indent=2) + "\n")
        record["collection"] = receipt
        print(json.dumps(receipt, indent=2))
        if failures:
            raise RuntimeError("Some selected manufacturer documents were not retrieved")


if __name__ == "__main__":
    main()
