#!/usr/bin/python3
"""Add the L1 engineering snapshot while verifying and preserving the published R1 snapshot."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import numpy as np
import trimesh

from draw_l1 import COLORS, components
from tactile_kit.records import execution

RELEASE=ROOT/"engineering/release"
OUTPUT=ROOT/"build/engineering/l1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def packed(mesh,name,group,color,explosion=(0,0,0)):
    return {"name":name,"group":group,"color":color,"explosion":list(explosion),
            "vertices":np.round(mesh.vertices,4).tolist(),"faces":mesh.faces.tolist()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-r1",action="store_true",
                        help="After an intentional fresh R1 freeze, record its new snapshot instead of preserving the old one")
    args=parser.parse_args()
    with execution(ROOT/"build/records","Preserve R1 geometry and freeze the additional L1 CAD, plans and actual-mesh viewer data") as record:
        previous=RELEASE/"r1_snapshot_manifest.json"
        if args.refresh_r1:
            r1=json.loads((RELEASE/"release_manifest.json").read_text())
            if r1["revision"]!="R1.0":raise ValueError("Run the R1 generator and freeze_release.py before --refresh-r1")
            for name,expected in r1["files"].items():
                if digest(RELEASE/name)!=expected:raise ValueError(f"Fresh R1 freeze changed: {name}")
            r1["files"]={name:checksum for name,checksum in r1["files"].items()
                         if name.split("/")[0] in {"r1","baseline","contact_regions","interfaces"}
                         or name in {"NOTICE.md","models.json"}}
            previous.write_text(json.dumps(r1,indent=2)+"\n")
        elif previous.exists():
            r1=json.loads(previous.read_text())
        else:
            raw=(RELEASE/"release_manifest.json").read_bytes()
            r1=json.loads(raw)
            if r1["revision"]!="R1.0":raise ValueError("Original R1 manifest is missing")
            previous.write_bytes(raw)
        for name,expected in r1["source_hashes"].items():
            if digest(ROOT/name)!=expected:raise ValueError(f"R1 source changed: {name}. Regenerate/freeze R1, then use --refresh-r1.")
        for name,expected in r1["files"].items():
            if digest(RELEASE/name)!=expected:raise ValueError(f"R1 geometry changed: {name}")
        plan=json.loads((OUTPUT/"l1_manifest.json").read_text())
        config=json.loads((ROOT/"engineering/designs/l1.json").read_text())
        for part in plan["parts"]:
            if digest(OUTPUT/part["step"])!=part["sha256_step"] or digest(OUTPUT/part["stl"])!=part["sha256_stl"]:
                raise ValueError(f"Generated L1 part changed after its CAD checks: {part['id']}")
        target=RELEASE/"l1"
        shutil.copytree(OUTPUT,target,dirs_exist_ok=True)
        groups={"frame":"frame","tpu":"tpu","fixed":"fixed","floating":"floating","cell":"cell","hardware":"hardware"}
        names={"frame":"Original PETG frame","tpu":"Original TPU insert","fixed":"Fixed aluminum carrier",
               "floating":"Floating aluminum carrier","cell":"Purchased TAL220B reference","hardware":"Reserved fastener envelope"}
        explosion={"frame":(0,-22,0),"tpu":(0,-22,-12),"fixed":(0,18,0),
                   "floating":(0,0,15),"cell":(18,0,0),"hardware":(0,0,24)}
        models=[{
            "id":"l1_assembly","title":"L1 · assembled finger and root force cell",
            "coordinates":"native_mm","assembly":True,
            "components":[packed(mesh,names[key],groups[key],COLORS[key],explosion[key]) for key,mesh in components(plan)],
            "note":"Original finger translated 20 mm; contact surfaces retained. Aluminum carriers, purchased-cell outline and reserved fastener space. Hardware fit, moment capacity and force performance are untested.",
        }]
        cell=trimesh.load_mesh(OUTPUT/"cad/tal220b_reference.stl",process=True)
        pose=config["load_cell"]["pose"]
        cx=pose["native_x_min_mm"]+config["load_cell"]["width_mm"]/2
        cell.apply_transform(np.array([
            [0,-1,0,pose["native_y_wire_end_mm"]],[1,0,0,-cx],
            [0,0,1,-pose["native_z_bottom_mm"]],[0,0,0,1],
        ],dtype=float))
        bench=[packed(cell,"Purchased cell outline","cell",COLORS["cell"])]
        for name,label,group,color,offset in (
            ("l1_bench_fixed_shoe","Fixed bench shoe","fixed",COLORS["fixed"],(0,0,-12)),
            ("l1_bench_live_spacer","Live-end spacer","floating",COLORS["floating"],(0,0,12)),
            ("l1_combined_load_plate","Moment test plate","fixture","#b79864",(0,0,25)),
            ("l1_center_load_cap","Center-loading cap","fixture","#657c89",(0,0,40)),
        ):
            bench.append(packed(trimesh.load_mesh(OUTPUT/f"cad/{name}.stl",process=True),label,group,color,offset))
        models.append({
            "id":"l1_bench","title":"L1 · cell and moment-test fixture","coordinates":"tool_mm","assembly":True,
            "components":bench,
            "note":"The cell is clamped only at its two solid ends. The plate's off-center ports expose leverage errors that a center-only calibration can miss. Fasteners and the external stand are not modeled.",
        })
        for part in plan["parts"]:
            models.append({
                "id":part["id"],"title":"L1 · "+part["id"].removeprefix("l1_").replace("_"," "),
                "coordinates":"tool_mm","components":[packed(
                    trimesh.load_mesh(OUTPUT/part["stl"],process=True),part["purpose"],"tool",COLORS["floating"]
                )],
                "note":part["purpose"]+" "+part["material"]+". "+
                       ("Purchased reference only; do not fabricate this envelope." if part["kind"]=="reference_only"
                        else "Physical fit and strength are not qualified."),
            })
        (target/"models.json").write_text(json.dumps(models,separators=(",",":"))+"\n")
        (target/"NOTICE.md").write_text(
            "# L1 attribution and scope\n\n"
            "The original finger and its mounting contour/key are by Wenli Xiao / NVIDIA ENPIRE.\n"
            "Original model: https://makerworld.com/en/models/2984746-gripper-finger-for-robot-arm#profileId-3349177\n"
            "Retrieved MakerWorld metadata identifies license code BY. Preserve the original attribution and terms.\n"
            "The source hashes and pinned community copy are documented in engineering/docs/GEOMETRY.md.\n\n"
            "Changes: new fixed/floating carriers derived from that mounting interface; original finger translated "
            "20 mm; independent cell-test tooling and test-location drawings.\n"
            "The TAL220B outline is a purchased-part reference, not a manufacturable load cell.\n"
            "No fabricated prototype or measured performance is included.\n"
        )
        dependencies=[
            "engineering/designs/l1.json","engineering/scripts/measure_root_interface.py",
            "engineering/scripts/build_l1_parts.py","engineering/scripts/draw_l1.py",
            "engineering/scripts/screen_l1_stiffness.py","engineering/scripts/make_l1_plans.py",
            "engineering/scripts/freeze_l1_release.py",
        ]
        source_hashes={**r1["source_hashes"],**{name:digest(ROOT/name) for name in dependencies}}
        files={str(path.relative_to(RELEASE)):digest(path) for path in sorted(RELEASE.rglob("*"))
               if path.is_file() and path!=RELEASE/"release_manifest.json"}
        checks={
            "cad_solids":r1["digital_geometry_checks"]["cad_solids"]+plan["checks"]["valid_solids"],
            "step_roundtrips":r1["digital_geometry_checks"]["step_roundtrips"]+plan["checks"]["step_roundtrips"],
            "watertight_stl_exports":r1["digital_geometry_checks"]["watertight_stl_exports"]+plan["checks"]["watertight_meshes"],
        }
        manifest={
            "revision":"R1.0 + L1.0","requested_per_finger_force_n":20,
            "physical_specimens_tested":0,"hardware_status":"awaiting fabrication and measurement",
            "digital_geometry_checks":checks,"purchased_reference_solids":1,
            "preserved_r1_manifest":"r1_snapshot_manifest.json",
            "source_hashes":source_hashes,"files":files,
        }
        (RELEASE/"release_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        record["snapshot"]={"files":len(files),"l1_models":len(models),"checks":checks}
        print(json.dumps(record["snapshot"],indent=2))


if __name__=="__main__":
    main()
