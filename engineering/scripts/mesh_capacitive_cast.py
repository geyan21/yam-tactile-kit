#!/usr/bin/python3
"""Tessellate a K1 casting master before nonlinear surface mapping."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--size-mm", type=float, default=.15)
    args = parser.parse_args()
    source, target = args.step.resolve(), args.destination.resolve()
    if not source.is_relative_to(ROOT / "build") or not target.is_relative_to(ROOT / "build") or target.exists():
        parser.error("Use an owned CAD master and a new generated output directory")
    if not .05 <= args.size_mm <= .5:
        parser.error("Surface element size must be 0.05..0.5 mm")
    tool_path = ROOT / "build/engineering/tools/fea/tools.json"
    tool = json.loads(tool_path.read_text())
    sys.path.insert(0, str(ROOT / tool["gmsh_python_directory"]))
    import gmsh
    if gmsh.__version__ != tool["versions"]["gmsh"]:
        raise ValueError("Unexpected cached Gmsh version")
    with execution(ROOT / "build/records", "Remesh only the surface of the saved K1 casting CAD with the existing scoped Gmsh tool; this is geometry tessellation, not a mechanical solve") as record:
        target.mkdir(parents=True, exist_ok=False)
        gmsh.initialize([], readConfigFiles=False, run=False)
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.logger.start()
        try:
            gmsh.model.add("k1_cast_surface")
            volumes = gmsh.model.occ.importShapes(str(source))
            gmsh.model.occ.synchronize()
            if len([v for v in volumes if v[0] == 3]) != 1:
                raise ValueError("Expected one connected casting solid")
            for name, value in {"Mesh.MeshSizeMin": args.size_mm/4, "Mesh.MeshSizeMax": args.size_mm,
                                "Mesh.MeshSizeFromPoints": 0, "Mesh.MeshSizeFromCurvature": 32,
                                "Mesh.MeshSizeExtendFromBoundary": 0, "Mesh.ElementOrder": 1,
                                "Mesh.Algorithm": 6}.items():
                gmsh.option.setNumber(name, value)
            gmsh.model.mesh.generate(2)
            tags, coordinates, _ = gmsh.model.mesh.getNodes()
            order = np.argsort(tags)
            tags, vertices = tags[order], np.asarray(coordinates).reshape(-1, 3)[order]
            kinds, _, connectivity = gmsh.model.mesh.getElements(2)
            if list(kinds) != [2]:
                raise ValueError("Expected a first-order triangular boundary")
            node_tags = np.asarray(connectivity[0]).reshape(-1, 3)
            faces = np.searchsorted(tags, node_tags)
            if not np.array_equal(tags[faces], node_tags):
                raise ValueError("Missing surface nodes")
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
            mesh.fix_normals(multibody=True)
            if not mesh.is_watertight or mesh.volume <= 0:
                raise ValueError("The refined surface is not a closed positive-volume solid")
            gmsh_volume = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in volumes if dim == 3)
            error = abs(mesh.volume-gmsh_volume)/gmsh_volume
            if error > .01 or mesh.edges_unique_length.max() > args.size_mm*2.5:
                raise ValueError("The refined mesh exceeds its volume/edge bound")
            mesh.export(target / "flat_refined.stl")
            report = {"source_step_sha256": digest(source), "tool_manifest_sha256": digest(tool_path),
                      "gmsh_version": gmsh.__version__, "requested_size_mm": args.size_mm,
                      "vertices": len(mesh.vertices), "faces": len(mesh.faces),
                      "maximum_edge_mm": float(mesh.edges_unique_length.max()),
                      "cad_volume_mm3": gmsh_volume, "mesh_volume_mm3": mesh.volume,
                      "relative_volume_difference": error, "watertight": True,
                      "mesh_sha256": digest(target / "flat_refined.stl"), "physical_specimens_tested": 0}
            (target / "report.json").write_text(json.dumps(report, indent=2)+"\n")
            record["result"] = report
            print(json.dumps(report, indent=2))
        finally:
            (target / "gmsh.log").write_text("\n".join(gmsh.logger.get())+"\n")
            gmsh.finalize()


if __name__ == "__main__":
    main()
