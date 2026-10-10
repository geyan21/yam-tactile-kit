#!/usr/bin/python3
"""Recover the original TPU cross-section and anchor keep-outs for the separate B1 design."""

import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"]=str(ROOT/"build/engineering/tools/cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import cadquery as cq
import numpy as np
from shapely.geometry import Polygon
import trimesh

from analyze_baseline_meshes import PARTS,outer_profile
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/b1"


def original_profile():
    mesh=trimesh.load_mesh(PARTS["soft_insert"],process=True)
    outer,curves=outer_profile(mesh,0,-7.5)
    outer_polygon=Polygon(outer)
    holes=[]
    for curve in curves:
        candidate=Polygon(curve)
        if candidate.area<outer_polygon.area-.01 and outer_polygon.covers(candidate):
            holes.append(candidate)
    profile=Polygon(outer_polygon.exterior.coords,[list(hole.exterior.coords) for hole in holes])
    if not profile.is_valid:raise ValueError("Original TPU cross-section is not a valid polygon")
    return mesh,profile,holes


def extruded_profile(profile):
    # YZ plane has +X normal; source TPU spans native X=-15..0.
    work=cq.Workplane("YZ").polyline(list(profile.exterior.coords)[:-1]).close()
    for ring in profile.interiors:
        work=work.polyline(list(ring.coords)[:-1]).close()
    return work.extrude(15).translate((-15,0,0)).val()


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Measure original TPU anchor regions and verify its reconstructed extrusion before modifying the B1 insert") as record:
        mesh,profile,holes=original_profile()
        shape=extruded_profile(profile)
        error=abs(shape.Volume()-mesh.volume)/mesh.volume
        if not shape.isValid() or len(shape.Solids())!=1 or error>1e-5:
            raise ValueError(f"Original extrusion does not match the source volume: {error}")
        anchors=[];cavities=[]
        for index,hole in enumerate(holes):
            points=np.asarray(hole.exterior.coords)[:-1]
            matrix=np.column_stack((2*points,np.ones(len(points))))
            cy,cz,constant=np.linalg.lstsq(matrix,(points*points).sum(axis=1),rcond=None)[0]
            radius=float(np.sqrt(constant+cy*cy+cz*cz))
            radial_error=float(np.max(np.abs(np.linalg.norm(points-[cy,cz],axis=1)-radius)))
            item={"id":index,"area_mm2":hole.area,"bounds_yz_mm":list(hole.bounds),
                  "center_yz_mm":[float(cy),float(cz)],"radius_mm":radius,"radial_error_mm":radial_error}
            if radial_error<.015 and radius<4:
                anchors.append(item)
            else:
                cavities.append(item)
        result={
            "source_sha256":hashlib.sha256(PARTS["soft_insert"].read_bytes()).hexdigest(),
            "source_volume_mm3":float(mesh.volume),"reconstructed_volume_mm3":shape.Volume(),
            "relative_volume_error":error,"outer_yz":list(profile.exterior.coords),
            "holes_yz":[list(ring.coords) for ring in profile.interiors],
            "anchors":anchors,"cavities":cavities,
            "notes":["Source cross-section reconstructed, not a measured mechanical compliance result.",
                     "Retain anchor bores and surrounding material in the new TPU insert."],
        }
        r1=json.loads((ROOT/"engineering/release/r1/r1_manifest.json").read_text())
        placements=[]
        for pad in r1["pads"]:
            front=np.asarray(pad["front_curve_native_yz_mm"])
            center=float(front[:,0].mean())
            slope=float(np.polyfit(front[:,0]-center,front[:,0]*0+front[:,1],1)[0])
            center_z=float(np.polyfit(front[:,0]-center,front[:,1],1)[1])
            placements.append({"channel":pad["id"],"center_yz_mm":[center,center_z],
                            "tangent_angle_deg":float(np.rad2deg(np.arctan(slope))),
                            "center_y_limits_mm":[float(front[:,0].min()),float(front[:,0].max())]})
        result["r1_smoothed_contact_planes"]=placements
        (OUTPUT/"source_interface.json").write_text(json.dumps(result,indent=2)+"\n")
        record["relative_volume_error"]=error;record["anchor_count"]=len(anchors)
        print(json.dumps({"relative_volume_error":error,"anchors":anchors,"cavities":len(cavities),"contact_planes":placements},indent=2))


if __name__=="__main__":
    main()
