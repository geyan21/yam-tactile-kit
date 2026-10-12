#!/usr/bin/python3
"""Inspect one O1 STEP/STL export without changing its geometry or evidence."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/optical-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import cadquery as cq
import numpy as np
import trimesh
from screen_f1_feedback import digest
from tactile_kit.records import execution


def inspect(path):
    mesh = trimesh.load_mesh(path, process=True)
    counts = np.bincount(mesh.edges_unique_inverse)
    bad = mesh.edges_unique[counts != 2]
    points = mesh.vertices[np.unique(bad)] if len(bad) else np.zeros((0, 3))
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path),
            "watertight": bool(mesh.is_watertight), "consistent_winding": bool(mesh.is_winding_consistent),
            "vertices": len(mesh.vertices), "faces": len(mesh.faces), "volume_mm3": float(mesh.volume),
            "boundary_edges": int(np.count_nonzero(counts == 1)),
            "nonmanifold_edges": int(np.count_nonzero(counts > 2)),
            "bad_edge_vertex_bounds": [points.min(axis=0).tolist(), points.max(axis=0).tolist()] if len(points) else [],
            "bad_edge_coordinates": mesh.vertices[bad[:80]].tolist()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", type=Path)
    args = parser.parse_args()
    source = args.step.resolve()
    if not source.is_relative_to(ROOT/"build") or source.suffix != ".step":
        parser.error("Use a generated O1 STEP file")
    folder = ROOT/"build/engineering/prototypes/optical/mesh_export_reviews"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Inspect the failed O1 tessellation and compare unchanged STEP exports at explicit tolerances; no repair or overwrite") as record:
        folder.mkdir(parents=True)
        shape = cq.importers.importStep(str(source)).val()
        results = [inspect(source.with_suffix(".stl"))]
        for tolerance, angle in ((.03, .1), (.015, .05), (.01, .02)):
            target = folder/f"frame_t{tolerance}_a{angle}.stl"
            cq.exporters.export(shape, str(target), tolerance=tolerance, angularTolerance=angle)
            result = inspect(target)
            result.update(tolerance_mm=tolerance, angular_tolerance_radians=angle)
            results.append(result)
        report = {"source": str(source.relative_to(ROOT)), "source_sha256": digest(source),
                  "source_valid": shape.isValid(), "source_solids": len(shape.Solids()),
                  "source_volume_mm3": shape.Volume(), "exports": results}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)),
                            "exports": [{k: row[k] for k in ("path", "watertight", "boundary_edges", "nonmanifold_edges")} for row in results]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
