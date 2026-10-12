"""Checked exports for new experimental parts, separate from frozen releases."""

import hashlib
from pathlib import Path

import cadquery as cq
import numpy as np
import trimesh


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def yz_prism(polygon, x, thickness):
    work = cq.Workplane("YZ",origin=(x,0,0)).polyline(list(polygon.exterior.coords)[:-1]).close()
    for ring in polygon.interiors:
        work = work.polyline(list(ring.coords)[:-1]).close()
    return work.extrude(thickness).val()


def x_cylinder(x,length,y,z,radius):
    return cq.Solid.makeCylinder(radius,length,cq.Vector(x,y,z),cq.Vector(1,0,0))


def block(x0,x1,y0,y1,z0,z1):
    return cq.Workplane("XY").box(x1-x0,y1-y0,z1-z0,centered=(False,False,False)).translate((x0,y0,z0)).val()


def export_part(shape,name,directory,parts,purpose,material,kind="fabricate"):
    shape = shape.clean()
    if not shape.isValid() or len(shape.Solids()) != 1 or shape.Volume() <= 0:
        raise ValueError(f"Invalid or disconnected prototype part: {name}")
    folder = directory/"cad"
    folder.mkdir(parents=True,exist_ok=True)
    step,stl = folder/f"{name}.step",folder/f"{name}.stl"
    cq.exporters.export(shape,str(step))
    cq.exporters.export(shape,str(stl),tolerance=.03,angularTolerance=.1)
    check = cq.importers.importStep(str(step)).val()
    mesh = trimesh.load_mesh(stl,process=True)
    if not check.isValid() or abs(check.Volume()-shape.Volume()) > max(.001,shape.Volume()*.001):
        raise ValueError(f"STEP round-trip failed: {name}")
    if not mesh.is_watertight or mesh.volume <= 0:
        raise ValueError(f"Invalid mesh: {name}")
    parts.append({
        "id":name,"purpose":purpose,"material":material,"kind":kind,
        "step":"cad/"+step.name,"stl":"cad/"+stl.name,
        "sha256_step":digest(step),"sha256_stl":digest(stl),
        "volume_mm3":shape.Volume(),"bounds_mm":mesh.bounds.tolist(),
        "checks":{"valid_single_solid":True,"step_roundtrip":True,"watertight_stl":True},
        "physical_fit_tested":False,
    })
    return mesh


def packed(mesh,name,group,color,explosion=(0,0,0)):
    return {"name":name,"group":group,"color":color,"explosion":list(explosion),
            "vertices":np.round(mesh.vertices,4).tolist(),"faces":mesh.faces.tolist()}
