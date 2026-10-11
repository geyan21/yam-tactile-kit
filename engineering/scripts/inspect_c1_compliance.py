#!/usr/bin/python3
"""Separate C1's approximate carrier/beam compliance from an existing solved mesh."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
from structural_tools import tools,parse_node_tables
from tactile_kit.records import execution


def skew(v):
    x,y,z = v
    return np.array([[0,-z,y],[z,0,-x],[-y,x,0]])


def section_fit(gmsh,center,config,displacements):
    b = config["beam"]
    xyz = [];values = []
    for dy in (-b["width_mm"]*.4,0,b["width_mm"]*.4):
        for dz in (-b["thickness_mm"]*.4,0,b["thickness_mm"]*.4):
            point = center+np.array([0,dy,dz])
            _,kind,nodes,u,v,w = gmsh.model.mesh.getElementByCoordinates(*point,dim=3,strict=True)
            components,basis,orientations = gmsh.model.mesh.getBasisFunctions(kind,[u,v,w],"Lagrange")
            if components!=1 or orientations!=1:
                raise ValueError("Unexpected displacement basis")
            displacement = np.asarray(basis)@np.asarray([displacements[int(node)] for node in nodes])
            xyz.append(point-center);values.append(displacement)
    equations = np.vstack([np.column_stack((np.eye(3),-skew(p))) for p in xyz])
    answer = np.linalg.lstsq(equations,np.asarray(values).reshape(-1),rcond=None)[0]
    return answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run",type=Path)
    args = parser.parse_args()
    folder = args.run.resolve()
    if not folder.is_relative_to(ROOT/"build/engineering/prototypes/c1/fea"):
        parser.error("Select a saved C1 structural run")
    cfg = json.loads((folder/"inputs/configuration.json").read_text())
    plan = json.loads((folder/"inputs/assembly_manifest.json").read_text())
    report = json.loads((folder/"screen.json").read_text())
    tables = [t for t in parse_node_tables(folder/"c1.dat") if t["kind"]=="U"]
    b = cfg["beam"]
    root = np.asarray(plan["root_reference_native_mm"])
    centers = [
        np.array([b["fixed_boundary_native_x_mm"]+.5,b["center_native_y_mm"],b["bottom_native_z_mm"]+b["thickness_mm"]/2]),
        np.array([b["fixed_boundary_native_x_mm"]+b["active_length_mm"]-.5,b["center_native_y_mm"],b["bottom_native_z_mm"]+b["thickness_mm"]/2]),
    ]
    with execution(ROOT/"build/records","Read an existing C1 solve and identify where its calculated added motion occurs; do not rerun or alter the experiment") as record:
        gmsh,_,_ = tools()
        gmsh.initialize([],readConfigFiles=False,run=False)
        gmsh.option.setNumber("General.Terminal",0)
        try:
            gmsh.open(str(folder/"mesh.msh"))
            modes = []
            for i,table in enumerate(tables):
                scale = report["forces_and_moments"][i]["applied_scale_n_or_nmm"]
                modes.append([section_fit(gmsh,center,cfg,table["rows"])/scale for center in centers])
            rows = []
            for site,case in zip(plan["contact_sites"],report["contact_cases_20n"]):
                p = np.asarray(site["native_xyz_mm"]);wrench = np.asarray(case["wrench_about_root_n_nmm"])
                q0 = np.asarray([m[0] for m in modes]).T@wrench
                q1 = np.asarray([m[1] for m in modes]).T@wrench
                fixed = q0[:3]+np.cross(q0[3:],p-centers[0])
                free = q1[:3]+np.cross(q1[3:],p-centers[1])
                total = np.asarray(case["added_tip_displacement_mm"])
                rows.append({"id":site["id"],"fixed_path_normal_mm":fixed[2],
                             "beam_normal_mm":float((free-fixed)[2]),"floating_path_normal_mm":float((total-free)[2]),
                             "total_normal_mm":total[2]})
            result = {"evidence_kind":"linear_FEA_decomposition","rows":rows,
                      "limits":"Rigid-section fits 0.5 mm inside each active end; warping is not fully represented. Values describe this ideal bonded model only."}
            (folder/"compliance_decomposition.json").write_text(json.dumps(result,indent=2)+"\n")
            record["decomposition"] = result
            print(json.dumps(rows,indent=2))
        finally:
            gmsh.finalize()


if __name__=="__main__":
    main()
