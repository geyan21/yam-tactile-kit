#!/usr/bin/python3
"""Read public workflow/release/Pages evidence for one exact kit commit."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

REPOSITORY = "geyan21/yam-tactile-kit"


def fetch(url, decode=True):
    request = Request(url, headers={"User-Agent": "yam-tactile-kit public publication verification",
                                   "Accept": "application/vnd.github+json" if decode else "text/html",
                                   "Cache-Control": "no-cache"})
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(3_000_001)
            if len(raw) > 3_000_000:
                raise ValueError("Unexpectedly large publication response")
            return {"status": response.status, "body": json.loads(raw) if decode else raw.decode()}
    except HTTPError as error:
        return {"status": error.code, "message": error.reason,
                "rate_limit_remaining": error.headers.get("X-RateLimit-Remaining")}
    except URLError as error:
        return {"status": 0, "message": str(error.reason)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commit")
    parser.add_argument("--pages", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        parser.error("Use a full commit SHA")
    folder = ROOT / "build/engineering/publication_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    tag = "kit-"+args.commit[:12]
    with execution(ROOT / "build/records", "Read public GitHub workflow, immutable release and optional Pages evidence for the exact authorized kit commit; do not use or reveal credentials") as record:
        folder.mkdir(parents=True, exist_ok=False)
        runs = fetch(f"https://api.github.com/repos/{REPOSITORY}/actions/runs?"+
                     urlencode({"head_sha": args.commit, "per_page": 5}))
        release = fetch(f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{tag}")
        (folder / "workflow_response.json").write_text(json.dumps(runs, indent=2)+"\n")
        (folder / "release_response.json").write_text(json.dumps(release, indent=2)+"\n")
        summary = {"commit": args.commit, "release_tag": tag,
                   "workflow_http": runs["status"], "release_http": release["status"]}
        if runs["status"] == 200:
            summary["runs"] = [{key: row.get(key) for key in
                                ("id", "name", "head_sha", "status", "conclusion", "html_url")}
                               for row in runs["body"]["workflow_runs"]]
        if release["status"] == 200:
            value = release["body"]
            summary["release"] = {key: value.get(key) for key in ("html_url", "draft", "prerelease", "target_commitish")}
            summary["assets"] = [{key: item.get(key) for key in ("name", "size", "digest", "browser_download_url")}
                                 for item in value["assets"]]
        if args.pages:
            page = fetch("https://geyan21.github.io/yam-tactile-kit/flexible-matrix.html?"+
                         urlencode({"commit": args.commit}), decode=False)
            summary["pages_http"] = page["status"]
            if page["status"] == 200:
                (folder / "f1_page.html").write_text(page["body"])
                summary["pages_contains_expected_release"] = tag in page["body"]
                models = ("f1_assembly_reference", "f1_r3_assembly_reference")
                summary["fit_viewer_models"] = [name for name in models if f'data-model-id="{name}"' in page["body"]]
                summary["pages_contains_fit_viewer"] = bool(summary["fit_viewer_models"])
                summary["pages_contains_rejected_r2_link"] = "r2-routing-study/file-index.html" in page["body"]
                summary["pages_contains_fitted_foil_packet"] = "fitted-foils-r3/file-index.html" in page["body"]
                summary["pages_contains_fitted_contact_map"] = "fitted-foils-r3/review/fitted_contact_map.png" in page["body"]
        (folder / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
        record["result"] = summary
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
