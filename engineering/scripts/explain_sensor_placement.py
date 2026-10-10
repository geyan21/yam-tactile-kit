#!/usr/bin/python3
"""Explain the released sensor choices and positions without changing any CAD."""

import csv
import hashlib
import json
from pathlib import Path
import sys
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union
from tactile_kit.records import execution

WEB=ROOT/"engineering/web"
RELEASE=ROOT/"engineering/release"


def path(points,transform):
    pairs=[transform(*point) for point in points]
    return "M"+"L".join(f"{x:.2f},{y:.2f}" for x,y in pairs)+"Z"


def main():
    with execution(ROOT/"build/records","Generate a clearly labeled sensor-placement guide from the unchanged B1 and R1 release geometry") as record:
        plan=json.loads((RELEASE/"b1/b1_manifest.json").read_text())
        interface=json.loads((RELEASE/"b1/source_interface.json").read_text())
        contact=json.loads((RELEASE/"contact_regions/contact_report.json").read_text())
        r1=json.loads((RELEASE/"r1/r1_manifest.json").read_text())
        model=json.loads((RELEASE/"b1/models.json").read_text())[0]
        tip=contact["hard_tip_native_y_mm"]
        rows=[]
        description=("Distal soft region","Second soft region","Raised middle region","Proximal soft region")
        for i,(magnet,sensor) in enumerate(zip(plan["magnet_locations"],plan["sensor_poses"])):
            m=np.array(magnet["native_xyz_mm"]);s=np.array(sensor["die_center_native_mm"])
            rows.append({"region":description[i],"magnet":magnet["id"],"head":sensor["id"],
                         "magnet_from_tip_mm":float(m[1]-tip),"head_from_tip_mm":float(s[1]-tip),
                         "magnet_center_native_xyz_mm":m.tolist(),"sensor_die_native_xyz_mm":s.tolist(),
                         "center_distance_mm":float(np.linalg.norm(s-m)),
                         "pcb_top_origin_native_mm":sensor["pcb_top_origin_native_mm"],
                         "rotation_sensor_to_native":sensor["rotation_sensor_to_native"]})
        reference=plan["sensor_poses"][4]
        source_paths=["b1/b1_manifest.json","b1/models.json","r1/r1_manifest.json","contact_regions/contact_report.json"]
        result={"basis":"Published B1 and R1 geometry; no mechanical redesign",
                "distance_definition":"Native Y displacement from hard nail tip, not contact-surface arc length",
                "pairs":rows,"reference":reference,"nail_cells":r1["nail_active_cells"],
                "nail_plane":{key:value for key,value in contact.items() if key.startswith("nail_plane_")},
                "sources_sha256":{name:hashlib.sha256((RELEASE/name).read_bytes()).hexdigest() for name in source_paths}}
        (WEB/"sensor-placement.json").write_text(json.dumps(result,indent=2)+"\n")
        with (WEB/"sensor-placement.csv").open("w",newline="") as stream:
            writer=csv.writer(stream,lineterminator="\n")
            writer.writerow(["pair","region","magnet_mm_from_tip","head_mm_from_tip","magnet_x","magnet_y","magnet_z",
                             "sensor_die_x","sensor_die_y","sensor_die_z","center_distance_mm","mux_channel"])
            for i,row in enumerate(rows):
                writer.writerow([f"M{i}/S{i}",row["region"],f"{row['magnet_from_tip_mm']:.3f}",f"{row['head_from_tip_mm']:.3f}",
                    *row["magnet_center_native_xyz_mm"],*row["sensor_die_native_xyz_mm"],row["center_distance_mm"],i])
            s=reference["die_center_native_mm"]
            writer.writerow(["S4","Fixed field reference","",f"{s[1]-tip:.3f}","","","",*s,"",4])
        svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 600" role="img" aria-labelledby="title desc">',
             '<title id="title">Exactly which B1 sensors go where</title>',
             '<desc id="desc">Four moving magnets M0 through M3 sit inside the TPU. Five MLX90393 heads S0 through S4 stay on the rigid side spine. Two N0 pressure-film pads T0 and T1 cover the object-facing nail prongs.</desc>',
             '<rect width="1280" height="600" fill="#fff"/>',
             '<g font-family="sans-serif" fill="#203f46">',
             '<text x="28" y="37" font-size="27" font-weight="bold">B1 recommended prototype: magnetic soft region + two pressure-film tip pads</text>',
             '<text x="28" y="65" font-size="17">Per finger: 5 × MLX90393 heads · 4 × 3 × 1 mm magnets · 2 × N0 nail pads</text>',
             '<rect x="20" y="89" width="852" height="395" rx="12" fill="#f5f8f4"/>',
             '<rect x="888" y="89" width="372" height="395" rx="12" fill="#f5f8f4"/>',
             '<text x="40" y="117" font-size="20" font-weight="bold">Side view — sensor boards are beside the finger</text>',
             '<text x="908" y="117" font-size="19" font-weight="bold">Thin tip — object-facing surface</text>']

        def side(y,z):return (65+(y-tip)*6.3,370-(z+4.4)*6.3)
        for group,color,opacity in (("frame","#91a2a7",".55"),("spine","#23877a",".85")):
            component=next(item for item in model["components"] if item["group"]==group)
            vertices=np.array(component["vertices"]);faces=np.array(component["faces"])
            triangles=vertices[faces][:,:,[1,2]]
            polygons=[Polygon(points) for points in triangles if Polygon(points).area>1e-7]
            union=unary_union(polygons).buffer(.001).buffer(-.001)
            parts=[union] if union.geom_type=="Polygon" else list(union.geoms)
            for polygon in parts:
                d=path(polygon.exterior.coords,side)+"".join(path(ring.coords,side) for ring in polygon.interiors)
                svg.append(f'<path d="{d}" fill="{color}" opacity="{opacity}" fill-rule="evenodd" stroke="{color}" stroke-width="1"/>')
        d=path(interface["outer_yz"],side)+"".join(path(hole,side) for hole in interface["holes_yz"])
        svg.append(f'<path d="{d}" fill="#a8bd80" fill-rule="evenodd" stroke="#708a4e" stroke-width="1.2"/>')
        for i,row in enumerate(rows):
            mx,my=side(*row["magnet_center_native_xyz_mm"][1:])
            sx,sy=side(*row["sensor_die_native_xyz_mm"][1:])
            svg.append(f'<path d="M{mx} {my}L{sx} {sy}" stroke="#747b79" stroke-width="1.8" stroke-dasharray="4 3"/>')
            svg.append(f'<circle cx="{mx}" cy="{my}" r="9.5" fill="#cd7c34" stroke="white" stroke-width="1.5"/>')
            label_y=414 if i%2==0 else 443
            svg.append(f'<path d="M{mx} {my+12}V{label_y-18}" fill="none" stroke="#ac622e"/>')
            svg.append(f'<text x="{mx}" y="{label_y}" text-anchor="middle" font-size="18" font-weight="bold">M{i}</text>')
            svg.append(f'<text x="{mx}" y="{label_y+19}" text-anchor="middle" font-size="13">{row["magnet_from_tip_mm"]:.1f} mm from tip</text>')
        for i,sensor in enumerate(plan["sensor_poses"]):
            svg.append(f'<path d="{path(sensor["footprint_yz"],side)}" fill="#7b6caa" fill-opacity=".83" stroke="#544c81" stroke-width="1.4"/>')
            sx,sy=side(*sensor["native_yz_mm"])
            lx=sx if i<4 else 805
            ly=154 if i<4 else 196
            svg.append(f'<path d="M{sx} {sy}L{lx} {ly+5}" fill="none" stroke="#544c81" stroke-width="1.5"/>')
            svg.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" font-size="19" font-weight="bold">S{i}</text>')
            if i==4:
                svg.append(f'<text x="{lx}" y="{ly+20}" text-anchor="middle" font-size="13">reference</text>')
        # Show all four targets clearly in this explanatory projection, even
        # where a fixed board overlaps one in the side view.
        for row in rows:
            mx,my=side(*row["magnet_center_native_xyz_mm"][1:])
            svg.append(f'<circle cx="{mx}" cy="{my}" r="9.5" fill="#cd7c34" stroke="white" stroke-width="1.5"/>')
        tx,ty=side(-109,-3.8)
        svg.append(f'<path d="M{tx} {ty}L115 401" stroke="#c3524a" stroke-width="2"/>')
        svg.append('<text x="48" y="423" font-size="17" fill="#ac443e">T0 + T1 on the nail</text>')
        svg.append('<text x="48" y="448" font-size="14">Shown separately at right →</text>')
        svg.append('<text x="60" y="185" font-size="16">TIP</text><text x="770" y="150" font-size="16">BASE</text>')

        def nail(u,v):return (1074+u*10,304-v*10)
        footprint=contact["nail_footprint"]
        d=path(footprint["outer"],nail)+"".join(path(hole,nail) for hole in footprint.get("holes",[]))
        svg.append(f'<path d="{d}" fill="#bbc6c6" stroke="#728486" stroke-width="1.5" fill-rule="evenodd"/>')
        for cell in r1["nail_active_cells"]:
            d=path(cell["outer"],nail)+"".join(path(hole,nail) for hole in cell.get("holes",[]))
            svg.append(f'<path d="{d}" fill="#d16a59" stroke="#9b4b40" stroke-width="1" fill-rule="evenodd"/>')
        for i,x in enumerate((1010,1140)):
            label_x=(1028,1120)[i]
            svg.append(f'<text x="{label_x}" y="247" text-anchor="middle" fill="#fff" font-size="20" font-weight="bold">T{i}</text>')
            svg.append(f'<text x="{x}" y="407" text-anchor="middle" font-size="15">T{i} = R1 CH{i}</text>')
        svg.append('<text x="1074" y="162" text-anchor="middle" font-size="14">Leading edge</text>')
        svg.append('<text x="1074" y="433" text-anchor="middle" font-size="15">N0 construction for BOTH pads</text>')
        svg.append('<text x="1074" y="458" text-anchor="middle" font-size="14">Leave the center notch open.</text>')
        svg += [
            '<circle cx="42" cy="514" r="9" fill="#cd7c34"/><text x="62" y="520" font-size="16">M0–M3: moving magnets inside TPU</text>',
            '<rect x="492" y="505" width="19" height="18" fill="#7b6caa"/><text x="525" y="520" font-size="16">S0–S4: fixed MLX90393 heads</text>',
            '<rect x="931" y="505" width="19" height="18" fill="#d16a59"/><text x="964" y="520" font-size="16">T0/T1: thin pressure-film pads</text>',
            '<text x="28" y="552" font-size="15">Purple heads bond to the rigid spine. Orange magnets move with the green TPU. Dashed lines indicate pairing, not wires.</text>',
            '<text x="28" y="579" font-size="14">Source: unchanged released CAD and R1 nail cut pattern. Side projection omits depth; use placement CSV/JSON for full coordinates.</text>',
            '</g></svg>']
        (WEB/"sensor-placement.svg").write_text("\n".join(svg)+"\n")
        table=["| Soft region | Magnet in TPU | Fixed sensor head | Center separation |",
               "|---|---|---|---|"]
        for i,row in enumerate(rows):
            table.append(f"| {row['region']} | M{i}: {row['magnet_from_tip_mm']:.1f} mm from tip | S{i}: {row['head_from_tip_mm']:.1f} mm from tip | {row['center_distance_mm']:.1f} mm |")
        reference_distance=reference["die_center_native_mm"][1]-tip
        template=(ROOT/"engineering/templates/sensor_guide.md").read_text()
        guide=template.replace("{{pair_table}}","\n".join(table)).replace("{{reference_distance}}",f"{reference_distance:.1f}")
        (ROOT/"engineering/docs/SENSORS.md").write_text(guide)
        record["source_hashes"]=result["sources_sha256"]
        print("\n".join(table))
        print(f"S4 reference: {reference_distance:.1f} mm from tip. Two N0 pads use original CH0/CH1 polygons.")


if __name__=="__main__":main()
