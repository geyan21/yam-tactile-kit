#!/usr/bin/python3
"""Extract the verified official JVM bundle without changing system Java."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from prepare_freerouting import digest

TOOLS = ROOT / "build/engineering/tools/freerouting/2.5.0"
ARCHIVE = TOOLS / "freerouting-2.5.0-linux-x64.zip"
EXPECTED = "e8ffca14914e5307a2fa9aea723fb93d11b99bebda20d126472da5460c03196e"


def main():
    if digest(ARCHIVE) != EXPECTED:
        raise ValueError("Bundle differs from the official release checksum")
    destination = TOOLS / "jvm-bundle"
    if destination.exists():
        raise ValueError("Preserve an existing bundle; use its saved manifest")
    with execution(ROOT / "build/records", "Extract the official Freerouting bundled runtime into the project cache and record its complete identity; leave system Java unchanged") as record:
        destination.mkdir()
        links = []
        with zipfile.ZipFile(ARCHIVE) as archive:
            members = archive.infolist()
            if len({item.filename for item in members}) != len(members):
                raise ValueError("Duplicate archive paths")
            if len(members) > 5000 or sum(item.file_size for item in members) > 800_000_000:
                raise ValueError("Unexpectedly large runtime bundle")
            for item in members:
                relative = Path(item.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe bundle path")
                target = destination / relative
                mode = item.external_attr >> 16
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif stat.S_ISLNK(mode):
                    value = archive.read(item).decode()
                    if Path(value).is_absolute() or not (target.parent / value).resolve().is_relative_to(destination):
                        raise ValueError("Bundle link escapes its own cache")
                    links.append((target, value))
                elif stat.S_IFMT(mode) in (0, stat.S_IFREG):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(archive.read(item))
                    target.chmod(0o755 if mode & 0o111 else 0o644)
                else:
                    raise ValueError("Unexpected special file in bundle")
        for target, value in links:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(value)
        package = destination / "freerouting-2.5.0-linux-x64"
        launcher = package / "bin/freerouting"
        jar = package / "lib/app/freerouting-executable.jar"
        if not launcher.is_file() or not jar.is_file():
            raise ValueError("Expected launcher and application jar are missing")
        launcher.chmod(0o755)
        manifest = {
            "schema": "yam-freerouting-jvm-bundle/1", "created_utc": datetime.now(timezone.utc).isoformat(),
            "archive_sha256": EXPECTED, "launcher": str(launcher.relative_to(ROOT)),
            "jar": str(jar.relative_to(ROOT)),
            "files_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sorted(destination.rglob("*"))
                             if p.is_file() and not p.is_symlink()},
            "links": {str(p.relative_to(ROOT)): os.readlink(p) for p, _ in links},
            "system_java_changed": False,
        }
        (TOOLS / "jvm-bundle.json").write_text(json.dumps(manifest, indent=2)+"\n")
        record["result"] = {"launcher": manifest["launcher"], "jar_sha256": digest(jar),
                            "files": len(manifest["files_sha256"]), "links": len(links)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
