"""Recover a checked faceted solid from the pinned source mesh for frame revisions."""

import json
from pathlib import Path

import cadquery as cq
import numpy as np
import trimesh

from analyze_baseline_meshes import PARTS
from prototype_cad import digest

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT/"build/engineering/source_brep"


def load(part):
    """Read only a previously checked conversion matching the original source."""
    if part not in ("hard_frame","soft_insert"):
        raise ValueError("Select an original ENPIRE component")
    folder = OUTPUT/part
    report = json.loads((folder/"conversion.json").read_text())
    if digest(PARTS[part])!=report["source_sha256"] or digest(folder/"source.step")!=report["step_sha256"]:
        raise ValueError("Source-solid conversion is stale")
    shape = cq.importers.importStep(str(folder/"source.step")).val()
    if not shape.isValid() or len(shape.Solids())!=1:
        raise ValueError("Recovered source is not one valid solid")
    return shape,report


def convert(part):
    if part not in ("hard_frame","soft_insert"):
        raise ValueError("Select an original ENPIRE component")
    baseline = json.loads((ROOT/"engineering/release/baseline/geometry_report.json").read_text())["parts"][part]
    source = PARTS[part]
    if digest(source)!=baseline["sha256"]:
        raise ValueError("Unexpected source mesh")
    mesh = trimesh.load_mesh(source,process=True)
    if not mesh.is_volume or len(mesh.faces)>12000:
        raise ValueError("Expected a bounded, closed source component")
    folder = OUTPUT/part
    if (folder/"conversion.json").exists():
        _,report = load(part)
        return report
    folder.mkdir(parents=True,exist_ok=True)
    faces = []
    for index,triangle in enumerate(mesh.triangles):
        wire = cq.Wire.makePolygon([cq.Vector(*point) for point in triangle],close=True)
        faces.append(cq.Face.makeFromWires(wire))
        if (index+1)%2000==0:
            print(f"Recovered {index+1}/{len(mesh.faces)} source triangle faces",flush=True)
    shape = cq.Solid.makeSolid(cq.Shell.makeShell(faces)).clean()
    if not shape.isValid() or len(shape.Solids())!=1:
        raise ValueError("Source faces did not form one valid solid")
    error = abs(shape.Volume()-mesh.volume)
    if error>max(.001,mesh.volume*1e-6):
        raise ValueError("Source conversion changed the enclosed volume")
    box = shape.BoundingBox()
    bounds = np.array([[box.xmin,box.ymin,box.zmin],[box.xmax,box.ymax,box.zmax]])
    if np.max(np.abs(bounds-mesh.bounds))>1e-5:
        raise ValueError("Source conversion changed its bounds")
    step = folder/"source.step"
    cq.exporters.export(shape,str(step))
    restored = cq.importers.importStep(str(step)).val()
    if not restored.isValid() or len(restored.Solids())!=1 or abs(restored.Volume()-shape.Volume())>.001:
        raise ValueError("Source STEP round trip failed")
    report = {
        "schema":"yam-source-solid/1","part":part,"source_sha256":digest(source),
        "step_sha256":digest(step),"source_triangles":len(mesh.faces),"solid_faces":len(shape.Faces()),
        "source_volume_mm3":float(mesh.volume),"solid_volume_mm3":shape.Volume(),
        "volume_difference_mm3":float(error),"bounds_mm":bounds.tolist(),
        "checks":{"single_valid_solid":True,"source_volume_and_bounds":True,"step_roundtrip":True},
        "scope":"Faceted recovery of the pinned STL, not the original author's analytic CAD or a physical fit measurement.",
    }
    (folder/"conversion.json").write_text(json.dumps(report,indent=2)+"\n")
    return report
