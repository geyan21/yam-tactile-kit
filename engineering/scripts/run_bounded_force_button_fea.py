#!/usr/bin/python3
"""Launch only the FB1 structural worker, retaining progress and a bounded owned process."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("worker_arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not 30 <= args.timeout <= 600 or not args.worker_arguments:
        parser.error("Use a 30..600 second limit and explicit FB1 worker arguments after --")
    arguments = args.worker_arguments[1:] if args.worker_arguments[0] == "--" else args.worker_arguments
    folder = ROOT / "build/engineering/prototypes/force_button/fea_jobs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Run only the declared FB1 structural worker, saving its PID/log and stopping that owned child if its explicit time limit expires") as record:
        folder.mkdir(parents=True, exist_ok=False)
        command = [sys.executable, str(ROOT / "engineering/scripts/run_force_button_fea.py"), *arguments]
        with (folder / "worker.log").open("w") as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            receipt = {"command": command, "pid": process.pid, "started_utc": datetime.now(timezone.utc).isoformat(),
                       "owned_process_group": process.pid, "timeout_seconds": args.timeout, "status": "running"}
            (folder / "process.json").write_text(json.dumps(receipt, indent=2)+"\n")
            print(json.dumps({"job_directory": str(folder.relative_to(ROOT)), "pid": process.pid}), flush=True)
            try:
                code = process.wait(timeout=args.timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                receipt["intentional_stop"] = (f"Stop this newly created owned process group after {args.timeout} seconds"
                                                if isinstance(error, subprocess.TimeoutExpired) else
                                                "Operator interrupted this newly created owned process group")
                record["intentional_stop_requests"].append(receipt["intentional_stop"])
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); code = process.wait(timeout=5)
                receipt["status"] = "timed_out" if isinstance(error, subprocess.TimeoutExpired) else "interrupted"
            else:
                receipt["status"] = "complete" if code == 0 else "failed"
            finally:
                receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
                receipt["returncode"] = process.poll()
                (folder / "process.json").write_text(json.dumps(receipt, indent=2)+"\n")
                record["child"] = receipt
        print((folder / "worker.log").read_text()[-7000:])
        if receipt["status"] != "complete":
            raise RuntimeError("FB1 worker "+receipt["status"]+"; original log and inputs retained")


if __name__ == "__main__":
    main()
