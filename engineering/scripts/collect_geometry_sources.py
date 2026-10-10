#!/usr/bin/python3
"""Fetch only relevant public geometry sources; never execute upstream code."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/sources"
REPOSITORIES = {
    "NVlabs/ENPIRE": "99ee90acf65b5b18957c8382ad580db999528be3",
    "pgeedh/Open-ENPIRE-Gripper": "72cc833bfe1521132318db6a2724e7e9bbb8cd6e",
}


def fetch(url: str, limit=32 * 1024 * 1024) -> bytes:
    request = Request(url, headers={"User-Agent": "yam-tactile-engineering-study", "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=25) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Source exceeded the scoped download limit")
    return content


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = {"sources": [], "notes": [
        "Community baseline identity must be checked against the original MakerWorld file before claiming exact equivalence.",
        "Downloaded upstream files are research inputs kept outside the published source tree.",
    ]}
    with execution(ROOT / "build/records", "Collect public ENPIRE finger geometry and provenance for actual prototype design") as record:
        for repository, commit in REPOSITORIES.items():
            api = f"https://api.github.com/repos/{repository}"
            tree_bytes = fetch(f"{api}/git/trees/{commit}?recursive=1")
            tree = json.loads(tree_bytes)
            directory = OUTPUT / repository.replace("/", "__")
            directory.mkdir(exist_ok=True)
            (directory / "tree.json").write_bytes(tree_bytes)
            matches = [
                item for item in tree["tree"]
                if item["type"] == "blob"
                and Path(item["path"]).suffix.lower() in {".stl", ".step", ".stp", ".3mf"}
                and ("gripp" in item["path"].lower() or "finger" in item["path"].lower())
            ]
            entry = {"repository": repository, "commit": commit, "geometry_paths": [item["path"] for item in matches], "downloaded": []}
            if repository == "pgeedh/Open-ENPIRE-Gripper":
                matches = [item for item in matches if item["path"].startswith("grippers-stl/enpire_i2rt_yam_stl/")]
            else:
                matches = [item for item in matches if item["path"]=="enpire/env/forge/robot/models/station/assets/gripper_finger.stl"]
            for item in matches:
                if item.get("size", 0) > 32 * 1024 * 1024:
                    continue
                relative = item["path"]
                if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
                    raise ValueError("Invalid upstream source path")
                url = f"https://raw.githubusercontent.com/{repository}/{commit}/{quote(relative,safe='/')}"
                data = fetch(url)
                destination = directory / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                entry["downloaded"].append({
                    "path": relative, "url": url, "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "local_file": str(destination.relative_to(ROOT)),
                })
            for name in ("README.md", "LICENSE"):
                try:
                    content = fetch(f"https://raw.githubusercontent.com/{repository}/{commit}/{name}")
                    (directory / name).write_bytes(content)
                except HTTPError as error:
                    if error.code != 404:
                        raise
            manifest["sources"].append(entry)
        for url in (
            "https://makerworld.com/api/v1/design-service/design/2984746",
            "https://api.makerworld.com/v1/design-service/design/2984746",
        ):
            try:
                data = fetch(url, 2 * 1024 * 1024)
                name = "makerworld_" + hashlib.sha256(url.encode()).hexdigest()[:8] + ".json"
                (OUTPUT / name).write_bytes(data)
                manifest.setdefault("makerworld_metadata", []).append({"url": url, "status": "retrieved", "file": name})
            except (HTTPError, URLError) as error:
                manifest.setdefault("makerworld_metadata", []).append({
                    "url": url, "status": "unavailable", "http_status": getattr(error, "code", None)
                })
        record["source_manifest"] = manifest
        (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
