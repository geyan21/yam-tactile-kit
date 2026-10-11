#!/usr/bin/python3
"""Rebuild and test the source ZIP in an isolated temporary checkout."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def main():
    source = ROOT / "build/site/downloads/enpire-source.zip"
    with execution(ROOT / "build/records", "Verify the delivered source ZIP can run software tests and rebuild its website without the CAD environment") as record:
        record["source_zip_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        record["commands"] = []
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        with tempfile.TemporaryDirectory(prefix="yam-portable-") as temporary:
            folder = Path(temporary)
            with zipfile.ZipFile(source) as archive:
                if sum(row.file_size for row in archive.infolist()) > 512 * 1024 * 1024:
                    raise ValueError("Source archive exceeds this check's scoped extraction bound")
                for name in archive.namelist():
                    if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                        raise ValueError("Source ZIP contains an unsafe path")
                archive.extractall(folder)
            commands = [
                ["/usr/bin/python3", "-m", "unittest", "discover", "-s", "engineering/tests"],
                ["/usr/bin/python3", "engineering/scripts/build_site.py"],
                ["/usr/bin/python3", "engineering/scripts/check_site.py"],
            ]
            for command in commands:
                process = subprocess.Popen(command, cwd=folder, env=environment,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                entry = {"command": command, "pid": process.pid}
                record["commands"].append(entry)
                try:
                    stdout, stderr = process.communicate(timeout=120)
                except subprocess.TimeoutExpired:
                    record["intentional_stop_requests"].append(f"Stop owned portability-check child {process.pid}: timeout")
                    process.kill(); process.communicate()
                    raise RuntimeError("Portable source verification timed out")
                entry.update({"exit_code": process.returncode, "stdout": stdout[-12000:], "stderr": stderr[-5000:]})
                if process.returncode:
                    raise RuntimeError("Portable source command failed: " + (stderr or stdout)[-2000:])
                print("Verified portable source: " + " ".join(command[1:]), flush=True)
            site_check = json.loads((folder / "build/engineering/site_checks.json").read_text())
            result = {"passed": True, "source_zip_sha256": record["source_zip_sha256"],
                      "independent_commands": len(commands), "design_pages": site_check["design_pages_verified"],
                      "local_links": site_check["local_links"], "physical_tests": 0}
        (ROOT / "build/engineering/portable_check.json").write_text(json.dumps(result, indent=2) + "\n")
        record["result"] = result
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
