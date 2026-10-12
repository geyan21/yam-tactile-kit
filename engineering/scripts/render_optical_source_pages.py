#!/usr/bin/python3
"""Render selected local primary-document pages for visual mechanical review."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs="+", required=True)
    args = parser.parse_args()
    source = args.pdf.resolve()
    if not source.is_relative_to(ROOT/"build") or not source.is_file() or any(not 1 <= page <= 100 for page in args.pages):
        parser.error("Use a downloaded document and explicit page numbers")
    folder = ROOT/"build/engineering/prototypes/optical/source_page_reviews"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Render only the selected manufacturer/paper pages for local visual inspection; keep them out of newly authored kit artwork") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        record["commands"] = []
        for page in args.pages:
            prefix = folder/(source.stem+"_p"+str(page))
            command = ["/usr/bin/pdftoppm", "-f", str(page), "-l", str(page), "-singlefile",
                       "-scale-to", "1800", "-png", str(source), str(prefix)]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            entry = {"command": command, "pid": process.pid}
            record["commands"].append(entry)
            try:
                stdout, stderr = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                record["intentional_stop_requests"].append(f"Stop owned PDF renderer {process.pid}: 30-second limit")
                process.kill()
                stdout, stderr = process.communicate()
                entry["timeout"] = True
            entry["returncode"] = process.returncode
            prefix.with_suffix(".log").write_text(stdout+stderr)
            if process.returncode or entry.get("timeout"):
                raise ValueError("PDF rendering failed")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "source": str(source.relative_to(ROOT)),
                            "pages": args.pages, "scope": "Local review, not new project artwork"}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
