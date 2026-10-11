#!/usr/bin/python3
"""Isolate native mesher failures and preserve N1 mesh stages for review."""

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["OPENBLAS_NUM_THREADS"]="1"
os.environ["OMP_NUM_THREADS"]="1"
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
from structural_tools import tools


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder",type=Path)
    args=parser.parse_args()
    folder=args.folder.resolve()
    if not folder.is_relative_to(ROOT/"build/engineering/prototypes/nail/fea"):
        parser.error("Select a generated N1 structural-run directory")
    request=json.loads((folder/"inputs/mesh_request.json").read_text())
    stages=[]
    def stage(name,**values):
        entry={"stage":name,"utc":datetime.now(timezone.utc).isoformat(),"pid":os.getpid(),**values}
        stages.append(entry)
        (folder/"mesh_stages.json").write_text(json.dumps(stages,indent=2)+"\n")
        print(json.dumps(entry),flush=True)
    gmsh,_,_=tools()
    gmsh.initialize([],readConfigFiles=False,run=False)
    gmsh.option.setNumber("General.Terminal",0)
    gmsh.option.setNumber("General.NumThreads",1)
    try:
        stage("started",request=request)
        gmsh.model.add("nail_structural_screen")
        volumes=gmsh.model.occ.importShapes(str(folder/"inputs/analysis.step"))
        gmsh.model.occ.synchronize()
        solids=[tag for dimension,tag in volumes if dimension==3]
        if len(solids)!=1:
            raise ValueError("Expected one ideal bonded nail solid")
        physical=gmsh.model.addPhysicalGroup(3,solids)
        gmsh.model.setPhysicalName(3,physical,"SOLID")
        size=request["global_mm"]
        settings={"Mesh.MeshSizeMin":min(size*.35,request["local_mm"]),"Mesh.MeshSizeMax":size,
                  "Mesh.MeshSizeFromPoints":0,"Mesh.MeshSizeFromCurvature":0,
                  "Mesh.MeshSizeExtendFromBoundary":0,"Mesh.Algorithm3D":1,
                  "Mesh.ElementOrder":2,"Mesh.SecondOrderLinear":0,"Mesh.SaveAll":0}
        for key,value in settings.items():
            gmsh.option.setNumber(key,value)
        fields=[]
        for region in request["refinements"]:
            field=gmsh.model.mesh.field.add("Box")
            for key,value in region.items():
                gmsh.model.mesh.field.setNumber(field,key,value)
            fields.append(field)
        combine=gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(combine,"FieldsList",fields)
        gmsh.model.mesh.field.setAsBackgroundMesh(combine)
        gmsh.model.mesh.generate(3)
        kinds,elements,connectivity=gmsh.model.mesh.getElements(3)
        if list(kinds)!=[11]:
            raise ValueError("Expected only C3D10-compatible quadratic tetrahedra")
        used=np.unique(np.concatenate(connectivity))
        count=len(used)
        if 3*count>400000:
            stage("resource_limit",nodes=count,displacement_dofs=3*count)
            raise ValueError("N1 mesh exceeds the existing 400,000 displacement-DOF limit")
        gmsh.option.setNumber("Mesh.SaveAll",1)
        gmsh.write(str(folder/"mesh_before_optimization.msh"))
        gmsh.option.setNumber("Mesh.SaveAll",0)
        stage("generated",nodes=count,elements=sum(len(values) for values in elements))
        algorithms={"direct":["HighOrder"],"elastic":["HighOrderElastic"],
                    "elastic-direct":["HighOrderElastic","HighOrder"]}[request["optimizer"]]
        all_elements=np.concatenate(elements)
        for algorithm in algorithms:
            stage("optimizer_started",algorithm=algorithm)
            gmsh.model.mesh.optimize(algorithm)
            determinants=np.asarray(gmsh.model.mesh.getElementQualities(all_elements,"minDetJac"))
            stage("optimizer_finished",algorithm=algorithm,minimum_jacobian=float(determinants.min()))
        determinants=np.asarray(gmsh.model.mesh.getElementQualities(all_elements,"minDetJac"))
        scaled=np.asarray(gmsh.model.mesh.getElementQualities(all_elements,"minSJ"))
        if not np.all(np.isfinite(determinants)) or determinants.min()<=0 or not np.all(np.isfinite(scaled)) or scaled.min()<=0:
            raise ValueError("N1 mesh still contains inverted or degenerate elements")
        volumes=np.asarray(gmsh.model.mesh.getElementQualities(all_elements,"volume"))
        metadata={"nodes":count,"elements":len(all_elements),"element":"C3D10","nominal_size_mm":size,
                  "local_refinement_regions":request["refinements"],"optimizer":request["optimizer"],
                  "minimum_jacobian_determinant":float(determinants.min()),
                  "minimum_sampled_scaled_jacobian":float(scaled.min()),
                  "reported_element_volume_sum_mm3":float(volumes.sum()),
                  "displacement_dof_limit":400000,"mesh_surface_elements_preserved":True}
        gmsh.write(str(folder/"mesh.inp"))
        if "C3D10" not in (folder/"mesh.inp").read_text():
            raise ValueError("Mesher did not export quadratic CalculiX volume elements")
        # Surface triangles are needed to reconstruct the pressure quadrature.
        # Keep them in MSH only; the solver deck contains volume elements only.
        gmsh.option.setNumber("Mesh.SaveAll",1)
        gmsh.write(str(folder/"mesh.msh"))
        (folder/"mesh_metadata.json").write_text(json.dumps(metadata,indent=2)+"\n")
        stage("complete",metadata=metadata)
    finally:
        gmsh.finalize()


if __name__=="__main__":
    main()
