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
            ]
            for name in required:
                if name not in archive.namelist():raise ValueError(f"Complete packet missing {name}")
        result={"passed":True,"local_links":local_links,"archives":archives,"hardware_validation":False}
        (ROOT/"build/engineering/site_checks.json").write_text(json.dumps(result,indent=2)+"\n")
        record["checks"]=result
        print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
