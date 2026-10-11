#!/usr/bin/python3
"""Preserve and inspect only the failed source-frame cut used by the nail design."""

from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"] = str(ROOT/"build/engineering/tools/cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import cadquery as cq
from prototype_cad import block,digest
from source_brep import load
from tactile_kit.records import execution


def describe(shape):
    rows=[]
    for solid in shape.Solids():
        bounds=solid.BoundingBox()
        rows.append({"valid":solid.isValid(),"volume_mm3":solid.Volume(),
                     "bounds_mm":[[bounds.xmin,bounds.ymin,bounds.zmin],
                                  [bounds.xmax,bounds.ymax,bounds.zmax]]})
    return {"valid":shape.isValid(),"solids":rows,"faces":len(shape.Faces())}


def main():
    cfg=json.loads((ROOT/"engineering/designs/nail.json").read_text())
    source,_=load("hard_frame")
    cut=cfg["source_frame"]["distal_cut_native_y_mm"]
    output=ROOT/"build/engineering/prototypes/nail/frame_review"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records","Inspect source-frame cut validity and connected components for the new nail; preserve cut variants without touching any released geometry") as record:
        output.mkdir(parents=True,exist_ok=False)
        report={}
        for name,shape in (("intersection",source.intersect(block(-60,40,cut,20,-30,70))),
                           ("subtraction",source.cut(block(-60,40,-150,cut,-30,70)))):
            for suffix,variant in (("raw",shape),("fixed",shape.fix()),("clean",shape.clean())):
                label=name+"_"+suffix
                report[label]=describe(variant)
                cq.exporters.export(variant,str(output/(label+".step")))
                print(label,json.dumps(report[label]),flush=True)
        result={"source_configuration_sha256":digest(ROOT/"engineering/designs/nail.json"),
                "cut_native_y_mm":cut,"variants":report}
        (output/"review.json").write_text(json.dumps(result,indent=2)+"\n")
        record["review_directory"]=str(output.relative_to(ROOT))
        record["variants"]=report


if __name__=="__main__":
    main()
