#!/usr/bin/python3
"""Package B2's entry point with the preserved B1 magnetic acquisition code."""

import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution


def main():
    files = {
        "main.py":ROOT/"engineering/firmware/b2/main.py",
        "config.json":ROOT/"engineering/firmware/b2/config.json",
        "magnetic_main.py":ROOT/"engineering/firmware/b1/main.py",
        "mlx90393.py":ROOT/"engineering/firmware/b1/mlx90393.py",
    }
    output = ROOT/"build/engineering/prototypes/b2/firmware"
    output.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Package B2 firmware from its own identity plus unchanged B1 sensor acquisition; no device is programmed") as record:
        hashes = {}
        for name,source in files.items():
            data = source.read_bytes()
            (output/name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        receipt = {
            "protocol":"yam-b2/1","hardware_revision":"B2.1","files":hashes,
            "physical_boards_tested":0,"actuator_control":False,
            "nail_cells_default":True,"nail_continuity_resistors_at_tips_ohm":100000,
            "note":"Copy all four files to a Raspberry Pi Pico running MicroPython. Do not copy the original B1 main.py over the B2 entry point.",
        }
        (output/"firmware_manifest.json").write_text(json.dumps(receipt,indent=2)+"\n")
        with zipfile.ZipFile(output.parent/"b2_firmware.zip","w",zipfile.ZIP_DEFLATED) as archive:
            for name in (*files,"firmware_manifest.json"):
                archive.write(output/name,name)
        record["package"] = receipt
        print(json.dumps({"protocol":receipt["protocol"],"files":list(files),"programmed_devices":0},indent=2))


if __name__ == "__main__":
    main()
