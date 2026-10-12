#!/usr/bin/python3
"""Freeze a coherent F1 R4 bench package after all declared geometry/artwork checks finish."""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest

R3 = ROOT/"engineering/development/f1/r3"
FITTED = ROOT/"engineering/development/f1/fitted-foils-r3"
WRIST = ROOT/"engineering/development/f1/wrist"


def verify(base, hashes):
    for name, expected in hashes.items():
        if digest(base/name) != expected:
            raise ValueError("Changed input or artifact: "+str(base/name))


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("skin", "terminals", "foils", "patterns", "assembly", "visuals",
             "artwork", "native_check", "tip_review", "dc", "network")
    for name in names:
        parser.add_argument("--"+name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--molds", nargs="+", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT/"engineering/prototypes/f1")
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in names}
    molds = [path.resolve() for path in args.molds]
    target = args.destination.resolve()
    if target.exists() or not all(path.is_relative_to(ROOT) for path in (*paths.values(), *molds, target)):
        parser.error("Use checked repository inputs and a fresh prototype destination")
    filenames = {name: "artwork.json" if name == "artwork" else "summary.json" if name == "native_check" else "report.json" for name in names}
    reports = {name: read(path/filenames[name]) for name, path in paths.items()}
    for name, report in reports.items():
        if name != "native_check":
            verify(ROOT, report.get("input_sha256", report.get("source_hashes", {})))
    if (not reports["assembly"]["passed_declared_checks"] or len(reports["foils"]["parts"]) != 12
            or len(reports["skin"]["cases"]) != 6 or not reports["skin"]["base_source_checks_pass"]
            or len(reports["patterns"]["patterns"]) != 6):
        raise ValueError("Complete the six-site assembly, foil and film checks before freezing")
    for consumer, dependencies in (("foils", ("skin", "terminals")),
                                   ("assembly", ("skin", "terminals", "foils")),
                                   ("patterns", ("skin",))):
        for dependency in dependencies:
            path = paths[dependency]/filenames[dependency]
            if reports[consumer]["input_sha256"].get(str(path.relative_to(ROOT))) != digest(path):
                raise ValueError("Mixed revisions: "+consumer+"/"+dependency)
    native = reports["native_check"]
    if (not native["all_passed"] or len(native["boards"]) != 12
            or native["artwork_manifest_sha256"] != digest(paths["artwork"]/"artwork.json")
            or native["checker_source_sha256"] != digest(ROOT/"engineering/scripts/check_f1_flex.py")):
        raise ValueError("Require twelve current independent native foil checks")
    if not all(row["meets_one_percent_electrical_screen"] for row in reports["dc"]["results"]):
        raise ValueError("Retain and resolve routed electrical-model findings before this freeze")
    terminal_artwork_paths = [ROOT/name for name in reports["terminals"]["input_sha256"] if name.endswith("/artwork.json")]
    if len(terminal_artwork_paths) != 1:
        raise ValueError("Missing terminal artwork provenance")
    terminal_artwork = terminal_artwork_paths[0]
    old_boards = {entry["name"]: entry["metadata"] for entry in read(terminal_artwork)["boards"]}
    new_boards = {entry["name"]: entry["metadata"] for entry in reports["artwork"]["boards"]}
    if old_boards != new_boards:
        raise ValueError("Terminal poses do not match the final artwork metadata")
    equivalence = []
    for name in sorted(new_boards):
        old = terminal_artwork.parent/name/(name+".json")
        new = paths["artwork"]/name/(name+".json")
        if digest(old) != digest(new):
            raise ValueError("Final foil geometry differs from the terminal assembly basis")
        equivalence.append({"foil": name, "identical_geometry_sha256": digest(new)})
    for name in ("r3", "fitted", "wrist"):
        base = {"r3": R3, "fitted": FITTED, "wrist": WRIST}[name]
        verify(base, read(base/"checkpoint.json")["files_sha256"])
    mold_reports = [read(path/"report.json") for path in molds]
    identities = [row["part"] for report in mold_reports for row in report["molds"]]
    expected = {f"f1_ch{i}_retained_cover" for i in range(6)} | {f"f1_ch{i}_compliant_fit_base" for i in range(2, 6)}
    if len(identities) != 10 or set(identities) != expected:
        raise ValueError("Require each of the ten distinct mold pairs exactly once")
    for report in mold_reports:
        verify(ROOT, report["input_sha256"])
        if (report["source_skin_sha256"] != digest(paths["skin"]/"report.json")
                or not all(row["passed"] for mold in report["molds"] for row in mold["checks"])):
            raise ValueError("Mold checks do not match the selected skin")
    verify(paths["visuals"], reports["visuals"]["files_sha256"])
    stage_root = ROOT/"build/engineering/prototypes/f1/package_runs"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    stage = stage_root/"package"
    with execution(ROOT/"build/records", "Package the coherent F1 R4 bench design, matching native flex/readout, materials, physical-test tools and full fit evidence; keep every unqualified physical interface explicit") as record:
        stage.mkdir(parents=True)
        record["staging_directory"] = str(stage_root.relative_to(ROOT))
        for name in ("cad", "checks", "patterns", "flex", "electronics", "firmware", "software", "docs", "visuals", "provenance"):
            (stage/name).mkdir()
        carrier = read(R3/"checks/carrier.json")
        sets = [(paths["foils"], reports["foils"]["parts"]),
                (paths["skin"], [part for part in reports["skin"]["parts"] if not part["id"].endswith(
                    ("_columns_body", "_rows_body", "_column_finish_envelope", "_row_finish_envelope"))]),
                (paths["terminals"], [part for part in reports["terminals"]["parts"] if "_stiffener_" in part["id"]]),
                (R3, carrier["parts"])]
        sets.extend((path, report["parts"]) for path, report in zip(molds, mold_reports))
        checked_parts = {part["id"] for origin, selected in sets if origin != R3
                         for part in selected if part["kind"] != "fabricate_tool"}
        if (set(reports["assembly"]["parts_checked"]) != checked_parts
                or reports["assembly"]["coverage"]["unique_comparisons"] != len(reports["assembly"]["checks"])
                or not reports["assembly"]["checks"]):
            raise ValueError("Complete assembly coverage does not match the packaged material parts")
        parts, seen = [], set()
        for origin, selected in sets:
            for part in selected:
                if part["id"] in seen:
                    raise ValueError("Duplicate CAD identity")
                seen.add(part["id"])
                for extension in ("step", "stl"):
                    path = origin/part[extension]
                    if digest(path) != part["sha256_"+extension]:
                        raise ValueError("CAD changed: "+part["id"])
                    shutil.copyfile(path, stage/part[extension])
                parts.append(part)
        for name in ("patterns", "terminals"):
            for path in sorted((paths[name]/"patterns").glob("*")):
                if path.is_file():
                    destination = stage/"patterns"/path.name
                    if destination.exists():
                        raise ValueError("Duplicate cut pattern")
                    shutil.copyfile(path, destination)
        for name in names:
            shutil.copyfile(paths[name]/filenames[name], stage/"checks"/(name+".json"))
        for number, path in enumerate(molds):
            shutil.copyfile(path/"report.json", stage/"checks"/f"molds_{number}.json")
        (stage/"checks/terminal_artwork_equivalence.json").write_text(json.dumps({
            "terminal_basis_artwork_sha256": digest(terminal_artwork),
            "final_artwork_sha256": digest(paths["artwork"]/"artwork.json"), "foils": equivalence,
            "note": "The rerun updates review provenance. All twelve per-foil geometry files and terminal metadata are identical."}, indent=2)+"\n")
        for name in ("pcb", "artwork"):
            shutil.copytree(R3/name, stage/"electronics/fanout"/name)
        shutil.copyfile(R3/"components.csv", stage/"electronics/fanout/components.csv")
        for name in ("pcb_drc.json", "pcb_summary.json", "local_copper.json", "ground_plane.json", "carrier.json"):
            shutil.copyfile(R3/"checks"/name, stage/"checks"/("r3_"+name))
        shutil.copytree(WRIST, stage/"electronics/wrist")
        for board in native["boards"]:
            name = board["name"]
            origin = paths["artwork"]/name
            if digest(origin/(name+".kicad_pcb")) != board["source_pcb_sha256"]:
                raise ValueError("Native foil source changed")
            checked = paths["native_check"]/name
            verify(checked/"development_fabrication", read(checked/"development_export.json")["files"])
            shutil.copytree(origin, stage/"flex"/name)
            shutil.copytree(checked, stage/"flex"/name/"native_checks")
        for name in reports["visuals"]["files_sha256"]:
            destination = stage/("models.json" if name == "models.json" else "visuals/"+name)
            shutil.copyfile(paths["visuals"]/name, destination)
        for origin, name in ((R3/"visuals/fanout_faces.png", "f1_fanout_faces.png"),
                             (WRIST/"visuals/wrist_faces.png", "f1_wrist_faces.png"),
                             (FITTED/"review/fitted_contact_map.png", "f1_contact_map.png")):
            shutil.copyfile(origin, stage/"visuals"/name)
        for extension in ("png", "pdf"):
            shutil.copyfile(paths["dc"]/("routed_dc_screen."+extension), stage/"visuals"/("routed_dc_screen."+extension))
        for name in ("taxels.csv", "foil_resistance.csv"):
            shutil.copyfile(FITTED/"review"/name, stage/name)
        for path in (ROOT/"engineering/firmware/f1").iterdir():
            if path.is_file() and path.suffix in (".py", ".json"):
                shutil.copyfile(path, stage/"firmware"/path.name)
        with zipfile.ZipFile(stage/"f1_firmware.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((stage/"firmware").iterdir()):
                archive.write(path, path.name)
        for name in ("f1_protocol.py", "f1_record.py", "f1_holds.py", "f1_force.py"):
            shutil.copyfile(ROOT/"engineering/software"/name, stage/"software"/name)
        for name in ("BUILD_F1", "F1_MANUFACTURING", "F1_TESTING", "F1_WRIST_CAPTURE", "F1_REPRODUCE"):
            text = (ROOT/"engineering/docs"/(name+".md")).read_text()
            text = text.replace("../web/f1_", "../visuals/f1_").replace("../prototypes/f1/", "../")
            (stage/"docs"/(name+".md")).write_text(text)
        shutil.copyfile(ROOT/"engineering/templates/f1_force_trials.json", stage/"force_trials.template.json")
        shutil.copyfile(ROOT/"engineering/designs/f1_bom.csv", stage/"bom.csv")
        with (stage/"bom.csv").open() as stream:
            if any(len(row) != 6 for row in csv.reader(stream)):
                raise ValueError("Malformed F1 BOM")
        for path in (ROOT/"engineering/designs").glob("f1*.json"):
            shutil.copyfile(path, stage/"provenance"/path.name)
        shutil.copyfile(ROOT/"engineering/research/f1_gold_wrist_link_r4.json", stage/"provenance/f1_gold_wrist_link_r4.json")
        (stage/"provenance/source_runs.json").write_text(json.dumps({
            "source_runs": {name: str(path.relative_to(ROOT)) for name, path in paths.items()},
            "mold_runs": [str(path.relative_to(ROOT)) for path in molds],
            "retained_module_sha256": {name: digest(path/"checkpoint.json") for name, path in
                                       (("r3", R3), ("fitted_foils", FITTED), ("wrist", WRIST))}}, indent=2)+"\n")
        for name in ("SOURCE_ATTRIBUTION.md", "SOURCE_GEOMETRY_LICENSE"):
            shutil.copyfile(R3/name, stage/name)
        with (stage/"parts.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["id", "kind", "purpose", "material", "STEP", "STL"])
            for part in parts:
                writer.writerow([part["id"], part["kind"], part["purpose"], part["material"], part["step"], part["stl"]])
        mating = reports["assembly"]["unqualified_mating_interfaces"]
        manifest = {"schema": "yam-f1-prototype-cad/1", "revision": "F1.1 R4", "parts": parts,
                    "physical_specimens_tested": 0, "physical_qualification": False,
                    "status": "Digital bench-assembly package; terminal/cable acceptance and physical qualification remain",
                    "nominal_nail_addition_mm": .4614, "nominal_stack_above_r1_tpu_datum_mm": .7264,
                    "unqualified_connector_count": len({row["connector"] for row in mating}),
                    "unqualified_part_connector_pairs": len(mating),
                    "inputs": {name: digest(path/filenames[name]) for name, path in paths.items()}}
        (stage/"f1_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
        (stage/"README.md").write_text(
            "# F1.1 R4 bench design\n\n"
            "**Six pressure-film islands, twelve custom flexes and 64 proposed electrical locations; 0 physical specimens tested.**\n\n"
            "Use flexible-matrix.html, f1-manufacturing.html, f1-capture.html and f1-testing.html "
            "on the kit website, or the corresponding files in docs/. Run host software from the complete repository.\n\n"
            "`cad/` contains the current retained covers/bases, complete foil envelopes, segmented terminal pieces, "
            "assembly forms, carrier and molds. `parts.csv` distinguishes fabrication, tooling and reference envelopes. "
            "Never print an electrode or purchased-component envelope and call it a working sensor. "
            "`patterns/` supplies the six developed film cuts and PI/adhesive pieces.\n\n"
            "`flex/` holds twelve distinct R4 native designs with full independent checks and their original development "
            "Gerber/drill exports. Use the proposed manufacturing contract and inspect terminal coupons before a larger order. "
            "The original warnings remain; material/finish tolerances and actual connector seating require physical acceptance. "
            "`electronics/fanout/` is the matching checked R3 board; `electronics/wrist/` retains the complete checked wrist module. "
            "Use both complete component CSVs in addition to bom.csv. Use package-level docs/ for current integration; "
            "the retained wrist module also includes its original historical instructions.\n\n"
            "Nominal nail addition is 0.4614 mm. The 0.7264 mm TPU figure is above the R1 fitting datum; "
            "the variable base below it is additional. TPU covers and bases are 14 mm wide around 13 mm foils. "
            "Earlier 13 mm covers lacked side skirts and remain historical only.\n\n"
            "The complete static overlap screen keeps twelve manufacturer mating cavities unqualified. "
            "Actual seals, strain relief, installed drive, loaded motion and tail slack require physical inspection. "
            "The Molex gold cable is an incoming-inspection candidate with documented dimensional/plating questions, "
            "not a guaranteed qualified connector pair.\n\n"
            "Raw firmware and version-2 host recordings preserve timestamps, faulty/incomplete frames and the fixed gain map. "
            "The stationary-force tool uses independent physical sessions and retains unavailable holds. "
            "There is no supplied measured force model or qualified contact detector. The routed ideal-feedback DC study "
            "does not include continuous-film lateral conduction or full coupled dynamics.\n\n"
            "All earlier F1 modules remain in engineering/development/f1. Use this revision's parts together, "
            "then compare independent physical specimens with the simpler designs through 20 N per finger.\n")
        sources = [ROOT/"engineering/designs/f1_bom.csv", ROOT/"engineering/designs/f1_skin_r4.json",
                   ROOT/"engineering/designs/f1_finished_tip_r4.json", ROOT/"engineering/designs/f1_terminal_mechanics_r4.json",
                   ROOT/"engineering/designs/f1_skin_molds_r4.json", ROOT/"engineering/web/f1_stack.svg", ROOT/"engineering/web/f1_wiring.svg",
                   Path(__file__)]
        sources += list((ROOT/"engineering/software").glob("f1_*.py"))
        sources += [ROOT/"engineering/software/capacitive_force.py", ROOT/"engineering/software/capacitive_protocol.py",
                    ROOT/"engineering/scripts/check_f1_flex.py", ROOT/"engineering/designs/f1_flex_targets.json"]
        sources += list((ROOT/"engineering/firmware/f1").glob("*.py"))+[ROOT/"engineering/firmware/f1/config.json"]
        for report in reports.values():
            sources += [ROOT/name for name in report.get("input_sha256", report.get("source_hashes", {}))
                        if name.startswith(("engineering/", "src/"))]
        snapshot = {"schema": "yam-prototype-snapshot/1", "id": "F1", "revision": "F1.1 R4",
                    "design_label": "F1", "design_page": "flexible-matrix.html", "physical_specimens_tested": 0,
                    "status": manifest["status"], "shared_release_sha256": digest(ROOT/"engineering/release/release_manifest.json"),
                    "source_hashes": {str(path.relative_to(ROOT)): digest(path) for path in sorted(set(sources))},
                    "files": {str(path.relative_to(stage)): digest(path) for path in sorted(stage.rglob("*")) if path.is_file()},
                    "checks": {"cad_parts": len(parts), "native_flex_designs": 12,
                               "drc_unreviewed_findings": 0, "unconnected_items": 0,
                               "assembly_comparisons": len(reports["assembly"]["checks"]),
                               "unqualified_connector_count": manifest["unqualified_connector_count"],
                               "physical_qualification": False}}
        (stage/"prototype_snapshot.json").write_text(json.dumps(snapshot, indent=2)+"\n")
        target.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(target)
        record["result"] = {"directory": str(target.relative_to(ROOT)), "files": len(snapshot["files"]), **snapshot["checks"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
