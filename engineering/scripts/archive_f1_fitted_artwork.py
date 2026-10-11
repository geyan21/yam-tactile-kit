#!/usr/bin/python3
"""Archive the checked R3-shaped electrode foils as a separate development module."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artwork", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("--destination", type=Path,
                        default=ROOT / "engineering/development/f1/fitted-foils-r3")
    args = parser.parse_args()
    source, review, target = [p.resolve() for p in (args.artwork, args.review, args.destination)]
    if not all(p.is_relative_to(ROOT) for p in (source, review, target)) or target.exists():
        parser.error("Use repository-owned inputs and a new checkpoint destination")
    plan_path = source / "artwork.json"
    plan = json.loads(plan_path.read_text())
    receipt = json.loads((source / "latest_independent_check.json").read_text())
    checked = ROOT / receipt["directory"]
    check_path = checked / "summary.json"
    check = json.loads(check_path.read_text())
    review_path = review / "report.json"
    report = json.loads(review_path.read_text())
    if (not check["all_passed"] or len(check["boards"]) != 12 or plan.get("failed_boards")
            or check["artwork_manifest_sha256"] != digest(plan_path)
            or report["input_sha256"].get(str(check_path.relative_to(ROOT))) != digest(check_path)
            or report["input_sha256"].get(str(plan_path.relative_to(ROOT))) != digest(plan_path)):
        raise ValueError("Use all twelve clean foils with the matching contact/resistance review")
    if len(report["taxels"]) != 64 or len(report["foil_paths"]) != 40:
        raise ValueError("Incomplete fitted map or conductor inventory")
    for name, expected in plan["source_hashes"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("A generation input changed: "+name)
    with execution(ROOT / "build/records", "Archive twelve independently checked fitted foils, all coverlay reports, native files, contact map and resistance limitations while preserving the earlier R3 interface packet") as record:
        target.mkdir(parents=True, exist_ok=False)
        for folder in ("foils", "checks", "review", "provenance"):
            (target / folder).mkdir()
        shutil.copyfile(plan_path, target / "provenance/artwork.json")
        shutil.copyfile(check_path, target / "checks/summary.json")
        input_paths = {}
        for path in sorted((source / "inputs").rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source / "inputs")
            archived = relative.with_name("checkpoint.input.json") if relative.name == "checkpoint.json" else relative
            destination = target / "provenance/inputs" / archived
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            input_paths[str(relative)] = {"archived_path": str(destination.relative_to(target)),
                                          "sha256": digest(path)}
        (target / "provenance/input_paths.json").write_text(json.dumps(input_paths, indent=2)+"\n")
        for path in review.iterdir():
            if path.is_file():
                shutil.copyfile(path, target / "review" / path.name)
        for row in check["boards"]:
            name = row["name"]
            entry = next(b for b in plan["boards"] if b["name"] == name)
            native = ROOT / entry["directory"]
            if (digest(native / (name+".kicad_pcb")) != row["source_pcb_sha256"]
                    or digest(native / (name+".json")) != row["source_metadata_sha256"]
                    or digest(native / (name+".kicad_dru")) != row["source_rules_sha256"]):
                raise ValueError("Native foil identity changed")
            shutil.copytree(native, target / "foils" / name)
            per_check = target / "checks" / name
            per_check.mkdir()
            for mode in ("unsuppressed", "manufacturing_intent"):
                shutil.copyfile(checked / name / mode / "drc.json", per_check / (mode+".json"))
            for filename in ("checks.json", "development_export.json"):
                shutil.copyfile(checked / name / filename, per_check / filename)
            exported = json.loads((checked / name / "development_export.json").read_text())
            for filename, expected in exported["files"].items():
                if digest(checked / name / "development_fabrication" / filename) != expected:
                    raise ValueError("A fabrication export changed")
            shutil.copytree(checked / name / "development_fabrication", target / "foils" / name / "artwork")
        nominal = max(p["nominal_20c_trace_ohm"] for p in report["foil_paths"])
        scenario = max(p["screen_50c_minimum_copper_width_trace_ohm"] for p in report["foil_paths"])
        mask_findings = sum(row["unsuppressed_coverlay_findings"] for row in check["boards"])
        readme = f"""# F1 R3 fitted electrode foils

This module contains twelve routed sensing foils on the nominal R3 fit shapes.
**It is development artwork, not a qualified complete tactile finger.**
The matching R3 interface/carrier packet and wrist electronics remain separate.
No physical foil, finger or 20 N force/contact result has been measured.

## What is included

- Twelve native KiCad boards, editable conductor metadata, footprints and drawings.
- Ten single-copper foils and two double-copper nail-row foils.
- Corresponding development Gerbers, coverlay layers, outline and drills.
- All independent copper/connectivity checks and both coverlay-report versions.
- A 64-location contact map and forty individual trace-resistance estimates.
- Captured generation inputs, the exact connector maps and each failed-run history in the workspace.

![Fitted contact allocation](review/fitted_contact_map.png)

The map uses the actual routed copper after separately unrolling the row and
column surfaces. CH0/CH1 have eight electrical locations each; CH2–CH5 have
twelve each. CH2 exits distally: its column order is reversed in source U.
CH4 uses global columns 13–15; CH5 uses 10–12. Use `review/taxels.csv`
and the per-foil pin maps instead of assuming sequential physical columns.
This map establishes nominal geometry, not independent pressure pixels or
freedom from lateral film conduction.

## Copper checks

All twelve boards pass the independent copper/connectivity checks with zero
unreviewed findings and zero missing connections. The unsuppressed reports
retain {mask_findings} shared-coverlay findings. These windows intentionally expose
separate unsoldered sensing electrodes and connector fingers; only that mask
rule is allowed. No copper short or missing connection is waived.

The R3 fit references are preserved. The fitted cuts record 10 nm coordinate
quantization to close numerical seams, with a bounded symmetric difference.
The traces include 0.29 mm necks, 0.44 mm long routes, short 0.225 mm
relief regions and 0.15 mm connector fanouts. Four row traces fit inside
the declared tail envelope. The two nail foils keep their plated transitions
in the supported body/tab regions, including a stagger at pin 1.

## Resistance result and limits

The largest nominal one-dimensional trace estimate is **{nominal:.4f} Ω** at
20 °C with 35 µm copper. The stated 50 °C scenario, 31.5 µm minimum copper
and 20% negative width tolerance gives **{scenario:.4f} Ω**.

These numbers exclude electrode spreading, plated barrels, current crowding,
finish, connector contacts, PCBs, the cable and bending-induced changes.
They are not upper bounds or a completed branch-resistance budget.
The earlier 0.25 Ω branch/path assumptions must be reviewed using the
whole circuit; a passing copper check does not establish that budget.

## Reproduce and assemble

Use the complete source repository with its documented CAD/Python environment:

```sh
build/engineering/tools/cad-venv/bin/python engineering/scripts/develop_f1_fitted_artwork.py
/usr/bin/python3 engineering/scripts/check_f1_flex.py ARTWORK_RUN --export
build/engineering/tools/cad-venv/bin/python engineering/scripts/review_f1_fitted_artwork.py ARTWORK_RUN
/usr/bin/python3 engineering/scripts/verify_f1_checkpoint.py engineering/development/f1/fitted-foils-r3
```

Use the F1 build guide for the six film islands, their surfaces, the R3
carrier, electrical mapping and raw recorder. The intended sensing material
is 0.10 mm conductive pressure film, with Adafruit 1361 as the documented
prototype material reference. Record supplier, lot and actual thickness.

Finish the connector mating datum, complete stiffener/adhesive/finish drawing
and 0.30 mm mating thickness before ordering finished foils. The plotted
stiffener rectangles are target regions, not a completed lamination process.
Complete sealing, object access, inextensible slack, loaded bending, wear,
the full resistance/reference/array checks, and physical calibration through
20 N before using F1 for force feedback or recommending it over the other designs.
"""
        (target / "README.md").write_text(readme)
        checkpoint = {"schema": "yam-f1-fitted-foils-checkpoint/1",
                      "created_utc": datetime.now(timezone.utc).isoformat(),
                      "integrated_f1_completed": False, "physical_specimens_tested": 0,
                      "independent_check": {"passed": True, "foils": 12, "unreviewed_findings": 0,
                                            "unconnected": 0, "reviewed_shared_coverlay_findings": mask_findings,
                                            "source_sha256": digest(check_path)},
                      "taxels": 64, "foil_conductor_paths": 40,
                      "review_sha256": digest(review_path),
                      "files_sha256": {str(p.relative_to(target)): digest(p) for p in sorted(target.rglob("*")) if p.is_file()}}
        (target / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2)+"\n")
        record["result"] = {"directory": str(target.relative_to(ROOT)),
                            "files": len(checkpoint["files_sha256"]),
                            "checkpoint_sha256": digest(target / "checkpoint.json"),
                            "integrated_f1_completed": False, "physical_specimens_tested": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
