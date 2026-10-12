#!/usr/bin/python3
"""Read official optical-gel/coating and blue-LED references for the O1 BOM."""

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
    "solaris": "https://www.smooth-on.com/products/solaris/",
    "psycho_paint": "https://www.smooth-on.com/products/psycho-paint/",
    "silc_pig": "https://www.smooth-on.com/products/silc-pig/",
    "blue_led": "https://www.kingbrightusa.com/images/catalog/SPEC/APT2012QBC-D.pdf",
}


def main():
    folder = ROOT/"build/engineering/prototypes/optical/material_sources"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Read only the named official material/LED references before selecting an O1 construction recipe; preserve incomplete lookups without inventing specifications") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        sources, errors = [], []
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = [(name, pool.submit(fetch, name, url, folder)) for name, url in SOURCES.items()]
            for name, job in jobs:
                try:
                    sources.append(job.result())
                except Exception as error:
                    errors.append({"name": name, "error": str(error)})
        report = {"sources": sources, "errors": errors,
                  "scope": "Primary reference collection, not qualification of the proposed tactile gel or coating."}
        (folder/"receipt.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
