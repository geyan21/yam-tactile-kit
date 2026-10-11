"""Explicit small-deflection model of FB1's four-leaf guide and compliant backing."""

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "engineering/designs/force_button_fb1.json"


def skew(vector):
    x, y, z = vector
    return np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])


def rigid_map(offset):
    result = np.eye(6)
    result[:3, 3:] = -skew(offset)
    return result


def beam_end_matrix(length, width, thickness, young, poisson):
    """Fixed root, free-end six-DOF Timoshenko beam stiffness in local axes."""
    area = width*thickness
    iy = width*thickness**3/12
    iz = thickness*width**3/12
    shear = young/(2*(1+poisson))
    torsion = width*thickness**3*(1/3-.21*(thickness/width)*(1-thickness**4/(12*width**4)))
    stiffness = np.zeros((6, 6))
    stiffness[0, 0] = young*area/length
    stiffness[3, 3] = shear*torsion/length
    for displacement, rotation, inertia, sign in ((1, 5, iz, -1), (2, 4, iy, 1)):
        phi = 12*young*inertia/((5/6)*shear*area*length**2)
        factor = young*inertia/(1+phi)
        stiffness[displacement, displacement] = 12*factor/length**3
        stiffness[displacement, rotation] = stiffness[rotation, displacement] = sign*6*factor/length**2
        stiffness[rotation, rotation] = (4+phi)*factor/length
    return stiffness


def geometry(cfg):
    interface = json.loads((ROOT / cfg["basis"]["root_interface"]).read_text())
    m = cfg["mechanism"]
    root_y = interface["mount_plane"]["native_y_mm"]
    fixed_face = root_y-m["root_plate_thickness_mm"]-m["fixed_clamp_to_root_plate_gap_mm"]-m["guide_clamp_length_mm"]
    moving_face = fixed_face-m["guide_active_length_mm"]
    center = np.array([m["center_native_x_mm"], (fixed_face+moving_face)/2, m["guide_midplane_native_z_mm"]])
    return {"root_plane_y": root_y, "fixed_guide_boundary_y": fixed_face,
            "moving_guide_boundary_y": moving_face, "reference_native_mm": center}


def guide(cfg, thickness_scales=None):
    m = cfg["mechanism"]
    length = m["guide_active_length_mm"]
    # Local beam axes: length toward native -Y, width +X, thickness +Z.
    axes = np.array([[0., 1., 0.], [-1., 0., 0.], [0., 0., 1.]])
    rotation = np.zeros((6, 6))
    rotation[:3, :3] = axes.T
    rotation[3:, 3:] = axes.T
    total, leaves = np.zeros((6, 6)), []
    scales = thickness_scales or [1.]*4
    for index, (x, z) in enumerate((x, z) for z in m["guide_z_offsets_mm"] for x in m["guide_x_offsets_mm"]):
        thickness = m["guide_thickness_mm"]*scales[index]
        stiffness = beam_end_matrix(length, m["guide_width_mm"], thickness,
                                    m["guide_young_mpa_assumed"], m["guide_poisson_assumed"])
        offset = np.array([x, -length/2, z])
        mapping = rotation @ rigid_map(offset)
        total += mapping.T @ stiffness @ mapping
        leaves.append({"index": index, "offset": offset, "mapping": mapping,
                     "local_stiffness": stiffness, "width": m["guide_width_mm"], "thickness": thickness,
                     "axes": axes})
    return total, leaves


def support_compliance(cfg):
    m = cfg["mechanism"]
    length, overhang = m["sensor_support_active_length_mm"], m["sensor_load_overhang_mm"]
    inertia = m["sensor_support_width_mm"]*m["sensor_support_thickness_mm"]**3/12
    compliance = (length**3/3+overhang*length**2+overhang**2*length)/(m["sensor_support_young_mpa_assumed"]*inertia)
    rotation_per_n = (length**2/2+overhang*length)/(m["sensor_support_young_mpa_assumed"]*inertia)
    return compliance, rotation_per_n


def solve(cfg, wrench, sensor_compliance, thickness_scales=None, sensor_offset=(0, 0, 0)):
    stiffness, leaves = guide(cfg, thickness_scales)
    compliance, rotation = support_compliance(cfg)
    sensor_k = 1/(compliance+sensor_compliance)
    normal = np.array([0., 0., 1., sensor_offset[1], -sensor_offset[0], 0.])
    combined = stiffness+sensor_k*np.outer(normal, normal)
    q = np.linalg.solve(combined, wrench)
    sensor_increment = sensor_k*float(normal @ q)
    guide_force = stiffness @ q
    reaction_residual = np.asarray(wrench)-guide_force-normal*sensor_increment
    return {"q": q, "sensor_increment": sensor_increment,
            "guide_reaction": guide_force, "reaction_residual": reaction_residual,
            "normal_displacement": float(normal @ q),
            "backup_pitch_radians": rotation*sensor_increment,
            "leaves": leaves}


def contact_sites(cfg):
    source = json.loads((ROOT / cfg["basis"]["contact_sites"]).read_text())
    old = json.loads((ROOT / "engineering/designs/l1.json").read_text())["finger_shift_native_y_mm"]
    shift = np.array(cfg["mechanism"]["finger_translation_native_mm"], dtype=float)-[0, old, 0]
    return [{"id": site["id"], "point": np.array(site["native_xyz_mm"])+shift,
             "source_surface": site["surface"]} for site in source["sites"]]
