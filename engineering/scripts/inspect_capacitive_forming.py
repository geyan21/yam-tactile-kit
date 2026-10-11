#!/usr/bin/python3
"""Inspect the failed forming map without changing the saved casting master."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from capacitive_geometry import load, offsets, formed_vertices
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cad_run", type=Path)
    parser.add_argument("--site", type=int, default=2)
    parser.add_argument("--mesh", type=Path)
    args = parser.parse_args()
    source = args.cad_run.resolve()
    if not source.is_relative_to(ROOT / "build") or args.site not in range(6):
        parser.error("Use an owned CAD run and site 0..5")
    cfg, surfaces = load()
    surface = surfaces[args.site]
    selected = offsets(args.site, cfg)
    path = args.mesh.resolve() if args.mesh else source / "cad" / f"k1_ch{args.site}_post_sheet_flat.stl"
    if not path.is_relative_to(ROOT / "build"):
        parser.error("Use a generated mesh inside the repository")
    mesh = trimesh.load_mesh(path, process=True)
    folder = source / "forming_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Inspect K1 flat/formed mesh topology, chart orientation and sampled offset curvature; keep the failed master and prior checks unchanged") as record:
        folder.mkdir(parents=True, exist_ok=False)
        formed = mesh.copy()
        formed.vertices = formed_vertices(mesh.vertices, surface, selected["flex_top"], selected["post_base_middle"])
        formed.invert()
        formed.export(folder / "formed_reference.stl")
        _, tangent, normal = surface.frame(surface.s)
        direction = surface.u if surface.kind == "nail" else np.array([1., 0., 0.])
        orient = np.einsum("ij,ij->i", np.cross(direction, tangent), normal)
        inside = (surface.s >= surface.body.bounds[1]) & (surface.s <= surface.body.bounds[3])
        curvature = surface.curvature()
        report = {
            "flat_source_sha256": digest(path), "site": args.site,
            "flat": {"volume": mesh.volume, "watertight": mesh.is_watertight,
                     "faces": len(mesh.faces), "maximum_edge_mm": mesh.edges_unique_length.max()},
            "formed": {"volume": formed.volume, "watertight": formed.is_watertight,
                        "winding_consistent": formed.is_winding_consistent,
                        "faces": len(formed.faces), "maximum_edge_mm": formed.edges_unique_length.max()},
            "sampled_chart_orientation": [float(min(orient)), float(max(orient))],
            "sampled_curvature_range": [float(min(curvature[inside])), float(max(curvature[inside]))],
            "sampled_offset_tangent_scale": {
                key: {"min": float(np.min((1+curvature*value)[inside])),
                      "max": float(np.max((1+curvature*value)[inside]))}
                for key, value in selected.items()},
            "physical_specimens_tested": 0}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
