"""Geometry helpers for the separate thin-nail prototype."""

import json
from pathlib import Path

import cadquery as cq
import numpy as np
from shapely.geometry import Polygon

from prototype_cad import block

ROOT = Path(__file__).resolve().parents[2]


def basis():
    report = json.loads((ROOT/"engineering/release/contact_regions/contact_report.json").read_text())
    normal=-np.asarray(report["nail_plane_outward_normal_native"])
    # The recovered face has a numerical X-normal component around 5e-9.
    # Snap that noise to zero so the milled side faces and screws share an
    # exact native X axis; the change is below one micrometer over this part.
    plane = cq.Plane(origin=tuple(report["nail_plane_origin_native_mm"]),
                     xDir=(1,0,0),normal=(0,float(normal[1]),float(normal[2])))
    footprint = Polygon([(x,-v) for x,v in report["nail_footprint"]["outer"]])
    return plane,footprint,report


def native(shape,plane):
    return shape.moved(plane.location)


def local_x(native_x,plane):
    # Source nail's X axis agrees with native X to better than 1e-8.
    if abs(plane.xDir.x-1)>1e-8:
        raise ValueError("Unexpected source width-axis rotation")
    return native_x-plane.origin.x


def x_bore(start,end,y,z,diameter):
    return cq.Solid.makeCylinder(diameter/2,end-start,cq.Vector(start,y,z),cq.Vector(1,0,0))


def nail_solid(config,plane,footprint):
    n = config["nail"]
    x0,y0,x1,y1 = footprint.bounds
    result = cq.Workplane("XY").polyline(list(footprint.exterior.coords)[:-1]).close().extrude(n["thick_body_mm"]).val()
    cut_profile = [(y0-1,n["leading_thickness_mm"]),
                   (n["taper_ends_local_y_mm"],n["leading_thickness_mm"]),
                   (n["taper_starts_local_y_mm"],n["thick_body_mm"]),
                   (y1+1,n["thick_body_mm"]),(y1+1,n["thick_body_mm"]+30),
                   (y0-1,n["thick_body_mm"]+30)]
    taper = cq.Workplane("YZ",origin=(x0-1,0,0)).polyline(cut_profile).close().extrude(x1-x0+2).val()
    result = result.cut(taper)
    centers = [local_x(value,plane) for value in n["web_native_x_centers_mm"]]
    half = n["web_thickness_mm"]/2
    free,fixed = n["web_free_end_local_y_mm"],n["web_fixed_boundary_local_y_mm"]
    z0 = n["web_lower_local_z_mm"];z1 = z0+n["web_height_mm"]
    front0,front1 = n["front_crossbar_local_y_mm"]
    crossbar = block(centers[0]-half,centers[1]+half,front0,front1,n["thick_body_mm"]-.5,z1)
    result = result.fuse(crossbar)
    blocks = []
    for index,center in enumerate(centers):
        web = block(center-half,center+half,free,fixed,z0,z1)
        inner = center+(half if index==0 else -half)
        outer = inner+(-1 if index==0 else 1)*n["clamp_block_thickness_mm"]
        clamp = block(min(inner,outer),max(inner,outer),fixed,fixed+n["clamp_end_length_mm"],z0,z1)
        result = result.fuse(web,clamp)
        blocks.append({"index":index,"inner_x":inner,"outer_x":outer,
                       "center_x":center,"local_y_range":[free,fixed],
                       "local_z_range":[z0,z1]})
    return result.clean(),blocks
