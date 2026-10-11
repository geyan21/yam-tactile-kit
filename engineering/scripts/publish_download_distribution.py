#!/usr/bin/python3
"""Publish exact checked packet assets using the GitHub Actions repository token."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.github_api import GitHub, GitHubError
from tactile_kit.records import execution
from prepare_pages_distribution import REPOSITORY, digest


def verify_local(folder, manifest):
    if manifest["repository"] != REPOSITORY:
        raise ValueError("Distribution targets a different repository")
    for name, item in manifest["assets"].items():
        if Path(name).name != name or name.startswith("."):
            raise ValueError("Asset names must be plain public filenames")
        path = folder / name
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise ValueError("Distribution asset changed: "+name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", type=Path)
    args = parser.parse_args()
    folder = args.distribution.resolve()
    if not folder.is_relative_to(ROOT / "build"):
        parser.error("Use the downloaded build artifact under build/")
    manifest = json.loads((folder / "distribution.json").read_text())
    verify_local(folder, manifest)
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_SHA") != manifest["commit"]):
        raise ValueError("Publication requires the matching repository's GitHub Actions run")
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("GitHub Actions must supply its scoped GH_TOKEN for this publication step")
    executable = shutil.which("gh")
    if not executable:
        raise RuntimeError("GitHub CLI is required on the publishing runner")
    client = GitHub(token)
    tag = manifest["release_tag"]
    with execution(ROOT / "build/records", "Publish only this commit's verified public packet files; preserve previous releases and refuse changed same-name assets") as record:
        record["commands"] = []
        def run(arguments, label):
            command = [executable, *arguments]
            log = folder / (label+".log")
            with log.open("w") as stream:
                process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
                receipt = {"argv": command, "pid": process.pid}
                record["commands"].append(receipt)
                code = None
                for _ in range(10):
                    try:
                        code = process.wait(timeout=30)
                        break
                    except subprocess.TimeoutExpired:
                        print("Transfer continues:", label, flush=True)
                if code is None:
                    receipt["intentional_stop"] = "300 second transfer bound on this owned GitHub CLI process"
                    process.terminate()
                    process.wait(timeout=10)
                    raise TimeoutError("Owned GitHub transfer exceeded 300 seconds")
            receipt["exit_code"] = code
            if code:
                print(log.read_text()[-3000:].replace(token, "[redacted]"))
                raise RuntimeError("GitHub CLI "+label+" failed; inspect its bounded CI log")
        try:
            existing_commit = client.request("GET", f"/repos/{REPOSITORY}/commits/{tag}")["sha"]
        except GitHubError as error:
            if error.status not in (404, 422):
                raise
        else:
            if existing_commit != manifest["commit"]:
                raise ValueError("Existing release tag belongs to another commit; preserving it")
        try:
            release = client.request("GET", f"/repos/{REPOSITORY}/releases/tags/{tag}")
        except GitHubError as error:
            if error.status != 404:
                raise
            release = client.request("POST", f"/repos/{REPOSITORY}/releases", {
                "tag_name": tag, "target_commitish": manifest["commit"],
                "name": manifest["release_title"], "draft": True, "prerelease": True,
                "body": (folder / "release-notes.md").read_text(), "make_latest": "false",
            })
        existing = {item["name"]: item for item in release["assets"]}
        for name, item in manifest["assets"].items():
            if name in existing:
                remote = existing[name]
                if remote["size"] != item["bytes"]:
                    raise ValueError("Existing release asset differs; it will not be overwritten: "+name)
                if remote.get("digest") == "sha256:"+item["sha256"]:
                    continue
                if remote.get("digest"):
                    raise ValueError("Existing release asset hash differs; preserving it: "+name)
                with tempfile.TemporaryDirectory(prefix="yam-release-verify-") as temporary:
                    run(["release", "download", tag, "--repo", REPOSITORY, "--pattern", name,
                         "--dir", temporary], "verify-existing-"+name)
                    if digest(Path(temporary) / name) != item["sha256"]:
                        raise ValueError("Existing release asset content differs; preserving it: "+name)
                continue
            if not release["draft"]:
                raise ValueError("An already published release is missing an asset; do not silently change it")
            run(["release", "upload", tag, str(folder / name), "--repo", REPOSITORY], "upload-"+name)
        release = client.request("GET", f"/repos/{REPOSITORY}/releases/{release['id']}")
        remote_assets = {item["name"]: item for item in release["assets"]}
        for name, item in manifest["assets"].items():
            remote = remote_assets.get(name)
            if not remote or remote["size"] != item["bytes"] or remote.get("digest") != "sha256:"+item["sha256"]:
                raise ValueError("Uploaded asset is missing a matching server checksum: "+name)
        if release["draft"]:
            release = client.request("PATCH", f"/repos/{REPOSITORY}/releases/{release['id']}",
                                     {"draft": False, "prerelease": True, "make_latest": "false"})
        commit = client.request("GET", f"/repos/{REPOSITORY}/commits/{tag}")["sha"]
        if commit != manifest["commit"]:
            raise ValueError("Published release tag resolves to a different commit")
        result = {"release": release["html_url"], "tag": tag, "commit": commit,
                  "verified_assets": list(manifest["assets"]), "physical_specimens_tested": 0}
        (folder / "publication.json").write_text(json.dumps(result, indent=2)+"\n")
        record["result"] = result
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
