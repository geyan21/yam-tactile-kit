#!/usr/bin/python3
"""Build the engineering website, offline guide, and complete portable packet."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from tactile_kit.records import execution
from tactile_kit.render import markdown
from design_pages import load_catalog,build_design_pages,design_content

SITE=ROOT/"build/site"
RELEASE=ROOT/"engineering/release"
WEB=ROOT/"engineering/web"
DOCS=[
    ("SENSORS","sensors","Sensor choice & placement"),
    ("ARCHITECTURE","architecture","Scalability & better designs"),
    ("START","start","Student starting packet"),("GEOMETRY","geometry","Measured geometry"),
    ("BUILD_R1","build-r1","Build R1"),("ELECTRONICS","electronics","Electronics & code"),
    ("BUILD_L1","build-l1","Build L1 root force"),("L1_ELECTRONICS","l1-electronics","L1 wiring & code"),
    ("L1_TESTING","l1-testing","L1 force & moment tests"),
    ("MATERIALS","materials","Material comparison"),("COMPARISON","comparison","Sensor comparison"),
    ("TESTING","testing","Test protocol"),
    ("CONTACT","contact","Contact reliability"),
    ("BUILD_B1","build-b1","Build B1 magnetic insert"),
    ("B1_ELECTRONICS","b1-electronics","B1 wiring & code"),
    ("B1_TESTING","b1-testing","B1 bending & force tests"),
]


def verify_snapshot():
    manifest=json.loads((RELEASE/"release_manifest.json").read_text())
    for name,expected in manifest["source_hashes"].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
            raise ValueError(f"Stale geometry snapshot: {name}. Rebuild CAD and freeze the release.")
    for name,expected in manifest["files"].items():
        if hashlib.sha256((RELEASE/name).read_bytes()).hexdigest()!=expected:
            raise ValueError(f"Geometry snapshot hash mismatch: {name}")
    concepts=ROOT/"engineering/concepts"
    concept_snapshot=json.loads((concepts/"concept_snapshot.json").read_text())
    for name,expected in concept_snapshot["source_hashes"].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
            raise ValueError(f"Stale concept calculation: {name}")
    for name,expected in concept_snapshot["files"].items():
        if hashlib.sha256((concepts/name).read_bytes()).hexdigest()!=expected:
            raise ValueError(f"Concept artifact changed: {name}")
    if hashlib.sha256((RELEASE/"b1/b1_manifest.json").read_bytes()).hexdigest()!=concept_snapshot["basis_b1_release"]:
        raise ValueError("Concept basis does not match released B1")
    return manifest


def source_entries():
    roots=[ROOT/"README.md",ROOT/"LICENSE",ROOT/".gitignore",ROOT/".github/workflows",ROOT/"src/tactile_kit"]
    roots += [ROOT/"engineering"/name for name in (
        "README.md","bom.csv","l1_bom.csv","b1_bom.csv","study.json","design_catalog.json","requirements.in","requirements.lock",
        "scripts","software","firmware","docs","templates","designs","tests","web","release","electronics","research","concepts",
    )]
    entries={}
    for root in roots:
        paths=[root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file() or "__pycache__" in path.parts or path.suffix==".pyc":
                continue
            entries[str(path.relative_to(ROOT))]=path.read_bytes()
    return entries


def write_zip(path,entries):
    with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=7) as archive:
        for name,data in sorted(entries.items()):
            info=zipfile.ZipInfo(name,date_time=(2026,10,10,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            archive.writestr(info,data)


def chapter(source):
    text=(ROOT/"engineering/docs"/f"{source}.md").read_text()
    for name,slug,_ in DOCS:
        text=text.replace(f"]({name}.md)",f"]({slug}.html)")
    for old,new in (
        ("https://geyan21.github.io/yam-tactile-kit/",""),
        ("../release/","assets/"),("../web/","assets/"),
        ("../concepts/","assets/concepts/"),("../research/","downloads/"),
        ("../templates/","downloads/"),("../l1_bom.csv","downloads/l1_bom.csv"),("../b1_bom.csv","downloads/b1_bom.csv"),
    ):
        text=text.replace(f"]({old}",f"]({new}")
    rendered=markdown(text)
    return rendered


def document_page(title,body,active=""):
    nav='<a class="all-designs-link" href="designs.html">All designs · one page each →</a>'
    nav+="".join(f'<a class="{"active" if slug==active else ""}" href="{slug}.html">{html.escape(label)}</a>' for _,slug,label in DOCS)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · ENPIRE tactile</title><link rel="stylesheet" href="assets/style.css"><link rel="stylesheet" href="assets/design-pages.css"></head><body>
<a class="skip" href="#document">Skip to instructions</a>
<header><a class="brand" href="index.html">ENPIRE <b>TACTILE</b></a><nav aria-label="Main"><a href="designs.html">Designs</a><a href="index.html#build">Files</a><a href="index.html#evidence">Results</a><a href="https://github.com/geyan21/yam-tactile-kit">GitHub ↗</a></nav></header>
<main class="doc-layout"><aside class="doc-nav" aria-label="Chapters"><span class="label">BUILD PACKET / R1 + L1 + B1</span>{nav}<hr><a href="guide.html">Complete printable guide</a><a href="downloads/enpire-engineering-kit.zip" download>Download everything ↓</a></aside>
<article class="doc-body" id="document"><p class="doc-source">Experimental design · 20 N per finger qualification target · physical measurements pending</p>{body}</article></main>
<footer><a href="index.html">← Engineering notebook</a><a href="downloads/enpire-source.zip" download>Source, CAD and documentation ↓</a></footer></body></html>'''


def main():
    with execution(ROOT/"build/records","Build a portable engineering website with verified CAD downloads and no synthetic performance claims") as record:
        manifest=verify_snapshot()
        catalog=load_catalog()
        (ROOT/"build/engineering").mkdir(parents=True,exist_ok=True)
        if SITE.exists():
            shutil.rmtree(SITE)
        SITE.mkdir(parents=True)
        assets=SITE/"assets";downloads=SITE/"downloads"
        assets.mkdir();downloads.mkdir()
        for name in ("style.css","l1.css","viewer.js","app.js","stack.svg","wiring.svg","l1-wiring.svg","contact-flow.svg","b1-wiring.svg",
                     "sensor-placement.svg","sensor-placement.csv","sensor-placement.json","n0-tip-stack.svg",
                     "design-pages.css","design-viewer.js","r1-placement.svg"):
            shutil.copyfile(WEB/name,assets/name)
        for name in ("baseline","contact_regions","interfaces","r1","l1","b1"):
            shutil.copytree(RELEASE/name,assets/name)
        shutil.copytree(ROOT/"engineering/concepts",assets/"concepts")
        for name in ("architecture_evidence.json","quote_template.json","scale_validation.json"):
            shutil.copyfile(ROOT/"engineering/research"/name,downloads/name)
        shutil.copytree(RELEASE/"r1/cad",downloads/"cad")
        shutil.copytree(RELEASE/"l1/cad",downloads/"l1/cad")
        shutil.copytree(RELEASE/"b1/cad",downloads/"b1/cad")
        for source,target in (
            (ROOT/"engineering/bom.csv","bom.csv"),(ROOT/"engineering/templates/specimen.json","specimen.json"),
            (RELEASE/"r1/r1_cut_sheet.svg","r1_cut_sheet.svg"),(RELEASE/"release_manifest.json","release_manifest.json"),
            (RELEASE/"r1/r1_cut_sheet.pdf","r1_cut_sheet.pdf"),
            (ROOT/"engineering/l1_bom.csv","l1_bom.csv"),
            (ROOT/"engineering/templates/l1_specimen.json","l1_specimen.json"),
            (RELEASE/"l1/l1_review_drawings.pdf","l1_review_drawings.pdf"),
            (RELEASE/"l1/l1_bench_plan.json","l1_bench_plan.json"),
            (RELEASE/"l1/l1_finger_plan.json","l1_finger_plan.json"),
            (ROOT/"engineering/templates/contact_setup.json","contact_setup.json"),
            (ROOT/"engineering/templates/contact_cases.json","contact_cases.json"),
            (ROOT/"engineering/b1_bom.csv","b1_bom.csv"),
            (ROOT/"engineering/templates/b1_specimen.json","b1_specimen.json"),
            (RELEASE/"b1/b1_review_drawings.pdf","b1_review_drawings.pdf"),
            (RELEASE/"b1/pcb/b1_head_fabrication.zip","b1_head_fabrication.zip"),
        ):
            shutil.copyfile(source,downloads/target)
        r1_models=json.loads((RELEASE/"models.json").read_text())
        l1_models=json.loads((RELEASE/"l1/models.json").read_text())
        b1_models=json.loads((RELEASE/"b1/models.json").read_text())
        payload={
            "models":[r1_models[0],b1_models[0],*l1_models[:2],*r1_models[1:],*l1_models[2:],*b1_models[1:]],
            "r1":json.loads((RELEASE/"r1/r1_manifest.json").read_text()),
            "l1":json.loads((RELEASE/"l1/l1_manifest.json").read_text()),
            "b1":json.loads((RELEASE/"b1/b1_manifest.json").read_text()),
            "l1Contacts":json.loads((RELEASE/"l1/contact_sites.json").read_text())["sites"],
            "study":json.loads((ROOT/"engineering/study.json").read_text()),
            "designPages":{item["id"]:item["slug"]+".html" for item in catalog["designs"]},
        }
        (assets/"data.js").write_text("window.ENGINEERING="+json.dumps(payload,separators=(",",":")).replace("</","<\\/")+";\n")
        design_links='<nav class="design-switcher" aria-label="Separate design pages"><a href="designs.html">All designs →</a>'
        design_links+="".join(f'<a href="{item["slug"]}.html">{html.escape(item["title"].split(" · ")[0])}</a>'
                              for item in catalog["designs"] if item["group"]!="research")
        design_links+="</nav>"
        (SITE/"index.html").write_text((WEB/"index.html").read_text().replace("<!-- DESIGN_PAGE_LINKS -->",design_links))
        build_design_pages(SITE,catalog)
        all_chapters=[]
        for source,slug,title in DOCS:
            content=chapter(source)
            (SITE/f"{slug}.html").write_text(document_page(title,content,slug))
            all_chapters.append(f'<section id="{slug}">{content}</section>')
        overviews=[f'<section id="design-{item["slug"]}">{design_content(item,catalog,viewer=False)}</section>' for item in catalog["designs"]]
        (SITE/"guide.html").write_text(document_page("Complete build and test guide",'<div class="all-guide">'+"".join(overviews+all_chapters)+"</div>"))
        source=source_entries()
        write_zip(downloads/"enpire-source.zip",source)
        designs={str(path.relative_to(RELEASE)):path.read_bytes() for path in RELEASE.rglob("*") if path.is_file() and path.name!="models.json"}
        designs.update({"concepts/"+str(path.relative_to(ROOT/"engineering/concepts")):path.read_bytes()
                        for path in (ROOT/"engineering/concepts").rglob("*") if path.is_file()})
        write_zip(downloads/"enpire-designs.zip",designs)
        # Offline pages carry CAD and source ZIPs. Links to the two enclosing
        # archives point at that included source packet, avoiding self-recursion.
        offline={}
        for path in SITE.rglob("*"):
            if not path.is_file():
                continue
            relative=str(path.relative_to(SITE));content=path.read_bytes()
            if path.suffix==".html":
                content=content.replace(b'downloads/enpire-engineering-kit.zip',b'downloads/enpire-source.zip')
                content=content.replace(b'downloads/enpire-site.zip',b'downloads/enpire-source.zip')
            offline[relative]=content
        write_zip(downloads/"enpire-site.zip",offline)
        complete={"source/"+name:content for name,content in source.items()}
        complete.update({"website/"+name:content for name,content in offline.items()})
        complete["START_HERE.txt"]=(
            "ENPIRE tactile R1.0 + L1.0 + B1.0 engineering packet\n\n"
            "Open website/index.html for the visual build guide and downloads.\n"
            "Open website/designs.html for one clear page per design and research alternative.\n"
            "Editable code and documents: source/engineering.\n"
            "STEP/STL tooling and carriers: source/engineering/release/r1/cad and l1/cad.\n"
            "R1: six local tactile zones. L1: purchased load cell in the complete finger force path.\n"
            "B1: separate compliant magnetic insert, fixed sensor spine, PCB files and raw readout.\n"
            "B1 files: source/engineering/release/b1; electronics source: source/engineering/electronics/b1.\n"
            "The requested range is 20 N per finger. Hardware qualification is pending.\n"
            "This package contains digital geometry and test instructions, not fabricated results.\n"
        ).encode()
        write_zip(downloads/"enpire-engineering-kit.zip",complete)
        # Preserve the download URLs used by the earlier public website.
        for old,new in (
            ("yam-tactile-complete.zip","enpire-engineering-kit.zip"),
            ("yam-tactile-kit.zip","enpire-source.zip"),
            ("yam-tactile-designs.zip","enpire-designs.zip"),
            ("yam-tactile-site.zip","enpire-site.zip"),
        ):
            shutil.copyfile(downloads/new,downloads/old)
        summary={
            "site":"build/site","cad_parts":sum(len(payload[name]["parts"]) for name in ("r1","l1","b1")),
            "purchased_reference_solids":3,
            "separate_concept_solids":2,
            "documents":len(DOCS)+len(catalog["designs"]),"design_pages":len(catalog["designs"]),
            "requested_per_finger_force_n":20,
            "physical_specimens_tested":payload["study"]["physical_specimens_tested"],
            "complete_packet_bytes":(downloads/"enpire-engineering-kit.zip").stat().st_size,
            "snapshot_files_verified":len(manifest["files"]),
        }
        record["build"]=summary
        (ROOT/"build/engineering/site_build.json").write_text(json.dumps(summary,indent=2)+"\n")
        print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()
