#!/usr/bin/python3
"""Freeze the checked B2 prototype separately, preserving R1/L1/B1 and concepts."""

import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/b2"
TARGET = ROOT/"engineering/prototypes/b2"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    with execution(ROOT/"build/records","Freeze B2 checked CAD, PCB, firmware and visuals as an unbuilt prototype; retain all prior releases") as record:
        release = ROOT/"engineering/release"
        baseline = json.loads((release/"release_manifest.json").read_text())
        for name,expected in baseline["source_hashes"].items():
            if digest(ROOT/name) != expected:
                raise ValueError(f"Preserved source changed: {name}")
        for name,expected in baseline["files"].items():
            if digest(release/name) != expected:
                raise ValueError(f"Preserved released file changed: {name}")
        plan = json.loads((OUTPUT/"b2_manifest.json").read_text())
        design = json.loads((OUTPUT/"pcb/b2_design_checks.json").read_text())
        if not design["routed"] or not design["hall_centers_and_axes_preserved"]:
            raise ValueError("B2 routing or sensing geometry is unfinished")
        for document in (plan,design):
            for name,expected in document["source_hashes"].items():
                if digest(ROOT/name) != expected:
                    raise ValueError(f"B2 source changed after generation: {name}")
        if digest(OUTPUT/"pcb/b2_main.json") != plan["pcb_layout_sha256"]:
            raise ValueError("Mechanical checks do not match the generated component layout")
        for part in plan["parts"]:
            for kind in ("step","stl"):
                if digest(OUTPUT/part[kind]) != part[f"sha256_{kind}"]:
                    raise ValueError(f"CAD changed after checking: {part['id']}")
            if not all(part["checks"].values()):
                raise ValueError("CAD checks incomplete")
        latest = json.loads((OUTPUT/"pcb/latest_check.json").read_text())
        checked = (OUTPUT/"pcb"/latest["directory"]).resolve()
        if not checked.is_relative_to((OUTPUT/"pcb/checks").resolve()):
            raise ValueError("Check receipt must be within the owned build directory")
        receipt = json.loads((checked/"pcb_checks.json").read_text())
        drc = json.loads((checked/"drc.json").read_text())
        if receipt["violations"] or receipt["unconnected"] or drc["violations"] or drc["unconnected_items"]:
            raise ValueError("Resolve all electrical DRC/connectivity findings before freezing")
        if digest(OUTPUT/"pcb/b2_main.kicad_pcb") != receipt["source_sha256"]:
            raise ValueError("Electrical check is stale")
        if digest(checked/"b2_main.kicad_pcb") != receipt["checked_pcb_sha256"]:
            raise ValueError("Checked board changed after DRC")
        for name,expected in receipt["files"].items():
            if Path(name).name != name or digest(checked/"manufacturing"/name) != expected:
                raise ValueError(f"Fabrication file changed: {name}")
        firmware = json.loads((OUTPUT/"firmware/firmware_manifest.json").read_text())
        for name,expected in firmware["files"].items():
            if digest(OUTPUT/"firmware"/name) != expected:
                raise ValueError("Firmware archive is stale")
        TARGET.mkdir(parents=True,exist_ok=True)
        shutil.copytree(OUTPUT/"cad",TARGET/"cad",dirs_exist_ok=True)
        shutil.copytree(OUTPUT/"firmware",TARGET/"firmware",dirs_exist_ok=True)
        for name in ("b2_manifest.json","b2_review_drawings.pdf","b2_placement.svg",
                     "b2_assembly.png","b2_exploded.png","models.json","b2_firmware.zip"):
            shutil.copyfile(OUTPUT/name,TARGET/name)
        pcb = TARGET/"pcb";pcb.mkdir(exist_ok=True)
        shutil.copyfile(checked/"b2_main.kicad_pcb",pcb/"b2_main.kicad_pcb")
        shutil.copyfile(OUTPUT/"pcb/b2_main.kicad_pcb",pcb/"b2_main.source.kicad_pcb")
        for name in ("b2_main.kicad_dru","b2_main.json","b2_main_pin_net.csv","b2_assembly.svg",
                     "b2_design_checks.json","fp-lib-table"):
            shutil.copyfile(OUTPUT/"pcb"/name,pcb/name)
        for name in ("pcb_checks.json","b2_main_fabrication.zip"):
            shutil.copyfile(checked/name,pcb/name)
        shutil.copytree(OUTPUT/"pcb/Prototype.pretty",pcb/"Prototype.pretty",dirs_exist_ok=True)
        shutil.copytree(checked/"manufacturing",pcb/"manufacturing",dirs_exist_ok=True)
        (pcb/"drc.json").write_text((checked/"drc.json").read_text().replace(str(ROOT),"<checkout>"))
        shutil.copyfile(ROOT/"engineering/web/b2-wiring.svg",TARGET/"b2-wiring.svg")
        (TARGET/"NOTICE.md").write_text(
            "# B2.1 prototype scope\n\n"
            "B2 is a new consolidated PCB and removable support for the preserved B1 sensing poses. "
            "The original ENPIRE frame and contact outline are attributed to Wenli Xiao / NVIDIA; "
            "the exact retrieved source and attribution are documented in engineering/docs/GEOMETRY.md.\n\n"
            "This package supplies checked digital CAD, PCB fabrication files, raw acquisition code and "
            "assembly material. No physical B2 specimen, calibrated force performance, manufacturing yield "
            "or robot qualification is reported. Component solids are dimensional reference envelopes.\n\n"
            "The earlier B2 outline/allocation study remains separately in engineering/concepts. "
            "Use this package's checked fabrication files for the B2.1 experiment.\n")
        sources = [
            "engineering/designs/b2.json","engineering/scripts/build_b2_pcb.py",
            "engineering/scripts/build_b2_parts.py","engineering/scripts/draw_b2.py",
            "engineering/scripts/prototype_pcb.py","engineering/scripts/prototype_route.py",
            "engineering/scripts/prototype_cad.py","engineering/scripts/check_prototype_pcb.py",
            "engineering/scripts/prepare_b2_firmware.py","engineering/scripts/freeze_b2_prototype.py",
            "engineering/firmware/b2/main.py","engineering/firmware/b2/config.json",
            "engineering/firmware/b1/main.py","engineering/firmware/b1/mlx90393.py",
            "engineering/software/b2_protocol.py","engineering/software/prototype_record.py",
            "engineering/software/b1_protocol.py","engineering/web/b2-wiring.svg",
            "engineering/electronics/b1/b1_head.json","engineering/release/b1/b1_manifest.json",
            "engineering/release/b1/models.json","engineering/release/models.json",
        ]
        snapshot = {
            "schema":"yam-prototype-snapshot/1","id":"B2","revision":plan["revision"],
            "status":"digital prototype; physical build and qualification pending",
            "physical_specimens_tested":0,"shared_release_sha256":digest(release/"release_manifest.json"),
            "source_hashes":{name:digest(ROOT/name) for name in sources},
            "files":{str(p.relative_to(TARGET)):digest(p) for p in sorted(TARGET.rglob("*"))
                     if p.is_file() and p.name != "prototype_snapshot.json"},
            "checks":{"cad_parts":len(plan["parts"]),"drc_violations":0,"unconnected_items":0,
                      "minimum_nominal_component_gap_mm":plan["minimum_component_to_frame_gap_mm"]},
        }
        (TARGET/"prototype_snapshot.json").write_text(json.dumps(snapshot,indent=2)+"\n")
        record["snapshot"] = {"files":len(snapshot["files"]),**snapshot["checks"],"physical_specimens_tested":0}
        print(json.dumps(record["snapshot"],indent=2))


if __name__ == "__main__":
    main()
