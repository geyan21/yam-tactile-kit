#!/usr/bin/python3
"""Verify a published commit, immutable release assets and the selected prototype's live pages."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from check_published import content_hash

API = "https://api.github.com/repos/geyan21/yam-tactile-kit"
SITE = "https://geyan21.github.io/yam-tactile-kit/"


def read(url, limit=16*1024*1024):
    request = Request(url, headers={"User-Agent": "yam-tactile-kit-delivery-check", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=30) as response:
        data = response.read(limit+1)
    if len(data) > limit:
        raise ValueError("Public response exceeds its declared scope")
    return data


def stream_hash(url, expected_size):
    request = Request(url, headers={"User-Agent": "yam-tactile-kit-delivery-check"})
    digest, count = hashlib.sha256(), 0
    with urlopen(request, timeout=30) as response:
        while True:
            chunk = response.read(8*1024*1024)
            if not chunk:
                break
            count += len(chunk)
            if count > expected_size:
                raise ValueError("Archive exceeds its published byte count")
            digest.update(chunk)
    if count != expected_size:
        raise ValueError("Incomplete archive transfer")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--hosted", type=Path, required=True)
    parser.add_argument("--prototype", default="f1")
    parser.add_argument("--pages", nargs="+", default=["flexible-matrix.html", "build-f1.html", "f1-manufacturing.html",
                                                     "f1-testing.html", "f1-reproduce.html"])
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args()
    distribution, hosted = args.distribution.resolve(), args.hosted.resolve()
    if not all(path.is_relative_to(ROOT/"build") for path in (distribution, hosted)):
        parser.error("Use the prepared local distributions")
    if not re.fullmatch(r"[a-z0-9_]+", args.prototype) or any(not re.fullmatch(r"[a-z0-9-]+\.html", name) for name in args.pages):
        parser.error("Select plain prototype and page names")
    manifest = json.loads((distribution/"distribution.json").read_text())
    commit, tag = manifest["commit"], manifest["release_tag"]
    if (manifest["repository"] != "geyan21/yam-tactile-kit"
            or not re.fullmatch(r"[0-9a-f]{40}", commit) or tag != "kit-"+commit[:12]):
        raise ValueError("Unexpected publication identity")
    folder = ROOT/"build/engineering/publication_checks"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Read the approved public repository, exact-commit workflow and release, then compare hosted prototype pages/assets and packet contents with the prepared local distribution") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        current = json.loads(read(API+"/commits/main"))
        runs = json.loads(read(API+"/actions/runs?head_sha="+commit+"&per_page=5"))["workflow_runs"]
        results = {"expected_commit": commit, "remote_main": current["sha"], "main_matches": current["sha"] == commit,
                   "runs": [{key: run.get(key) for key in ("id", "head_sha", "status", "conclusion")} for run in runs],
                   "published_verified": False}
        succeeded = any(run["status"] == "completed" and run["conclusion"] == "success" for run in runs)
        if not args.status_only and succeeded and results["main_matches"]:
            release = json.loads(read(API+"/releases/tags/"+tag))
            if release["draft"] or release["tag_name"] != tag or release["target_commitish"] != commit:
                raise ValueError("Release identity or publication state differs")
            assets = {item["name"]: item for item in release["assets"]}
            sums = read(assets["SHA256SUMS.txt"]["browser_download_url"]).decode()
            published_sums = {}
            for line in sums.splitlines():
                digest, name = line.split(None, 1)
                if not re.fullmatch(r"[a-f0-9]{64}", digest):
                    raise ValueError("Malformed published checksum")
                published_sums[name.lstrip("*")] = digest
            asset_checks = {}
            for name, expected in manifest["assets"].items():
                remote = assets[name]
                if remote.get("state") != "uploaded":
                    raise ValueError("Release asset is not fully uploaded")
                if name == "SHA256SUMS.txt":
                    checksum = hashlib.sha256(sums.encode()).hexdigest()
                else:
                    checksum = published_sums[name]
                provider = remote.get("digest")
                actual = provider.removeprefix("sha256:") if provider and provider.startswith("sha256:") else stream_hash(
                    remote["browser_download_url"], remote["size"])
                asset_checks[name] = {"published_bytes": remote["size"], "published_sha256": checksum,
                                      "provider_or_stream_sha256": actual, "published_checksum_matches": checksum == actual,
                                      "local_compressed_hash_matches": checksum == expected["sha256"],
                                      "verification_method": "GitHub asset digest" if provider else "streamed SHA-256"}
            page_checks = {}
            for name in args.pages:
                actual = read(SITE+name)
                expected = (hosted/name).read_bytes()
                page_checks[name] = {"matches_prepared_hosted_page": actual == expected,
                                     "expected_release_link_visible": tag.encode() in actual}
            prototype = hosted/"assets/prototypes"/args.prototype
            names = ["prototype_snapshot.json", args.prototype+"_manifest.json", "models.json", "bom.csv", "parts.csv"]
            names += ["visuals/"+path.name for path in sorted((prototype/"visuals").glob("*.svg"))]
            asset_pages = {}
            for name in names:
                local = (prototype/name).read_bytes()
                remote = read(SITE+"assets/prototypes/"+args.prototype+"/"+name, max(16*1024*1024, len(local)+1024))
                asset_pages[name] = hashlib.sha256(remote).hexdigest() == hashlib.sha256(local).hexdigest()
            zip_name = args.prototype+"-prototype.zip"
            local_zip = (hosted/"downloads"/zip_name).read_bytes()
            remote_zip = read(SITE+"downloads/"+zip_name, len(local_zip)+4*1024*1024)
            zip_matches = content_hash(local_zip, zip_name) == content_hash(remote_zip, zip_name)
            results.update({"release_assets": asset_checks, "pages": page_checks, "prototype_assets_match": asset_pages,
                            "prototype_zip_content_matches": zip_matches,
                            "prototype_zip_bytes": len(remote_zip),
                            "published_verified": (all(row["published_checksum_matches"] for row in asset_checks.values())
                                                   and all(row["matches_prepared_hosted_page"] for row in page_checks.values())
                                                   and all(asset_pages.values()) and zip_matches),
                            "limits": ["Release archive bytes are checked against published SHA-256 values using provider digests or streamed bytes.",
                                       "Local compressed hashes are reported separately because CI zlib versions may encode identical entries differently.",
                                       "Selected live pages and prototype files match locally prepared content; the prototype ZIP is compared by all nested file contents.",
                                       "Publication verification is not physical hardware qualification."]})
        (folder/"report.json").write_text(json.dumps(results, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **results}
        print(json.dumps(record["result"], indent=2))
        if not args.status_only and not results["published_verified"]:
            raise SystemExit("Publication not yet verified; inspect status and retained report")


if __name__ == "__main__":
    main()
