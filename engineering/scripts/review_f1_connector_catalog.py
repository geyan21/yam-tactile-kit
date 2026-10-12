#!/usr/bin/python3
"""Render selected pages of the cached primary FH12 catalog for mating review."""

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
    parser.add_argument("--pdf", type=Path, default=ROOT / "build/engineering/prototypes/f1/sources/20261011T045640.766365Z/hirose_catalog_public_copy.pdf")
    parser.add_argument("--pages", type=int, nargs="+", default=[8, 11, 14])
    args = parser.parse_args()
    source = args.pdf.resolve()
    if not source.is_relative_to(ROOT / "build") or not source.is_file():
        parser.error("Use the saved manufacturer PDF in the project source cache")
    if not args.pages or len(args.pages) > 4 or any(p < 1 or p > 30 for p in args.pages):
        parser.error("Select one to four numbered catalog pages")
    tool = Path("/usr/bin/pdftoppm")
    if not tool.is_file():
        raise RuntimeError("The explicit pdftoppm renderer is unavailable")
    folder = ROOT / "build/engineering/prototypes/f1/mating_source_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Read-only review of selected FH12 manufacturer-catalog pages: confirm mating, FPC and stiffener dimensions without treating the unverified STEP as available") as record:
        folder.mkdir(parents=True)
        record["commands"] = []
        for page in args.pages:
            output = folder / f"catalog_page_{page:02d}"
            command = [str(tool), "-f", str(page), "-singlefile", "-scale-to", "2200", "-png", str(source), str(output)]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            entry = {"argv": command, "pid": process.pid}; record["commands"].append(entry)
            try:
                stdout, stderr = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                record["intentional_stop_requests"].append(f"Stop owned PDF renderer {process.pid}: 30 second bound")
                process.kill(); stdout, stderr = process.communicate()
                raise RuntimeError("PDF rendering exceeded the scoped review bound")
            entry.update({"exit_code": process.returncode, "stderr": stderr[-1000:]})
            if process.returncode or not output.with_suffix(".png").is_file():
                raise RuntimeError("Selected PDF page did not render")
        report = {"source": str(source.relative_to(ROOT)), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "pages": args.pages, "scope": "Working manufacturer-source review; publish selected dimensions and attribution, not complete proprietary catalog images.",
                  "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob("*.png")}}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "pages": args.pages}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
