#!/usr/bin/python3
"""Check a narrow stem and outboard hose sleeve at the constrained P1 front port."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT/"build/engineering/tools/pneumatic-cad-cache"))
sys.path.insert(0, str(ROOT/"src"))
import cadquery as cq
from tactile_kit.records import execution
from source_brep import load as source_solid
from prototype_cad import export_part, packed
from build_pneumatic_ports import cylinder
from build_pneumatic_insert_witness import common_volume
from screen_f1_feedback import digest

CONFIG = ROOT/"engineering/designs/pneumatic_slim_port.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout", type=Path)
    parser.add_argument("witness", type=Path)
    args = parser.parse_args()
    layout, witness = args.layout.resolve(), args.witness.resolve()
    plan = json.loads((layout/"report.json").read_text())
    base = json.loads((witness/"report.json").read_text())
    for report in (plan, base):
        for name, expected in report["input_sha256"].items():
            if digest(ROOT/name) != expected:
                raise ValueError("Source input changed")
    cfg = json.loads(CONFIG.read_text())
    entry = next(row for row in plan["cases"] if row["site"] == cfg["site"])[cfg["role"]]
    _, y, z = entry["center_native_mm"]
    part = next(part for part in base["parts"] if part["id"] == "p1_soft_insert_channel_witness")
    path = witness/part["step"]
    if digest(path) != part["sha256_step"]:
        raise ValueError("Witness changed")
    body = cq.importers.importStep(str(path)).val()
    hard, receipt = source_solid("hard_frame")
    folder = ROOT/"build/engineering/prototypes/pneumatic/slim_port_probes"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Check one narrow bonded stem with its hose connection moved beyond the frame, including a declared radial clearance guard; do not infer loaded fit or seal performance") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [CONFIG, Path(__file__), layout/"report.json", witness/"report.json",
                  ROOT/"engineering/scripts/build_pneumatic_ports.py", ROOT/"engineering/scripts/source_brep.py"]
        for source in inputs:
            destination = folder/"inputs"/source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        cases, parts, models = [], [], []
        for sign in (-1, 1):
            face = -15. if sign < 0 else 0.
            length = cfg["embedded_length_mm"]+cfg["external_length_mm"]
            start = face-sign*cfg["embedded_length_mm"]
            stem_outer = cylinder(cfg["stem_outer_diameter_mm"]/2, length, start, y, z, sign)
            stem = stem_outer.cut(cylinder(cfg["stem_inner_diameter_mm"]/2, length, start, y, z, sign))
            sleeve_start = face+sign*(cfg["external_length_mm"]-cfg["sleeve_length_mm"])
            sleeve_outer = cylinder(cfg["sleeve_outer_diameter_mm"]/2, cfg["sleeve_length_mm"], sleeve_start, y, z, sign)
            sleeve = sleeve_outer.cut(cylinder(cfg["sleeve_inner_diameter_mm"]/2, cfg["sleeve_length_mm"], sleeve_start, y, z, sign))
            guard = cfg["radial_clearance_guard_mm"]
            stem_guard = cylinder(cfg["stem_outer_diameter_mm"]/2+guard, length, start, y, z, sign)
            hose_guard = cylinder(cfg["hose_envelope_diameter_mm"]/2+guard, cfg["sleeve_length_mm"], sleeve_start, y, z, sign)
            checks = {
                "stem_frame_overlap_mm3": common_volume(stem_outer, hard),
                "stem_insert_overlap_mm3": common_volume(stem, body),
                "stem_guard_frame_overlap_mm3": common_volume(stem_guard, hard),
                "hose_guard_frame_overlap_mm3": common_volume(hose_guard, hard),
                "hose_guard_insert_overlap_mm3": common_volume(hose_guard, body),
            }
            passed = all(value <= .001 for value in checks.values())
            cases.append({"sign": sign, "center_native_yz_mm": [y, z], **checks, "passed": passed})
            for name, shape, material in (("stem", stem, "304/316 stainless dimensional target"),
                                           ("sleeve", sleeve, "304/316 stainless dimensional target"),
                                           ("hose_guard", hose_guard, "Clearance reference; not a physical tube")):
                identifier = f"p1_ch{cfg['site']}_{cfg['role']}_slim_{sign:+d}_{name}"
                display = export_part(shape, identifier, folder, parts, "Slim-port fit reference", material, "reference_only")
                models.append(packed(display, identifier, "p1_slim_port", "#7194a6"))
        report = {"schema": "yam-pneumatic-slim-port-probe/1", "physical_specimens_tested": 0,
                  "cases": cases, "parts": parts, "radial_clearance_guard_mm": cfg["radial_clearance_guard_mm"],
                  "source_hard_conversion": receipt,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
                  "limits": cfg["limits"]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "cases": cases}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
