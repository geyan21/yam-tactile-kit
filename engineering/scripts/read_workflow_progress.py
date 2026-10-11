#!/usr/bin/python3
"""Read the public job stages of one kit workflow run, without credentials."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=int)
    args = parser.parse_args()
    if args.run_id <= 0:
        parser.error("Use the specific public workflow run ID")
    folder = ROOT / "build/engineering/publication_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Read only the public job stages for the specified geyan21/yam-tactile-kit workflow; do not inspect credentials or other repositories") as record:
        folder.mkdir(parents=True, exist_ok=False)
        url = f"https://api.github.com/repos/geyan21/yam-tactile-kit/actions/runs/{args.run_id}/jobs?per_page=20"
        request = Request(url, headers={"User-Agent": "yam-tactile-kit-public-workflow-check",
                                       "Accept": "application/vnd.github+json", "Cache-Control": "no-cache"})
        with urlopen(request, timeout=20) as response:
            data = response.read(500001)
        if len(data) > 500000:
            raise ValueError("Unexpectedly large job response")
        value = json.loads(data)
        (folder / "jobs.json").write_text(json.dumps(value, indent=2)+"\n")
        summary = [{"name": job["name"], "status": job["status"], "conclusion": job["conclusion"],
                    "steps": [{"name": step["name"], "status": step["status"], "conclusion": step.get("conclusion")}
                              for step in job["steps"]]} for job in value["jobs"]]
        record["result"] = {"run_id": args.run_id, "jobs": summary}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
