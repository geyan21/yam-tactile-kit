#!/usr/bin/python3
"""Extend K1 rigid saddles down to the retained TPU-fit geometry."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/capacitive-cad-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq

from tactile_kit.records import execution
from capacitive_geometry import CONFIG, load, offsets
from build_f1_stack_parts import slab
from analyze_b1_interfaces import original_profile, extruded_profile
from source_brep import load as source_solid
from check_f1_tail_fit import check_pair
from prototype_cad import export_part, packed, block
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cell_cad", type=Path)
    args = parser.parse_args()
    source = args.cell_cad.resolve()
    if not source.is_relative_to(ROOT / "build"):
        parser.error("Use the saved K1 cell CAD run")
    cfg, surfaces = load()
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    r1_path = ROOT / cfg["basis"]["r1_manifest"]
    r1 = json.loads(r1_path.read_text())
    folder = ROOT / "build/engineering/prototypes/capacitive/saddle_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Create full K1 conforming supports from the checked R1 witness geometry, reserve a flex bond line, and check source/peer intersections; retain the earlier floating slab references") as record:
        folder.mkdir(parents=True, exist_ok=False)
        source_paths = [CONFIG, manifest_path, r1_path, Path(__file__),
                        ROOT / "engineering/scripts/capacitive_geometry.py",
                        ROOT / "engineering/scripts/build_f1_stack_parts.py",
                        ROOT / "engineering/scripts/prototype_cad.py",
                        ROOT / "engineering/scripts/check_f1_tail_fit.py",
                        ROOT / "engineering/scripts/source_brep.py",
                        ROOT / "engineering/scripts/analyze_b1_interfaces.py"]
        hard, hard_check = source_solid("hard_frame")
        soft_mesh, profile, _ = original_profile()
        soft = extruded_profile(profile)
        if abs(soft.Volume()-soft_mesh.volume) > soft_mesh.volume*1e-5:
            raise ValueError("TPU extrusion differs from its source volume")
        parts, models, checks, supports = [], [], [], []
        record["generated_parts"] = parts
        bond_mm = .05
        for site in range(2, 6):
            surface = surfaces[site]
            positions = offsets(site, cfg)
            witness = next(p for p in r1["parts"] if p["id"] == f"pad_{site}_saddle_witness")
            witness_path = ROOT / "engineering/release/r1" / witness["step"]
            if digest(witness_path) != witness["sha256_step"]:
                raise ValueError("R1 support witness changed")
            source_paths.append(witness_path)
            base = cq.importers.importStep(str(witness_path)).val()
            volume_before = base.Volume()
            x0 = r1["pads"][site-2]["assembly_native_x_limits_mm"][0]
            # R1 tooling XYZ = native Y, native Z, transverse distance.
            base = base.rotate((0, 0, 0), (1, 1, 1), 120).translate((x0, 0, 0))
            if abs(base.Volume()-volume_before) > 1e-7:
                raise ValueError("Rigid source-coordinate transform changed volume")
            start, _, _ = surface.frame(surface.body.bounds[1])
            end, _, _ = surface.frame(surface.body.bounds[3])
            bb = base.BoundingBox()
            trim = block(bb.xmin-1, bb.xmax+1, float(start[1]), float(end[1]), bb.zmin-2, bb.zmax+2)
            base = base.intersect(trim)
            extension = slab(surface, surface.body, -.03, positions["flex_bottom"]-bond_mm)
            support = base.fuse(extension).clean()
            name = f"k1_ch{site}_conforming_saddle"
            mesh = export_part(support, name, folder, parts,
                               f"CH{site} complete rigid support from the retained TPU-fit back surface to the flex bond",
                               "PETG prototype; actual fit, bond, stiffness and durability remain untested", "fabricate")
            models.append(packed(mesh, name, "k1_rigid_saddle", "#b9c5d0"))
            for other, solid in (("source_hard_frame", hard), ("source_TPU", soft), *supports):
                checks.append(check_pair(name, support, other, solid))
            flex_part = next(p for p in manifest["parts"] if p["id"] == f"k1_ch{site}_flex_reference")
            flex_path = source / flex_part["step"]
            if digest(flex_path) != flex_part["sha256_step"]:
                raise ValueError("K1 flex reference changed")
            flex = cq.importers.importStep(str(flex_path)).val()
            checks.append(check_pair(name, support, flex_part["id"], flex))
            supports.append((name, support))
            (folder / "partial.json").write_text(json.dumps({"parts": parts, "checks": checks}, indent=2)+"\n")
            print(f"CH{site}: conforming support exported; {sum(not p['passed'] for p in checks)} unresolved checks", flush=True)
        for path in source_paths:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        report = {"schema": "yam-k1-conforming-saddles/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in source_paths},
                  "parts": parts, "checks": checks, "passed_nominal_checks": all(p["passed"] for p in checks),
                  "hard_source_conversion": hard_check, "flex_bond_normal_mm": bond_mm,
                  "replaces": [f"k1_ch{site}_rigid_saddle" for site in range(2, 6)],
                  "limits": [
                      "The initial 0.8 mm slab alone did not reach the raw TPU surface; use these full supports.",
                      "The R1 witness supplies the variable-thickness fitting base below the smoothed surface datum.",
                      "The nominal K1 stack height is measured above the R1 smoothed datum, not the total addition to raw TPU.",
                      "The back-to-TPU clearance and adhesive filling must be measured on the actual print.",
                      "The declared 0.05 mm flex bond line, source motion, retention, cable routing and force response remain physically unverified."
                  ]}
        (folder / "manifest.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts),
                            "checks": len(checks), "passed_nominal_checks": report["passed_nominal_checks"]}
        print(json.dumps(record["result"], indent=2))
        if not report["passed_nominal_checks"]:
            raise ValueError("Conforming support intersections remain unresolved")


if __name__ == "__main__":
    main()
