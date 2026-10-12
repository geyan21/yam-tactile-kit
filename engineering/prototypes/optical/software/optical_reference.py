#!/usr/bin/python3
"""Freeze a no-contact O1 image reference and emit its numbered marker overlay."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from optical_core import SCHEMA, digest, config_hash, read_pgm, crop_image, pgm_bytes, write_gray_png, establish_reference, observe, metadata_faults


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--roi", type=int, nargs=4, required=True, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--threshold", type=int, default=80)
    parser.add_argument("--area-min", type=int, default=8)
    parser.add_argument("--area-max", type=int, default=300)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh reference directory")
    source = args.capture.resolve()
    header = json.loads((source/"session.json").read_text())
    receipt = json.loads((source/"receipt.json").read_text())
    if header.get("schema") != SCHEMA or not receipt.get("capture_complete"):
        raise ValueError("Use an identified completed O1 no-contact setup capture")
    for name, expected in receipt["files_sha256"].items():
        if digest(source/name) != expected:
            raise ValueError("Capture index changed")
    rows = [json.loads(line) for line in (source/"frames.jsonl").read_text().splitlines()]
    row = next((r for r in rows if r["index"] == args.frame), None)
    if row is None or metadata_faults(row["metadata"], header["camera_config"], row["host_monotonic_ns"]):
        raise ValueError("Use a frame with complete matching camera metadata")
    if len(row["metadata"].get("ScalerCrop", [])) != 4:
        raise ValueError("The actual camera crop must be recorded")
    image_path = (source/row["blue_path"]).resolve()
    if not image_path.is_relative_to(source) or digest(image_path) != row["blue_sha256"]:
        raise ValueError("Setup image changed")
    image = crop_image(read_pgm(image_path), args.roi)
    detection = {"threshold": args.threshold, "area_min_px": args.area_min, "area_max_px": args.area_max,
                 "expected_markers": 42, "minimum_contrast": 30, "maximum_motion_px": 16,
                 "area_ratio_min": .4, "area_ratio_max": 2.5, "maximum_clipped_fraction": .10}
    markers = establish_reference(image, detection)
    cfg = dict(header["camera_config"])
    x, y, _, _ = cfg["save_roi"]
    cfg["save_roi"] = [x+args.roi[0], y+args.roi[1], args.roi[2], args.roi[3]]
    reference = {"schema": "yam-o1-marker-reference/1", "evidence_kind": "physical_setup_unreviewed",
                 "created_utc": datetime.now(timezone.utc).isoformat(), "specimen": header["specimen"],
                 "device_id": header["device_id"], "geometry_sha256": header["geometry_sha256"],
                 "camera_config": cfg, "camera_config_sha256": config_hash(cfg), "detection": detection,
                 "camera_model": header["camera_model"], "scaler_crop": row["metadata"]["ScalerCrop"],
                 "markers": markers, "source_session_sha256": digest(source/"session.json"),
                 "source_frame_blue_sha256": row["blue_sha256"], "physical_performance_qualified": False,
                 "limits": "Inspect the overlay: all 42 numbered components must be the painted dots. Fixed image coordinates are not a calibrated millimetre/pressure/normal map."}
    self_check = observe(image, reference)
    if not self_check["available"]:
        raise ValueError("Reference image quality failed: "+str(self_check["faults"]))
    with execution(ROOT/"build/records", "Freeze O1's no-contact marker image and settings, with a numbered overlay for inspection; do not infer a force calibration"):
        args.output.mkdir(parents=True)
        (args.output/"baseline.pgm").write_bytes(pgm_bytes(*image))
        write_gray_png(args.output/"baseline.png", image)
        reference["baseline_sha256"] = digest(args.output/"baseline.pgm")
        (args.output/"reference.json").write_text(json.dumps(reference, indent=2)+"\n")
        (args.output/"camera.json").write_text(json.dumps(cfg, indent=2)+"\n")
        width, height, _ = image
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
               f'<image href="baseline.png" width="{width}" height="{height}"/>']
        for i, point in enumerate(markers):
            svg += [f'<circle cx="{point["x"]}" cy="{point["y"]}" r="{point["search_radius_px"]}" fill="none" stroke="#e99430" stroke-width=".8"/>',
                    f'<text x="{point["x"]+3}" y="{point["y"]-3}" font-size="9" fill="#e43b3b">{i}</text>']
        (args.output/"markers.svg").write_text("\n".join(svg+["</svg>"])+"\n")
    print(json.dumps({"directory": str(args.output), "markers": len(markers), "inspect": "markers.svg", "capture_config": "camera.json"}, indent=2))


if __name__ == "__main__":
    main()
