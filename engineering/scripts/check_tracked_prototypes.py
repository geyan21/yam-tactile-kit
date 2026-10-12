#!/usr/bin/python3
"""Require every frozen artifact/source to be tracked and match its saved hash."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(ROOT/"engineering/scripts"))
from tactile_kit.records import execution
from build_site import verify_snapshot


def main():
    folder = ROOT/"build/engineering/tracked_snapshot_checks"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Compare frozen snapshot member/source paths with this repository's Git index so ignored local artifacts cannot disappear in a clean GitHub checkout") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        record["commands"] = []
        def git(arguments):
            command = ["/usr/bin/git", *arguments]
            process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            entry = {"command": command, "pid": process.pid}
            record["commands"].append(entry)
            try:
                stdout, stderr = process.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                record["intentional_stop_requests"].append(f"Stop owned Git inspection {process.pid}: 20-second bound")
                process.kill()
                stdout, stderr = process.communicate()
                raise ValueError("Git inspection exceeded its bounded runtime")
            entry["returncode"] = process.returncode
            if process.returncode:
                raise ValueError("Git tracking inspection failed: "+stderr.decode(errors="replace")[-1000:])
            return stdout
        if Path(git(["rev-parse", "--show-toplevel"]).decode().strip()).resolve() != ROOT:
            raise ValueError("This script needs the actual project Git checkout, not a portable source directory inside another repository")
        tracked = set(git(["ls-files", "-z"]).decode().split("\0"))-{""}
        paths = [ROOT/"engineering/release/release_manifest.json", ROOT/"engineering/concepts/concept_snapshot.json"]
        paths += sorted((ROOT/"engineering/prototypes").glob("*/prototype_snapshot.json"))
        paths += sorted((ROOT/"engineering/development").rglob("checkpoint.json"))
        expected = set()
        for path in paths:
            snapshot = json.loads(path.read_text())
            members = snapshot.get("files", snapshot.get("files_sha256"))
            if not isinstance(members, dict):
                raise ValueError("Unrecognized frozen file manifest: "+str(path))
            expected.add(str(path.relative_to(ROOT)))
            for member in members:
                target = (path.parent/member).resolve()
                if not target.is_relative_to(ROOT):
                    raise ValueError("Frozen member leaves the project")
                expected.add(str(target.relative_to(ROOT)))
            for member in snapshot.get("source_hashes", {}):
                target = (ROOT/member).resolve()
                if not target.is_relative_to(ROOT):
                    raise ValueError("Frozen source leaves the project")
                expected.add(str(target.relative_to(ROOT)))
        missing = sorted(expected-tracked)
        if not missing:
            verify_snapshot()
        report = {"schema": "yam-tracked-snapshots/1", "passed": not missing,
                  "manifests_checked": len(paths), "expected_paths": len(expected),
                  "missing_from_git": missing,
                  "snapshot_hashes_verified": not missing,
                  "scope": "Git inclusion and frozen file/source hashes. Physical qualification remains absent."}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))
        if missing:
            raise ValueError("Frozen local files are missing from the Git index; inspect the named paths before publishing")


if __name__ == "__main__":
    main()
