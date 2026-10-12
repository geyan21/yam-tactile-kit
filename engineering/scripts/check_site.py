#!/usr/bin/python3
"""Check local website links and all portable archives; perform no network requests."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import posixpath
import sys
from urllib.parse import unquote, urlsplit
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
from design_pages import load_catalog


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references=[]
        self.ids=set()
    def handle_starttag(self,tag,attributes):
        values=dict(attributes)
        if "id" in values:self.ids.add(values["id"])
        for attribute in ("href","src"):
            if attribute in values:self.references.append(values[attribute])


def verify_entries(entries):
    documents={}
    for name,data in entries.items():
        if name.endswith(".html"):
            parser=Links();parser.feed(data.decode("utf-8"));documents[name]=parser
    checked=0
    for name,parser in documents.items():
        for reference in parser.references:
            url=urlsplit(reference)
            if url.scheme or url.netloc:continue
            target=posixpath.normpath(str(PurePosixPath(name).parent/unquote(url.path))) if url.path else name
            if target==".." or target.startswith("../") or target.startswith("/"):
                raise ValueError(f"Local target escapes the packet: {name} -> {reference}")
            if target not in entries:
                raise ValueError(f"Missing local target: {name} -> {reference}")
            if url.fragment and target in documents and unquote(url.fragment) not in documents[target].ids:
                raise ValueError(f"Missing local anchor: {name} -> {reference}")
            checked+=1
    return checked


def main():
    site=ROOT/"build/site"
    with execution(ROOT/"build/records","Verify engineering website links, archive integrity, and required build artifacts") as record:
        (ROOT/"build/engineering").mkdir(parents=True,exist_ok=True)
        entries={str(path.relative_to(site)):path.read_bytes() for path in site.rglob("*") if path.is_file()}
        local_links=verify_entries(entries)
        catalog=load_catalog()
        design_pages=["designs.html",*[item["slug"]+".html" for item in catalog["designs"]]]
        for item in catalog["designs"]:
            page=entries.get(item["slug"]+".html",b"").decode("utf-8")
            if f'data-design-id="{item["id"]}"' not in page:
                raise ValueError(f"Missing dedicated design page: {item['id']}")
            if not all(marker in page for marker in ("design-sensor-table","design-resource-table","design-missing","design-next")):
                raise ValueError(f"Incomplete design content: {item['id']}")
        archives={}
        for name in ("enpire-source.zip","enpire-designs.zip","enpire-site.zip","enpire-engineering-kit.zip"):
            with zipfile.ZipFile(site/"downloads"/name) as archive:
                if archive.testzip() is not None:raise ValueError(f"Corrupt ZIP: {name}")
                names=archive.namelist()
                if len(names)!=len(set(names)) or any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts for n in names):
                    raise ValueError(f"Unsafe archive paths: {name}")
                archives[name]={"files":len(names),"bytes":(site/"downloads"/name).stat().st_size}
                if name=="enpire-site.zip":
                    archives[name]["local_links"]=verify_entries({n:archive.read(n) for n in names})
                if name=="enpire-designs.zip":
                    for required in ("concepts/cad/b2_pcb_fit_witness.step","concepts/cad/c1_strain_beam_coupon.step","concepts/NOTICE.md"):
                        if required not in names:raise ValueError(f"CAD archive missing concept artifact: {required}")
        with zipfile.ZipFile(site/"downloads/enpire-engineering-kit.zip") as archive:
            required=[
                "START_HERE.txt","source/engineering/firmware/r1/main.py",
                "source/engineering/firmware/r1/config.json","source/engineering/software/bench.py",
                "source/engineering/software/calibrate.py","source/engineering/bom.csv",
                "source/engineering/templates/specimen.json","source/engineering/release/r1/r1_cut_sheet.svg",
                "website/index.html","website/guide.html",
                "source/engineering/firmware/l1/main.py","source/engineering/firmware/l1/nau7802.py",
                "source/engineering/firmware/l1/ina219.py","source/engineering/software/l1_bench.py",
                "source/engineering/software/l1_calibrate.py","source/engineering/software/l1_validate_finger.py",
                "source/engineering/software/l1_monitor.py","source/engineering/l1_bom.csv",
                "source/engineering/release/l1/l1_bench_plan.json","source/engineering/release/l1/l1_finger_plan.json",
                "source/engineering/release/l1/cad/l1_floating_finger_carrier.step",
                "website/build-l1.html","website/l1-electronics.html","website/l1-testing.html",
                "website/contact.html","website/assets/contact-flow.svg",
                "source/engineering/software/contact_bench.py","source/engineering/software/contact_report.py",
                "source/engineering/software/contact_core.py","source/engineering/software/contact_monitor.py",
                "source/engineering/templates/contact_setup.json","source/engineering/templates/contact_cases.json",
                "source/engineering/firmware/b1/main.py","source/engineering/firmware/b1/mlx90393.py",
                "source/engineering/firmware/b1/config.json","source/engineering/software/b1_monitor.py",
                "source/engineering/electronics/b1/b1_head.kicad_pcb",
                "source/engineering/release/b1/cad/b1_magnetic_tpu_insert.step",
                "source/engineering/release/b1/pcb/b1_head_fabrication.zip",
                "source/engineering/release/r1_l1_snapshot_manifest.json",
                "website/build-b1.html","website/b1-electronics.html","website/b1-testing.html",
                "website/sensors.html","website/assets/sensor-placement.svg",
                "website/assets/sensor-placement.csv","website/assets/n0-tip-stack.svg",
                "website/architecture.html",
                "website/assets/concepts/b2_board_concept.svg","website/assets/concepts/c1_concept.svg",
                "website/assets/concepts/magnetic_scaling.svg",
                "source/engineering/concepts/cad/b2_pcb_fit_witness.step",
                "source/engineering/concepts/cad/c1_strain_beam_coupon.step",
                "source/engineering/software/architecture_math.py",
                "source/engineering/software/architecture_cost.py",
                "source/engineering/research/quote_template.json",
                "source/engineering/firmware/c1/main.py",
                "source/engineering/firmware/c1/ads1232.py",
                "source/engineering/firmware/c1/ina219.py",
                "source/engineering/software/c1_protocol.py",
                "source/engineering/software/c1_record.py",
                "source/engineering/software/c1_force.py",
                "source/engineering/templates/c1_force_trials.json",
                "source/engineering/prototypes/c1/prototype_snapshot.json",
                "source/engineering/prototypes/c1/cad/c1_strain_beam.step",
                "source/engineering/prototypes/c1/pcb/c1_readout.kicad_pcb",
                "source/engineering/prototypes/c1/pcb/c1_readout_fabrication.zip",
                "source/engineering/prototypes/c1/c1_structural_inputs.zip",
                "source/engineering/prototypes/c1/c1_structural_review.json",
                "website/build-c1.html","website/c1-testing.html","website/c1-analysis.html",
                "website/assets/prototypes/c1/c1_gauge_placement.svg",
                "website/assets/prototypes/c1/c1-wiring.svg",
                "website/downloads/c1_bom.csv",
                "source/engineering/firmware/nail/main.py",
                "source/engineering/firmware/nail/pressure_scan.py",
                "source/engineering/software/nail_protocol.py",
                "source/engineering/software/nail_record.py",
                "source/engineering/software/nail_force.py",
                "source/engineering/software/raw_capture.py",
                "source/engineering/prototypes/nail/prototype_snapshot.json",
                "source/engineering/prototypes/nail/cad/nail_bare_sensing_fork.step",
                "source/engineering/prototypes/nail/cad/nail_revised_hard_frame.stl",
                "source/engineering/prototypes/nail/nail_firmware.zip",
                "source/engineering/prototypes/nail/nail_structural_inputs.zip",
                "source/engineering/prototypes/nail/fastener_checks.json",
                "website/build-nail.html","website/nail-testing.html","website/nail-analysis.html",
                "website/assets/prototypes/nail/nail-wiring.svg",
                "website/assets/prototypes/nail/nail_placement.svg",
                "source/engineering/firmware/recessed/main.py",
                "source/engineering/firmware/recessed/mlx90393.py",
                "source/engineering/software/recessed_protocol.py",
                "source/engineering/software/recessed_record.py",
                "source/engineering/prototypes/recessed/prototype_snapshot.json",
                "source/engineering/prototypes/recessed/cad/recessed_hard_frame.step",
                "source/engineering/prototypes/recessed/cad/recessed_locating_spacer_1.stl",
                "source/engineering/prototypes/recessed/recessed_firmware.zip",
                "source/engineering/prototypes/recessed/recessed_clearance_review.json",
                "source/engineering/prototypes/recessed/recessed_magnetic_review.json",
                "website/build-recessed.html","website/recessed-testing.html","website/recessed-analysis.html",
                "website/assets/prototypes/recessed/recessed_placement.svg",
                "website/assets/prototypes/recessed/recessed-wiring.svg",
                "website/downloads/recessed_bom.csv","website/downloads/recessed_specimen.json",
                "source/engineering/development/f1/mechanics/checkpoint.json",
                "source/engineering/development/f1/mechanics/cad/f1_r2_carrier.step",
                "source/engineering/development/f1/mechanics/patterns/f1_ch0_rows_fit.pdf",
                "source/engineering/development/f1/wrist/pcb/f1_wrist.kicad_pcb",
                "source/engineering/firmware/f1/main.py",
                "source/engineering/software/f1_record.py",
                "source/engineering/docs/BUILD_F1.md",
                "website/flexible-matrix.html","website/build-f1.html","website/f1-capture.html",
                "website/assets/development/f1/mechanics/file-index.html",
                "source/engineering/development/f1/r3/checkpoint.json",
                "source/engineering/development/f1/r3/pcb/f1_fanout_r3.kicad_pcb",
                "source/engineering/development/f1/r3/cad/f1_r3_carrier.step",
                "source/engineering/development/f1/r3/patterns/f1_ch0_rows_fit.pdf",
                "website/assets/development/f1/r3/file-index.html",
                "website/assets/development/f1/r3/visuals/inner_ground.png",
                "source/engineering/development/f1/fitted-foils-r3/checkpoint.json",
                "source/engineering/development/f1/fitted-foils-r3/foils/f1_ch1_rows/f1_ch1_rows.kicad_pcb",
                "website/assets/development/f1/fitted-foils-r3/file-index.html",
                "website/assets/development/f1/fitted-foils-r3/review/fitted_contact_map.png",
                "website/assets/development/f1/fitted-foils-r3/review/taxels.csv",
                "source/engineering/prototypes/f1/prototype_snapshot.json",
                "source/engineering/prototypes/f1/f1_manifest.json",
                "source/engineering/prototypes/f1/cad/f1_ch2_retained_cover.step",
                "source/engineering/prototypes/f1/patterns/f1_ch0_pressure_film_cut.svg",
                "source/engineering/prototypes/f1/flex/f1_ch0_rows/f1_ch0_rows.kicad_pcb",
                "source/engineering/prototypes/f1/checks/assembly.json",
                "source/engineering/prototypes/f1/f1_firmware.zip",
                "source/engineering/software/f1_holds.py",
                "source/engineering/software/f1_force.py",
                "source/engineering/templates/f1_force_trials.json",
                "website/f1-manufacturing.html","website/f1-testing.html","website/f1-reproduce.html",
                "website/assets/prototypes/f1/visuals/f1_r4_assembly.png",
                "website/assets/prototypes/f1/visuals/f1_stack.svg",
                "website/assets/prototypes/f1/file-index.html",
                "website/downloads/f1-prototype.zip",
                "source/engineering/development/capacitive/k1/checkpoint.json",
                "source/engineering/development/capacitive/k1/pcb/k1_readout.kicad_pcb",
                "source/engineering/docs/BUILD_CAPACITIVE.md",
                "website/build-capacitive.html",
                "website/assets/development/capacitive/k1/file-index.html",
                "website/assets/development/capacitive/k1/visuals/k1_stack.svg",
                "website/downloads/k1-development.zip",
                "source/engineering/prototypes/capacitive/prototype_snapshot.json",
                "source/engineering/prototypes/capacitive/capacitive_manifest.json",
                "source/engineering/prototypes/capacitive/flex/k1_ref_flex/k1_ref_flex.kicad_pcb",
                "source/engineering/prototypes/capacitive/readout/pcb/k1_readout.kicad_pcb",
                "source/engineering/prototypes/capacitive/cad/k1_ch0_retained_plate.step",
                "source/engineering/prototypes/capacitive/cad/k1_bank_case.stl",
                "source/engineering/prototypes/capacitive/k1_firmware.zip",
                "source/engineering/software/capacitive_force.py",
                "source/engineering/templates/capacitive_force_trials.json",
                "source/engineering/docs/CAPACITIVE_TESTING.md",
                "website/capacitive-testing.html",
                "website/assets/prototypes/capacitive/visuals/k1_wiring.svg",
                "website/assets/prototypes/capacitive/visuals/assembly_sensitivity.png",
                "website/downloads/k1-prototype.zip",
            ]
            for name in required:
                if name not in archive.namelist():raise ValueError(f"Complete packet missing {name}")
            for name in design_pages:
                if "website/"+name not in archive.namelist():raise ValueError(f"Complete packet missing design page: {name}")
            if "source/engineering/design_catalog.json" not in archive.namelist():
                raise ValueError("Portable source missing design catalog")
            # Every frozen prototype must be present in both halves of the
            # complete packet, including new designs not in the older list.
            packaged=set(archive.namelist())
            prototype_members=0
            for snapshot_path in sorted((ROOT/"engineering/prototypes").glob("*/prototype_snapshot.json")):
                snapshot=json.loads(snapshot_path.read_text())
                for name in (*snapshot["files"], "prototype_snapshot.json"):
                    for prefix in ("source/engineering/prototypes/", "website/assets/prototypes/"):
                        member=prefix+snapshot_path.parent.name+"/"+name
                        if member not in packaged:
                            raise ValueError("Complete packet missing frozen prototype member: "+member)
                        prototype_members+=1
        result={"passed":True,"local_links":local_links,"design_pages_verified":len(catalog["designs"]),
                "frozen_prototype_members_verified":prototype_members,"archives":archives,"hardware_validation":False}
        (ROOT/"build/engineering/site_checks.json").write_text(json.dumps(result,indent=2)+"\n")
        record["checks"]=result
        print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
