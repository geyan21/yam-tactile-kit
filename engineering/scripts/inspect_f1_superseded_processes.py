#!/usr/bin/python3
"""Record identities of only the two superseded F1 checkers and their owned workers."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

CADPY = str(ROOT/"build/engineering/tools/cad-venv/bin/python")
SCRIPTS = {"engineering/scripts/check_f1_complete_assembly.py",
           "engineering/scripts/check_f1_assembly_parallel.py"}


def identity(pid):
    folder = Path("/proc")/str(pid)
    args = (folder/"cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
    status = (folder/"status").read_text().splitlines()
    uid = int(next(line for line in status if line.startswith("Uid:")).split()[1])
    stat = (folder/"stat").read_text()
    fields = stat[stat.rfind(")")+2:].split()
    return {"pid": pid, "uid": uid, "parent_pid": int(fields[1]), "start_ticks": int(fields[19]), "command": args}


def children(pid):
    path = Path("/proc")/str(pid)/"task"/str(pid)/"children"
    return [int(value) for value in path.read_text().split()] if path.exists() else []


def allowed_parent(item):
    args = item["command"]
    return item["uid"] == os.geteuid() and len(args) >= 2 and args[0] == CADPY and args[1] in SCRIPTS


def allowed_worker(item):
    args = item["command"]
    return (item["uid"] == os.geteuid() and len(args) >= 3 and args[0] == CADPY and args[1] == "-c"
            and args[2].startswith(("from multiprocessing.spawn import spawn_main;",
                                   "from multiprocessing.resource_tracker import main;")))


def main():
    folder = ROOT/"build/engineering/prototypes/f1/process_reviews"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Read identities of the two named superseded F1 CAD checkers and their direct multiprocessing workers; this inspection sends no signals") as record:
        folder.mkdir(parents=True)
        matches = subprocess.run(["/usr/bin/pgrep", "-u", str(os.geteuid()), "-f", CADPY],
                                 capture_output=True, text=True, check=False)
        if matches.returncode not in (0, 1):
            raise RuntimeError("Scoped process lookup failed")
        groups = []
        for value in matches.stdout.split():
            try:
                parent = identity(int(value))
            except FileNotFoundError:
                continue
            if not allowed_parent(parent):
                continue
            workers = []
            for pid in children(parent["pid"]):
                worker = identity(pid)
                if worker["parent_pid"] != parent["pid"] or not allowed_worker(worker) or children(pid):
                    raise ValueError("Unrecognized child; no stop plan is produced")
                workers.append(worker)
            groups.append({"parent": parent, "workers": workers})
        report = {"schema": "yam-f1-owned-process-review/1", "created_utc": datetime.now(timezone.utc).isoformat(),
                  "owner_uid": os.geteuid(), "groups": groups,
                  "purpose": "Superseded distance-based checks only; current direct-common checker and all generated evidence are outside the stop scope."}
        (folder/"review.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"review": str((folder/"review.json").relative_to(ROOT)), "groups": groups}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
