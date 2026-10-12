#!/usr/bin/python3
"""Read public compact-camera references before finalizing the O1 mounting space."""

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
    "waveshare_zero_product": "https://www.waveshare.com/rpi-zero-v1.3-camera.htm",
    "arducam_spy_catalog": "https://www.arducam.com/catalogsearch/result/?q=spy",
    "spy_120_bing_locator": "https://www.bing.com/search?q=%22Raspberry+Pi+Zero+Spy+Camera%22+120",
}


def main():
    folder = ROOT/"build/engineering/prototypes/optical/mini_camera_sources"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Read bounded public manufacturer pages and a product-name locator for the paper's compact camera; do not assume an unverified ordering code or field of view") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        sources, errors = [], []
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [(name, pool.submit(fetch, name, url, folder)) for name, url in SOURCES.items()]
            for name, job in jobs:
                try:
                    sources.append(job.result())
                except Exception as error:
                    errors.append({"name": name, "error": str(error)})
        receipt = {"sources": sources, "errors": errors,
                   "scope": "Local product identification. Search results locate sources; only manufacturer documents or the paper may support technical selections."}
        (folder/"receipt.json").write_text(json.dumps(receipt, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **receipt}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
