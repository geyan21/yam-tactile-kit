#!/usr/bin/python3
"""Package separate B3 gain-5 acquisition with preserved B1 transport."""

import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def main():
    files = {
        "main.py": "engineering/firmware/recessed/main.py",
        "config.json": "engineering/firmware/recessed/config.json",
        "mlx90393.py": "engineering/firmware/recessed/mlx90393.py",
        "mlx90393_base.py": "engineering/firmware/b1/mlx90393.py",
        "magnetic_main.py": "engineering/firmware/b1/main.py",
    }
    output = ROOT / "build/engineering/prototypes/recessed/firmware"
    with execution(ROOT / "build/records", "Package B3 gain-5 firmware; no physical device is programmed") as record:
        output.mkdir(parents=True, exist_ok=True)
        hashes = {}
        for name, source in files.items():
            data = (ROOT / source).read_bytes()
            (output / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        receipt = {
            "protocol": "yam-b3/1", "hardware_revision": "B3.1", "files": hashes,
            "source_paths": files, "gain_sel": 5, "resolution": 1,
            "lsb_ut_at_25c": [0.501, 0.501, 0.807],
            "physical_boards_tested": 0, "actuator_control": False,
            "nail_cells_required": True, "nail_continuity_resistors_at_tips_ohm": 100000,
            "note": "Copy all five files to a Raspberry Pi Pico running MicroPython. The wrapper sets B3 identity; its gain-5 driver replaces the magnetic scale only. Preserve raw data and use a new B3 calibration.",
        }
        (output / "firmware_manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
        with zipfile.ZipFile(output.parent / "recessed_firmware.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for name in (*files, "firmware_manifest.json"):
                archive.write(output / name, name)
        record["firmware"] = receipt
        print(json.dumps({"protocol": receipt["protocol"], "gain_sel": 5,
                          "files": list(files), "programmed_devices": 0}, indent=2))


if __name__ == "__main__":
    main()
