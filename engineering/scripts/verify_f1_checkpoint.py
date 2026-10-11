#!/usr/bin/python3
"""Verify the distributed F1 development files without modifying the snapshot."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint_directory", type=Path,
                        nargs="?", default=ROOT / "engineering/development/f1/fanout")
    args = parser.parse_args()
    source = args.checkpoint_directory.resolve()
    if not source.is_relative_to(ROOT):
        parser.error("Use a repository-owned development snapshot")
    checkpoint_path = source / "checkpoint.json"
    data = json.loads(checkpoint_path.read_text())
    with execution(ROOT / "build/records", "Verify all distributed F1 development files and the saved incomplete-assembly status") as record:
        expected = data["files_sha256"]
        actual = {str(p.relative_to(source)): digest(p) for p in source.rglob("*")
                  if p.is_file() and p != checkpoint_path}
        missing = sorted(set(expected)-set(actual))
        extra = sorted(set(actual)-set(expected))
        changed = sorted(name for name in set(actual) & set(expected) if actual[name] != expected[name])
        status_ok = (data["integrated_f1_completed"] is False and data["physical_specimens_tested"] == 0
                     and data["independent_check"]["passed"] is True)
        result = {"checkpoint_sha256": digest(checkpoint_path), "verified_files": len(actual),
                  "missing": missing, "extra": extra, "changed": changed,
                  "development_status_preserved": status_ok,
                  "passed": not (missing or extra or changed) and status_ok,
                  "scope": "Snapshot identity and declared evidence status, not new physical or electrical validation"}
        folder = ROOT / "build/engineering/prototypes/f1/checkpoint_verifications"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+".json")
        path.write_text(json.dumps(result, indent=2)+"\n")
        record["verification"] = result
        print(json.dumps(result, indent=2))
        if not result["passed"]:
            raise ValueError("Distributed F1 checkpoint changed; inspect the preserved result")


if __name__ == "__main__":
    main()
