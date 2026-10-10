#!/usr/bin/python3
"""Measure nail contact patches, mounting sections, and TPU unroll coordinates."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
import numpy as np
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
import trimesh

from analyze_baseline_meshes import PARTS, outer_profile
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/contact_regions"


def rectangle_candidates(polygon):
    interior = polygon.buffer(-0.3)
    results = []
    for width, length in ((4,12),(6,12),(8,12),(8,16),(10,12),(12,14),(14,16)):
        best = None
        for x in np.arange(polygon.bounds[0]+width/2, polygon.bounds[2]-width/2+.01,.25):
            for y in np.arange(polygon.bounds[1]+length/2, polygon.bounds[3]-length/2+.01,.25):
                candidate = box(x-width/2,y-length/2,x+width/2,y+length/2)
                if interior.covers(candidate):
                    leading_gap = polygon.bounds[3]-(y+length/2)
                    if best is None or leading_gap < best["leading_gap_mm"]:
                        best = {"width_mm":width,"length_mm":length,"center_plane_uv":[float(x),float(y)],"leading_gap_mm":float(leading_gap)}
        results.append(best or {"width_mm":width,"length_mm":length,"fits":False})
    return results


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with execution(ROOT / "build/records", "Measure actual candidate contact regions and root sections for prototype interfaces") as record:
        hard=trimesh.load_mesh(PARTS["hard_frame"],process=True)
        soft=trimesh.load_mesh(PARTS["soft_insert"],process=True)
        distal = (hard.triangles_center[:,1] < soft.bounds[0,1]) & (hard.face_normals[:,2] < -.5)
        candidates_facets = []
        for facet in hard.facets:
            selected = facet[distal[facet]]
            if len(selected):
                candidates_facets.append((float(hard.area_faces[selected].sum()), selected))
        if not candidates_facets:
            raise RuntimeError("No forward-facing distal facet found")
        _, seed = max(candidates_facets,key=lambda item:item[0])
        normal=np.average(hard.face_normals[seed],axis=0,weights=hard.area_faces[seed])
        normal/=np.linalg.norm(normal)
        origin=np.average(hard.triangles_center[seed],axis=0,weights=hard.area_faces[seed])
        distances=np.max(np.abs((hard.triangles-origin)@normal),axis=1)
        flat=distal&((hard.face_normals@normal)>1-1e-5)&(distances<.02)
        u=np.array([1.,0.,0.]);u-=np.dot(u,normal)*normal;u/=np.linalg.norm(u)
        v=np.cross(normal,u)
        basis=np.column_stack((u,v))
        projected=(hard.triangles[flat]-origin)@basis
        polygons=[Polygon(triangle) for triangle in projected]
        planar=unary_union([p for p in polygons if p.area>1e-8])
        if planar.is_empty:
            raise RuntimeError("No distal planar contact patch found; inspect orientation")
        candidates=rectangle_candidates(planar)
        profile,curves=outer_profile(soft,0,-7.5)
        outer=Polygon(profile)
        sampled=[]
        for y in np.arange(outer.bounds[0]+.02,outer.bounds[2]-.02,.1):
            crossing=outer.intersection(LineString([(y,outer.bounds[1]-1),(y,outer.bounds[3]+1)]))
            if crossing.is_empty:
                continue
            coords=[]
            if hasattr(crossing,"geoms"):
                for geometry in crossing.geoms:
                    coords.extend(list(geometry.coords))
            else:
                coords=list(crossing.coords)
            sampled.append([float(y),min(point[1] for point in coords)])
        sampled=np.asarray(sampled)
        arc=np.concatenate(([0],np.cumsum(np.linalg.norm(np.diff(sampled,axis=0),axis=1))))
        with (OUTPUT/"tpu_contact_unroll.csv").open("w",newline="") as stream:
            writer=csv.writer(stream)
            writer.writerow(["arc_length_mm","native_y_mm","native_z_mm","surface_width_mm"])
            writer.writerows((float(s),float(p[0]),float(p[1]),15.0) for s,p in zip(arc,sampled))
        roots=[]
        for y in (-4,-8,-12,-16,-20):
            section=hard.section(plane_origin=[-7.5,y,14],plane_normal=[0,1,0])
            if section is None:
                continue
            loops=[]
            for curve in section.discrete:
                points=np.asarray(curve)[:,[0,2]]
                if len(points)<4 or np.linalg.norm(points[0]-points[-1])>1e-5:
                    continue
                p=Polygon(points)
                loops.append({"area_mm2":float(p.area),"centroid_xz":list(p.centroid.coords)[0],"bounds_xz":list(p.bounds),"points":points.tolist()})
            roots.append({"native_y_mm":y,"loops":loops})
        with (OUTPUT/"root_sections.json").open("w") as stream:
            json.dump(roots,stream,indent=2)
        result={
            "model_basis":"Retrieved community YAM baseline; original MakerWorld file sizes match; physical fit still requires verification.",
            "native_contact_normal_into_finger":[0,0,1],
            "native_distal_direction":[0,-1,0],
            "hard_tip_native_y_mm":float(hard.bounds[0,1]),
            "soft_distal_native_y_mm":float(soft.bounds[0,1]),
            "hard_only_distal_length_mm":float(soft.bounds[0,1]-hard.bounds[0,1]),
            "nail_plane_origin_native_mm":origin.tolist(),
            "nail_plane_outward_normal_native":normal.tolist(),
            "nail_plane_u_axis_native":u.tolist(),
            "nail_plane_v_axis_native":v.tolist(),
            "nail_selected_planarity_error_mm":float(distances[flat].max()),
            "nail_planar_area_mm2":float(planar.area),
            "nail_planar_bounds_uv":list(planar.bounds),
            "nail_footprint": {"outer":list(planar.exterior.coords),"holes":[list(r.coords) for r in planar.interiors]} if planar.geom_type=="Polygon" else None,
            "rectangular_pad_screen":candidates,
            "tpu_front_arc_length_mm":float(arc[-1]),
            "tpu_width_coordinates_mm":np.unique(np.round(soft.vertices[:,0],7)).tolist(),
            "cautions":[
                "Rectangle tests include 0.3 mm planar edge clearance only; laminate sealing, tail routing, and assembly tolerance are additional.",
                "The original TPU front has serrations; a smooth or segmented sensor seat must address their local bend radius.",
                "Only digital geometry has been measured. No sensing or material performance is inferred from these results.",
            ],
        }
        (OUTPUT/"contact_report.json").write_text(json.dumps(result,indent=2)+"\n")
        fig,axes=plt.subplots(1,2,figsize=(13,5),constrained_layout=True)
        geoms=[planar] if planar.geom_type=="Polygon" else list(planar.geoms)
        for polygon in geoms:
            points=np.asarray(polygon.exterior.coords)
            axes[0].fill(points[:,0],points[:,1],color="#ced8df")
            for ring in polygon.interiors:
                points=np.asarray(ring.coords);axes[0].fill(points[:,0],points[:,1],color="white")
        for candidate in candidates:
            if "center_plane_uv" not in candidate or candidate["width_mm"] not in (6,10):
                continue
            x,y=candidate["center_plane_uv"];w=candidate["width_mm"];l=candidate["length_mm"]
            points=np.asarray(box(x-w/2,y-l/2,x+w/2,y+l/2).exterior.coords)
            axes[0].plot(points[:,0],points[:,1],label=f"{w}×{l} mm")
        axes[0].set_aspect("equal");axes[0].legend();axes[0].grid(alpha=.2)
        axes[0].set_title("Measured hard-nail contact plane");axes[0].set_xlabel("Local U / width (mm)");axes[0].set_ylabel("Local V / distal (mm)")
        axes[1].plot(sampled[:,0],sampled[:,1],color="#518833")
        axes[1].set_aspect("equal");axes[1].grid(alpha=.2)
        axes[1].set_title("TPU front profile — flatten by arc length");axes[1].set_xlabel("Native Y (mm)");axes[1].set_ylabel("Native Z (mm)")
        fig.savefig(OUTPUT/"contact_regions.png",dpi=180)
        fig.savefig(OUTPUT/"contact_regions.svg")
        plt.close(fig)
        record["geometry_findings"]=result
        print(json.dumps({key:value for key,value in result.items() if key!="nail_footprint"},indent=2))


if __name__=="__main__":
    main()
