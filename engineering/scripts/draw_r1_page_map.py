#!/usr/bin/python3
"""Draw R1's six sensing locations from its released meshes and nail cut patterns."""

import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union
from tactile_kit.records import execution

COLORS=["#c66d31","#d9982f","#268479","#44958a","#648e41","#907ca8"]


def path(points,transform):
    return "M"+"L".join(f"{x:.2f},{y:.2f}" for x,y in (transform(*point) for point in points))+"Z"


def polygons(component):
    triangles=np.asarray(component["vertices"])[np.asarray(component["faces"])][:,:,[1,2]]
    shapes=[Polygon(triangle) for triangle in triangles if Polygon(triangle).area>1e-8]
    shape=unary_union(shapes).buffer(.001).buffer(-.001)
    return [shape] if shape.geom_type=="Polygon" else list(shape.geoms)


def main():
    release=ROOT/"engineering/release"
    model=json.loads((release/"models.json").read_text())[0]
    r1=json.loads((release/"r1/r1_manifest.json").read_text())
    contact=json.loads((release/"contact_regions/contact_report.json").read_text())
    tip=contact["hard_tip_native_y_mm"]
    def side(y,z):return 55+(y-tip)*6.3,363-(z+4.4)*6.3
    def nail(u,v):return 1074+u*10,304-v*10
    with execution(ROOT/"build/records","Draw R1's actual six cell locations for its separate design page; no CAD modification") as record:
        svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 560" role="img" aria-labelledby="title desc">',
             '<title id="title">R1: two nail cells and four compliant-pad cells</title>',
             '<desc id="desc">CH0 and CH1 occupy the two object-facing nail prongs. CH2 through CH5 follow the four TPU contact regions on their conformal saddles.</desc>',
             '<rect width="1280" height="560" fill="white"/>',
             '<g font-family="sans-serif" fill="#203f46">',
             '<text x="28" y="36" font-size="26" font-weight="bold">R1 · six independent pressure-film cells</text>',
             '<text x="28" y="65" font-size="17">CH0 / CH1 on the hard nail · CH2–CH5 on conformal saddles along the soft contact surface</text>',
             '<rect x="20" y="90" width="852" height="385" rx="12" fill="#f5f8f4"/>',
             '<rect x="888" y="90" width="372" height="385" rx="12" fill="#f5f8f4"/>',
             '<text x="40" y="120" font-size="20" font-weight="bold">Side view · four soft-region cells</text>',
             '<text x="908" y="120" font-size="19" font-weight="bold">Nail · object-facing view</text>']
        for group,color in (("frame","#c3cece"),("tpu","#d9e3c7"),("saddles","#abc4ae")):
            for component in model["components"]:
                if component["group"]!=group:continue
                for polygon in polygons(component):
                    d=path(polygon.exterior.coords,side)+"".join(path(ring.coords,side) for ring in polygon.interiors)
                    svg.append(f'<path d="{d}" fill="{color}" stroke="#889c95" stroke-width=".8" fill-rule="evenodd"/>')
        for component in model["components"]:
            if component["group"]!="laminate":continue
            number=int(component["name"][2])
            if number<2:continue
            projected=polygons(component)
            for polygon in projected:
                svg.append(f'<path d="{path(polygon.exterior.coords,side)}" fill="{COLORS[number]}" stroke="{COLORS[number]}" stroke-width="1.5"/>')
            center=max(projected,key=lambda p:p.area).centroid
            x,y=side(center.x,center.y)
            label_y=410 if number%2==0 else 441
            svg.append(f'<path d="M{x} {y}V{label_y-18}" stroke="{COLORS[number]}" stroke-width="1.5"/>')
            svg.append(f'<text x="{x}" y="{label_y}" text-anchor="middle" font-size="19" font-weight="bold">CH{number}</text>')
        tx,ty=side(-109,-3.8)
        svg.append(f'<path d="M{tx} {ty}L115 400" stroke="#a8602a" stroke-width="1.5"/>')
        svg.append('<text x="45" y="425" font-size="17">CH0 + CH1 on nail</text><text x="45" y="449" font-size="14">See contact-facing view →</text>')
        footprint=contact["nail_footprint"]
        svg.append(f'<path d="{path(footprint["outer"],nail)}" fill="#c3cece" stroke="#8d9a9b" stroke-width="1.5"/>')
        for cell in r1["nail_active_cells"]:
            number=cell["id"]
            svg.append(f'<path d="{path(cell["outer"],nail)}" fill="{COLORS[number]}" stroke="#a36634"/>')
            x=(1028,1120)[number]
            svg.append(f'<text x="{x}" y="254" text-anchor="middle" font-size="17" font-weight="bold" fill="white">CH{number}</text>')
        svg.append('<text x="1074" y="162" text-anchor="middle" font-size="14">Leading edge</text>')
        svg.append('<text x="1074" y="422" text-anchor="middle" font-size="16">Start with N0 on both prongs.</text>')
        svg.append('<text x="1074" y="449" text-anchor="middle" font-size="14">Leave the center notch open.</text>')
        svg.append('<text x="28" y="510" font-size="16">All six cells use separate conductive-film islands, copper electrodes and insulating backing.</text>')
        svg.append('<text x="28" y="540" font-size="14">Released R1 geometry and active cut regions. This map is not a cutting template; fabricate from the R1 cut sheet.</text></g></svg>')
        (ROOT/"engineering/web/r1-placement.svg").write_text("\n".join(svg)+"\n")
        record["source_sha256"]={name:hashlib.sha256((release/name).read_bytes()).hexdigest()
                                 for name in ("models.json","r1/r1_manifest.json","contact_regions/contact_report.json")}
        print("Generated R1 page map from six released sensing cells.")


if __name__=="__main__":main()
