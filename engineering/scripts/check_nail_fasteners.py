#!/usr/bin/python3
"""Measure carrier material around the N1 countersinks and threaded clamp holes."""

from datetime import datetime,timezone
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
from nail_geometry import x_bore
from prototype_cad import digest
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/prototypes/nail"


def main():
    cfg=json.loads((ROOT/"engineering/designs/nail.json").read_text())
    plan=json.loads((OUTPUT/"nail_manifest.json").read_text())
    for name,expected in plan["source_hashes"].items():
        if digest(ROOT/name)!=expected:
            raise ValueError("Check fasteners only against current generated CAD")
    with execution(ROOT/"build/records","Check explicit bearing rims around N1 countersinks after visual review; no joint strength or preload rating") as record:
        carriers=[cq.importers.importStep(str(OUTPUT/"cad"/f"nail_{side}_fixed_carrier.step")).val() for side in ("left","right")]
        nail=cq.importers.importStep(str(OUTPUT/"cad/nail_bare_sensing_fork.step")).val()
        rows=[]
        for hole in plan["clamp_holes"]:
            index=hole["carrier"];direction=1 if index==0 else -1
            outer=hole["outer_x_mm"];y,z=hole["center_native_yz_mm"]
            start,end=sorted((outer,outer+direction*1.0))
            required=x_bore(start,end,y,z,8.0).cut(x_bore(start-.1,end+.1,y,z,cfg["mount"]["countersink_diameter_mm"]))
            missing=required.cut(carriers[index]).Volume()
            face=hole["nail_outer_x_mm"]
            a,b=sorted((face,face+direction*1.0))
            threaded_ring=x_bore(a,b,y,z,5.0).cut(x_bore(a-.1,b+.1,y,z,cfg["mount"]["m3_tap_drill_mm"]))
            missing_thread=threaded_ring.cut(nail).Volume()
            rows.append({"kind":"front_clamp","carrier":index,"center_native_yz_mm":[y,z],
                         "missing_counterbore_rim_mm3":missing,
                         "missing_thread_surround_mm3":missing_thread,
                         "passed":missing<1e-6 and missing_thread<1e-6})
        for mount in plan["mounts"]:
            index=mount["carrier"];direction=1 if index==0 else -1
            outer=mount["outer_x_mm"];y,z=mount["center_native_yz_mm"]
            a,b=sorted((outer,outer+direction))
            outside=5.0 if index==0 else 8.0
            inside=cfg["mount"]["m3_tap_drill_mm"] if index==0 else cfg["mount"]["countersink_diameter_mm"]
            ring=x_bore(a,b,y,z,outside).cut(x_bore(a-.1,b+.1,y,z,inside))
            missing=ring.cut(carriers[index]).Volume()
            rows.append({"kind":"side_mount","carrier":index,"center_native_yz_mm":[y,z],
                         "required_outer_diameter_mm":outside,"missing_surround_mm3":missing,
                         "passed":missing<1e-6})
        report={"schema":"yam-nail-fastener-geometry/1","evidence_kind":"CAD_only",
                "countersink_diameter_mm":cfg["mount"]["countersink_diameter_mm"],
                "required_outer_rim_diameter_mm":8.0,"rim_check_depth_mm":1.0,
                "required_thread_surround_diameter_mm":5.0,
                "manifest_sha256":digest(OUTPUT/"nail_manifest.json"),
                "checks":rows,"passed":all(row["passed"] for row in rows),
                "scope":"Geometric material checks only; tightening, thread engagement and joint load tests remain required."}
        folder=OUTPUT/"fastener_checks"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        folder.mkdir(parents=True,exist_ok=False)
        (folder/"checks.json").write_text(json.dumps(report,indent=2)+"\n")
        record["fasteners"]=report
        print(json.dumps(report,indent=2))
        if not report["passed"]:
            raise ValueError("A nail fastener lacks the declared surrounding material")


if __name__=="__main__":
    main()
