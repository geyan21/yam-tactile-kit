#!/usr/bin/python3
"""Build the P1 channel-body witness and compare added material with the source frame."""

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
from shapely.geometry import Polygon
from tactile_kit.records import execution
from analyze_b1_interfaces import original_profile, extruded_profile
from prototype_cad import export_part, packed, yz_prism
from source_brep import load as source_solid
from screen_f1_feedback import digest


def common_volume(a, b):
    common = a.intersect(b)
    if common.wrapped.IsNull():
        return 0.
    if not common.isValid():
        raise ValueError("Invalid native intersection result")
    return abs(common.Volume())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout", type=Path)
    args = parser.parse_args()
    source = args.layout.resolve()
    if not source.is_relative_to(ROOT/"build"):
        parser.error("Use this checkout's generated wall-pair layout")
    plan = json.loads((source/"report.json").read_text())
    for name, expected in plan["input_sha256"].items():
        if digest(ROOT/name) != expected:
            raise ValueError("Layout input changed: "+name)
    profile = Polygon(plan["modified_profile"]["outer"], plan["modified_profile"]["holes"])
    folder = ROOT/"build/engineering/prototypes/pneumatic/insert_witnesses"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Build the actual P1 insert with eight straight through-channel references and check only added-material/frame interference; ports, plugs and sensing qualification remain") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        shape = yz_prism(profile, -15., plan["source_width_mm"])
        mesh, original_section, _ = original_profile()
        original = extruded_profile(original_section)
        hard, hard_receipt = source_solid("hard_frame")
        if abs(original.Volume()-mesh.volume) > mesh.volume*1e-5:
            raise ValueError("Original source conversion changed")
        added = shape.cut(original)
        added_volume = 0. if added.wrapped.IsNull() else added.Volume()
        baseline_overlap = common_volume(original, hard)
        modified_overlap = common_volume(shape, hard)
        added_overlap = 0. if added.wrapped.IsNull() else common_volume(added, hard)
        no_new_overlap = added_overlap <= .001 and modified_overlap <= baseline_overlap+.001
        parts, models = [], []
        display = export_part(
            shape, "p1_soft_insert_channel_witness", folder, parts,
            "Eight open through-channels in the original outer profile; port and plug interfaces are not yet supplied",
            "Flexible 80A resin is the published reference material; actual material/process and force response unqualified",
            "fabricate_fit_witness")
        models.append(packed(display, "p1_soft_insert_channel_witness", "p1_insert", "#91ab8a"))
        channels = []
        for case in plan["cases"]:
            for role in ("front", "back"):
                entry = case[role]
                x, y, z = entry["center_native_mm"]
                void = cq.Solid.makeCylinder(plan["channel_diameter_mm"]/2, plan["source_width_mm"],
                                              cq.Vector(-15, y, z), cq.Vector(1, 0, 0))
                identifier = entry["id"]+"_channel_volume"
                display = export_part(void, identifier, folder, parts, "Reserved gas volume; not a solid insert",
                                      "Air-space reference", "reference_only")
                models.append(packed(display, identifier, "p1_front_channels" if role == "front" else "p1_back_channels",
                                     "#327f9a" if role == "front" else "#805b95"))
                # The native circular reference differs from the 256-sided
                # layout cut by a small, explicitly retained faceting volume.
                overlap = common_volume(shape, void)
                channels.append({"site": case["site"], "role": role, "center_native_mm": entry["center_native_mm"],
                                 "nominal_volume_mm3": void.Volume(), "faceting_overlap_mm3": overlap,
                                 "faceting_screen_passed": overlap <= .005})
        if not all(row["faceting_screen_passed"] for row in channels):
            raise ValueError("Channel witness differs excessively from its nominal circular volume")
        paths = [Path(__file__), source/"report.json", ROOT/"engineering/scripts/prototype_cad.py",
                 ROOT/"engineering/scripts/source_brep.py", ROOT/"engineering/scripts/analyze_b1_interfaces.py"]
        for path in paths:
            target = folder/"inputs"/path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        report = {"schema": "yam-pneumatic-insert-witness/1", "physical_specimens_tested": 0,
                  "parts": parts, "channels": channels, "added_material_mm3": added_volume,
                  "original_frame_overlap_mm3": baseline_overlap, "modified_frame_overlap_mm3": modified_overlap,
                  "added_material_frame_overlap_mm3": added_overlap, "no_new_frame_interference": no_new_overlap,
                  "source_hard_conversion": hard_receipt,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in paths},
                  "limits": ["Open channels require accessible cleaning, plugs and sealed tube connections before pressure use.",
                             "This is an insert/fit witness, not a complete tactile prototype or a 20 N rating.",
                             "The comparison preserves any pre-existing source interference; it does not qualify actual mating.",
                             "Printing, resin aging, compliance, leakage, tube motion and calibration remain unmeasured."]}
        (folder/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder/"models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts": len(parts),
                            "added_material_mm3": added_volume, "no_new_frame_interference": no_new_overlap}
        print(json.dumps(record["result"], indent=2))
        if not no_new_overlap:
            raise ValueError("Resolve added-material interference before developing P1 ports")


if __name__ == "__main__":
    main()
