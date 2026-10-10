"""Explicit-unit envelope calculations for a conceptual finger, not structural FEA."""

from __future__ import annotations

import math


# Limits guard the numerical exercise, not the engineering operating envelope.
RANGES = {
    "finger_length_mm": (10, 300),
    "face_width_mm": (1, 80),
    "nose_thickness_mm": (0.1, 30),
    "body_thickness_mm": (0.2, 60),
    "pad_length_mm": (1, 250),
    "pad_border_mm": (0, 10),
    "cell_pitch_mm": (0.25, 10),
    "pad_stack_mm": (0, 10),
    "pad_recess_mm": (0, 10),
    "sensor_force_n": (0.01, 1000),
    "allowed_adapter_deflection_mm": (0.001, 5),
    "station_spacing_mm": (0.1, 100),
    "contact_distance_mm": (0.2, 300),
    "applied_force_n": (0, 1000),
    "end_moment_nmm": (-10000, 10000),
    "mass_kg": (0, 100),
    "friction_coefficient": (0.01, 2),
    "static_load_factor": (1, 10),
}


def validate(design: dict) -> dict:
    if not isinstance(design, dict):
        raise ValueError("Design must be a JSON object")
    if isinstance(design.get("schema_version"), bool) or design.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    if design.get("geometry_status") not in {"illustrative", "measured_inputs"}:
        raise ValueError("geometry_status must be illustrative or measured_inputs")
    label = design.get("label")
    if not isinstance(label, str) or not label.strip() or len(label) > 100:
        raise ValueError("label must be 1–100 characters")
    cleaned = {key: design[key] for key in ("schema_version", "label", "geometry_status")}
    for key, (lower, upper) in RANGES.items():
        value = design.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number")
        if not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f"{key} must be finite and between {lower} and {upper}")
        cleaned[key] = float(value)
    if cleaned["nose_thickness_mm"] > cleaned["body_thickness_mm"]:
        raise ValueError("Nose thickness cannot exceed body thickness")
    if cleaned["pad_length_mm"] > cleaned["finger_length_mm"]:
        raise ValueError("Pad length cannot exceed finger length")
    if not cleaned["station_spacing_mm"] < cleaned["contact_distance_mm"] <= cleaned["finger_length_mm"]:
        raise ValueError("Contact must lie beyond both stations and within finger length")
    if cleaned["pad_recess_mm"] >= cleaned["body_thickness_mm"]:
        raise ValueError("Pad recess must be less than body thickness")
    return cleaned


def evaluate(design: dict) -> dict:
    d = validate(design)
    usable_w = max(0.0, d["face_width_mm"] - 2 * d["pad_border_mm"])
    usable_l = max(0.0, d["pad_length_mm"] - 2 * d["pad_border_mm"])
    cols = math.floor((usable_w + 1e-10) / d["cell_pitch_mm"])
    rows = math.floor((usable_l + 1e-10) / d["cell_pitch_mm"])
    if cols * rows == 0:
        cols = rows = 0
    force = d["applied_force_n"]
    distance = d["contact_distance_mm"]
    spacing = d["station_spacing_mm"]
    m1 = force * distance + d["end_moment_nmm"]
    m2 = force * (distance - spacing) + d["end_moment_nmm"]
    required_force = d["mass_kg"] * 9.80665 * d["static_load_factor"] / (
        2 * d["friction_coefficient"]
    )
    issues = []
    if cols == 0:
        issues.append("No full sensing cell fits after the assumed borders.")
    if d["applied_force_n"] > d["sensor_force_n"]:
        issues.append("Applied force exceeds the entered sensor range.")
    if required_force > d["sensor_force_n"]:
        issues.append("Static support estimate exceeds the entered per-jaw sensor range.")
    if cols > 16 or rows > 32:
        issues.append("Layout exceeds the cited 16-column × 32-row example scanner envelope.")
    return {
        "schema_version": 1,
        "geometry_status": d["geometry_status"],
        "hardware_validated": False,
        "columns": cols,
        "rows": rows,
        "taxels": cols * rows,
        "electrode_nets": cols + rows if cols else 0,
        "active_width_mm": cols * d["cell_pitch_mm"],
        "active_length_mm": rows * d["cell_pitch_mm"],
        "opening_loss_mm": 2 * max(0, d["pad_stack_mm"] - d["pad_recess_mm"]),
        "minimum_adapter_stiffness_n_per_mm": d["sensor_force_n"] / d["allowed_adapter_deflection_mm"],
        "required_static_force_per_jaw_n": required_force,
        "moment_1_nmm": m1,
        "moment_2_nmm": m2,
        "recovered_normal_force_n": (m1 - m2) / spacing,
        "single_station_fixed_lever_force_n": m1 / d["finger_length_mm"],
        "force_range_remaining_n": d["sensor_force_n"] - required_force,
        "issues": issues,
        "scope": "Envelope arithmetic and ideal static force balance; not CAD fit, FEA, sensor accuracy, or an actuator guarantee.",
    }
