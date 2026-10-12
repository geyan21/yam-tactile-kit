#!/usr/bin/python3
"""Capture local O1 lossless images, camera metadata and raw N0 ADC samples."""

import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from optical_core import SCHEMA, config_hash, digest, pgm_bytes, validate_config, metadata_faults, nail_signals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-config", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    for key in ("specimen", "session", "condition", "device-id"):
        parser.add_argument("--"+key, required=True)
    parser.add_argument("--mode", choices=("setup", "capture"), default="capture")
    parser.add_argument("--duration", type=float, default=15)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.duration <= 600:
        parser.error("Use a fresh output and a duration of 1..600 seconds")
    cfg = validate_config(json.loads(args.camera_config.read_text()))
    # Hardware dependencies are loaded only for an explicit capture invocation.
    from picamera2 import Picamera2
    from libcamera import controls
    from optical_adc import LinuxBus, scan
    camera, bus, completed, failure, count = None, None, False, None, 0
    folder = args.output.resolve()
    folder.mkdir(parents=True)
    (folder/"frames").mkdir()
    header = {"schema": SCHEMA, "mode": args.mode,
              "evidence_kind": "physical_recording_unreviewed" if args.mode == "capture" else "optical_setup_only",
              "created_utc": datetime.now(timezone.utc).isoformat(), "specimen": args.specimen,
              "session_id": args.session, "condition": args.condition, "device_id": args.device_id,
              "geometry_sha256": digest(args.geometry), "camera_config": cfg, "camera_config_sha256": config_hash(cfg),
              "blue_format": "P5 8-bit blue channel", "colour_format": "gzip P6 8-bit RGB, converted from Picamera2 RGB888 B,G,R memory",
              "adc": "ADS1115 0x48, A0 nail0 / A1 nail1 / A2 3.3V; +/-4.096V, 860SPS single shot",
              "camera_source": "Official Picamera2 manual; capture_request(wait=False), Job.get_result(timeout=3), queued frames disabled"}
    with execution(ROOT/"build/records", "Capture the user's local O1 camera/ADC with fixed recorded settings and lossless image hashes; no actuator commands or network streaming") as record:
        try:
            camera = Picamera2()
            lens_range = camera.camera_controls.get("LensPosition")
            if lens_range is None or not lens_range[0] <= cfg["lens_position_dioptres"] <= lens_range[1]:
                raise ValueError("Requested focus is unsupported by the actual camera")
            settings = {"AeEnable": False, "AwbEnable": False, "ExposureTime": cfg["exposure_us"],
                        "AnalogueGain": cfg["analogue_gain"], "ColourGains": tuple(cfg["colour_gains"]),
                        "AfMode": controls.AfModeEnum.Manual, "LensPosition": cfg["lens_position_dioptres"],
                        "FrameDurationLimits": (cfg["frame_duration_us"], cfg["frame_duration_us"])}
            camera.configure(camera.create_video_configuration(main={"size": tuple(cfg["size"]), "format": "RGB888"},
                                                               controls=settings, buffer_count=4, queue=False))
            header["camera_model"] = str(camera.camera_properties.get("Model", "unknown"))
            header["supported_lens_position"] = [float(v) for v in lens_range]
            (folder/"session.json").write_text(json.dumps(header, indent=2, allow_nan=False)+"\n")
            if args.mode == "capture":
                bus = LinuxBus()
            camera.start()
            for _ in range(5):
                request = camera.capture_request(wait=False).get_result(timeout=3)
                request.release()
            start, previous = time.monotonic(), None
            with (folder/"frames.jsonl").open("x") as stream:
                while time.monotonic()-start < args.duration:
                    request = camera.capture_request(wait=False).get_result(timeout=3)
                    try:
                        metadata = request.get_metadata()
                        captured_ns = time.monotonic_ns()
                        array = request.make_array("main")
                        x, y, width, height = cfg["save_roi"]
                        crop = array[y:y+height, x:x+width]
                        blue = crop[:, :, 0].tobytes()
                        rgb = crop[:, :, ::-1].tobytes()
                        keep = {}
                        for key in ("SensorTimestamp", "ExposureTime", "AnalogueGain", "LensPosition", "FrameDuration", "ColourGains", "ScalerCrop"):
                            if key in metadata:
                                value = metadata[key]
                                keep[key] = list(value) if key in ("ColourGains", "ScalerCrop") else value
                    finally:
                        request.release()
                    adc, faults = None, metadata_faults(keep, cfg, captured_ns, previous)
                    previous = keep.get("SensorTimestamp", previous)
                    if bus is not None:
                        try:
                            adc = scan(bus)
                            faults += nail_signals(adc["raw"])["faults"]
                            if adc["end_monotonic_ns"]-captured_ns > 50000000:
                                faults.append("nail_capture_skew_over_50ms")
                        except (OSError, TimeoutError, ValueError) as error:
                            faults.append("nail_read_error:"+str(error))
                    stem = f"frames/{count:06d}"
                    pgm = folder/(stem+".pgm")
                    colour = folder/(stem+".ppm.gz")
                    pgm.write_bytes(pgm_bytes(width, height, blue))
                    with gzip.GzipFile(filename=str(colour), mode="wb", compresslevel=1, mtime=0) as encoded:
                        encoded.write(f"P6\n{width} {height}\n255\n".encode()+rgb)
                    row = {"index": count, "host_elapsed_s": (captured_ns/1e9-start), "host_monotonic_ns": captured_ns,
                           "metadata": keep, "adc": adc, "capture_faults": sorted(set(faults)),
                           "blue_path": stem+".pgm", "blue_sha256": digest(pgm),
                           "colour_path": stem+".ppm.gz", "colour_sha256": digest(colour)}
                    stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False)+"\n"); stream.flush()
                    count += 1
            completed = True
        except BaseException as error:
            failure = type(error).__name__+": "+str(error)
            raise
        finally:
            if camera is not None:
                camera.stop(); camera.close()
            if bus is not None:
                bus.close()
            receipt = {"schema": "yam-o1-capture-receipt/1", "capture_complete": completed, "failure": failure,
                       "requested_duration_s": args.duration, "frames": count,
                       "files_sha256": {name: digest(folder/name) for name in ("session.json", "frames.jsonl") if (folder/name).is_file()},
                       "physical_performance_qualified": False}
            (folder/"receipt.json").write_text(json.dumps(receipt, indent=2)+"\n")
            record["result"] = {"directory": str(folder), "frames": count, "capture_complete": completed, "failure": failure}
        print(json.dumps({"directory": str(folder), "frames": count, "capture_complete": completed}, indent=2))


if __name__ == "__main__":
    main()
