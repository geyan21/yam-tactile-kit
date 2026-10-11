#!/usr/bin/python3
"""Screen FB1 ideal load coupling and expose limits before hardware qualification."""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/force-button-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from tactile_kit.records import execution
from force_button_mechanics import CONFIG, geometry, guide, support_compliance, solve, contact_sites
from screen_f1_feedback import digest


def main():
    cfg = json.loads(CONFIG.read_text())
    m = cfg["mechanism"]
    reference = geometry(cfg)["reference_native_mm"]
    sites = contact_sites(cfg)
    inputs = [CONFIG, Path(__file__), ROOT / "engineering/scripts/force_button_mechanics.py",
              ROOT / cfg["basis"]["root_interface"], ROOT / cfg["basis"]["contact_sites"],
              ROOT / "engineering/designs/l1.json"]
    folder = ROOT / "build/engineering/prototypes/force_button/screens" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Model FB1 ideal six-axis guide/support coupling, stop motion and sensitivity; retain the distinction from measured sensor accuracy and hardware performance") as record:
        folder.mkdir(parents=True, exist_ok=False)
        for source in inputs:
            target = folder / "inputs" / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        stiffness, _ = guide(cfg)
        preload_q = np.linalg.solve(stiffness, [0., 0., -m["preload_sensor_force_n_assumed"], 0., 0., 0.])
        checks = {"symmetry": abs(stiffness-stiffness.T).max(),
                    "smallest_eigenvalue": float(np.linalg.eigvalsh(stiffness)[0]),
                    "normal_to_torque_coupling": abs(stiffness[2, 3:]).max(),
                    "backup_compliance_mm_per_n": support_compliance(cfg)[0]}
        if checks["symmetry"] >= 1e-7 or checks["smallest_eigenvalue"] <= 0:
            raise ValueError("Guide stiffness is not a symmetric positive system")
        results = []
        for sensor_c in cfg["mechanism"]["sensor_compliance_mm_per_n_cases"]:
            unit = solve(cfg, np.array([0., 0., 1., 0., 0., 0.]), sensor_c)
            nominal_gain = unit["sensor_increment"]
            for site in sites:
                force = np.array([0., 0., cfg["normal_force_target_n"]])
                arm = site["point"]-reference
                wrench = np.r_[force, np.cross(arm, force)]
                solved = solve(cfg, wrench, sensor_c)
                result = {"site": site["id"], "sensor_compliance_mm_per_n": sensor_c,
                          "force_model_input_n": force[2],
                          "sensor_increment_n": solved["sensor_increment"],
                          "modeled_preloaded_sensor_n": solved["sensor_increment"]+m["preload_sensor_force_n_assumed"],
                          "ideal_gain": nominal_gain, "modeled_normal_force_n": solved["sensor_increment"]/nominal_gain,
                          "ideal_change_of_contact_location_error_n": abs(solved["sensor_increment"]/nominal_gain-force[2]),
                          "translation_mm": solved["q"][:3].tolist(), "rotation_radians": solved["q"][3:].tolist(),
                          "additional_motion_at_contact_mm": np.linalg.norm(solved["q"][:3]+np.cross(solved["q"][3:], arm)),
                          "backup_pitch_deg": math.degrees(solved["backup_pitch_radians"]),
                          "reaction_error_n": float(np.max(np.abs(solved["reaction_residual"]))),
                          "stop_displacements_mm": []}
                for angle in m["stop_angles_deg"]:
                    theta = math.radians(angle)
                    r = np.array([m["stop_radius_mm"]*math.cos(theta), m["stop_radius_mm"]*math.sin(theta),
                                 m["fixed_stop_bottom_z_mm"]-reference[2]])
                    result["stop_displacements_mm"].append((solved["q"][:3]+np.cross(solved["q"][3:], r))[2])
                result["would_reach_minimum_stop_gap"] = bool(max(result["stop_displacements_mm"]) >= m["overload_gap_mm_target"]-m["overload_gap_tolerance_mm"])
                result["ideal_stress_check"] = []
                for leaf in solved["leaves"]:
                    end = leaf["local_stiffness"] @ leaf["mapping"] @ (solved["q"]+preload_q)
                    # Fixed-end bending moments include the force lever arm.
                    root_m = end[3:]+np.cross([m["guide_active_length_mm"], 0, 0], end[:3])
                    axial = abs(end[0])/(leaf["width"]*leaf["thickness"])
                    bending = 6*abs(root_m[1])/(leaf["width"]*leaf["thickness"]**2)+6*abs(root_m[2])/(leaf["thickness"]*leaf["width"]**2)
                    inertia = leaf["width"]*leaf["thickness"]**3/12
                    pinned_euler = math.pi**2*m["guide_young_mpa_assumed"]*inertia/m["guide_active_length_mm"]**2
                    result["ideal_stress_check"].append({"leaf": leaf["index"],
                                                       "root_axial_plus_bending_mpa_with_assumed_preload": axial+bending,
                                                       "axial_force_n": end[0],
                                                       "pinned_euler_load_n": pinned_euler})
                results.append(result)
        # Reference-point placement and one-leaf thickness perturbations expose
        # coupling hidden by the perfectly symmetric nominal model.
        sensitivity = []
        for sensor_offset in ((.25, 0, 0), (0, .25, 0), (0, -.25, 0)):
            for leaf_scale in (.95, 1.05):
                scales = [leaf_scale, 1., 1., 1.]
                selected = sites[0]
                force = np.array([0., 0., 20.])
                wrench = np.r_[force, np.cross(selected["point"]-reference, force)]
                result = solve(cfg, wrench, .00025, scales, sensor_offset)
                gain = solve(cfg, np.array([0., 0., 1., 0., 0., 0.]), .00025, scales, sensor_offset)["sensor_increment"]
                apparent = result["sensor_increment"]/gain
                sensitivity.append({"one_leaf_thickness_scale": leaf_scale, "sensor_offset_mm": list(sensor_offset),
                                    "apparent_normal_n": apparent, "error_n": abs(apparent-20)})
        checks["maximum_reaction_error_n"] = max(r["reaction_error_n"] for r in results)
        if checks["maximum_reaction_error_n"] > 1e-6:
            raise ValueError("Force/moment equilibrium failed")
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
        for sensor_c in cfg["mechanism"]["sensor_compliance_mm_per_n_cases"]:
            rows = [r for r in results if sensor_c == r["sensor_compliance_mm_per_n"]]
            axes[0].plot([r["site"] for r in rows], [r["additional_motion_at_contact_mm"] for r in rows], marker="o",
                        label=f"{sensor_c*20*1000:g} µm sensor motion at 20 N")
            axes[1].plot([r["site"] for r in rows], [r["sensor_increment_n"] for r in rows], marker="o")
        axes[0].axhline(.1, color="red", linestyle="--", label="Provisional 0.1 mm screen")
        axes[0].set(ylabel="Model-added motion at contact (mm)")
        axes[1].set(ylabel="Model force increment at FMA (N)")
        for ax in axes:
            ax.tick_params(axis="x", rotation=25)
            ax.grid(alpha=.25)
        axes[0].legend(fontsize=8)
        fig.suptitle("FB1 ideal guide/support screen at 20 N\n"
                     "No carrier, joint, sensor-accuracy or physical validation", fontsize=12)
        for suffix in ("png", "pdf", "svg"):
            fig.savefig(folder / ("mechanical_screen."+suffix), dpi=160)
        plt.close(fig)
        report = {"schema": "yam-fb1-mechanical-screen/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "reference_native_mm": reference.tolist(), "guide_stiffness": stiffness.tolist(),
                  "assumed_unloaded_preload_displacement": preload_q.tolist(),
                  "checks": checks, "cases": results, "sensitivity": sensitivity,
                  "limits": ["Small-deflection, ideal-clamp beam model; carriers, fasteners, slip, contact and original finger deformation are omitted.",
                             "The backing and sensor displacement cases are assumptions, not a measured assembly law.",
                             "Stops, preload, guide buckling, fatigue and sensor alignment require complete geometry and independent structural/physical checks.",
                             "No factory-error, noise, contact reliability or 20 N installed qualification follows from this ideal force-recovery model."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "cases": len(results),
                            "maximum_added_contact_motion_mm": max(r["additional_motion_at_contact_mm"] for r in results),
                            "maximum_contact_location_error_n": max(r["ideal_change_of_contact_location_error_n"] for r in results),
                            "maximum_perturbed_error_n": max(r["error_n"] for r in sensitivity),
                            "minimum_stop_gap_reached": sum(r["would_reach_minimum_stop_gap"] for r in results),
                            "guide_normal_stiffness_n_per_mm": stiffness[2, 2], **checks}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
