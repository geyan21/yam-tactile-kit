#!/usr/bin/python3
"""Join F1 body, contact-finish and tail references into complete material envelopes."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/f1-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
import cadquery as cq
from tactile_kit.records import execution
from prototype_cad import export_part, packed
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skin", type=Path)
    parser.add_argument("terminals", type=Path)
    args = parser.parse_args()
    paths = {"skin": args.skin.resolve(), "terminals": args.terminals.resolve()}
    reports = {key: json.loads((path / "report.json").read_text()) for key, path in paths.items()}
    for report in reports.values():
        for name, expected in report["input_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError("An assembly input changed")
    lookup = {key: {part["id"]: part for part in report["parts"]} for key, report in reports.items()}
    def shape(kind, identifier):
        part = lookup[kind][identifier]; path = paths[kind] / part["step"]
        if digest(path) != part["sha256_step"]:
            raise ValueError("A source shape changed")
        return cq.importers.importStep(str(path)).val()
    folder = ROOT / "build/engineering/prototypes/f1/joined_foil_cad" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Join each F1 sensing-body envelope to its actual tail and plated-contact height reference; require one connected valid solid and retain all source geometry") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [Path(__file__), paths["skin"] / "report.json", paths["terminals"] / "report.json"]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        parts, models, joins = [], [], []
        for site in range(6):
            for role, finish_role in (("columns", "column"), ("rows", "row")):
                name = f"f1_ch{site}_{role}"
                body = shape("skin", name+"_body")
                finish = shape("skin", f"f1_ch{site}_{finish_role}_finish_envelope")
                tail = shape("terminals", name+"_finished_tail")
                gap = body.distance(tail)
                overlap = body.intersect(tail)
                common_volume = 0. if overlap.wrapped.IsNull() else overlap.Volume()
                joined = body.fuse(finish, tail).clean()
                identifier = name+"_complete_envelope"
                display = export_part(joined, identifier, folder, parts,
                                      "Complete formed FPC material envelope; native copper and mask artwork remain authoritative",
                                      "PI/Cu/coverlay/finish envelope, not a printable functional sensor", "reference_only")
                models.append(packed(display, identifier, "f1_foils", "#729ba8" if role == "columns" else "#a89b72"))
                joins.append({"foil": name, "body_tail_distance_mm": gap, "shared_envelope_volume_mm3": common_volume,
                              "valid_connected_envelope": True, "physical_continuity_tested": False})
                (folder / "partial.json").write_text(json.dumps({"parts": parts, "joins": joins}, indent=2)+"\n")
                print(name+": complete body/tail envelope exported", flush=True)
        report = {"schema": "yam-f1-complete-foil-envelopes/1", "physical_specimens_tested": 0,
                  "parts": parts, "joins": joins, "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "limits": ["Homogenized material envelopes, not an electrical copper model or a measured neutral axis.",
                             "The 6.4 µm nominal active-stack finish allowance is within the earlier 20 µm forming-axis sensitivity, but real forming and strain remain unqualified.",
                             "Body/neck overlap represents a continuous foil envelope; manufacture from the checked flat copper, mask and cutting files.",
                             "Connector mating, loaded motion, fatigue and physical force/contact performance remain separate requirements."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        (folder / "models.json").write_text(json.dumps(models, separators=(",", ":"))+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "complete_foil_envelopes": len(parts)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
