#!/usr/bin/python3
"""Verify one public module manifest and its downloadable ZIP without downloading the ZIP."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Relative public Pages manifest path")
    parser.add_argument("--local-manifest", type=Path, required=True)
    parser.add_argument("--download", required=True, help="Relative public Pages ZIP path")
    parser.add_argument("--local-download", type=Path, required=True)
    args = parser.parse_args()
    for value in (args.manifest, args.download):
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or ":" in value or "?" in value:
            parser.error("Use a relative path beneath this kit's public Pages site")
    local = [p.resolve() for p in (args.local_manifest, args.local_download)]
    if not all(p.is_relative_to(ROOT) and p.is_file() for p in local):
        parser.error("Use existing repository-owned comparison files")
    folder = ROOT / "build/engineering/publication_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Compare one published kit manifest to its checked local copy and verify the public ZIP's HTTP status and size; no credentials or remote writes") as record:
        folder.mkdir(parents=True, exist_ok=False)
        base = "https://geyan21.github.io/yam-tactile-kit/"
        headers = {"User-Agent": "yam-tactile-kit-module-verification", "Cache-Control": "no-cache"}
        with urlopen(Request(base+args.manifest, headers=headers), timeout=20) as response:
            raw = response.read(2_000_001)
            manifest_status = response.status
        if len(raw) > 2_000_000:
            raise ValueError("Unexpectedly large module manifest")
        (folder / "public_manifest.json").write_bytes(raw)
        with urlopen(Request(base+args.download, headers=headers, method="HEAD"), timeout=20) as response:
            size = int(response.headers.get("Content-Length", "-1"))
            download_status = response.status
        expected = hashlib.sha256(local[0].read_bytes()).hexdigest()
        observed = hashlib.sha256(raw).hexdigest()
        result = {"manifest_http": manifest_status, "manifest_sha256": observed,
                  "expected_manifest_sha256": expected, "manifest_matches": observed == expected,
                  "download_http": download_status, "download_bytes": size,
                  "expected_download_bytes": local[1].stat().st_size,
                  "download_size_matches": size == local[1].stat().st_size,
                  "physical_performance_verified": False}
        (folder / "result.json").write_text(json.dumps(result, indent=2)+"\n")
        record["result"] = result
        print(json.dumps(result, indent=2))
        if not result["manifest_matches"] or not result["download_size_matches"]:
            raise ValueError("The public module differs from the checked local package")


if __name__ == "__main__":
    main()
