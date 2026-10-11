#!/usr/bin/python3
"""Inspect the selected vendor STEP as a dimensional reference, without modifying it."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/force-button-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface

from tactile_kit.records import execution
from screen_f1_feedback import digest


def bounds(shape):
    b = shape.BoundingBox()
    return [[b.xmin, b.ymin, b.zmin], [b.xmax, b.ymax, b.zmax]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", type=Path)
    args = parser.parse_args()
    source = args.step.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/force_button/sources"):
        parser.error("Use the extracted public vendor model")
    folder = ROOT / "build/engineering/prototypes/force_button/vendor_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Inspect the manufacturer FMA STEP bounds, contact sphere and vent/land geometry; do not modify or redistribute the source model") as record:
        folder.mkdir(parents=True, exist_ok=False)
        shape = cq.importers.importStep(str(source)).val()
        solids = [{"index": i, "bounds": bounds(s), "volume": s.Volume(), "valid": s.isValid()}
                  for i, s in enumerate(shape.Solids())]
        surfaces = []
        for index, face in enumerate(shape.Faces()):
            kind = face.geomType()
            item = {"index": index, "kind": kind, "area": face.Area(), "bounds": bounds(face)}
            adaptor = BRepAdaptor_Surface(face.wrapped)
            if kind == "SPHERE":
                sphere = adaptor.Sphere()
                item["radius_mm"] = sphere.Radius()
                item["center_mm"] = [sphere.Location().X(), sphere.Location().Y(), sphere.Location().Z()]
            elif kind == "CYLINDER":
                cylinder = adaptor.Cylinder()
                item["radius_mm"] = cylinder.Radius()
                item["axis_point_mm"] = [cylinder.Location().X(), cylinder.Location().Y(), cylinder.Location().Z()]
                item["axis_direction"] = [cylinder.Axis().Direction().X(), cylinder.Axis().Direction().Y(), cylinder.Axis().Direction().Z()]
            elif kind == "PLANE":
                normal = face.normalAt()
                item["normal"] = [normal.x, normal.y, normal.z]
            surfaces.append(item)
        report = {"source_step_sha256": digest(source), "bounds": bounds(shape),
                  "solids": solids, "faces": surfaces, "physical_measurements": False}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "bounds": report["bounds"],
                            "solid_count": len(solids), "solids": solids,
                            "spheres": [s for s in surfaces if s["kind"] == "SPHERE"],
                            "small_cylinders": [s for s in surfaces if s["kind"] == "CYLINDER" and s["radius_mm"] < .4]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
