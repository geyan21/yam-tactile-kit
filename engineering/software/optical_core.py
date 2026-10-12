"""O1 lossless image/marker observations; no physical calibration is embedded."""

import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import zlib

SCHEMA = "yam-o1-capture/1"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def config_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid "+name)
    return float(value)


def validate_config(cfg):
    if cfg.get("schema") != "yam-o1-camera-config/1":
        raise ValueError("Unknown camera configuration")
    width, height = cfg["size"]
    if type(width) is not int or type(height) is not int or not (64 <= width <= 4608 and 64 <= height <= 2592):
        raise ValueError("Unsupported image dimensions")
    x, y, w, h = cfg["save_roi"]
    if any(type(v) is not int for v in (x, y, w, h)) or not (0 <= x < x+w <= width and 0 <= y < y+h <= height):
        raise ValueError("ROI outside camera frame")
    duration = finite(cfg["frame_duration_us"], "frame duration")
    exposure = finite(cfg["exposure_us"], "exposure")
    if not (33333 <= duration <= 200000 and 100 <= exposure < duration):
        raise ValueError("Unsupported bench timing")
    if not (1 <= finite(cfg["analogue_gain"], "gain") <= 8 and 0 <= finite(cfg["lens_position_dioptres"], "focus") <= 32):
        raise ValueError("Unsupported gain/focus target")
    if len(cfg["colour_gains"]) != 2 or any(not .1 <= finite(v, "colour gain") <= 8 for v in cfg["colour_gains"]):
        raise ValueError("Invalid colour gains")
    if cfg.get("rotation_about_optical_axis_deg") != 180:
        raise ValueError("This mount uses the documented 180-degree camera orientation")
    return cfg


def pgm_bytes(width, height, pixels):
    if len(pixels) != width*height or min(width, height) <= 0 or width*height > 12000000:
        raise ValueError("Invalid image length")
    return f"P5\n{width} {height}\n255\n".encode()+bytes(pixels)


def read_pgm(path):
    data = Path(path).read_bytes()
    try:
        magic, dimensions, maximum, pixels = data.split(b"\n", 3)
        width, height = map(int, dimensions.split())
    except (ValueError, TypeError) as error:
        raise ValueError("Use the capture tool's bounded P5 image") from error
    if magic != b"P5" or maximum != b"255":
        raise ValueError("Expected the lossless blue-channel P5 format")
    pgm_bytes(width, height, pixels)
    return width, height, pixels


def crop_image(image, roi):
    width, height, pixels = image
    x, y, w, h = roi
    if any(type(v) is not int for v in roi) or not (0 <= x < x+w <= width and 0 <= y < y+h <= height):
        raise ValueError("Crop outside image")
    return w, h, b"".join(pixels[(y+j)*width+x:(y+j)*width+x+w] for j in range(h))


def write_gray_png(path, image):
    width, height, pixels = image
    def chunk(kind, value):
        return struct.pack(">I", len(value))+kind+value+struct.pack(">I", zlib.crc32(kind+value)&0xffffffff)
    rows = b"".join(b"\0"+pixels[j*width:(j+1)*width] for j in range(height))
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
                          +chunk(b"IDAT", zlib.compress(rows, 6))+chunk(b"IEND", b""))


def detect_markers(image, cfg):
    """Connected dark components; reject borders, low contrast and gross shapes."""
    width, height, pixels = image
    threshold = cfg["threshold"]
    if type(threshold) is not int or not 1 <= threshold <= 254:
        raise ValueError("Threshold must be an 8-bit value")
    visited = bytearray(width*height)
    components = []
    for seed, value in enumerate(pixels):
        if visited[seed] or value >= threshold:
            continue
        stack, indices = [seed], []
        visited[seed] = 1
        while stack:
            current = stack.pop(); indices.append(current)
            x, y = current % width, current // width
            for adjacent in ((current-1 if x else None), (current+1 if x+1 < width else None),
                             (current-width if y else None), (current+width if y+1 < height else None)):
                if adjacent is not None and not visited[adjacent] and pixels[adjacent] < threshold:
                    visited[adjacent] = 1; stack.append(adjacent)
        if not cfg["area_min_px"] <= len(indices) <= cfg["area_max_px"]:
            continue
        xs, ys = [i % width for i in indices], [i // width for i in indices]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        if x0 < 2 or y0 < 2 or x1 >= width-2 or y1 >= height-2:
            continue
        aspect = (x1-x0+1)/(y1-y0+1)
        if not .25 <= aspect <= 4:
            continue
        ring = [pixels[y*width+x] for y in range(y0-2, y1+3) for x in range(x0-2, x1+3)
                if not (x0 <= x <= x1 and y0 <= y <= y1)]
        contrast = statistics.median(ring)-statistics.mean(pixels[i] for i in indices)
        if contrast < cfg["minimum_contrast"]:
            continue
        weights = [threshold-pixels[i] for i in indices]; total = sum(weights)
        components.append({"x": sum(x*w for x, w in zip(xs, weights))/total,
                           "y": sum(y*w for y, w in zip(ys, weights))/total,
                           "area": len(indices), "contrast": contrast})
    return sorted(components, key=lambda point: (point["y"], point["x"]))


def establish_reference(image, cfg):
    points = detect_markers(image, cfg)
    if len(points) != cfg["expected_markers"]:
        raise ValueError(f"Expected {cfg['expected_markers']} painted dots, found {len(points)}; inspect the image and setup")
    if len(points) < 3:
        raise ValueError("At least three distinct markers are required")
    for index, point in enumerate(points):
        separation = min(math.dist((point["x"], point["y"]), (other["x"], other["y"]))
                         for j, other in enumerate(points) if j != index)
        point["search_radius_px"] = min(cfg["maximum_motion_px"], .40*separation)
        if point["search_radius_px"] < 1:
            raise ValueError("Markers are not optically separated")
    return points


def observe(image, reference):
    cfg, baseline = reference["detection"], reference["markers"]
    points = detect_markers(image, cfg)
    faults, matched = [], []
    if len(points) != len(baseline):
        faults.append("marker_count_changed")
    used = set()
    for original in baseline:
        if not points:
            faults.append("marker_missing"); break
        distance, index = min((math.dist((original["x"], original["y"]), (p["x"], p["y"])), i)
                              for i, p in enumerate(points))
        point = points[index]
        if index in used:
            faults.append("ambiguous_marker_assignment")
        if distance > original["search_radius_px"]:
            faults.append("marker_outside_reference_search")
        ratio = point["area"]/original["area"]
        if not cfg["area_ratio_min"] <= ratio <= cfg["area_ratio_max"]:
            faults.append("marker_area_outside_setup_limits")
        used.add(index)
        matched.append({"dx": point["x"]-original["x"], "dy": point["y"]-original["y"],
                        "log_area_ratio": math.log(ratio), "contrast": point["contrast"]})
    bright = sum(value >= 250 for value in image[2])/len(image[2])
    if bright > cfg["maximum_clipped_fraction"]:
        faults.append("image_saturated")
    if faults:
        return {"available": False, "faults": sorted(set(faults)), "observed_markers": len(points),
                "clipped_fraction": bright, "features": None}
    return {"available": True, "faults": [], "observed_markers": len(points), "clipped_fraction": bright,
            "features": [value for p in matched for value in (p["dx"], p["dy"], p["log_area_ratio"])],
            "markers": matched}


def nail_signals(raw):
    faults = []
    if not isinstance(raw, list) or len(raw) != 3 or any(type(v) is not int or not -32768 <= v <= 32767 for v in raw):
        return {"available": False, "faults": ["nail_adc_missing"], "signals": None}
    volts = [v*4.096/32768 for v in raw]
    supply = volts[2]
    if not 3.135 <= supply <= 3.465:
        faults.append("nail_supply_outside_limits")
    signals = []
    for value in volts[:2]:
        if value < .025*supply:
            faults.append("nail_continuity_missing")
        if value >= .94*supply or value < 0:
            faults.append("nail_adc_headroom")
        signals.append(1e6*value/(10000*(supply-value)) if 0 <= value < supply else None)
    return {"available": not faults, "faults": sorted(set(faults)), "signals": signals if not faults else None,
            "volts": volts, "note": "Apparent conductance includes the parallel 100k continuity resistor"}


def metadata_faults(metadata, cfg, host_monotonic_ns, previous_sensor_ns=None):
    faults = []
    try:
        stamp = metadata["SensorTimestamp"]
        if type(stamp) is not int or stamp <= 0:
            raise ValueError("Sensor timestamp")
        age = (host_monotonic_ns-stamp)/1e9
        if not -.002 <= age <= .20:
            faults.append("camera_frame_age")
        if previous_sensor_ns is not None:
            if stamp <= previous_sensor_ns:
                faults.append("camera_timestamp_not_increasing")
            elif stamp-previous_sensor_ns > 1.5*cfg["frame_duration_us"]*1000:
                faults.append("camera_frame_gap")
        for key, target, tolerance in (("ExposureTime", cfg["exposure_us"], max(100, cfg["exposure_us"]*.03)),
                                      ("AnalogueGain", cfg["analogue_gain"], max(.05, cfg["analogue_gain"]*.05)),
                                      ("LensPosition", cfg["lens_position_dioptres"], .1),
                                      ("FrameDuration", cfg["frame_duration_us"], cfg["frame_duration_us"]*.10)):
            if abs(finite(metadata[key], key)-target) > tolerance:
                faults.append("camera_control_changed_"+key)
        if len(metadata["ColourGains"]) != 2 or any(abs(finite(a, "colour gain")-b) > .05 for a, b in zip(metadata["ColourGains"], cfg["colour_gains"])):
            faults.append("camera_colour_gains_changed")
    except (KeyError, ValueError, TypeError):
        faults.append("camera_metadata_missing_or_invalid")
    return sorted(set(faults))
