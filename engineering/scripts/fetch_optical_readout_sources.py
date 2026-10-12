#!/usr/bin/python3
"""Read primary references for O1's external host/ADC and gel adhesive."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from fetch_optical_camera_sources import fetch

SOURCES = {
    "pi4_brief": "https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-product-brief.pdf",
    "ads1115": "https://www.ti.com/lit/ds/symlink/ads1115.pdf",
    "adafruit1085": "https://www.adafruit.com/product/1085",
    "sil_poxy": "https://www.smooth-on.com/products/sil-poxy/",
}


def main():
    folder = ROOT/"build/engineering/prototypes/optical/readout_sources"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Read four named manufacturer references for the local O1 host, ADC and silicone bond; retain failed requests and exact source hashes") as record:
        folder.mkdir(parents=True)
        sources, errors = [], []
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = [(name, pool.submit(fetch, name, url, folder)) for name, url in SOURCES.items()]
            for name, job in jobs:
                try:
                    sources.append(job.result())
                except Exception as error:
                    errors.append({"name": name, "error": str(error)})
        report = {"sources": sources, "errors": errors,
                  "scope": "Primary component facts only; actual O1 assembly, optics and force response remain unqualified."}
        (folder/"receipt.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
