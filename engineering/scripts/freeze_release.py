#!/usr/bin/python3
"""Publish a reviewable geometry snapshot and real mesh viewer data, without bench claims."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"]=str(ROOT/"build/engineering/tools/cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import cadquery as cq
import numpy as np
from shapely.geometry import Polygon
import trimesh

from analyze_baseline_meshes import PARTS
from build_r1_parts import polygon_solid
from tactile_kit.records import execution

RELEASE=ROOT/"engineering/release"
COLORS=["#c66d31","#e5a44f","#268479","#44958a","#74a04a","#907ca8"]


def packed(mesh,name,group,color,explosion=(0,0,0)):
    return {"name":name,"group":group,"color":color,"explosion":list(explosion),
        "vertices":np.round(mesh.vertices,4).tolist(),"faces":mesh.faces.tolist()}


def mesh_from_solid(solid,directory,name):
    path=directory/f"{name}.stl"
    cq.exporters.export(solid,str(path),tolerance=.06,angularTolerance=.12)
    return trimesh.load_mesh(path,process=True)


def main():
    with execution(ROOT/"build/records","Freeze verified geometry outputs, generate real-mesh visuals, and record source hashes for publication") as record:
        r1=ROOT/"build/engineering/r1"
        plan=json.loads((r1/"r1_manifest.json").read_text())
        contact=json.loads((ROOT/"build/engineering/contact_regions/contact_report.json").read_text())
        RELEASE.mkdir(parents=True,exist_ok=True)
        shutil.copytree(r1,RELEASE/"r1",dirs_exist_ok=True)
        for folder,files in {
            "baseline":["geometry_report.json","baseline_projections.png","baseline_assembly.png","section_profiles.svg"],
            "contact_regions":["contact_report.json","contact_regions.svg","tpu_contact_unroll.csv"],
            "interfaces":["interface_report.json","nail_thickness.svg"],
        }.items():
            target=RELEASE/folder;target.mkdir(exist_ok=True)
            for filename in files:
                shutil.copyfile(ROOT/"build/engineering"/folder/filename,target/filename)
        components=[
            packed(trimesh.load_mesh(PARTS["hard_frame"],process=True),"Original PETG frame","frame","#657c89"),
            packed(trimesh.load_mesh(PARTS["soft_insert"],process=True),"Original TPU insert","tpu","#a8bd80"),
        ]
        with tempfile.TemporaryDirectory(prefix="yam-r1-mesh-",dir=ROOT/"build") as temporary:
            temporary=Path(temporary)
            for pad in plan["pads"]:
                number=pad["id"]
                mesh=trimesh.load_mesh(r1/f"cad/pad_{number}_saddle_witness.stl",process=True)
                # Tooling coordinates are native Y, native Z, then extrusion width.
                mesh.apply_transform(np.array([[0,0,1,pad["assembly_native_x_limits_mm"][0]],
                                               [1,0,0,0],[0,1,0,0],[0,0,0,1]],dtype=float))
                components.append(packed(mesh,f"CH{number} cast saddle","saddles",COLORS[number],(0,0,-8)))
                front=np.asarray(pad["front_curve_native_yz_mm"])
                slope=np.gradient(front[:,1],front[:,0])
                normal=np.column_stack((slope,-np.ones(len(slope))))
                normal/=np.linalg.norm(normal,axis=1)[:,None]
                outside=front+normal*.3
                polygon=Polygon(np.vstack((front,outside[::-1]))).simplify(.004,preserve_topology=True)
                solid=polygon_solid(polygon,pad["width_mm"])
                film=mesh_from_solid(solid,temporary,f"film-{number}")
                film.apply_transform(np.array([[0,0,1,pad["assembly_native_x_limits_mm"][0]],
                                                [1,0,0,0],[0,1,0,0],[0,0,0,1]],dtype=float))
                components.append(packed(film,f"CH{number} laminate envelope","laminate",COLORS[number],(0,0,-16)))
            transform=np.eye(4)
            transform[:3,0]=contact["nail_plane_u_axis_native"]
            transform[:3,1]=contact["nail_plane_v_axis_native"]
            transform[:3,2]=contact["nail_plane_outward_normal_native"]
            transform[:3,3]=np.asarray(contact["nail_plane_origin_native_mm"])+.1*transform[:3,2]
            for cell in plan["nail_active_cells"]:
                solid=polygon_solid(Polygon(cell["outer"]),.3)
                mesh=mesh_from_solid(solid,temporary,f"nail-{cell['id']}")
                mesh.apply_transform(transform)
                components.append(packed(mesh,f"CH{cell['id']} nail laminate","laminate",COLORS[cell["id"]],(0,0,-16)))
        models=[{
            "id":"assembly","title":"Actual ENPIRE frame with R1 saddle and laminate shapes",
            "coordinates":"native_mm","components":components,
            "note":"Baseline meshes and designed interface geometry. Laminate display shows shape and allowance, not internal copper layers or physical sensor readings.",
        }]
        for part in plan["parts"]:
            mesh=trimesh.load_mesh(r1/part["stl"],process=True)
            models.append({
                "id":part["id"],"title":part["id"].replace("_"," "),
                "coordinates":"tool_mm","components":[packed(mesh,part["purpose"],"tool","#d4aa72")],
                "note":part["print_note"],
            })
        (RELEASE/"models.json").write_text(json.dumps(models,separators=(",",":"))+"\n")
        (RELEASE/"NOTICE.md").write_text(
            "# Geometry attribution\n\nOriginal ENPIRE finger: Wenli Xiao / NVIDIA ENPIRE.\n"
            "Original model: https://makerworld.com/en/models/2984746-gripper-finger-for-robot-arm#profileId-3349177\n"
            "Original metadata license code: BY. Retain original attribution and terms.\n"
            "Visualization inputs retrieved from the pinned community YAM baseline; see engineering/docs/GEOMETRY.md.\n"
            "Changes: added independent sensor-shape visualizations, new saddle and cover tooling, coupon tools, and fit gauge.\n"
            "These are digital designs; no physical performance is asserted.\n"
        )
        dependencies=[
            "engineering/designs/r1.json","engineering/scripts/build_r1_parts.py",
            "engineering/scripts/analyze_baseline_meshes.py","engineering/scripts/analyze_contact_regions.py",
            "engineering/scripts/measure_interfaces.py","engineering/scripts/freeze_release.py",
            "engineering/scripts/prepare_environment.py","engineering/scripts/collect_geometry_sources.py",
            "engineering/requirements.lock",
        ]
        source_hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in dependencies}
        files={
            str(path.relative_to(RELEASE)):hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(RELEASE.rglob("*")) if path.is_file() and path.name!="release_manifest.json"
        }
        manifest={
            "revision":"R1.0","requested_per_finger_force_n":20,
            "physical_specimens_tested":0,"hardware_status":"awaiting fabrication and measurement",
            "digital_geometry_checks":plan["checks"],
            "source_hashes":source_hashes,"files":files,
        }
        (RELEASE/"release_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        record["snapshot"]={"files":len(files),"models":len(models),"digital_checks":plan["checks"]}
        print(json.dumps(record["snapshot"],indent=2))


if __name__=="__main__":
    main()
