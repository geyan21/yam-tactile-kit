#!/usr/bin/python3
"""Download the official KiCad lite AppImage into this build tree; no system install."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

URL = "https://kicad-downloads.s3.cern.ch/appimage/stable/kicad-10.0.7-x86_64-lite.AppImage.tar"
DEST = ROOT / "build/engineering/tools/b1-kicad"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    archive = DEST / URL.rsplit("/", 1)[1]
    with execution(ROOT / "build/records", "Fetch and optionally extract the official, isolated KiCad CLI for B1 PCB manufacturing checks") as record:
        if not archive.exists():
            partial = archive.with_suffix(".partial")
            count = 0
            with urlopen(Request(URL, headers={"User-Agent": "enpire-b1-design-study"}), timeout=40) as response, partial.open("wb") as output:
                if response.url != URL:
                    raise ValueError("Unexpected tool download redirect")
                while block := response.read(1024 * 1024):
                    count += len(block)
                    if count > 400 * 1024 * 1024:
                        raise ValueError("Tool archive exceeds the bounded download")
                    output.write(block)
            partial.replace(archive)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        record["artifact"] = {"url": URL, "sha256": checksum, "bytes": archive.stat().st_size,
                              "trust": "Official KiCad download mirror; no separately published digest verified"}
        if args.extract:
            with tarfile.open(archive) as package:
                files = [item for item in package.getmembers() if item.isfile()]
                if len(files) != 1 or not files[0].name.endswith(".AppImage"):
                    raise ValueError("Expected exactly one AppImage")
                member = files[0]
                executable = DEST / Path(member.name).name
                with package.extractfile(member) as source, executable.open("wb") as target:
                    while block := source.read(1024 * 1024):
                        target.write(block)
                executable.chmod(0o755)
            log = DEST / "extract.log"
            with log.open("w") as stream:
                process = subprocess.Popen([str(executable), "--appimage-extract"], cwd=DEST, stdout=stream, stderr=subprocess.STDOUT)
                record["extraction"] = {"pid": process.pid, "command": [str(executable), "--appimage-extract"]}
                try:
                    code = process.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    record["extraction"]["intentional_stop"] = "120 second extraction limit"
                    process.terminate()
                    process.wait(timeout=10)
                    raise
                if code:
                    raise RuntimeError(f"AppImage extraction exited {code}; inspect {log}")
        (DEST / "provenance.json").write_text(json.dumps(record["artifact"], indent=2) + "\n")
        print(json.dumps(record["artifact"], indent=2))


if __name__ == "__main__":
    main()
