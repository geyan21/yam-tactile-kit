"""Scoped Gmsh/CalculiX helpers for explicit linear structural screens."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tools():
    manifest = json.loads((ROOT/"build/engineering/tools/fea/tools.json").read_text())
    binary = ROOT/manifest["calculix"]
    if digest(binary) != manifest["calculix_sha256"]:
        raise ValueError("Cached CalculiX executable changed")
    sys.path.insert(0,str(ROOT/manifest["gmsh_python_directory"]))
    import gmsh
    if gmsh.__version__ != manifest["versions"]["gmsh"]:
        raise ValueError("Unexpected Gmsh version")
    return gmsh,binary,manifest


def write_set(name,values):
    values = [int(v) for v in values]
    lines = [f"*NSET,NSET={name}"]
    lines += [",".join(map(str,values[i:i+16])) for i in range(0,len(values),16)]
    return "\n".join(lines)+"\n"


def run_solver(binary,folder,job,record,timeout=240):
    argv = [str(binary),"-i",job]
    env = dict(os.environ)
    env.update({"OMP_NUM_THREADS":"1","CCX_NPROC_RESULTS":"1","CCX_NPROC_EQUATION_SOLVER":"1"})
    manifest = json.loads((ROOT/"build/engineering/tools/fea/tools.json").read_text())
    runtime = str(ROOT/manifest["runtime_library_directory"])
    env["LD_LIBRARY_PATH"] = runtime+(os.pathsep+env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    start = time.monotonic()
    with (folder/f"{job}.log").open("w") as stream:
        process = subprocess.Popen(argv,cwd=folder,env=env,stdout=stream,stderr=subprocess.STDOUT)
        item = {"argv":argv,"pid":process.pid,"cwd":str(folder)}
        record.setdefault("solver_runs",[]).append(item)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            item["intentional_stop"] = f"{timeout}s limit for this owned structural solve"
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)
            raise
        item.update({"returncode":code,"elapsed_s":round(time.monotonic()-start,3)})
    log = (folder/f"{job}.log").read_text(errors="replace")
    if code or "*ERROR" in log.upper() or "segmentation" in log.lower() or not (folder/f"{job}.dat").exists():
        raise RuntimeError("CalculiX did not complete:\n"+log[-6000:])
    return item


def parse_node_tables(path):
    """Read complete displacement and force tables from NODE PRINT ASCII output."""
    tables = []
    current = None
    pattern = re.compile(r"^\s*(\d+)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s*$")
    with path.open() as stream:
        for line in stream:
            lower = line.lower()
            if ("displacements" in lower or "forces" in lower) and "for set" in lower and "time" in lower:
                current = {"kind":"U" if "displacements" in lower else "RF","heading":line.strip(),"rows":{}}
                tables.append(current)
                continue
            match = pattern.match(line)
            if match and current is not None:
                current["rows"][int(match.group(1))] = [float(match.group(i).replace("D","E").replace("d","e")) for i in (2,3,4)]
            elif line.strip() and not line.lstrip().startswith(("number","node")):
                current = None
    return tables


def create_mesh(gmsh,step_path,folder,size,physical_name="SOLID",refinements=None):
    gmsh.initialize([],readConfigFiles=False,run=False)
    gmsh.option.setNumber("General.Terminal",0)
    gmsh.option.setNumber("General.NumThreads",1)
    gmsh.model.add("structural_screen")
    volumes = gmsh.model.occ.importShapes(str(step_path))
    gmsh.model.occ.synchronize()
    if len([v for v in volumes if v[0]==3]) != 1:
        raise ValueError("Expected one bonded analysis solid")
    group = gmsh.model.addPhysicalGroup(3,[tag for dim,tag in volumes if dim==3])
    gmsh.model.setPhysicalName(3,group,physical_name)
    for name,value in {
        "Mesh.MeshSizeMin":size*.35,"Mesh.MeshSizeMax":size,
        "Mesh.MeshSizeFromPoints":0,"Mesh.MeshSizeFromCurvature":0,
        "Mesh.MeshSizeExtendFromBoundary":0,"Mesh.Algorithm3D":1,
        "Mesh.ElementOrder":2,"Mesh.SecondOrderLinear":0,"Mesh.SaveAll":0,
    }.items():
        gmsh.option.setNumber(name,value)
    fields = []
    for region in refinements or []:
        tag = gmsh.model.mesh.field.add("Box")
        for key,value in region.items():
            gmsh.model.mesh.field.setNumber(tag,key,value)
        fields.append(tag)
    if fields:
        gmsh.option.setNumber("Mesh.MeshSizeMin",min(size*.35,*[r["VIn"] for r in refinements]))
        minimum = gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(minimum,"FieldsList",fields)
        gmsh.model.mesh.field.setAsBackgroundMesh(minimum)
    gmsh.model.mesh.generate(3)
    gmsh.model.mesh.optimize("HighOrder")
    tags,coordinates,_ = gmsh.model.mesh.getNodes()
    tags = np.asarray(tags,dtype=np.int64)
    coordinates = np.asarray(coordinates).reshape(-1,3)
    element_types,element_tags,_ = gmsh.model.mesh.getElements(3)
    if list(element_types)!=[11]:
        raise ValueError(f"Expected quadratic tetrahedra, got {element_types}")
    determinants = np.asarray(gmsh.model.mesh.getElementQualities(np.concatenate(element_tags),"minDetJac"))
    if not np.all(np.isfinite(determinants)) or min(determinants)<=0:
        raise ValueError(f"Mesh contains inverted elements after high-order optimization: {min(determinants)}")
    if len(tags)*3 > 400000:
        raise ValueError("Mesh exceeds the declared 400,000 displacement-DOF budget")
    gmsh.write(str(folder/"mesh.inp"))
    gmsh.write(str(folder/"mesh.msh"))
    if "C3D10" not in (folder/"mesh.inp").read_text():
        raise ValueError("Gmsh did not export CalculiX-compatible quadratic tetrahedra")
    return tags,coordinates,{"nodes":len(tags),"elements":sum(len(x) for x in element_tags),
                            "element":"C3D10","nominal_size_mm":size,
                            "local_refinement_regions":refinements or [],
                            "minimum_jacobian_determinant":float(min(determinants)),
                            "optimizer":"HighOrder"}


def axial_strain_sampler(gmsh,tags,coordinates,points):
    """Build d(Ux)/dx rows using Gmsh's own element basis and local coordinates."""
    by_id = {int(tag):i for i,tag in enumerate(tags)}
    rows = []
    for point,weight in points:
        _,element_type,node_tags,u,v,w = gmsh.model.mesh.getElementByCoordinates(*point,dim=3,strict=True)
        if element_type!=11:
            raise ValueError("Gauge sample is not in a quadratic tetrahedron")
        components,basis,orientations = gmsh.model.mesh.getBasisFunctions(element_type,[u,v,w],"GradLagrange")
        if components!=3 or orientations!=1:
            raise ValueError("Unexpected tetrahedral gradient basis")
        grad = np.asarray(basis).reshape(-1,3)
        indexes = np.asarray([by_id[int(tag)] for tag in node_tags],dtype=np.int64)
        xyz = coordinates[indexes]
        jacobian = xyz.T@grad
        if np.linalg.det(jacobian)<=0:
            raise ValueError("Inverted or degenerate element at a gauge sample")
        physical_gradient = grad@np.linalg.inv(jacobian)
        if abs(np.sum(physical_gradient[:,0]))>1e-8:
            raise ValueError("Shape gradients fail partition of unity")
        # Independent affine reproduction checks catch ordering/Jacobian mistakes.
        if abs(np.dot(xyz[:,0],physical_gradient[:,0])-1)>1e-8:
            raise ValueError("Shape gradients fail linear X reproduction")
        if abs(np.dot(xyz[:,1],physical_gradient[:,0]))>1e-8:
            raise ValueError("Shape gradients spuriously couple affine Y into d(Ux)/dx")
        rows.append({"node_tags":[int(t) for t in node_tags],"gradient_x":physical_gradient[:,0].tolist(),"weight":weight})
    return rows


def sample_strain(rows,displacements):
    return sum(row["weight"]*sum(displacements[tag][0]*gradient
                                for tag,gradient in zip(row["node_tags"],row["gradient_x"])) for row in rows)
