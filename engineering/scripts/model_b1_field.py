#!/usr/bin/python3
"""Screen B1 field range and displacement sensitivity; never infer force from CAD."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/b1"


def cylinder_field(points, center, axis, radius, height, remanence, radial_order=12, angular_order=48):
    """Uniform cylinder, magnetic surface poles; exterior field in tesla.

    Lengths share millimeter units. Gauss-Legendre radial quadrature and uniform
    azimuth integration evaluate Br/(4*pi)*integral(r/|r|^3)dA on both ends.
    This excludes steel, neighboring jaws, eddy currents and magnet variation.
    """
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    helper = np.array([0., 1., 0.]) if abs(axis[1]) < .9 else np.array([0., 0., 1.])
    u = np.cross(axis, helper); u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    nodes, weights = np.polynomial.legendre.leggauss(radial_order)
    radii = (nodes + 1) * radius / 2
    angles = np.arange(angular_order) * (2 * np.pi / angular_order)
    disk = (radii[:, None, None] * (np.cos(angles)[None, :, None] * u +
                                  np.sin(angles)[None, :, None] * v)).reshape(-1, 3)
    area = np.repeat(weights * radius / 2 * radii * (2 * np.pi / angular_order), angular_order)
    result = np.zeros((len(points), 3))
    for sign in (-1, 1):
        poles = np.asarray(center) + disk + sign * axis * height / 2
        delta = np.asarray(points)[:, None, :] - poles[None, :, :]
        distance = np.linalg.norm(delta, axis=2)
        if np.min(distance) < 0.1:
            raise ValueError("Field query too close to the pole surface")
        result += sign * np.sum(delta / distance[:, :, None] ** 3 * area[None, :, None], axis=1)
    return result * remanence / (4 * np.pi)


def main():
    config = json.loads((ROOT / "engineering/designs/b1.json").read_text())
    plan = json.loads((OUTPUT / "b1_manifest.json").read_text())
    magnets = config["magnet"]
    centers = np.array([entry["native_xyz_mm"] for entry in plan["magnet_locations"]])
    sensors = np.array([entry["die_center_native_mm"] for entry in plan["sensor_poses"]])
    rotations = np.array([entry["rotation_sensor_to_native"] for entry in plan["sensor_poses"]])

    def field(center, axis=(1., 0., 0.), **options):
        return cylinder_field(sensors, center, axis, magnets["diameter_mm"]/2,
                             magnets["thickness_mm"], magnets["remanence_nominal_t"], **options)

    def local(native):
        return np.einsum("sji,sj->si", rotations, native) * 1e6

    with execution(ROOT / "build/records", "Screen B1 nominal magnetic geometry with a finite-cylinder field model; no force or hardware performance claim") as record:
        fields = np.array([field(center) for center in centers])
        baseline = fields.sum(axis=0)
        counts = []
        couplings = []
        derivative_per_magnet = []
        displacement = np.arange(-1., 2.0001, .05)
        curves = []
        jacobian = np.zeros((15, 12))
        for index, center in enumerate(centers):
            angle = np.deg2rad(plan["magnet_locations"][index]["front_tangent_angle_deg"])
            directions = np.array([[1, 0, 0], [0, np.cos(angle), np.sin(angle)],
                                  [0, -np.sin(angle), np.cos(angle)]], dtype=float)
            # Tactile motion is unknown until measured; these are independent
            # geometric perturbations, not a deformation prediction under load.
            own_changes = []
            for axis_index, direction in enumerate(directions):
                finite_difference = local(field(center + .01*direction) - field(center - .01*direction)) / .02
                jacobian[:, index*3+axis_index] = finite_difference.reshape(-1)
                own_changes.append(float(np.linalg.norm(finite_difference[index])))
            derivative_per_magnet.append({
                "magnet": f"M{index}", "directions": ["side_x", "surface_tangent", "surface_inward"],
                "direction_unit_vectors_native": directions.tolist(),
                "own_sensor_derivative_ut_per_mm": own_changes,
            })
            own_curve = []
            for offset in displacement:
                changed = baseline - fields[index] + field(center + offset * directions[2])
                own_curve.append(float(np.linalg.norm(local(changed - baseline)[index])))
                counts.append(local(changed))
            curves.append(own_curve)
            # Also screen +/-2 mm independently along each native displacement
            # direction and +/-10 degree magnet-axis rotation about Y/Z.
            for direction in directions:
                for amount in (-2, 2):
                    counts.append(local(baseline - fields[index] + field(center + amount*direction)))
            for angle_deg in (-10, 10):
                radians = np.deg2rad(angle_deg)
                for axis in ([np.cos(radians), np.sin(radians), 0],
                             [np.cos(radians), 0, np.sin(radians)]):
                    counts.append(local(baseline - fields[index] + field(center, axis)))
            own = fields[index, index]
            matrix = [float(np.linalg.norm(value)) for value in fields[index]]
            couplings.append({"magnet": f"M{index}", "field_magnitude_ut_at_each_sensor": np.array(matrix)*1e6,
                           "reference_to_own_ratio": float(np.linalg.norm(fields[index, 4])/np.linalg.norm(own))})
        peak = np.max(np.abs(np.array(counts)), axis=0)
        model_error = max(np.linalg.norm(field(center) - field(center, radial_order=24, angular_order=96))
                               for center in centers)
        onaxis = cylinder_field([[7, 0, 0]], [0, 0, 0], [1, 0, 0], 1.5, 1, 1.395)[0, 0]
        closed_form = 1.395/2 * (7.5/np.sqrt(7.5**2+1.5**2)-6.5/np.sqrt(6.5**2+1.5**2))
        if model_error > 1e-8 or abs(onaxis-closed_form) > 1e-6:
            raise ValueError("Cylinder quadrature check failed")
        singular = np.linalg.svd(jacobian, compute_uv=False)
        result = {
            "evidence_kind": "calculated_geometry_only", "force_calibrated": False,
            "model": "Uniformly magnetized finite cylinders, air, pole-surface quadrature",
            "magnet_nominal_remanence_t": magnets["remanence_nominal_t"],
            "magnet_centers_native_mm": centers.tolist(), "sensor_die_allowance_native_mm": sensors.tolist(),
            "nominal_local_field_ut": local(baseline).tolist(),
            "individual_perturbation_peak_abs_field_ut": peak.tolist(),
            "screened_motion": "Each magnet independently: -1..2 mm inward; +/-2 mm along side/tangent/inward; +/-10 degree Y/Z tilt. Other magnets fixed.",
            "sensor_to_paired_magnet_distance_mm": [float(np.linalg.norm(sensors[i]-centers[i])) for i in range(4)],
            "derivatives": derivative_per_magnet,
            "cross_coupling": [{**row, "field_magnitude_ut_at_each_sensor": row["field_magnitude_ut_at_each_sensor"].tolist()} for row in couplings],
            "jacobian_singular_values_ut_per_mm": singular.tolist(),
            "jacobian_condition_number": float(singular[0]/singular[-1]),
            "quadrature_convergence_max_ut": float(model_error*1e6),
            "analytic_axial_check_relative_error": float(abs(onaxis-closed_form)/abs(closed_form)),
            "limits": ["No force-to-displacement model; no 20 N rating or contact threshold.",
                       "No steel, motor field, second jaw, manufacturing tolerance, creep or temperature simulation.",
                       "Perturbations do not establish mechanical travel or collision clearance.",
                       "Die position is an allowance, not a verified internal package location.",
                       "Reference sensor observes embedded magnets too; subtraction cannot isolate arbitrary external fields."],
        }
        (OUTPUT / "field_screen.json").write_text(json.dumps(result, indent=2) + "\n")
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
        for index, values in enumerate(curves):
            axes[0].plot(displacement, values, label=f"M{index} → S{index}")
        axes[0].set_xlabel("Assumed single-magnet inward displacement (mm)")
        axes[0].set_ylabel("Change in own sensor vector (µT)")
        axes[0].set_title("Geometry screen · no force mapping")
        axes[0].legend(); axes[0].grid(alpha=.2)
        image = axes[1].imshow(np.abs(jacobian), aspect="auto", cmap="viridis")
        axes[1].set_xlabel("Independent magnet displacement directions")
        axes[1].set_ylabel("Sensor axis")
        axes[1].set_xticks(np.arange(1,12,3), labels=[f"M{i}" for i in range(4)])
        axes[1].set_yticks(np.arange(1,15,3), labels=[f"S{i}" for i in range(5)])
        axes[1].set_title("Coupling · µT per unit millimeter")
        fig.colorbar(image, ax=axes[1], shrink=.7)
        fig.suptitle("Calculated fields in air · unbuilt B1 · same-sign axial magnets")
        fig.savefig(OUTPUT / "field_screen.svg")
        plt.close(fig)
        record["screen"] = {key: result[key] for key in ("sensor_to_paired_magnet_distance_mm",
            "jacobian_condition_number", "quadrature_convergence_max_ut")}
        print(json.dumps(record["screen"], indent=2))
        print("Peak field including independent perturbations:", float(np.max(peak)), "µT")


if __name__ == "__main__":
    main()
