#!/usr/bin/python3
"""Extract text and selected pages from one cached F1 manufacturer reference."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--pages", nargs="*", type=int, default=[])
    args = parser.parse_args()
    pdf = args.pdf.resolve()
    allowed = ROOT / "build/engineering/prototypes/f1/sources"
    if not pdf.is_relative_to(allowed) or not pdf.is_file() or pdf.suffix != ".pdf":
        parser.error("Select one PDF from the owned F1 source cache")
    if len(args.pages) > 5 or any(not 1 <= page <= 100 for page in args.pages):
        parser.error("Select at most five one-based pages")
    output = pdf.parent / (pdf.stem + "_review") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Read one cached F1 manufacturer PDF and render only the selected dimensional-reference pages") as record:
        output.mkdir(parents=True, exist_ok=False)
        record["pdf_sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
        commands = [["/usr/bin/pdftotext", "-layout", str(pdf), str(output / "text.txt")]]
        commands += [["/usr/bin/pdftoppm", "-f", str(page), "-singlefile", "-scale-to", "2400",
                     "-png", str(pdf), str(output / f"page_{page}")] for page in args.pages]
        record["commands"] = []
        for command in commands:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            item = {"command": command, "pid": process.pid}
            record["commands"].append(item)
            try:
                stdout, stderr = process.communicate(timeout=45)
            except subprocess.TimeoutExpired:
                record["intentional_stop_requests"].append(f"Stop owned PDF reader {process.pid}: timeout")
                process.kill(); process.communicate()
                raise RuntimeError("Manufacturer PDF review timed out")
            item.update({"exit_code": process.returncode, "stderr": stderr[-2000:]})
            if process.returncode:
                raise RuntimeError((stderr or stdout)[-2000:])
        result = {"source": str(pdf.relative_to(ROOT)), "sha256": record["pdf_sha256"],
                  "review_folder": str(output.relative_to(ROOT)), "pages": args.pages,
                  "evidence_kind": "manufacturer_document_review"}
        (output / "review.json").write_text(json.dumps(result, indent=2) + "\n")
        record["result"] = result
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
