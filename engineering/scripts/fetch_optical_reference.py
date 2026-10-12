#!/usr/bin/python3
"""Preserve the named public Baby Fin Ray paper for local optical-design review."""

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

URL = "https://arxiv.org/pdf/2303.14883v1"


def main():
    folder = ROOT/"build/engineering/prototypes/optical/reference_sources"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Download the explicitly referenced public optical-finger paper; retain primary-source text, URL and hash for local design review") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        with urlopen(Request(URL, headers={"User-Agent": "yam-tactile-kit-research/1.0"}), timeout=30) as response:
            data = response.read(32*1024*1024+1)
            resolved = response.url
        if len(data) > 32*1024*1024 or not data.startswith(b"%PDF"):
            raise ValueError("Expected a bounded public PDF")
        pdf = folder/"baby_fin_ray_2303.14883v1.pdf"
        pdf.write_bytes(data)
        command = ["/usr/bin/pdftotext", "-layout", str(pdf), str(folder/"paper.txt")]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        record["text_conversion"] = {"command": command, "pid": process.pid}
        stdout, stderr = process.communicate(timeout=30)
        record["text_conversion"]["returncode"] = process.returncode
        (folder/"pdftotext.log").write_text(stdout+stderr)
        if process.returncode:
            raise ValueError("Paper text conversion failed")
        receipt = {"url": URL, "resolved_url": resolved, "bytes": len(data),
                   "sha256": hashlib.sha256(data).hexdigest(),
                   "scope": "Local source review. Do not republish the full paper or its figures as new kit artwork."}
        (folder/"receipt.json").write_text(json.dumps(receipt, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **receipt}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
