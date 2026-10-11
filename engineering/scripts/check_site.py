#!/usr/bin/python3
"""Check local website links and all portable archives; perform no network requests."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
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
            target=str(PurePosixPath(name).parent/unquote(url.path)) if url.path else name
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
            ]
            for name in required:
                if name not in archive.namelist():raise ValueError(f"Complete packet missing {name}")
            for name in design_pages:
                if "website/"+name not in archive.namelist():raise ValueError(f"Complete packet missing design page: {name}")
            if "source/engineering/design_catalog.json" not in archive.namelist():
                raise ValueError("Portable source missing design catalog")
        result={"passed":True,"local_links":local_links,"design_pages_verified":len(catalog["designs"]),"archives":archives,"hardware_validation":False}
        (ROOT/"build/engineering/site_checks.json").write_text(json.dumps(result,indent=2)+"\n")
        record["checks"]=result
        print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
