"""O1 CAD export with explicitly bounded cleanup of STL precision artifacts."""

import json
from pathlib import Path
import shutil

import cadquery as cq
import numpy as np
from scipy.spatial import cKDTree
import trimesh
from prototype_cad import export_part as standard_export, digest


def export_part(shape, name, directory, parts, purpose, material, kind="fabricate"):
    try:
        return standard_export(shape, name, directory, parts, purpose, material, kind)
    except ValueError as error:
        if str(error) != f"Invalid mesh: {name}":
            raise
    step, stl = directory/"cad"/(name+".step"), directory/"cad"/(name+".stl")
    original = trimesh.load_mesh(stl, process=True)
    # This only coalesces coincident tessellation vertices and removes their
    # duplicate/zero-area triangles. It does not fill holes, close gaps, move
    # a CAD surface, or substitute a new solid for an invalid STEP.
    candidate = original.copy()
    candidate.merge_vertices(digits_vertex=5)
    candidate.update_faces(candidate.unique_faces())
    candidate.update_faces(candidate.nondegenerate_faces(height=1e-8))
    candidate.remove_unreferenced_vertices()
    max_displacement = float(cKDTree(candidate.vertices).query(original.vertices)[0].max())
    volume_delta = float(abs(candidate.volume-original.volume))
    valid = (candidate.is_watertight and candidate.is_winding_consistent and candidate.volume > 0
             and candidate.body_count == 1 and max_displacement <= 0.00005
             and volume_delta <= max(.001, abs(original.volume)*1e-5))
    diagnostics = directory/"mesh_diagnostics"
    diagnostics.mkdir(exist_ok=True)
    raw = diagnostics/(name+".unprocessed.stl")
    shutil.copyfile(stl, raw)
    report = {"method": "Merge vertices at 5 decimal places; remove duplicate/degenerate triangles only",
              "source_stl_sha256": digest(raw), "source_vertices": len(original.vertices), "source_faces": len(original.faces),
              "result_vertices": len(candidate.vertices), "result_faces": len(candidate.faces),
              "max_original_vertex_displacement_mm": max_displacement, "max_allowed_displacement_mm": .00005,
              "volume_change_mm3": volume_delta, "watertight": bool(candidate.is_watertight),
              "consistent_winding": bool(candidate.is_winding_consistent), "connected_bodies": int(candidate.body_count),
              "passed": bool(valid)}
    (diagnostics/(name+".json")).write_text(json.dumps(report, indent=2)+"\n")
    if not valid:
        raise ValueError(f"Unresolved O1 mesh topology: {name}: {report}")
    candidate.export(stl)
    mesh = trimesh.load_mesh(stl, process=True)
    check = cq.importers.importStep(str(step)).val()
    if (not mesh.is_watertight or not mesh.is_winding_consistent or mesh.body_count != 1 or mesh.volume <= 0
            or not check.isValid() or len(check.Solids()) != 1):
        raise ValueError("O1 normalized mesh/STEP round-trip failed")
    parts.append({"id": name, "purpose": purpose, "material": material, "kind": kind,
                  "step": "cad/"+step.name, "stl": "cad/"+stl.name,
                  "sha256_step": digest(step), "sha256_stl": digest(stl),
                  "volume_mm3": check.Volume(), "bounds_mm": mesh.bounds.tolist(),
                  "checks": {"valid_single_solid": True, "step_roundtrip": True, "watertight_stl": True,
                             "bounded_mesh_normalization": report},
                  "physical_fit_tested": False})
    return mesh
