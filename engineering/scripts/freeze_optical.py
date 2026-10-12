#!/usr/bin/python3
"""Freeze the matched O1 CAD, light PCB, optical model, code and build documents."""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def verify(root, mapping):
    for name, expected in mapping.items():
        if digest(root/name) != expected:
            raise ValueError("Changed input/artifact: "+str(root/name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("assembly", "tools", "board", "refraction", "visuals", "diagrams")
    for name in names:
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT/"engineering/prototypes/optical")
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in names}
    target = args.destination.resolve()
    if target.exists() or not all(path.is_relative_to(ROOT) for path in (*paths.values(), target)):
        parser.error("Use matching repository inputs and a fresh destination")
    reports = {name: json.loads((path/("o1_blue_ring.json" if name == "board" else "report.json")).read_text())
               for name, path in paths.items()}
    for name, report in reports.items():
        verify(ROOT, report.get("input_sha256", {}))
        verify(paths[name], report.get("files_sha256", {}))
    if (any(not reports[name]["passed_nominal_checks"] for name in ("assembly", "tools"))
            or not reports["diagrams"]["passed_canvas_bounds"]):
        raise ValueError("Resolve every required assembly, mold and card finding")
    for name in ("assembly", "tools", "refraction"):
        path = paths[name]/"report.json"
        if reports["visuals"]["input_sha256"].get(str(path.relative_to(ROOT))) != digest(path):
            raise ValueError("Visuals belong to another "+name+" run")
    board_json = paths["board"]/"o1_blue_ring.json"
    for name in ("assembly", "visuals"):
        if reports[name]["input_sha256"].get(str(board_json.relative_to(ROOT))) != digest(board_json):
            raise ValueError("Mismatched light board")
    for name in ("o1_wiring.svg", "o1_led_assembly.svg"):
        path = paths["visuals"]/name
        if not any(row["source"] == str(path.relative_to(ROOT)) and row["source_sha256"] == digest(path)
                   for row in reports["diagrams"]["diagrams"]):
            raise ValueError("Card review does not cover current "+name)
    shared_search = next(name for name in reports["assembly"]["input_sha256"] if "/path_searches/" in name and name.endswith("report.json"))
    for name in ("tools", "refraction"):
        if reports[name]["input_sha256"].get(shared_search) != reports["assembly"]["input_sha256"][shared_search]:
            raise ValueError("Mixed gel/tool optical paths")
    native = json.loads((paths["board"]/"latest_check.json").read_text())
    checked = paths["board"]/native["directory"]
    pcb_check = json.loads((checked/"pcb_checks.json").read_text())
    if (native["violations"] or native["unconnected"] or pcb_check["violations"] or pcb_check["unconnected"]
            or native["source_sha256"] != digest(paths["board"]/"o1_blue_ring.kicad_pcb")
            or pcb_check["checked_pcb_sha256"] != digest(checked/"o1_blue_ring.kicad_pcb")):
        raise ValueError("Use a complete passing matching PCB export")
    verify(checked/"manufacturing", pcb_check["files"])
    folder = ROOT/"build/engineering/prototypes/optical/package_runs"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    stage = folder/"package"
    with execution(ROOT/"build/records", "Freeze matched O1 frame/gel/light/nail CAD, molds, checked board, raw software, physical-analysis tools and separate-page documents; retain optical limits and zero physical evidence") as record:
        for name in ("cad", "checks", "visuals", "patterns", "docs", "templates", "software", "provenance", "research"):
            (stage/name).mkdir(parents=True, exist_ok=True)
        parts, seen = [], set()
        for module in ("assembly", "tools"):
            for part in reports[module]["parts"]:
                if part["id"] in seen:
                    raise ValueError("Duplicate part identity")
                seen.add(part["id"])
                for extension in ("step", "stl"):
                    path = paths[module]/part[extension]
                    if digest(path) != part["sha256_"+extension]:
                        raise ValueError("CAD changed")
                    shutil.copyfile(path, stage/part[extension])
                parts.append(part)
            if (paths[module]/"mesh_diagnostics").exists():
                shutil.copytree(paths[module]/"mesh_diagnostics", stage/"provenance"/module/"mesh_diagnostics")
        gel = next(p for p in parts if p["id"] == "o1_retained_gel_blank")
        cavity = next(p for p in parts if p["id"] == "o1_gel_mold_cavity_reference")
        if abs(gel["volume_mm3"]-cavity["volume_mm3"]) > .001:
            raise ValueError("Gel and mold cavity differ")
        for name, report in reports.items():
            (stage/"checks"/(name+".json")).write_text(json.dumps(report, indent=2)+"\n")
            if (paths[name]/"inputs").is_dir():
                shutil.copytree(paths[name]/"inputs", stage/"provenance"/name/"inputs")
        for name in reports["visuals"]["files_sha256"]:
            shutil.copyfile(paths["visuals"]/name, stage/("models.json" if name == "models.json" else "visuals/"+name))
        for name in ("o1_wiring.png", "o1_led_assembly.png"):
            shutil.copyfile(paths["diagrams"]/name, stage/"visuals"/name)
        for name in ("o1_marker_pattern.svg", "o1_mirror_cut.svg"):
            shutil.copyfile(paths["visuals"]/name, stage/"patterns"/name)
        shutil.copyfile(paths["tools"]/"markers.json", stage/"patterns/markers.json")
        for name in ("r1_cut_sheet.svg", "r1_cut_sheet.pdf"):
            shutil.copyfile(ROOT/"engineering/release/r1"/name, stage/"patterns"/name)
        r1 = json.loads((ROOT/"engineering/release/r1/r1_manifest.json").read_text())
        (stage/"patterns/nail_cells.json").write_text(json.dumps(r1["nail_active_cells"], indent=2)+"\n")
        electronics = stage/"electronics/led"; electronics.mkdir(parents=True)
        for name in ("o1_blue_ring.kicad_pcb", "o1_blue_ring.kicad_dru", "o1_blue_ring.json", "pin_net.csv",
                     "fp-lib-table", "latest_check.json", "optical_led_board.json", "optical_materials.json"):
            shutil.copyfile(paths["board"]/name, electronics/name)
        shutil.copytree(paths["board"]/"O1.pretty", electronics/"O1.pretty")
        shutil.copytree(checked, electronics/native["directory"])
        shutil.copyfile(checked/"o1_blue_ring_fabrication.zip", electronics/"o1_blue_ring_fabrication.zip")
        with (electronics/"components.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["reference", "value", "x_mm", "y_mm", "rotation_deg"])
            for p in reports["board"]["parts"]:
                writer.writerow([p["reference"], p["value"], *p["center_mm"], p["rotation_deg"]])
        docs = ("BUILD_OPTICAL", "OPTICAL_ELECTRONICS", "OPTICAL_TESTING", "OPTICAL_REPRODUCE")
        for name in docs:
            shutil.copyfile(ROOT/"engineering/docs"/(name+".md"), stage/"docs"/(name+".md"))
        for name in ("optical_camera.json", "optical_force_trials.json"):
            shutil.copyfile(ROOT/"engineering/templates"/name, stage/"templates"/name)
        software = list((ROOT/"engineering/software").glob("optical_*.py"))
        software += [ROOT/"engineering/software"/name for name in ("capacitive_force.py", "capacitive_protocol.py", "contact_core.py")]
        for path in software:
            shutil.copyfile(path, stage/"software"/path.name)
        shutil.copyfile(ROOT/"engineering/designs/optical_bom.csv", stage/"bom.csv")
        for name in ("optical_materials.json", "optical_readout.json"):
            shutil.copyfile(ROOT/"engineering/designs"/name, stage/"research"/name)
        shutil.copyfile(ROOT/"engineering/research/optical_source_review.json", stage/"research/optical_source_review.json")
        with (stage/"parts.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["id", "kind", "purpose", "material", "STEP", "STL"])
            for part in parts:
                writer.writerow([part["id"], part["kind"], part["purpose"], part["material"], part["step"], part["stl"]])
        manifest = {"schema": "yam-o1-prototype-cad/1", "revision": "O1.0", "parts": parts,
                    "status": "Digital bench package; no physical specimens or performance qualification",
                    "physical_specimens_tested": 0, "physical_qualification": False, "requested_per_finger_n": 20,
                    "added_reach_mm": reports["assembly"]["added_reach_mm"], "nominal_nail_addition_mm": .4,
                    "marker_count": reports["tools"]["marker_count"], "camera": "Raspberry Pi Camera Module 3 Wide, visible-light IR-cut",
                    "assembly_material_checks": len(reports["assembly"]["checks"]), "mold_material_checks": len(reports["tools"]["checks"]),
                    "neutral_air_ray_segments": reports["assembly"]["ray_segments"],
                    "neutral_refraction_edge_exits": len(reports["refraction"]["edge_exits"]),
                    "neutral_refraction_rays": reports["refraction"]["ray_count"],
                    "force_or_contact_model_supplied": False,
                    "inputs": {name: digest(path/("o1_blue_ring.json" if name == "board" else "report.json")) for name, path in paths.items()}}
        (stage/"optical_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
        (stage/"provenance/source_runs.json").write_text(json.dumps({name: str(path.relative_to(ROOT)) for name, path in paths.items()}, indent=2)+"\n")
        (stage/"README.md").write_text(
            "# O1.0 fixed-optics tactile finger\n\n"
            "Camera Module 3 Wide, rigid PET mirror backing, clear Solaris gel with 42 markers, four blue LEDs and two thin R1 N0 nail cells. "
            "The camera bay adds 32 mm reach. Zero physical builds or tests; 20 N is a target, not a rating.\n\n"
            "Start at optical.html and build-optical.html. Separate wiring, physical-testing and reproduction pages accompany this packet. "
            "Use the complete repository/source packet to run Python tools and obtain shared setup dependencies; this ZIP is not a standalone installed environment.\n\n"
            "`cad/` and `parts.csv` distinguish fabricated parts from gel, bond, camera/electronic and hardware references. "
            "Cast the gel with the supplied molds; do not substitute a rigid printed gel. "
            "`patterns/` contains 1:1 mirror and marker sheets plus the retained R1 nail sheet. Use only CH0/CH1 from that R1 sheet.\n\n"
            "`electronics/led/o1_blue_ring_fabrication.zip` is the independently checked two-layer board export. "
            "Native PCB, embedded footprints, pin/net CSV and complete component positions are included. "
            "Use optical-electronics.html for Pi/ADS1115 wiring and the two separate nail nodes.\n\n"
            "`software/` provides lossless capture, marker-reference creation, raw replay and physical force/contact fitting/evaluation. "
            "No coefficients, measured images or force/contact results are supplied. `templates/` contains empty setup/trial files.\n\n"
            "The undeformed-gel refraction screen retains three distal edge-exit rays out of 105 sampled rays. "
            "Pupil, focus, distorted/deformed visibility, actual drive/harness fit, stiffness, surface wear and force/contact performance need physical acceptance. "
            "The preserved CAD/PCB checks are limited to their declared nominal properties.\n")
        if (ROOT/"LICENSE").is_file():
            shutil.copyfile(ROOT/"LICENSE", stage/"LICENSE")
        sources = [Path(__file__), ROOT/"engineering/web/o1_wiring.svg", ROOT/"engineering/designs/optical_bom.csv",
                   ROOT/"engineering/research/optical_source_review.json"]
        sources += list((ROOT/"engineering/scripts").glob("*optical*.py"))
        sources += list((ROOT/"engineering/designs").glob("optical_*.json"))
        sources += list((ROOT/"engineering/templates").glob("optical_*.json"))
        sources += list((ROOT/"engineering/tests").glob("test_optical*.py"))
        sources += software+[ROOT/"engineering/docs"/(name+".md") for name in docs]
        shared = ("prototype_cad.py", "source_brep.py", "build_pneumatic_ported_assembly.py", "build_b1_parts.py",
                  "analyze_baseline_meshes.py", "analyze_b1_interfaces.py", "screen_f1_feedback.py",
                  "f1_native_pcb.py", "f1_board_routes.py", "prototype_route.py", "prototype_pcb.py",
                  "route_force_button_board.py", "check_prototype_pcb.py", "draw_capacitive_prototype.py", "capacitive_geometry.py")
        sources += [ROOT/"engineering/scripts"/name for name in shared]
        snapshot = {"schema": "yam-prototype-snapshot/1", "id": "O1", "revision": "O1.0", "design_label": "O1",
                    "design_page": "optical.html", "physical_specimens_tested": 0,
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "shared_release_sha256": digest(ROOT/"engineering/release/release_manifest.json"),
                    "source_hashes": {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(sources))},
                    "files": {str(p.relative_to(stage)): digest(p) for p in sorted(stage.rglob("*")) if p.is_file()}}
        (stage/"prototype_snapshot.json").write_text(json.dumps(snapshot, indent=2)+"\n")
        shutil.copytree(stage, target)
        record["result"] = {"destination": str(target.relative_to(ROOT)), "files": len(snapshot["files"]),
                            "parts": len(parts), "snapshot_sha256": digest(target/"prototype_snapshot.json")}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
