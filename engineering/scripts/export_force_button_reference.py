"""Export the FMA envelope, removing only collapsed zero-area STL pole facets."""

from pathlib import Path

import cadquery as cq
import numpy as np
import trimesh
from prototype_cad import digest


def export_reference(shape, name, folder, parts, purpose, material, kind):
    if name != "fb1_fma25_envelope":
        raise ValueError("This repair is restricted to the FMA reference sphere")
    shape = shape.clean()
    if not shape.isValid() or len(shape.Solids()) != 1 or shape.Volume() <= 0:
        raise ValueError("Invalid native sensor envelope")
    destination = folder / "cad"; destination.mkdir(exist_ok=True)
    raw_dir = folder / "reference_tessellation"; raw_dir.mkdir(exist_ok=True)
    step = destination / (name+".step")
    stl = destination / (name+".stl")
    raw = raw_dir / (name+"_raw.stl")
    cq.exporters.export(shape, str(step))
    cq.exporters.export(shape, str(raw), tolerance=.03, angularTolerance=.1)
    mesh = trimesh.load_mesh(raw, process=True)
    faces = mesh.faces
    collapsed = (faces[:, 0] == faces[:, 1]) | (faces[:, 0] == faces[:, 2]) | (faces[:, 1] == faces[:, 2])
    if np.sum(collapsed) > 2 or np.any(mesh.area_faces[collapsed] != 0):
        raise ValueError("Unexpected tessellation fault; do not change geometry to mask it")
    mesh.update_faces(~collapsed)
    mesh.remove_unreferenced_vertices()
    if not mesh.is_watertight or mesh.volume <= 0:
        raise ValueError("Sensor STL has a remaining topological fault")
    mesh.export(stl)
    restored = trimesh.load_mesh(stl, process=True)
    native = cq.importers.importStep(str(step)).val()
    if (not restored.is_watertight or not native.isValid() or
            abs(native.Volume()-shape.Volume()) > 1e-6 or
            abs(restored.volume-shape.Volume()) > shape.Volume()*.001):
        raise ValueError("Sensor STEP/STL round trip failed")
    parts.append({"id": name, "purpose": purpose, "material": material, "kind": kind,
                  "step": "cad/"+step.name, "stl": "cad/"+stl.name,
                  "sha256_step": digest(step), "sha256_stl": digest(stl),
                  "volume_mm3": shape.Volume(), "bounds_mm": restored.bounds.tolist(),
                  "checks": {"valid_single_solid": True, "step_roundtrip": True, "watertight_stl": True},
                  "tessellation_cleanup": {"collapsed_zero_area_facets_removed": int(np.sum(collapsed)),
                                            "raw_file": str(raw.relative_to(folder)), "raw_sha256": digest(raw),
                                            "scope": "No vertex moved, hole filled or positive-area face removed; native STEP is unchanged"},
                  "physical_fit_tested": False})
    return restored
