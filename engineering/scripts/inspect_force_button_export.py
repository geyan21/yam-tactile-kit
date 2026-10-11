#!/usr/bin/python3
"""Inspect one failed FB1 reference export and retain finer STL candidates."""

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
import numpy as np
import trimesh
from tactile_kit.records import execution
from screen_f1_feedback import digest


def describe(path):
    mesh = trimesh.load_mesh(path, process=True)
    counts = np.bincount(mesh.edges_unique_inverse)
    indexes = np.where(counts != 2)[0]
    return {"file": path.name, "sha256": digest(path), "faces": len(mesh.faces), "vertices": len(mesh.vertices),
            "watertight": bool(mesh.is_watertight), "volume_mm3": float(mesh.volume),
            "nonmanifold_edges": len(indexes),
            "first_edges": [{"count": int(counts[i]), "vertices": mesh.vertices[mesh.edges_unique[i]].tolist()} for i in indexes[:6]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cad_directory", type=Path)
    args = parser.parse_args()
    source = args.cad_directory.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/force_button"):
        parser.error("Use an owned FB1 CAD directory")
    folder = source.parent / "export_review" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Inspect only the failed FMA reference's STEP/STL topology and retain independent finer tessellations without replacing the original failure") as record:
        folder.mkdir(parents=True, exist_ok=False)
        shape = cq.importers.importStep(str(source / "fb1_fma25_envelope.step")).val()
        result = {"native_valid": shape.isValid(), "native_volume_mm3": shape.Volume(),
                  "original": describe(source / "fb1_fma25_envelope.stl"), "candidates": []}
        for index, (linear, angular) in enumerate(((.01, .05), (.003, .03))):
            path = folder / f"fma_finer_{index}.stl"
            cq.exporters.export(shape, str(path), tolerance=linear, angularTolerance=angular)
            result["candidates"].append({"tolerance_mm": linear, "angular_tolerance": angular, **describe(path)})
        (folder / "report.json").write_text(json.dumps(result, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **result}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
