"""Explicitly conceptual component envelopes; not manufacturing geometry."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .model import evaluate, validate

QUADS = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 4, 5, 1),
         (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def subtract(a, b):
    return [a[i]-b[i] for i in range(3)]


def component(identifier, title, color, vertices, explosion):
    center = [sum(v[i] for v in vertices)/len(vertices) for i in range(3)]
    faces = []
    for quad in QUADS:
        for face in ((quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])):
            face = list(face)
            a, b, c = [vertices[i] for i in face]
            normal = cross(subtract(b, a), subtract(c, a))
            face_center = [(a[i]+b[i]+c[i])/3 for i in range(3)]
            if sum(normal[i]*(face_center[i]-center[i]) for i in range(3)) < 0:
                face[1], face[2] = face[2], face[1]
            faces.append(face)
    return {
        "id": identifier, "title": title, "color": color,
        "vertices": vertices, "faces": faces, "explosion": explosion,
        "envelope_only": True,
    }


def box(identifier, title, color, low, high, explosion):
    x0, y0, z0 = low
    x1, y1, z1 = high
    vertices = [[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],
                [x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]]
    return component(identifier, title, color, vertices, explosion)


def scene(design: dict) -> dict:
    d = validate(design)
    summary = evaluate(d)
    length, width = d["finger_length_mm"], d["face_width_mm"]
    body, nose = d["body_thickness_mm"], d["nose_thickness_mm"]
    sensor_width, sensor_depth = max(12, width+4), max(8, body+2)
    mount_width, mount_depth = max(14, width+6), max(10, body+4)
    center_x = -body/2
    parts = [
        box("mount", "Fixed mount placeholder", "#8c9d91",
            [center_x-mount_depth/2,-mount_width/2,-32],
            [center_x+mount_depth/2,mount_width/2,-20], [0,0,-22]),
        box("sensor", "Force module placeholder", "#609b83",
            [center_x-sensor_depth/2,-sensor_width/2,-18],
            [center_x+sensor_depth/2,sensor_width/2,-2], [0,0,-10]),
        component("finger", "Thin finger envelope", "#bdd5bf",
            [[-body,-width/2,0],[0,width*-0.5,0],[0,width/2,0],[-body,width/2,0],
             [-nose,-width/2,length],[0,-width/2,length],[0,width/2,length],[-nose,width/2,length]],
            [0,0,0]),
    ]
    clearance = min(2, max(0, (length-d["pad_length_mm"])/2))
    if summary["taxels"] and d["pad_stack_mm"] > 0:
        parts.append(box(
            "pad", "Pressure laminate allowance", "#c89453",
            [-d["pad_recess_mm"],-width/2,length-clearance-d["pad_length_mm"]],
            [d["pad_stack_mm"]-d["pad_recess_mm"],width/2,length-clearance],
            [8,0,0],
        ))
    return {
        "schema_version": 1, "kind": "concept_envelopes", "units": "mm",
        "geometry_status": d["geometry_status"], "hardware_validated": False,
        "frame": {"x":"inward normal","y":"finger width","z":"distal finger"},
        "assumptions": {
            "mount_length_mm": 12, "sensor_length_mm": 16,
            "mount_width_mm": mount_width, "mount_depth_mm": mount_depth,
            "sensor_width_mm": sensor_width, "sensor_depth_mm": sensor_depth,
            "status": "Illustrative packaging assumptions; no selected force element or measured mounting interface.",
        },
        "limitations": [
            "Generic envelopes, not the user's exact finger or a manufactured sensor.",
            "No mounting holes, calibrated flexures, cable channels, or production tolerances.",
            "Laminate overlap represents a recess allowance, not a finished mating pocket.",
            "The force-plot stations form a separate ideal model; these boxes do not model strain gauges.",
        ],
        "components": parts,
    }


def stl(part: dict) -> str:
    lines = [f"solid concept_only_{part['id']}"]
    for face in part["faces"]:
        a, b, c = [part["vertices"][i] for i in face]
        normal = cross(subtract(b, a), subtract(c, a))
        size = math.sqrt(sum(value*value for value in normal))
        if size <= 0:
            raise ValueError("Degenerate triangle in concept envelope")
        normal = [value/size for value in normal]
        lines.append("  facet normal " + " ".join(f"{v:.10g}" for v in normal))
        lines.append("    outer loop")
        lines.extend("      vertex " + " ".join(f"{v:.10g}" for v in p) for p in (a,b,c))
        lines.extend(("    endloop", "  endfacet"))
    lines.append(f"endsolid concept_only_{part['id']}")
    return "\n".join(lines) + "\n"


def openscad(design: dict, model: dict) -> str:
    d = validate(design)
    lines = [
        "// CONCEPT ENVELOPES ONLY — NOT FOR FABRICATION",
        "// Units: mm. X: inward normal; Y: width; Z: distal.",
        "// Mount/sensor blocks are packaging placeholders. See README.md.",
        "explode = 0; // 0 assembled; 1 separated for viewing",
        f"finger_length = {d['finger_length_mm']};",
        f"finger_width = {d['face_width_mm']};",
        f"body_thickness = {d['body_thickness_mm']};",
        f"nose_thickness = {d['nose_thickness_mm']};",
        "",
        'color("#bdd5bf") rotate([90,0,0])',
        "  linear_extrude(height=finger_width, center=true)",
        "  polygon(points=[[-body_thickness,0],[0,0],",
        "                  [0,finger_length],[-nose_thickness,finger_length]]);",
        "",
    ]
    for part in model["components"]:
        if part["id"] == "finger":
            continue
        low = [min(v[i] for v in part["vertices"]) for i in range(3)]
        high = [max(v[i] for v in part["vertices"]) for i in range(3)]
        size = [high[i]-low[i] for i in range(3)]
        location = ",".join(f"{low[i]:.8g}+explode*{part['explosion'][i]}" for i in range(3))
        lines.extend((
            f"// {part['title']}",
            f'color("{part["color"]}") translate([{location}])',
            f"  cube([{','.join(f'{v:.8g}' for v in size)}]);",
            "",
        ))
    return "\n".join(lines)


def write_design(directory: Path, design: dict, summary: dict, svg: str, root: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    model = scene(design)
    (directory/"assembly-envelopes.json").write_text(json.dumps(model,indent=2)+"\n")
    (directory/"assembly-envelopes.scad").write_text(openscad(design,model),encoding="utf-8")
    for part in model["components"]:
        (directory/f"{part['id']}-envelope.stl").write_text(stl(part))
    (directory/"design-inputs.json").write_text(json.dumps(design,indent=2)+"\n")
    (directory/"design-summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    (directory/"finger-concept.svg").write_text(svg,encoding="utf-8")
    (directory/"original-architecture.svg").write_bytes((root/"docs/yam_force_finger_concept.svg").read_bytes())
    (directory/"README.md").write_bytes((root/"design/README.md").read_bytes())
    for name in ("bom.csv","measurements.template.json","data-contract.example.json"):
        (directory/name).write_bytes((root/"hardware"/name).read_bytes())
    return model
