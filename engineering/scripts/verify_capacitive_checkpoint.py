#!/usr/bin/python3
"""Check K1 snapshot identity and its explicitly unfinished hardware status."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    folder = ROOT / "engineering/development/capacitive/k1"
    path = folder / "checkpoint.json"
    data = json.loads(path.read_text())
    with execution(ROOT / "build/records", "Verify the distributed K1 development files and incomplete-hardware status without changing the snapshot") as record:
        actual = {str(p.relative_to(folder)): digest(p) for p in folder.rglob("*") if p.is_file() and p != path}
        expected = data["files_sha256"]
        status_ok = (data["design_id"] == "CAPACITIVE" and data["integrated_prototype_complete"] is False
                     and data["physical_specimens_tested"] == 0 and data["independent_pcb_check"]["passed"] is True)
        result = {"files": len(actual), "missing": sorted(set(expected)-set(actual)),
                  "extra": sorted(set(actual)-set(expected)),
                  "changed": sorted(n for n in set(actual)&set(expected) if actual[n] != expected[n]),
                  "development_status_preserved": status_ok, "checkpoint_sha256": digest(path)}
        result["passed"] = status_ok and not any(result[name] for name in ("missing", "extra", "changed"))
        record["result"] = result
        print(json.dumps(result, indent=2))
        if not result["passed"]:
            raise ValueError("K1 checkpoint identity or scope changed")


if __name__ == "__main__":
    main()
