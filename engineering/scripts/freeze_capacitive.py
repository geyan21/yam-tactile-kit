#!/usr/bin/python3
"""Freeze the K1.2 bench prototype with its passing fit checks and retained model findings."""

import argparse
import csv
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def verify(base, values):
    for name, expected in values.items():
        if digest(base / name) != expected:
            raise ValueError("Changed input or artifact: "+str(base / name))


def read(folder, name="report.json"):
    return json.loads((folder / name).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("cells", "saddles", "foils", "foil_fit", "native", "native_check", "mechanics",
             "clearances", "assembly", "stiffeners", "enclosure", "screen", "visuals")
    for name in names:
        parser.add_argument("--"+name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--molds", nargs="+", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / "engineering/prototypes/capacitive")
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in names}
    molds = [p.resolve() for p in args.molds]; target = args.destination.resolve()
    if target.exists() or not all(p.is_relative_to(ROOT) for p in (*paths.values(), *molds, target)):
        parser.error("Use repository-owned inputs and a fresh prototype directory")
    reports = {name: read(path, "manifest.json" if name in ("cells", "saddles") else "report.json")
               for name, path in paths.items()}
    for name in ("cells", "saddles", "foils", "mechanics", "stiffeners", "enclosure", "screen", "visuals", "assembly"):
        verify(ROOT, reports[name]["input_sha256"])
    foil_hash = digest(paths["foils"] / "report.json")
    if (reports["native"]["source_geometry_report_sha256"] != foil_hash
            or reports["native_check"]["source_set_sha256"] != digest(paths["native"] / "report.json")
            or reports["foil_fit"]["source_geometry_sha256"] != foil_hash
            or reports["foil_fit"]["pose_sha256"] != digest(ROOT / "engineering/designs/capacitive_tail_poses.json")):
        raise ValueError("Native copper, formed foils and tail pose must share the same checked source")
    for consumer, dependencies in (
            ("assembly", ("mechanics", "foil_fit")), ("enclosure", ("mechanics", "foils")),
            ("stiffeners", ("foils",)), ("screen", ("foils",))):
        for dependency in dependencies:
            path = paths[dependency] / "report.json"
            if reports[consumer]["input_sha256"].get(str(path.relative_to(ROOT))) != digest(path):
                raise ValueError(f"{consumer} was not checked against the selected {dependency}")
    if (not reports["saddles"]["passed_nominal_checks"]
            or not reports["foil_fit"]["passed_declared_checks"]
            or not reports["assembly"]["passed_declared_checks"]
            or set(reports["assembly"]["sites_checked"]) != set(range(6))
            or not reports["clearances"]["passed_lip_stop_screen"]
            or not reports["enclosure"]["passed"]):
        raise ValueError("Resolve nominal mechanical checks before packaging")
    if reports["clearances"]["mechanics_report_sha256"] != digest(paths["mechanics"] / "report.json"):
        raise ValueError("Lip check belongs to another cell assembly")
    if not all(row["below_joined_shield_planning_limit"] for row in reports["screen"]["shield"]):
        raise ValueError("The complete foil/cable planning budget exceeds its limit")
    board_checks = reports["native_check"]["boards"]
    if len(board_checks) != 7 or any(row["violations"] or row["unconnected"]
                                    or not row["native_material_stack_checked"] for row in board_checks):
        raise ValueError("Resolve all seven native foil checks")
    artwork_by_site = {entry["site"]: entry["sha256"] for entry in reports["foils"]["boards"]}
    if any(artwork_by_site.get(entry["site"]) != entry["geometry_sha256"] for entry in reports["native"]["boards"]):
        raise ValueError("A native board does not match the selected flat artwork")
    mold_reports = [read(path) for path in molds]
    sites = [case["site"] for report in mold_reports for case in report["cases"]]
    if len(sites) != 7 or set(sites) != {"CH0", "CH1", "CH2", "CH3", "CH4", "CH5", "REF"}:
        raise ValueError("Each cell needs its own checked cover tooling")
    for report in mold_reports:
        verify(ROOT, report["input_sha256"])
        if report["source_mechanics_sha256"] != digest(paths["mechanics"] / "report.json"):
            raise ValueError("Mold geometry does not match the retained covers")
        if not all(c["passed"] for case in report["cases"] for c in case["checks"]):
            raise ValueError("Mold cavity checks failed")
    old = ROOT / "engineering/development/capacitive/k1"
    verify(old, read(old, "checkpoint.json")["files_sha256"])
    verify(paths["visuals"], reports["visuals"]["files_sha256"])
    with execution(ROOT / "build/records", "Freeze K1.2 build files, native flex and readout artwork, raw firmware and physical-test tools; retain the nominal checks and failing material/stop scenarios without claiming measured performance") as record:
        target.mkdir(parents=True)
        for name in ("cad", "patterns", "checks", "provenance", "visuals", "flex", "readout", "firmware", "software"):
            (target / name).mkdir()
        parts = []
        cad_sets = []
        # Superseded full-outline plate/cover/foil references and slab-only
        # supports remain in the older development module.
        retained = [p for p in reports["cells"]["parts"] if p["id"].endswith(
            ("_post_sheet_flat", "_post_stencil", "_backing_spacer", "_spreader_form"))]
        cad_sets.append((paths["cells"], retained))
        for name in ("saddles", "foil_fit", "mechanics", "stiffeners", "enclosure"):
            cad_sets.append((paths[name], reports[name]["parts"]))
        cad_sets += [(path, report["parts"]) for path, report in zip(molds, mold_reports)]
        seen = set()
        for origin, selected in cad_sets:
            for part in selected:
                if part["id"] in seen:
                    raise ValueError("Duplicate CAD identity: "+part["id"])
                seen.add(part["id"])
                for extension in ("step", "stl"):
                    source = origin / part[extension]
                    if digest(source) != part["sha256_"+extension]:
                        raise ValueError("CAD changed: "+part["id"])
                    shutil.copyfile(source, target / part[extension])
                parts.append(part)
        for name in ("cells", "mechanics", "stiffeners"):
            for source in sorted((paths[name] / "patterns").glob("*")):
                if source.is_file():
                    destination = target / "patterns" / source.name
                    if destination.exists():
                        raise ValueError("Duplicate cutting pattern: "+source.name)
                    shutil.copyfile(source, destination)
        for name, report in reports.items():
            filename = "manifest.json" if name in ("cells", "saddles") else "report.json"
            shutil.copyfile(paths[name] / filename, target / "checks" / (name+".json"))
        for number, path in enumerate(molds):
            shutil.copyfile(path / "report.json", target / "checks" / f"cover_molds_{number}.json")
        for cell in reports["cells"]["cells"]:
            formed = cell.get("formed_reference")
            if formed:
                source = paths["cells"] / formed["file"]
                if digest(source) != formed["sha256"]:
                    raise ValueError("Formed post reference changed")
                shutil.copyfile(source, target / "cad" / source.name)
        for board in board_checks:
            source = paths["native"] / board["name"]
            checked = ROOT / board["directory"]
            if digest(source / (board["name"]+".kicad_pcb")) != board["source_pcb_sha256"]:
                raise ValueError("Native source PCB changed")
            if digest(checked / (board["name"]+".kicad_pcb")) != board["checked_pcb_sha256"]:
                raise ValueError("Checked native PCB changed")
            verify(checked / "manufacturing", board["files_sha256"])
            shutil.copytree(source, target / "flex" / board["name"])
        shutil.copytree(old / "pcb", target / "readout/pcb")
        shutil.copytree(old / "artwork", target / "readout/artwork")
        shutil.copyfile(old / "pcb_components.csv", target / "readout/pcb_components.csv")
        for name in ("pcb_drc.json", "pcb_summary.json"):
            shutil.copyfile(old / "checks" / name, target / "readout" / name)
        for name in reports["visuals"]["files_sha256"]:
            destination = target / ("models.json" if name == "models.json" else "visuals/"+name)
            shutil.copyfile(paths["visuals"] / name, destination)
        for name in ("k1_readout.png", "k1_readout.pdf"):
            shutil.copyfile(old / "visuals" / name, target / "visuals" / name)
        for source in (ROOT / "engineering/firmware/capacitive").iterdir():
            if source.is_file() and source.suffix in (".py", ".json"):
                shutil.copyfile(source, target / "firmware" / source.name)
        with zipfile.ZipFile(target / "k1_firmware.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for source in sorted((target / "firmware").iterdir()):
                archive.write(source, source.name)
        for name in ("capacitive_protocol.py", "capacitive_record.py", "capacitive_force.py"):
            shutil.copyfile(ROOT / "engineering/software" / name, target / "software" / name)
        shutil.copyfile(ROOT / "engineering/templates/capacitive_force_trials.json", target / "force_trials.template.json")
        shutil.copyfile(ROOT / "engineering/designs/capacitive_bom.csv", target / "bom.csv")
        with (target / "bom.csv").open() as stream:
            if any(len(row) != 6 for row in csv.reader(stream)):
                raise ValueError("Malformed K1 bill of materials")
        for source in sorted((ROOT / "engineering/designs").glob("capacitive*.json")):
            shutil.copyfile(source, target / "provenance" / source.name)
        (target / "provenance/source_runs.json").write_text(json.dumps(
            {"source_runs": {name: str(path.relative_to(ROOT)) for name, path in paths.items()},
             "cover_mold_runs": [str(path.relative_to(ROOT)) for path in molds],
             "retained_readout_module_sha256": digest(old / "checkpoint.json")}, indent=2)+"\n")
        with (target / "parts.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["id", "kind", "purpose", "material", "STEP", "STL"])
            for part in parts:
                writer.writerow([part["id"], part["kind"], part["purpose"], part["material"], part["step"], part["stl"]])
        manifest = {"schema": "yam-k1-prototype-cad/1", "revision": "K1.2",
                    "physical_specimens_tested": 0, "parts": parts,
                    "status": "Digital bench-assembly package; real drive bracket, fabrication, motion and physical qualification remain",
                    "inputs": {name: digest(path / ("manifest.json" if name in ("cells", "saddles") else "report.json"))
                               for name, path in paths.items()},
                    "nominal_nail_addition_mm": .836, "nominal_stack_above_r1_tpu_datum_mm": 1.786,
                    "model_signal_planning_failures": reports["screen"]["signal_planning_failures"],
                    "model_stop_scenario_findings": len(reports["screen"]["stop_scenario_findings"]),
                    "physical_qualification": False}
        (target / "capacitive_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
        for name in ("SOURCE_ATTRIBUTION.md", "SOURCE_GEOMETRY_LICENSE"):
            shutil.copyfile(old / name, target / name)
        (target / "README.md").write_text(
            "# K1.2 capacitive bench prototype\n\n"
            "**Six contact cells and two protected references; 0 physical specimens tested.**\n\n"
            "Use the separate capacitive.html page, build-capacitive.html and capacitive-testing.html "
            "for sensor placement, assembly and evaluation. Matching source documents are "
            "engineering/docs/BUILD_CAPACITIVE.md and CAPACITIVE_TESTING.md.\n\n"
            "The tactile sensor is the custom plate/post-sheet/flex capacitor. Two TI FDC1004DGSR "
            "boards read it; an FDC1004 board alone is not a tactile sensor. CH0 and CH1 cover the "
            "two nail prongs. CH2–CH5 are curved cells on local rigid saddles over the TPU.\n\n"
            "`cad/` and `patterns/` contain manufactured parts, tools and explicitly labeled fit "
            "references. `flex/` has seven independently checked native boards and Gerber/drill "
            "sets: order each contact shape once and REF twice. `readout/` retains the checked "
            "23-component board used for both banks. `bom.csv` includes materials and quantities. "
            "No proprietary sensor or tool executable is represented by a printed CAD envelope.\n\n"
            "`checks/native.json` records the native writer's pre-check stage. "
            "`checks/native_check.json` records the subsequent independent checks of all seven foils. "
            "Use the matching checked fabrication ZIPs, not an intermediate export.\n\n"
            "The nail flex has a lifted free bend and a flat terminal. The curved terminal stiffeners "
            "have their own neutral-plane patterns and bonding forms. The seven cover molds have "
            "registration, steel-insert cavities and overflow channels. Actual fabrication, cure, "
            "demolding, ground bonds, fatigue and adhesion remain unqualified.\n\n"
            "The two bank cases protect unloaded references and provide harness tie slots. Keep "
            "the Pico outside these cases. The actual YAM drive is unidentified: use the tabs "
            "with a measured bracket and inspect all jaw motion before installed use.\n\n"
            "The assembly screen retains failing assumptions. Soft-post/thick-bond scenarios can "
            "bottom a nail before 20 N; high assumed post stiffness reduces the 0.2 N signal. "
            "Finite plate loading, hysteresis and no-contact bending are not solved by this model. "
            "Nominal nail addition is 0.836 mm. The 1.786 mm TPU number is above the R1 datum, "
            "not total addition to bare TPU.\n\n"
            "Four-file raw firmware and host recording/static-calibration tools are supplied. "
            "Run host tools from the complete repository. There is no measured calibration or "
            "contact threshold. Fit and evaluate independent physical sessions; preserve all failures.\n\n"
            "The older K1 development module is retained at engineering/development/capacitive/k1. "
            "Use this package's artwork, stops, retained plates and tooling together; do not mix revisions.\n")
        sources = list((ROOT / "engineering/designs").glob("capacitive*"))
        sources += list((ROOT / "engineering/scripts").glob("*capacitive*.py"))
        sources += list((ROOT / "engineering/firmware/capacitive").glob("*.py"))
        sources += [ROOT / "engineering/firmware/capacitive/config.json"]
        sources += list((ROOT / "engineering/software").glob("capacitive_*.py"))
        sources += [ROOT / "engineering/web/k1_stack.svg", ROOT / "engineering/web/k1_wiring.svg"]
        snapshot = {"schema": "yam-prototype-snapshot/1", "id": "CAPACITIVE", "revision": "K1.2",
                    "design_label": "K1", "design_page": "capacitive.html",
                    "status": "Digital bench-assembly build files; manufacturing and physical comparison pending",
                    "physical_specimens_tested": 0,
                    "shared_release_sha256": digest(ROOT / "engineering/release/release_manifest.json"),
                    "source_hashes": {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(sources))},
                    "files": {str(p.relative_to(target)): digest(p) for p in sorted(target.rglob("*")) if p.is_file()},
                    "checks": {"cad_parts": len(parts), "native_flex_designs": 7, "readout_copies": 2,
                               "drc_violations": 0, "unconnected_items": 0,
                               "foil_fit_checks": len(reports["foil_fit"]["checks"]),
                               "cell_assembly_checks": len(reports["assembly"]["checks"]),
                               "enclosure_checks": len(reports["enclosure"]["checks"]),
                               "physical_qualification": False,
                               "model_signal_planning_failures": reports["screen"]["signal_planning_failures"],
                               "model_stop_scenario_findings": len(reports["screen"]["stop_scenario_findings"])}}
        (target / "prototype_snapshot.json").write_text(json.dumps(snapshot, indent=2)+"\n")
        record["result"] = {"directory": str(target.relative_to(ROOT)), "files": len(snapshot["files"]), **snapshot["checks"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
