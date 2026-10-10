#!/usr/bin/python3
"""Freeze a separate B1 package after verifying every preserved R1/L1 hash."""

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
from draw_b1 import components,COLORS
from tactile_kit.records import execution

RELEASE=ROOT/"engineering/release"
OUTPUT=ROOT/"build/engineering/b1"


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def packed(mesh,name,group,color,explosion=(0,0,0)):
    return {"name":name,"group":group,"color":color,"explosion":list(explosion),
            "vertices":np.round(mesh.vertices,4).tolist(),"faces":mesh.faces.tolist()}


def main():
    with execution(ROOT/"build/records","Preserve both existing designs and freeze checked B1 CAD, PCB, field calculations and actual-mesh visualizations") as record:
        previous=RELEASE/"r1_l1_snapshot_manifest.json"
        if not previous.exists():
            raw=(RELEASE/"release_manifest.json").read_bytes()
            if json.loads(raw)["revision"]!="R1.0 + L1.0":
                raise ValueError("Expected original combined R1/L1 manifest")
            previous.write_bytes(raw)
        baseline=json.loads(previous.read_text())
        for name,expected in baseline["source_hashes"].items():
            if digest(ROOT/name)!=expected:raise ValueError(f"Preserved source changed: {name}")
        for name,expected in baseline["files"].items():
            if digest(RELEASE/name)!=expected:raise ValueError(f"Preserved release changed: {name}")
        plan=json.loads((OUTPUT/"b1_manifest.json").read_text())
        for part in plan["parts"]:
            for kind in ("step","stl"):
                if digest(OUTPUT/part[kind])!=part[f"sha256_{kind}"]:
                    raise ValueError(f"B1 part changed after CAD checking: {part['id']}")
        pcb=json.loads((OUTPUT/"pcb/pcb_checks.json").read_text())
        if pcb["drc_violations"] or pcb["unconnected_items"]:
            raise ValueError("B1 PCB has unresolved findings")
        if digest(ROOT/"engineering/electronics/b1/b1_head.kicad_pcb")!=pcb["source_pcb_sha256"]:
            raise ValueError("PCB check is stale")
        if digest(OUTPUT/"pcb/b1_head.kicad_pcb")!=pcb["checked_pcb_sha256"]:
            raise ValueError("Checked PCB has changed")
        for name,checksum in pcb["files"].items():
            if digest(OUTPUT/"pcb/manufacturing"/name)!=checksum:raise ValueError(f"Gerber/drill changed: {name}")
        target=RELEASE/"b1";target.mkdir(exist_ok=True)
        shutil.copytree(OUTPUT/"cad",target/"cad",dirs_exist_ok=True)
        for name in ("b1_manifest.json","source_interface.json","b1_assembly.png","b1_exploded.png",
                     "b1_layout.svg","b1_review_drawings.pdf","field_screen.json","field_screen.svg"):
            shutil.copyfile(OUTPUT/name,target/name)
        (target/"pcb").mkdir(exist_ok=True)
        for name in ("b1_head.kicad_pcb","b1_head_fabrication.zip","pcb_checks.json"):
            shutil.copyfile(OUTPUT/"pcb"/name,target/"pcb"/name)
        for name in ("b1_head_assembly.svg","b1_head.json","b1_head_pin_net.csv","b1_head.kicad_dru","fp-lib-table"):
            shutil.copyfile(ROOT/"engineering/electronics/b1"/name,target/"pcb"/name)
        shutil.copytree(ROOT/"engineering/electronics/b1/B1.pretty",target/"pcb/B1.pretty",dirs_exist_ok=True)
        # Keep the independent report portable instead of publishing host paths.
        drc=(OUTPUT/"pcb/drc.json").read_text().replace(str(ROOT),"<checkout>")
        (target/"pcb/drc.json").write_text(drc)
        names={"frame":"Original hard frame","b1tpu":"B1 magnetic TPU insert","spine":"Fixed sensor spine",
               "magnet":"Embedded magnet","plug":"Flush retaining plug","pcb":"Fixed magnetic head","hardware":"Reserved M3 head"}
        explosion={"b1tpu":(-10,0,-8),"magnet":(2,0,-8),"plug":(6,0,-8),
                   "pcb":(16,0,0),"spine":(30,0,0),"hardware":(40,0,0)}
        models=[{"id":"b1_assembly","title":"B1 · compliant magnetic insert and fixed sensor spine",
                 "coordinates":"native_mm","assembly":True,
                 "components":[packed(mesh,names[key],key,COLORS[key],explosion.get(key,(0,0,0))) for key,mesh in components(plan)],
                 "note":"Separate B1 prototype. Original hard frame and nail retained; TPU gains magnet pockets. PCB/package and screw heads are envelopes. Wires, adhesive fillets and optional R1 nail cells are not pictured. Physical fit and force performance are untested."}]
        for part in plan["parts"]:
            models.append({"id":part["id"],"title":"B1 · "+part["id"].removeprefix("b1_").replace("_"," "),
                           "coordinates":"tool_mm","components":[packed(trimesh.load_mesh(OUTPUT/part["stl"],process=True),
                           part["purpose"],"tool",COLORS["spine"])],
                           "note":part["purpose"]+" "+part["material"]+". Physical qualification pending."})
        (target/"models.json").write_text(json.dumps(models,separators=(",",":"))+"\n")
        references=[
            {"title":"MLX90393 datasheet rev012","url":"https://media.melexis.com/-/media/files/documents/datasheets/mlx90393-datasheet-melexis.pdf","cached_sha256":digest(OUTPUT/"sources/b9e8d182ae57.pdf")},
            {"title":"S-03-01-N N48 magnet datasheet","url":"https://www.supermagnete.de/eng/data_sheet_S-03-01-N.pdf","cached_sha256":digest(OUTPUT/"sources/ab1d042db587.pdf")},
            {"title":"Structured compliance for connector insertion","url":"https://arxiv.org/abs/2307.15589"},
            {"title":"eFlesh concept precedent","url":"https://github.com/notvenky/eFlesh"},
        ]
        (target/"references.json").write_text(json.dumps(references,indent=2)+"\n")
        (target/"NOTICE.md").write_text(
            "# B1 attribution and scope\n\n"
            "Original hard frame and TPU contact outline: Wenli Xiao / NVIDIA ENPIRE.\n"
            "https://makerworld.com/en/models/2984746-gripper-finger-for-robot-arm#profileId-3349177\n"
            "The recovered source, author attribution and BY metadata are documented in GEOMETRY.md.\n"
            "B1 modifies internal TPU material with magnet pockets and creates a new fixed sensor spine, "
            "PCB, firmware and build documentation. The original hard frame is unchanged.\n\n"
            "Prior R1/L1 files and geometry-generator hashes are preserved and verified separately.\n"
            "Magnet/PCB solids are reference envelopes, not printable functional devices.\n"
            "Digital geometry, circuit DRC and calculated fields do not establish physical performance.\n"
        )
        dependencies=[ROOT/"engineering/designs/b1.json"]
        dependencies += sorted((ROOT/"engineering/scripts").glob("*b1*.py"))
        dependencies += [p for p in (ROOT/"engineering/electronics/b1").rglob("*") if p.is_file()]
        source_hashes={**baseline["source_hashes"],**{str(p.relative_to(ROOT)):digest(p) for p in dependencies}}
        files={str(path.relative_to(RELEASE)):digest(path) for path in sorted(RELEASE.rglob("*"))
               if path.is_file() and path!=RELEASE/"release_manifest.json"}
        checks={key:baseline["digital_geometry_checks"][key]+plan["checks"][key]
                for key in ("cad_solids","step_roundtrips","watertight_stl_exports")}
        manifest={"revision":"R1.0 + L1.0 + B1.0","requested_per_finger_force_n":20,
                  "physical_specimens_tested":0,"hardware_status":"awaiting fabrication and measurement",
                  "digital_geometry_checks":checks,"purchased_reference_solids":3,
                  "preserved_r1_l1_manifest":"r1_l1_snapshot_manifest.json",
                  "source_hashes":source_hashes,"files":files}
        (RELEASE/"release_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        record["snapshot"]={"files":len(files),"b1_models":len(models),"checks":checks,
                            "preserved_files":len(baseline["files"]),"pcb_drc_violations":0}
        print(json.dumps(record["snapshot"],indent=2))


if __name__=="__main__":main()
