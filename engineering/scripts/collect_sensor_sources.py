#!/usr/bin/python3
"""Cache a small, pinned set of public sensor design references without running them."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

REPOSITORIES = (
    "raunaqbhirangi/reskin_sensor",
    "raunaqbhirangi/anyskin",
    "notvenky/eFlesh",
    "FlexiTac/FlexiTac_Hardware_Repo",
    "WT-MM/PyFlexiTac",
)
OUTPUT = ROOT / "build/engineering/sensor_sources"
LIMIT = 12 * 1024 * 1024


def fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "yam-tactile-engineering-study"})
    with urlopen(request, timeout=35) as response:
        content = response.read(LIMIT + 1)
    if len(content) > LIMIT:
        raise ValueError(f"File exceeds {LIMIT} byte limit")
    return content


def catalog(repository: str) -> dict:
    directory = OUTPUT / repository.replace("/", "__")
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    api = f"https://api.github.com/repos/{repository}"
    info = json.loads(fetch(api))
    branch = quote(info["default_branch"], safe="")
    commit = json.loads(fetch(f"{api}/commits/{branch}"))["sha"]
    tree = json.loads(fetch(f"{api}/git/trees/{commit}?recursive=1"))
    if tree.get("truncated"):
        raise ValueError(f"Incomplete tree for {repository}")
    (directory / "tree.json").write_text(json.dumps(tree, indent=2) + "\n")
    files = [
        {"path": item["path"], "bytes": item.get("size")}
        for item in tree["tree"] if item["type"] == "blob"
    ]
    manifest = {"repository": repository, "commit": commit, "files": files, "downloaded": []}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def download(repository: str, paths: list[str]) -> dict:
    manifest = catalog(repository)
    available = {item["path"] for item in manifest["files"]}
    directory = OUTPUT / repository.replace("/", "__")
    for relative in paths:
        part = PurePosixPath(relative)
        if part.is_absolute() or ".." in part.parts or relative not in available:
            raise ValueError(f"Path outside the pinned repository tree: {relative}")
        url = f"https://raw.githubusercontent.com/{repository}/{manifest['commit']}/{quote(relative, safe='/')}"
        data = fetch(url)
        destination = directory.joinpath(*part.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        entry = {"path": relative, "url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        manifest["downloaded"] = [item for item in manifest["downloaded"] if item["path"] != relative]
        manifest["downloaded"].append(entry)
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", choices=REPOSITORIES)
    parser.add_argument("--path", action="append", default=[])
    args = parser.parse_args()
    if args.path and not args.repository:
        parser.error("--path requires --repository")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with execution(ROOT / "build/records", "Read pinned public sensor schematics, firmware, and manufacturing documentation") as record:
        if args.repository:
            manifests = [download(args.repository, args.path)]
        else:
            # Independent, read-only requests; inspect every future.
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {repository: pool.submit(catalog, repository) for repository in REPOSITORIES}
                manifests, failures = [], {}
                for repository, future in futures.items():
                    try:
                        manifests.append(future.result())
                    except Exception as error:
                        failures[repository] = f"{type(error).__name__}: {error}"
            record["failures"] = failures
            if failures:
                print(json.dumps({"failures": failures}, indent=2))
        record["repositories"] = [{"repository": m["repository"], "commit": m["commit"]} for m in manifests]
        for manifest in manifests:
            print(json.dumps({
                "repository": manifest["repository"],
                "commit": manifest["commit"],
                "catalog_file_count": len(manifest["files"]),
                "downloaded": manifest["downloaded"],
                "catalog_path": str(OUTPUT / manifest["repository"].replace("/", "__") / "manifest.json"),
            }, indent=2))


if __name__ == "__main__":
    main()
