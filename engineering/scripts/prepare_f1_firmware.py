#!/usr/bin/python3
"""Generate F1 bench firmware configuration from the wrist pin/ADC contract."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    source = ROOT / "engineering/designs/f1_wrist_development.json"
    wrist = json.loads(source.read_text())
    adc = json.loads((ROOT / wrist["adc_candidate"]).read_text())
    reference = adc["adc"]["reference_v"]
    config = {
        "schema": "yam-f1-wrist-firmware/1",
        "status": "Fixed-gain experimental bench capture; no force or contact calibration",
        "wrist_configuration_sha256": digest(source),
        "gpio": wrist["controller"]["gpio"],
        "adc_spi_hz": wrist["adc_timing"]["spi_frequency_hz"],
        "monitor_spi_hz": wrist["monitor"]["spi_frequency_hz"],
        "conversion_wait_us": wrist["adc_timing"]["conversion_wait_us"],
        "post_read_acquisition_wait_us": wrist["adc_timing"]["post_read_acquisition_wait_us"],
        "startup_wait_ms": 250, "settle_us": 500, "samples_per_phase": 4,
        "gain_ids": [0]*64,
        "gain_order": "row-major index = row*16+column; change deliberately after a bench range check",
        "nominal_reference_v": reference,
        "development_headroom_codes": [int(.1/reference*65536)+1, int(3.2/reference*65536)],
        "link_test_gain": 1, "development_link_drop_window_v": [.70, .95],
        "pause_between_frames_ms": 20,
        "limits": [
            "Default gain 0 covers the broadest current span but is not a validated contact setting.",
            "Record separate gain runs or edit the declared per-pixel gain map after measuring saturation/noise. No automatic force calibration is supplied.",
            "500 us is a starting bench settling delay, not measured full-array settling.",
            "Column tests are electrical observations and must not be included as tactile data.",
            "Host backpressure changes scan timing; per-sample device timestamps and frame duration are retained."
        ],
    }
    destination = ROOT / "engineering/firmware/f1/config.json"
    folder = ROOT / "build/engineering/prototypes/f1/firmware_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Generate the F1 sensor-only firmware configuration and a four-file bench package; do not connect to or program hardware") as record:
        folder.mkdir(parents=True, exist_ok=False)
        destination.write_text(json.dumps(config, indent=2)+"\n")
        files = {}
        with zipfile.ZipFile(folder / "f1_firmware.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for name in ("config.json", "main.py", "hardware.py", "scan.py"):
                path = destination.parent / name
                shutil.copyfile(path, folder / name)
                archive.write(path, name)
                files[name] = digest(path)
        receipt = {"files_sha256": files, "configuration_sha256": digest(source),
                   "hardware_programmed": False, "physical_specimens_tested": 0}
        (folder / "package.json").write_text(json.dumps(receipt, indent=2)+"\n")
        record["package"] = {"directory": str(folder.relative_to(ROOT)), **receipt}
        print(json.dumps(record["package"], indent=2))


if __name__ == "__main__":
    main()
