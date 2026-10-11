#!/usr/bin/python3
"""Preserve the failed B3 frame export and inspect its mesh boundary."""

from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"]=str(ROOT/"build/engineering/tools/cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import cadquery as cq
import numpy as np
import trimesh
from tactile_kit.records import execution
from prototype_cad import digest

WORK=ROOT/"build/engineering/prototypes/recessed"


def main():
    with execution(ROOT/"build/records","Inspect and preserve only the failed B3 frame mesh and its input geometry; no source or published prototype is altered") as record:
        output=WORK/"failed_exports"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        output.mkdir(parents=True,exist_ok=False)
        for name in ("recessed_hard_frame.step","recessed_hard_frame.stl"):
            shutil.copyfile(WORK/"cad"/name,output/name)
        for path in (ROOT/"engineering/designs/recessed.json",ROOT/"engineering/scripts/build_recessed_parts.py"):
            shutil.copyfile(path,output/path.name)
        shape=cq.importers.importStep(str(output/"recessed_hard_frame.step")).val()
        mesh=trimesh.load_mesh(output/"recessed_hard_frame.stl",process=True)
        counts=np.bincount(mesh.edges_unique_inverse,minlength=len(mesh.edges_unique))
        bad=mesh.edges_unique[counts!=2]
        points=mesh.vertices[bad]
        lengths=np.linalg.norm(points[:,1]-points[:,0],axis=1)
        result={"schema":"yam-b3-export-inspection/1","evidence_kind":"CAD_and_mesh_diagnostic",
                "source_step_sha256":digest(output/"recessed_hard_frame.step"),
                "step_valid":shape.isValid(),"step_solids":len(shape.Solids()),"step_volume_mm3":shape.Volume(),
                "mesh_watertight":bool(mesh.is_watertight),"mesh_volume_mm3":float(mesh.volume),
                "mesh_vertices":len(mesh.vertices),"mesh_faces":len(mesh.faces),
                "bad_edges":len(bad),"boundary_edges":int(np.sum(counts==1)),
                "nonmanifold_edges":int(np.sum(counts>2)),
                "bad_edge_lengths_mm":lengths.tolist(),
                "bad_edge_coordinates_mm":points.tolist(),
                "bad_edge_incidence_counts":counts[counts!=2].tolist()}
        (output/"inspection.json").write_text(json.dumps(result,indent=2)+"\n")
        record["inspection_directory"]=str(output.relative_to(ROOT))
        record["inspection"]={key:result[key] for key in result if key not in ("bad_edge_coordinates_mm","bad_edge_lengths_mm","bad_edge_incidence_counts")}
        print(json.dumps(record["inspection"],indent=2))
        if len(points):
            print("Bad-edge bounding box:",np.array([points.min(axis=(0,1)),points.max(axis=(0,1))]).tolist())
            print("Longest bad edge:",float(lengths.max()))


if __name__=="__main__":
    main()
