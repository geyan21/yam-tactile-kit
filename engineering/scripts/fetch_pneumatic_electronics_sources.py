#!/usr/bin/python3
"""Fetch four public primary documents for the P1 readout, with bounded receipts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution

SOURCES = {
    "tca9548a": "https://www.ti.com/lit/ds/symlink/tca9548a.pdf",
    "lp5907": "https://www.ti.com/lit/ds/symlink/lp5907.pdf",
    "ads1115": "https://www.ti.com/lit/ds/symlink/ads1115.pdf",
    "pico": "https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf",
}


def fetch(item, folder):
    name, url = item
    with urlopen(Request(url, headers={"User-Agent": "yam-tactile-kit-research/1.0"}), timeout=30) as response:
        data = response.read(20*1024*1024+1)
        resolved = response.url
    if len(data) > 20*1024*1024 or not data.startswith(b"%PDF"):
        raise ValueError("Expected a bounded PDF: "+name)
    path = folder/(name+".pdf")
    path.write_bytes(data)
    command = ["/usr/bin/pdftotext", "-layout", str(path), str(folder/(name+".txt"))]
    result = subprocess.run(command, check=True, capture_output=True, timeout=30)
    return {"name": name, "url": url, "resolved_url": resolved, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "text_command": command,
            "text_returncode": result.returncode}


def main():
    folder = ROOT/"build/engineering/prototypes/pneumatic/electronics_sources"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Read four named public manufacturer documents for the P1 readout; save source hashes and local text for pin/power review") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(fetch, item, folder) for item in SOURCES.items()]
            results, errors = [], []
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as error:
                    errors.append(str(error))
        receipt = {"sources": results, "errors": errors, "physical_boards_tested": 0,
                   "scope": "Local primary-document review; the full PDFs are not kit artwork."}
        (folder/"receipt.json").write_text(json.dumps(receipt, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **receipt}
        print(json.dumps(record["result"], indent=2))
        if errors:
            raise ValueError("Some source downloads failed; successful results are preserved")


if __name__ == "__main__":
    main()
