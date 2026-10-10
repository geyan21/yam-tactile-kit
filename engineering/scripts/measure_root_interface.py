#!/usr/bin/python3
"""Extract real rear mounting planes from the ENPIRE frame for the force adapter."""

import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union
import trimesh

from analyze_baseline_meshes import PARTS
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/l1"


def describe_polygon(polygon):
    return {"area_mm2":polygon.area,"bounds_mm":list(polygon.bounds),
            "outer":list(polygon.exterior.coords),"holes":[list(r.coords) for r in polygon.interiors]}


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Measure the actual ENPIRE rear mounting plane, locating feature, and bolt-hole geometry") as record:
        mesh=trimesh.load_mesh(PARTS["hard_frame"],process=True)
        normals=mesh.face_normals
        candidates=(normals[:,1]>.999)&(mesh.triangles_center[:,1]>-20)
        planes={}
        for index in np.flatnonzero(candidates):
            y=round(float(mesh.triangles_center[index,1]),7)
            planes.setdefault(y,[]).append(index)
        groups=[]
        for y,indices in planes.items():
            region=unary_union([Polygon(mesh.triangles[index][:,[0,2]]) for index in indices])
            polygons=[region] if region.geom_type=="Polygon" else [p for p in region.geoms if p.geom_type=="Polygon"]
            if not polygons:continue
            groups.append({"native_y_mm":y,"area_mm2":sum(p.area for p in polygons),
                "regions":[describe_polygon(p) for p in polygons]})
        groups.sort(key=lambda item:item["area_mm2"],reverse=True)
        if not groups:raise ValueError("No rear-facing root plane found")
        mount=groups[0]
        figure,axes=plt.subplots(1,min(3,len(groups)),figsize=(12,4),constrained_layout=True)
        for axis,group in zip(np.atleast_1d(axes),groups[:3]):
            for region in group["regions"]:
                points=np.asarray(region["outer"]);axis.fill(points[:,0],points[:,1],color="#bccbb7")
                for ring in region["holes"]:
                    points=np.asarray(ring);axis.fill(points[:,0],points[:,1],color="white")
            axis.set_aspect("equal");axis.set_xlabel("Native X (mm)");axis.set_ylabel("Native Z (mm)")
            axis.set_title(f"Rear-facing surface: Y = {group['native_y_mm']:.4f} mm")
        figure.savefig(OUTPUT/"root_interface.svg");figure.savefig(OUTPUT/"root_interface.png",dpi=180)
        result={
            "source_mesh":str(PARTS["hard_frame"].relative_to(ROOT)),
            "mount_plane":mount,"other_rear_planes":groups[1:],
            "bolt_centers_native_xz_mm":[[-20.7108135565,14.2832396625],[.2891864694,14.2832396625]],
            "force_target_n":20,
            "distal_lever_from_mount_mm":abs(float(mesh.bounds[0,1])-mount["native_y_mm"]),
            "maximum_normal_load_moment_at_mount_nm":20*abs(float(mesh.bounds[0,1])-mount["native_y_mm"])/1000,
            "cautions":["The maker's exact original-file identity and physical mount remain to be checked.",
                        "The load moment is calculated for a normal 20 N load at the distal bound; it is not a strength rating."],
        }
        (OUTPUT/"root_interface.json").write_text(json.dumps(result,indent=2)+"\n")
        record["planes"]=[{k:v for k,v in group.items() if k!="regions"} for group in groups]
        print(json.dumps({"planes":record["planes"],"distal_lever_mm":result["distal_lever_from_mount_mm"],
            "normal_20n_moment_nm":result["maximum_normal_load_moment_at_mount_nm"]},indent=2))


if __name__=="__main__":
    main()
