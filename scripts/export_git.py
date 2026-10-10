#!/usr/bin/python3
"""Create a portable Git bundle from a fresh temporary copy of the source ZIP."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

from _bootstrap import ROOT
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git", type=Path, default=Path("/usr/bin/git"))
    parser.add_argument("--archive", type=Path, default=ROOT / "build/site/downloads/yam-tactile-kit.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "build/yam-tactile-kit.bundle")
    args = parser.parse_args()
    if not args.git.is_file() or not args.archive.is_file():
        parser.error("An explicit Git executable and a built source ZIP are required")
    target = args.output.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with execution(ROOT / "build/records", "Export only the built kit source into a fresh temporary Git repository") as record:
        record["commands"] = []
        with tempfile.TemporaryDirectory(prefix="yam-tactile-git-export-") as temporary:
            temporary = Path(temporary)
            with zipfile.ZipFile(args.archive) as archive:
                for name in archive.namelist():
                    if not name.startswith("yam-tactile-kit/") or ".." in Path(name).parts:
                        raise ValueError("Unexpected path in source archive")
                archive.extractall(temporary)
            repo = temporary / "yam-tactile-kit"

            def git(*arguments):
                command = [str(args.git), "-C", str(repo), *arguments]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                entry = {"command": command, "pid": process.pid}
                record["commands"].append(entry)
                try:
                    stdout, stderr = process.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    record["intentional_stop_requests"].append(f"Timeout: stop owned Git process {process.pid}")
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise RuntimeError("Git export timed out")
                entry.update({"exit_code": process.returncode, "stderr": stderr[-1500:]})
                if process.returncode:
                    raise RuntimeError(f"Git export failed: {stderr.strip()}")
                return stdout.strip()

            git("init", "--initial-branch=main")
            git("add", "--all")
            git("-c", "user.name=YAM Tactile Kit exporter", "-c", "user.email=export@localhost",
                "-c", "commit.gpgsign=false", "commit", "-m", "Package reproducible tactile design lab")
            commit = git("rev-parse", "HEAD")
            git("bundle", "create", str(target), "--all")
            git("bundle", "verify", str(target))
            bundle_refs = git("bundle", "list-heads", str(target))
            receipt = {
                "commit": commit,
                "bundle": target.name,
                "source_archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
                "bundle_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "bundle_refs": bundle_refs.splitlines(),
                "scope": "Fresh export repository only; no surrounding repository changed.",
            }
            record.update(receipt)
            target.with_suffix(".json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
