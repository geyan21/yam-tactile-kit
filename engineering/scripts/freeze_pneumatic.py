#!/usr/bin/python3
"""Freeze a coherent P1 bench package while retaining its physical/model limits."""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def verify(root, mapping):
    for name, expected in mapping.items():
        if digest(root/name) != expected:
            raise ValueError("Changed input or artifact: "+str(root/name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("assembly", "bench", "board", "pairs", "integration", "visuals", "diagrams")
    for name in names:
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT/"engineering/prototypes/pneumatic")
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in names}
    target = args.destination.resolve()
    if target.exists() or not all(path.is_relative_to(ROOT) for path in (*paths.values(), target)):
        parser.error("Use repository inputs and a fresh destination")
    reports = {name: json.loads((path/"report.json").read_text()) for name, path in paths.items()}
    for name, report in reports.items():
        verify(ROOT, report.get("input_sha256", {}))
        verify(paths[name], report.get("files_sha256", {}))
    if (any(not reports[name]["passed_nominal_checks"] for name in ("assembly", "bench"))
            or not reports["integration"]["passed"] or not reports["diagrams"]["passed_canvas_bounds"]):
        raise ValueError("Resolve geometry, electrical-contract and drawing checks before freezing")
    for consumer, dependencies in (("integration", ("assembly", "bench", "board")),
                                   ("visuals", ("assembly", "bench", "board", "pairs")),
                                   ("pairs", ("assembly",))):
        for dependency in dependencies:
            path = paths[dependency]/"report.json"
            if reports[consumer]["input_sha256"].get(str(path.relative_to(ROOT))) != digest(path):
                raise ValueError("Mixed P1 run selection: "+consumer+"/"+dependency)
    for drawing in reports["diagrams"]["diagrams"]:
        if digest(ROOT/drawing["source"]) != drawing["source_sha256"]:
            raise ValueError("A reviewed diagram changed")
    expected_card = paths["integration"]/"p1_pcb_orientation.svg"
    if not any(row["source"] == str(expected_card.relative_to(ROOT)) for row in reports["diagrams"]["diagrams"]):
        raise ValueError("The diagram review must cover this integration's card")
    native = json.loads((paths["board"]/"latest_check.json").read_text())
    checked = paths["board"]/native["directory"]
    receipt = json.loads((checked/"pcb_checks.json").read_text())
    if (native["violations"] or native["unconnected"] or receipt["violations"] or receipt["unconnected"]
            or native["source_sha256"] != reports["board"]["pcb_sha256"]
            or digest(checked/"p1_readout.kicad_pcb") != receipt["checked_pcb_sha256"]):
        raise ValueError("Require a complete matching native PCB/fabrication check")
    verify(checked/"manufacturing", receipt["files"])
    folder = ROOT/"build/engineering/prototypes/pneumatic/package_runs"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    stage = folder/"package"
    with execution(ROOT/"build/records", "Freeze the matching P1 CAD, checked readout, explicit hoses/nails, acquisition code, static-force tools and drawings; preserve model failures and all physical qualification limits") as record:
        stage.mkdir(parents=True)
        record["staging_directory"] = str(folder.relative_to(ROOT))
        for name in ("cad", "checks", "visuals", "patterns", "docs", "templates", "software", "firmware", "provenance"):
            (stage/name).mkdir()
        parts, seen = [], set()
        for module in ("assembly", "bench"):
            for part in reports[module]["parts"]:
                if part["id"] in seen:
                    raise ValueError("Duplicate part identity")
                seen.add(part["id"])
                for extension in ("step", "stl"):
                    path = paths[module]/part[extension]
                    if digest(path) != part["sha256_"+extension]:
                        raise ValueError("CAD export changed")
                    shutil.copyfile(path, stage/part[extension])
                parts.append(part)
        nails = {part["id"] for part in reports["bench"]["parts"] if part["id"].startswith(("p1_ch0_", "p1_ch1_"))}
        air = {part["id"] for part in reports["assembly"]["parts"]}
        observed_pairs = {(row["a"], row["b"]) for row in reports["integration"]["cross_module_checks"]}
        if observed_pairs != {(a, b) for a in nails for b in air}:
            raise ValueError("The cross-module fit review is incomplete")
        for name in names:
            shutil.copyfile(paths[name]/"report.json", stage/"checks"/(name+".json"))
            if (paths[name]/"inputs").is_dir():
                shutil.copytree(paths[name]/"inputs", stage/"provenance"/name/"inputs")
        for name in ("scenarios.csv", "common_compression.csv"):
            shutil.copyfile(paths["pairs"]/name, stage/"checks"/name)
        for name in reports["visuals"]["files_sha256"]:
            output = stage/("models.json" if name == "models.json" else
                           "port_cut_and_hose_map.csv" if name == "port_cut_and_hose_map.csv" else "visuals/"+name)
            shutil.copyfile(paths["visuals"]/name, output)
        shutil.copyfile(expected_card, stage/"visuals/p1_pcb_orientation.svg")
        shutil.copyfile(ROOT/"engineering/web/p1_wiring.svg", stage/"visuals/p1_wiring.svg")
        for name in ("p1_pcb_orientation.png", "p1_wiring.png"):
            shutil.copyfile(paths["diagrams"]/name, stage/"visuals"/name)
        electronics = stage/"electronics/readout"
        electronics.mkdir(parents=True)
        for name in ("p1_readout.kicad_pcb", "p1_readout.kicad_dru", "p1_readout.json", "p1_readout_pin_net.csv",
                     "fp-lib-table", "report.json", "latest_check.json", "assembly.svg"):
            shutil.copyfile(paths["board"]/name, electronics/name)
        shutil.copytree(paths["board"]/"Prototype.pretty", electronics/"Prototype.pretty")
        shutil.copytree(checked, electronics/native["directory"])
        shutil.copyfile(checked/"p1_readout_fabrication.zip", electronics/"p1_readout_fabrication.zip")
        board = json.loads((paths["board"]/"p1_readout.json").read_text())
        with (electronics/"components.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["reference", "value", "x_mm", "y_mm", "rotation_deg", "source", "note"])
            for component in board["components"]:
                writer.writerow([component["reference"], component["value"], *component["center_mm"],
                                 component["rotation_deg"], component.get("source", ""), component.get("note", "")])
        for name in ("r1_cut_sheet.svg", "r1_cut_sheet.pdf"):
            shutil.copyfile(ROOT/"engineering/release/r1"/name, stage/"patterns"/name)
        nail_basis = json.loads((ROOT/"engineering/release/r1/r1_manifest.json").read_text())
        (stage/"patterns/nail_cells.json").write_text(json.dumps(nail_basis["nail_active_cells"], indent=2)+"\n")
        doc_names = ("BUILD_PNEUMATIC", "PNEUMATIC_ELECTRONICS", "PNEUMATIC_TESTING", "PNEUMATIC_REPRODUCE")
        for name in doc_names:
            shutil.copyfile(ROOT/("engineering/docs/"+name+".md"), stage/"docs"/(name+".md"))
        shutil.copyfile(ROOT/"engineering/templates/pneumatic_force_trials.json", stage/"templates/pneumatic_force_trials.json")
        shutil.copyfile(ROOT/"engineering/designs/pneumatic_bom.csv", stage/"bom.csv")
        for path in (ROOT/"engineering/firmware/pneumatic").glob("*"):
            if path.is_file() and path.suffix in (".py", ".json"):
                shutil.copyfile(path, stage/"firmware"/path.name)
        for path in [*(ROOT/"engineering/software").glob("pneumatic_*.py"),
                     ROOT/"engineering/software/capacitive_force.py", ROOT/"engineering/software/capacitive_protocol.py"]:
            shutil.copyfile(path, stage/"software"/path.name)
        with zipfile.ZipFile(stage/"p1_firmware.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((stage/"firmware").iterdir()):
                archive.write(path, path.name)
        with (stage/"parts.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["id", "kind", "purpose", "material", "STEP", "STL"])
            for part in parts:
                writer.writerow([part["id"], part["kind"], part["purpose"], part["material"], part["step"], part["stl"]])
        manifest = {"schema": "yam-p1-prototype-cad/1", "revision": "P1.0", "parts": parts,
                    "physical_specimens_tested": 0, "physical_qualification": False,
                    "status": "Digital bench package; actual seals, tubing, motion and tactile performance unqualified",
                    "nominal_nail_addition_mm": .4, "air_channel_count": 8, "differential_transducers": 4,
                    "pressure_sensor": "ELVR-L30D-F1RD-C-NI3H", "pcb_components": len(board["components"]),
                    "parts_and_air_comparisons": reports["integration"]["module_comparisons"],
                    "gas_model_out_of_nominal_range": reports["pairs"]["scenarios_outside_nominal_range"],
                    "inputs": {name: digest(path/"report.json") for name, path in paths.items()}}
        (stage/"pneumatic_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
        (stage/"provenance/source_runs.json").write_text(json.dumps({
            name: {"directory": str(path.relative_to(ROOT)), "report_sha256": digest(path/"report.json")}
            for name, path in paths.items()}, indent=2)+"\n")
        (stage/"README.md").write_text(
            "# P1.0 pneumatic bench design\n\n"
            "**Eight air channels, four remote differential transducers and two thin R1 N0 nail cells. Zero physical builds or tests.**\n\n"
            "Start at pneumatic.html and build-pneumatic.html on the website. Exact wiring is on "
            "pneumatic-electronics.html; testing and digital reproduction have their own pages. "
            "For host scripts, shared R1 construction instructions and regeneration, use the complete "
            "repository or the complete portable kit's source directory. This prototype ZIP is the "
            "matching design/fabrication packet, not a standalone installed Python environment.\n\n"
            "`cad/` contains 112 parts and references. Print the replacement insert, closure plugs and "
            "bench carrier as specified. Gas spaces, bond envelopes, metal tubes, electronics and nail "
            "laminates are references: do not print them as substitutes for functional materials.\n\n"
            "`port_cut_and_hose_map.csv` is the actual selected tube table. Six standard tubes are "
            "6 mm long, CH5 back is 8 mm, and CH4 front uses the 15 mm slim stem plus its 3 mm sleeve. "
            "Front goes to B high and back to A low of the same PS0..PS3 sensor. "
            "The first 3 mm engagement and 5 mm straight hose departure are modeled; measure and "
            "support the remaining slack hoses on the actual assembly.\n\n"
            "`electronics/readout/p1_readout_fabrication.zip` is the checked PCB fabrication export. "
            "Use its complete components.csv as well as bom.csv. The native source, embedded footprints, "
            "pin/net list and independent DRC remain alongside it. The orientation card identifies all "
            "pressure-chip pins and both Pico socket pin-one positions. Inspect actual sensor ports "
            "and supplied headers/fasteners before assembly.\n\n"
            "`patterns/r1_cut_sheet.*` retains the original R1 sheet; only its CH0/CH1 nail patterns "
            "are used by P1. Nominal N0 nail addition is 0.4 mm; measure the installed stack. "
            "Each nail cell needs its own 100k continuity resistor at the nail joint.\n\n"
            "`firmware/` streams raw pressure/nail/supply data. `software/` preserves missing data, "
            "raw bytes and receipts and provides a fixed signed linear stationary-force baseline "
            "with independent physical evaluation. It supplies no measured model or qualified contact detector.\n\n"
            "Nominal assembly, hose-clearance, cross-module and board checks pass. The ideal-gas study "
            "retains 26 out-of-range scenarios among 3,888 and an explicit common-pressure cancellation "
            "example. These are scenario inputs, not a 20 N force prediction. Actual seals, printed "
            "channels, pressure span, thermal/hose effects, loaded motion, contact reliability, force "
            "accuracy and task precision remain to be measured.\n\n"
            "The original rigid ENPIRE frame is retained. Geometry attribution and source limitations "
            "remain in the shared geometry guide/release manifest. Earlier failed development runs "
            "remain in their original build directories; this package contains the coherent selected revision.\n")
        sources = [Path(__file__), ROOT/"engineering/web/p1_wiring.svg", ROOT/"engineering/designs/pneumatic_bom.csv",
                   ROOT/"engineering/templates/pneumatic_force_trials.json",
                   ROOT/"engineering/software/capacitive_force.py", ROOT/"engineering/software/capacitive_protocol.py"]
        sources += [ROOT/("engineering/docs/"+name+".md") for name in doc_names]
        sources += [p for p in (ROOT/"engineering/firmware/pneumatic").glob("*") if p.is_file() and p.suffix in (".py", ".json")]
        sources += list((ROOT/"engineering/software").glob("pneumatic_*.py"))
        sources += list((ROOT/"engineering/designs").glob("pneumatic_*.json"))
        sources += [ROOT/"engineering/research/pneumatic_source_review.json"]
        for report in reports.values():
            sources += [ROOT/name for name in report.get("input_sha256", {}) if name.startswith(("engineering/", "src/"))]
        sources += [ROOT/"engineering/scripts/check_prototype_pcb.py"]
        snapshot = {"schema": "yam-prototype-snapshot/1", "id": "PNEUMATIC", "revision": "P1.0",
                    "design_label": "P1", "design_page": "pneumatic.html", "physical_specimens_tested": 0,
                    "status": manifest["status"], "shared_release_sha256": digest(ROOT/"engineering/release/release_manifest.json"),
                    "source_hashes": {str(path.relative_to(ROOT)): digest(path) for path in sorted(set(sources))},
                    "files": {str(path.relative_to(stage)): digest(path) for path in sorted(stage.rglob("*")) if path.is_file()},
                    "checks": {"cad_parts": len(parts), "pcb_components": len(board["components"]),
                               "drc_violations": 0, "unconnected_items": 0,
                               "declared_geometry_comparisons": sum(reports["integration"]["module_comparisons"].values()),
                               "gas_model_range_failures_retained": reports["pairs"]["scenarios_outside_nominal_range"],
                               "physical_qualification": False}}
        (stage/"prototype_snapshot.json").write_text(json.dumps(snapshot, indent=2)+"\n")
        target.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(target)
        record["result"] = {"directory": str(target.relative_to(ROOT)), "files": len(snapshot["files"]),
                            "snapshot_sha256": digest(target/"prototype_snapshot.json"), **snapshot["checks"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
