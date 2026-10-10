#!/usr/bin/python3
"""Read the approved public repository, Actions run, and deployed engineering snapshot."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
from design_pages import load_catalog

API="https://api.github.com/repos/geyan21/yam-tactile-kit"
SITE="https://geyan21.github.io/yam-tactile-kit/"


def read(url,limit=64*1024*1024):
    request=Request(url,headers={"User-Agent":"enpire-engineering-publication-check","Cache-Control":"no-cache"})
    with urlopen(request,timeout=25) as response:
        data=response.read(limit+1)
    if len(data)>limit:raise ValueError("Public resource exceeds the scoped download limit")
    return data


def content_hash(data,name,depth=0):
    if not name.endswith(".zip") or depth>=4:
        return hashlib.sha256(data).hexdigest()
    # Different CI zlib versions may encode identical ZIP contents differently.
    # Verify every named entry, not a platform-dependent compression stream.
    digest=hashlib.sha256()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.testzip() is not None:
            raise ValueError("Corrupt published ZIP")
        names=archive.namelist()
        if len(names)!=len(set(names)):
            raise ValueError("Duplicate entries in published ZIP")
        for entry in sorted(names):
            digest.update(entry.encode()+b"\0"+bytes.fromhex(content_hash(archive.read(entry),entry,depth+1)))
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit",required=True)
    args=parser.parse_args()
    if len(args.commit)!=40 or any(c not in "0123456789abcdef" for c in args.commit):
        parser.error("Expected a complete lowercase commit SHA")
    with execution(ROOT/"build/records","Verify the published engineering commit, public workflow result, webpage, and download hashes") as record:
        current=json.loads(read(API+"/commits/main"))
        runs=json.loads(read(API+"/actions/runs?head_sha="+args.commit+"&per_page=5"))["workflow_runs"]
        summary={
            "expected_commit":args.commit,"remote_main":current["sha"],
            "main_matches":current["sha"]==args.commit,
            "runs":[{key:run.get(key) for key in ("id","head_sha","status","conclusion","html_url")} for run in runs],
        }
        try:
            page=read(SITE).decode("utf-8")
            summary["page_title_matches"]="<title>ENPIRE tactile — Build, measure, compare</title>" in page
            summary["b1_feature_visible"]='id="bending"' in page and "build-b1.html" in page
            remote_manifest=read(SITE+"downloads/release_manifest.json")
            local_manifest=(ROOT/"engineering/release/release_manifest.json").read_bytes()
            summary["release_manifest_matches"]=remote_manifest==local_manifest
            if summary["release_manifest_matches"]:
                checks={}
                for name in ("enpire-engineering-kit.zip","r1_cut_sheet.pdf","cad/nail_cover_mold.step",
                             "l1/cad/l1_floating_finger_carrier.step","l1_review_drawings.pdf","l1_finger_plan.json",
                             "b1/cad/b1_magnetic_tpu_insert.step","b1_review_drawings.pdf","b1_head_fabrication.zip",
                             "b2_main_fabrication.zip","b2_firmware.zip","b2_review_drawings.pdf",
                             "prototypes/b2/cad/b2_removable_backer.step","campaign_requirements.json"):
                    remote=read(SITE+"downloads/"+name)
                    local=(ROOT/"build/site/downloads"/name).read_bytes()
                    checks[name]=content_hash(remote,name)==content_hash(local,name)
                summary["download_hashes_match"]=checks
                summary["b1_guide_pages_match"]={name:read(SITE+name)==(ROOT/"build/site"/name).read_bytes()
                    for name in ("build-b1.html","b1-electronics.html","b1-testing.html","sensors.html","architecture.html","build-b2.html","build-all.html")}
                summary["b2_prototype_assets_match"]={name:read(SITE+"assets/prototypes/b2/"+name)==(ROOT/"build/site/assets/prototypes/b2"/name).read_bytes()
                    for name in ("prototype_snapshot.json","b2_manifest.json","b2_placement.svg","b2-wiring.svg",
                                 "b2_assembly.png","b2_exploded.png","models.json","pcb/pcb_checks.json","pcb/b2_main.kicad_pcb")}
                summary["sensor_placement_assets_match"]={name:read(SITE+"assets/"+name)==(ROOT/"build/site/assets"/name).read_bytes()
                    for name in ("sensor-placement.svg","sensor-placement.csv","sensor-placement.json","n0-tip-stack.svg")}
                summary["architecture_artifacts_match"]={name:read(SITE+"assets/concepts/"+name)==(ROOT/"build/site/assets/concepts"/name).read_bytes()
                    for name in ("concept_snapshot.json","b2_board_concept.svg","c1_concept.svg","magnetic_scaling.svg","magnetic_gap.svg",
                                 "cad/b2_pcb_fit_witness.step","cad/c1_strain_beam_coupon.step")}
                pages=["designs.html",*[item["slug"]+".html" for item in load_catalog()["designs"]]]
                summary["separate_design_pages_match"]={name:read(SITE+name)==(ROOT/"build/site"/name).read_bytes() for name in pages}
                summary["design_assets_match"]={name:read(SITE+"assets/"+name)==(ROOT/"build/site/assets"/name).read_bytes()
                    for name in ["design-catalog.json","design-pages.css","design-viewer.js","r1-placement.svg",
                                 *["design-schematics/"+item["slug"]+".svg" for item in load_catalog()["designs"]]]}
        except HTTPError as error:
            summary["site_http_error"]=error.code
        summary["published_verified"]=(
            summary["main_matches"] and summary.get("page_title_matches",False)
            and summary.get("release_manifest_matches",False)
            and bool(summary.get("download_hashes_match"))
            and all(summary.get("download_hashes_match",{}).values())
            and summary.get("b1_feature_visible",False)
            and bool(summary.get("b1_guide_pages_match"))
            and all(summary.get("b1_guide_pages_match",{}).values())
            and bool(summary.get("sensor_placement_assets_match"))
            and all(summary.get("sensor_placement_assets_match",{}).values())
            and bool(summary.get("architecture_artifacts_match"))
            and all(summary.get("architecture_artifacts_match",{}).values())
            and bool(summary.get("separate_design_pages_match"))
            and all(summary.get("separate_design_pages_match",{}).values())
            and bool(summary.get("design_assets_match"))
            and all(summary.get("design_assets_match",{}).values())
            and bool(summary.get("b2_prototype_assets_match"))
            and all(summary.get("b2_prototype_assets_match",{}).values())
            and any(run["conclusion"]=="success" for run in summary["runs"])
        )
        record["publication"]=summary
        (ROOT/"build/engineering/publication_status.json").write_text(json.dumps(summary,indent=2)+"\n")
        print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()
