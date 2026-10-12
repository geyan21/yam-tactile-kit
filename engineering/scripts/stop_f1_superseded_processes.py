#!/usr/bin/python3
"""Request SIGTERM only for the previously inspected superseded F1 checkers and workers."""

import argparse
import json
import os
from pathlib import Path
import signal

from inspect_f1_superseded_processes import ROOT, allowed_parent, allowed_worker, children, identity
from tactile_kit.records import execution


def same_process(expected, allow_reparent=False):
    try:
        current = identity(expected["pid"])
    except FileNotFoundError:
        return None
    if (not any(current["command"]) and current["uid"] == expected["uid"]
            and current["start_ticks"] == expected["start_ticks"]):
        return None  # Same process has already exited and is awaiting reaping.
    compared = {**current, "parent_pid": expected["parent_pid"]} if allow_reparent else current
    if compared != expected:
        raise ValueError("Process identity changed; refusing to signal this PID")
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path)
    args = parser.parse_args()
    path = args.review.resolve()
    if not path.is_relative_to(ROOT/"build/engineering/prototypes/f1/process_reviews"):
        parser.error("Use a saved F1 process review")
    report = json.loads(path.read_text())
    if report.get("schema") != "yam-f1-owned-process-review/1" or report.get("owner_uid") != os.geteuid():
        raise ValueError("Wrong review schema or owner")
    with execution(ROOT/"build/records", "Stop only identity-verified superseded F1 distance checkers and their inspected workers; preserve partial geometry reports and original artifacts") as record:
        record["review"] = str(path.relative_to(ROOT))
        targets = []
        for group in report["groups"]:
            parent = group["parent"]
            if not allowed_parent(parent) or any(not allowed_worker(worker) for worker in group["workers"]):
                raise ValueError("Stop scope includes an unexpected program")
            current = same_process(parent)
            if current is None:
                continue
            expected_children = {worker["pid"] for worker in group["workers"]}
            if set(children(parent["pid"])) != expected_children:
                raise ValueError("Worker membership changed; inspect again")
            for worker in group["workers"]:
                if worker["parent_pid"] != parent["pid"] or same_process(worker) is None or children(worker["pid"]):
                    raise ValueError("Worker identity changed; inspect again")
            targets.extend(group["workers"])
            targets.append(parent)
        for item in targets:
            current = same_process(item, allow_reparent=True)
            if current is None:
                continue
            record["intentional_stop_requests"].append({
                "pid": item["pid"], "signal": "SIGTERM", "identity": current,
                "reason": "Superseded by the complete native common-volume check; keep all partial reports as interrupted work."})
            try:
                os.kill(item["pid"], signal.SIGTERM)
            except ProcessLookupError:
                continue
        record["result"] = {"stop_requests": len(record["intentional_stop_requests"]),
                            "artifacts_removed": 0, "other_processes_signaled": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
