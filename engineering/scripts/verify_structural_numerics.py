#!/usr/bin/python3
"""Check mesh export, solver displacements and strain sampling against a uniform-strain patch."""

from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"] = str(ROOT/"build/engineering/tools/cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
from structural_tools import tools,create_mesh,write_set,run_solver,parse_node_tables,axial_strain_sampler,sample_strain,digest
from tactile_kit.records import execution


def main():
    output = ROOT/"build/engineering/prototypes/c1/fea/numerical_verification"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Verify the structural pipeline with a known affine strain field; this produces no physical hardware evidence") as record:
        gmsh,binary,manifest = tools()
        gmsh.initialize([],readConfigFiles=False,run=False)
        gmsh.option.setNumber("General.Terminal",0)
        gmsh.model.add("affine_patch")
        gmsh.model.occ.addBox(0,0,0,8,6,4)
        gmsh.model.occ.synchronize()
        gmsh.write(str(output/"patch.step"))
        gmsh.finalize()
        try:
            tags,xyz,mesh = create_mesh(gmsh,output/"patch.step",output,1.2)
            matrix = np.array([[2e-4,3e-5,0],[0,-6.6e-5,2e-5],[-1e-5,0,-6.6e-5]])
            expected = xyz@matrix.T
            on_surface = np.any(np.isclose(xyz,0,atol=1e-7)|np.isclose(xyz,[8,6,4],atol=1e-7),axis=1)
            deck = "** Uniform strain patch, numerical verification only.\n*INCLUDE,INPUT=mesh.inp\n"
            deck += write_set("OUTPUT",tags)
            deck += "*MATERIAL,NAME=AL\n*ELASTIC\n69000,0.33\n*SOLID SECTION,ELSET=SOLID,MATERIAL=AL\n"
            deck += "*STEP\n*STATIC\n*BOUNDARY\n"
            for tag,u in zip(tags[on_surface],expected[on_surface]):
                for i,value in enumerate(u):
                    deck += f"{int(tag)},{i+1},{i+1},{value:.12g}\n"
            deck += "*NODE PRINT,NSET=OUTPUT\nU\n*END STEP\n"
            (output/"patch.inp").write_text(deck)
            run_solver(binary,output,"patch",record,60)
            tables = [t for t in parse_node_tables(output/"patch.dat") if t["kind"]=="U"]
            if len(tables)!=1:
                raise ValueError("Patch output table missing")
            measured = tables[0]["rows"]
            actual = np.asarray([measured[int(tag)] for tag in tags])
            max_error = float(np.max(np.abs(actual-expected)))
            samples = [([2.3,1.7,.01],.25),([4.7,3.1,.01],.25),([2.3,1.7,3.99],.25),([4.7,3.1,3.99],.25)]
            average = sample_strain(axial_strain_sampler(gmsh,tags,xyz,samples),measured)
            strain_error = abs(average-2e-4)
            if max_error>1e-6 or strain_error>1e-8:
                raise ValueError(f"Affine patch failed: {max_error}, {strain_error}")
            result = {
                "evidence_kind":"numerical_verification_only","physical_specimens_tested":0,
                "mesh":mesh,"expected_uniform_exx":2e-4,"measured_uniform_exx":average,
                "max_nodal_displacement_error_mm":max_error,"relative_strain_error":strain_error/2e-4,
                "passed":True,"tools":manifest,"source_hashes":{name:digest(ROOT/name) for name in (
                    "engineering/scripts/structural_tools.py","engineering/scripts/verify_structural_numerics.py")},
                "limits":"Verifies the mesh/export/solver/strain-sampler pipeline on an exact affine field. It does not validate real joints, materials or force-sensor performance.",
            }
            (output/"verification.json").write_text(json.dumps(result,indent=2)+"\n")
            (output.parent/"latest.json").write_text(json.dumps({"directory":output.name,"sha256":digest(output/"verification.json")},indent=2)+"\n")
            record["verification"] = result
            print(json.dumps({"passed":True,"max_nodal_error_mm":max_error,"relative_strain_error":result["relative_strain_error"]},indent=2))
        finally:
            gmsh.finalize()


if __name__=="__main__":
    main()
