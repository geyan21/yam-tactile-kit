#!/usr/bin/python3
"""Check the F1 readout study and optionally extract exact cases to a fresh build directory."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "engineering/development/f1/readout-study")
    parser.add_argument("--extract", action="store_true")
    args = parser.parse_args()
    source = args.checkpoint.resolve()
    if not source.is_relative_to(ROOT):
        parser.error("Use a repository-owned checkpoint")
    manifest = json.loads((source / "checkpoint.json").read_text())
    contents = json.loads((source / "runs/contents.json").read_text())
    destination = ROOT / "build/engineering/prototypes/f1/study_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Verify every F1 readout checkpoint file and archive member; optionally extract to a fresh build directory without changing the checkpoint") as record:
        destination.mkdir(parents=True, exist_ok=False)
        for name, expected in manifest["files_sha256"].items():
            path = (source / name).resolve()
            if not path.is_relative_to(source) or digest(path) != expected:
                raise ValueError(f"Checkpoint file mismatch: {name}")
        members_checked = 0
        for label, archive_info in contents.items():
            archive_path = source / "runs" / f"{label}.tar.gz"
            if digest(archive_path) != archive_info["sha256"]:
                raise ValueError(f"Changed archive: {label}")
            names = set()
            with tarfile.open(archive_path, "r:gz") as archive:
                for member in archive:
                    relative = PurePosixPath(member.name)
                    if relative.is_absolute() or ".." in relative.parts or not member.isfile():
                        raise ValueError("Unexpected path/type in circuit archive")
                    if member.name in names or member.name not in archive_info["members"]:
                        raise ValueError("Duplicate or undeclared circuit archive member")
                    expected = archive_info["members"][member.name]
                    if member.size != expected["bytes"] or member.size > 32*1024*1024:
                        raise ValueError("Unexpected circuit member size")
                    data = archive.extractfile(member).read()
                    if hashlib.sha256(data).hexdigest() != expected["sha256"]:
                        raise ValueError(f"Changed archive member: {member.name}")
                    if args.extract:
                        target = destination / Path(*relative.parts)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data)
                    names.add(member.name)
                    members_checked += 1
            if names != set(archive_info["members"]):
                raise ValueError("Missing archive members")
        report = {"passed": True, "files_checked": len(manifest["files_sha256"]),
                  "archive_members_checked": members_checked, "extracted": args.extract,
                  "checkpoint_sha256": digest(source / "checkpoint.json"),
                  "physical_evidence": False, "directory": str(destination.relative_to(ROOT))}
        (destination / "verification.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = report
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
