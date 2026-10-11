#!/usr/bin/python3
"""Inspect and cache an official Freerouting release in the project tool folder."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tarfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

VERSION = "2.5.0"
API = f"https://api.github.com/repos/freerouting/freerouting/releases/tags/v{VERSION}"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", help="Exact official release asset to cache; omit to inspect the listing")
    parser.add_argument("--extract-native", action="store_true")
    args = parser.parse_args()
    folder = ROOT / "build/engineering/tools/freerouting" / VERSION
    run = folder / "fetch_records" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Inspect the official Freerouting release and optionally cache one checksum-verified local routing tool; do not modify system Java or start a service") as record:
        run.mkdir(parents=True, exist_ok=False)
        request = Request(API, headers={"User-Agent": "yam-tactile-kit engineering tool setup",
                                       "Accept": "application/vnd.github+json"})
        with urlopen(request, timeout=30) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Unexpectedly large release metadata")
        (run / "release.json").write_bytes(raw)
        release = json.loads(raw)
        if release["tag_name"] != "v"+VERSION:
            raise ValueError("Unexpected release version")
        assets = [{key: item.get(key) for key in ("id", "name", "size", "digest", "browser_download_url")}
                  for item in release["assets"]]
        record["release"] = {"tag": release["tag_name"], "url": release["html_url"],
                             "metadata_sha256": digest(run / "release.json")}
        if not args.asset:
            print(json.dumps({"release": release["html_url"], "assets": assets}, indent=2))
            return
        found = [item for item in assets if item["name"] == args.asset]
        if len(found) != 1 or Path(args.asset).name != args.asset:
            raise ValueError("Choose one exact plain filename from the official listing")
        asset = found[0]
        if not asset["digest"] or not asset["digest"].startswith("sha256:") or asset["size"] > 200_000_000:
            raise ValueError("Require a bounded asset with the release's SHA-256 digest")
        expected = asset["digest"].split(":", 1)[1]
        target = folder / asset["name"]
        if target.exists():
            if digest(target) != expected or target.stat().st_size != asset["size"]:
                raise ValueError("Existing cached tool differs; preserve and inspect it")
        else:
            request = Request(asset["browser_download_url"], headers={"User-Agent": "yam-tactile-kit engineering tool setup"})
            with urlopen(request, timeout=30) as response, target.open("xb") as stream:
                total = 0
                while chunk := response.read(1024*1024):
                    total += len(chunk)
                    if total > asset["size"]:
                        raise ValueError("Download exceeded the declared asset size")
                    stream.write(chunk)
            if target.stat().st_size != asset["size"] or digest(target) != expected:
                raise ValueError("Downloaded tool fails the official size/hash check; retained for inspection")
        result = {"file": str(target.relative_to(ROOT)), "sha256": expected, "bytes": asset["size"],
                  "source": asset["browser_download_url"], "executed": False}
        if args.extract_native:
            if asset["name"] != "freerouting-cli-2.5.0-linux-x64.tar.gz":
                raise ValueError("Extraction is limited to the selected official Linux CLI archive")
            native = folder / "native"
            native.mkdir(exist_ok=True)
            executable = native / "freerouting-cli"
            with tarfile.open(target, "r:gz") as archive:
                members = archive.getmembers()
                if len(members) != 1 or members[0].name != "freerouting-cli" or not members[0].isfile():
                    raise ValueError("Unexpected native archive members")
                if members[0].size > 150_000_000:
                    raise ValueError("Unexpected native executable size")
                data = archive.extractfile(members[0]).read()
            binary_hash = hashlib.sha256(data).hexdigest()
            if executable.exists():
                if digest(executable) != binary_hash:
                    raise ValueError("Existing native executable differs; preserve it")
            else:
                executable.write_bytes(data)
                executable.chmod(0o755)
            result["native"] = {"file": str(executable.relative_to(ROOT)), "sha256": binary_hash,
                                "bytes": len(data)}
        (run / "download.json").write_text(json.dumps(result, indent=2)+"\n")
        record["result"] = result
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
