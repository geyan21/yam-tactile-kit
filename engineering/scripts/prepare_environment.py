#!/usr/bin/python3
"""Create an isolated CAD/mesh-analysis environment inside generated build data."""

from __future__ import annotations

import os
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

TOOLS = ROOT / "build/engineering/tools"
VENV = TOOLS / "cad-venv"
LOCK = ROOT / "engineering/requirements.lock"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv",type=Path,help="Explicit path to uv; otherwise resolve uv from PATH")
    args=parser.parse_args()
    found=str(args.uv) if args.uv else shutil.which("uv")
    if not found:
        parser.error("Install uv or pass --uv /absolute/path/to/uv")
    uv=Path(found).resolve()
    if not uv.is_file():
        parser.error("The uv executable does not exist")
    TOOLS.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update({
        "UV_CACHE_DIR": str(TOOLS / "uv-cache"),
        "UV_PYTHON_INSTALL_DIR": str(TOOLS / "python"),
        "UV_LINK_MODE": "copy",
        "UV_NATIVE_TLS": "true",
    })
    with execution(ROOT / "build/records", "Install isolated, locked CAD and mesh-analysis tools for real prototype geometry") as record:
        record["commands"] = []

        def run(arguments):
            command = [str(uv), *arguments]
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            entry = {"command": command, "pid": process.pid}
            record["commands"].append(entry)
            try:
                stdout, stderr = process.communicate(timeout=600)
            except subprocess.TimeoutExpired:
                record["intentional_stop_requests"].append(f"Stop owned environment setup process {process.pid}: timeout")
                process.kill()
                process.communicate()
                raise RuntimeError("Environment setup timed out")
            entry.update({"exit_code": process.returncode, "stdout": stdout[-4000:], "stderr": stderr[-6000:]})
            if process.returncode:
                raise RuntimeError(stderr[-4000:])

        if not (VENV / "bin/python").is_file():
            run(["venv", "--python", "3.12", str(VENV)])
        if not LOCK.is_file():
            run([
                "pip", "compile", "engineering/requirements.in", "--python-version", "3.12",
                "--generate-hashes", "--output-file", str(LOCK.relative_to(ROOT)),
            ])
        run(["pip", "sync", "--python", str(VENV / "bin/python"), "--require-hashes", "--only-binary", ":all:", str(LOCK)])
        record["interpreter"] = str(VENV / "bin/python")
        record["lock_file"] = str(LOCK.relative_to(ROOT))
        print(f"CAD interpreter: {VENV / 'bin/python'}")
        print(f"Locked dependencies: {LOCK.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
