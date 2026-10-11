#!/usr/bin/python3
"""Refresh only the checked FB1 host evaluator after the 20 N coverage correction."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    target = ROOT / "engineering/prototypes/force_button"
    snapshot_path = target / "prototype_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    source_name = "engineering/software/force_button_force.py"
    bundled_name = "software/force_button_force.py"
    if (ROOT / source_name).read_bytes() != (target / bundled_name).read_bytes():
        raise ValueError("The packaged evaluator must match its editable source")
    if "and (level != 20 or r[\"reference_n\"] >= 20)" not in (ROOT / source_name).read_text():
        raise ValueError("The explicit actual-20-N guard is missing")
    for name, expected in snapshot["source_hashes"].items():
        if name != source_name and digest(ROOT / name) != expected:
            raise ValueError("Unrelated prototype source changed: "+name)
    for name, expected in snapshot["files"].items():
        if name != bundled_name and digest(target / name) != expected:
            raise ValueError("Unrelated artifact changed: "+name)
    with execution(ROOT / "build/records", "Refresh only the FB1 host force-evaluator hashes after the tested actual-20-N coverage fix; preserve all CAD, PCB, firmware and structural evidence") as record:
        folder = ROOT / "build/engineering/prototypes/force_button/software_updates" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        folder.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(snapshot_path, folder / "previous_snapshot.json")
        previous = digest(snapshot_path)
        snapshot["source_hashes"][source_name] = digest(ROOT / source_name)
        snapshot["files"][bundled_name] = digest(target / bundled_name)
        snapshot.setdefault("software_updates", []).append({
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "previous_snapshot_sha256": previous,
            "reason": "General force-level tolerance must not qualify an actual load below 20 N as a 20 N endpoint.",
            "source": source_name, "source_sha256": snapshot["source_hashes"][source_name],
            "geometry_electronics_firmware_unchanged": True})
        snapshot_path.write_text(json.dumps(snapshot, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)),
                            "previous_snapshot_sha256": previous,
                            "new_snapshot_sha256": digest(snapshot_path)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
