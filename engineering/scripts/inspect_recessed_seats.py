#!/usr/bin/python3
"""Measure source material behind candidate B3 spacer bearing annuli."""

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
from source_brep import load
from prototype_cad import x_cylinder,digest
from tactile_kit.records import execution


def main():
    source,_=load("hard_frame")
    cfg=json.loads((ROOT/"engineering/designs/recessed.json").read_text())
    b1=json.loads((ROOT/"engineering/release/b1/b1_manifest.json").read_text())
    output=ROOT/"build/engineering/prototypes/recessed/seat_review"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records","Measure the actual source seating geometry to choose B3 contact faces; no physical load capacity is inferred") as record:
        output.mkdir(parents=True,exist_ok=False)
        rows=[]
        for index,mount in enumerate(b1["carrier_mounts"]):
            y,z=mount["center_yz_mm"]
            for plane in (4.0,3.5,3.0):
                for inner in (3.2,3.6,4.0,4.6,5.0):
                    ring=x_cylinder(plane-.15,.15,y,z,cfg["mechanical"]["spacer_outer_diameter_mm"]/2)
                    ring=ring.cut(x_cylinder(plane-.2,.3,y,z,inner/2))
                    present=source.intersect(ring).Volume()
                    row={"mount":index,"seat_plane_x_mm":plane,"bearing_inner_diameter_mm":inner,
                         "annulus_volume_mm3":ring.Volume(),"missing_source_volume_mm3":ring.Volume()-present}
                    rows.append(row)
            print("Seat",index,json.dumps([row for row in rows if row["mount"]==index]),flush=True)
        report={"schema":"yam-b3-seat-review/1","configuration_sha256":digest(ROOT/"engineering/designs/recessed.json"),
                "evidence_kind":"source_CAD_only","bearing_depth_mm":.15,"rows":rows}
        (output/"review.json").write_text(json.dumps(report,indent=2)+"\n")
        record["review_directory"]=str(output.relative_to(ROOT));record["rows"]=rows


if __name__=="__main__":
    main()
