#!/usr/bin/python3
"""Freeze the checked N1 digital packet while preserving all earlier designs."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/prototypes/nail"
TARGET=ROOT/"engineering/prototypes/nail"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root,entries):
    for name,expected in entries.items():
        if digest(root/name)!=expected:
            raise ValueError("Checked input or artifact changed: "+str(root/name))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fastener-checks",type=Path,required=True)
    args=parser.parse_args()
    with execution(ROOT/"build/records","Freeze N1 CAD, firmware, wiring, calibration tools and numerical evidence; preserve prior packages and physical-evidence limits") as record:
        release=ROOT/"engineering/release"
        baseline=json.loads((release/"release_manifest.json").read_text())
        verify(ROOT,baseline["source_hashes"]);verify(release,baseline["files"])
        for name in ("b2","c1"):
            folder=ROOT/"engineering/prototypes"/name
            prior=json.loads((folder/"prototype_snapshot.json").read_text())
            verify(ROOT,prior["source_hashes"]);verify(folder,prior["files"])
        plan=json.loads((OUTPUT/"nail_manifest.json").read_text())
        verify(ROOT,plan["source_hashes"])
        for part in plan["parts"]:
            if not all(part["checks"].values()):
                raise ValueError("N1 CAD checks are incomplete")
            for suffix in ("step","stl"):
                if digest(OUTPUT/part[suffix])!=part["sha256_"+suffix]:
                    raise ValueError("N1 export changed after checking")
        if any(value>1e-5 for value in plan["rigid_overlap_checks_mm3"].values()):
            raise ValueError("N1 has unresolved rigid interference")
        if plan["protected_central_frame_removed_mm3"]>1e-6 or any(
                row["removed_source_material_mm3"]>1e-6 for row in plan["preserved_attachment_checks"]):
            raise ValueError("Required source frame regions changed")
        fasteners=json.loads(args.fastener_checks.read_text())
        if fasteners["manifest_sha256"]!=digest(OUTPUT/"nail_manifest.json") or not fasteners["passed"] or len(fasteners["checks"])!=8:
            raise ValueError("Current N1 geometry needs all eight fastener-surround checks")
        review=json.loads((OUTPUT/"nail_structural_review.json").read_text())
        if not review["convergence"]["passed"] or not review["motion_screen_met"]:
            raise ValueError("N1 structural convergence or provisional motion screen is incomplete")
        for source in review["inputs"]:
            folder=ROOT/source["directory"]
            if digest(folder/"screen.json")!=source["screen_sha256"] or digest(folder/"inputs/analysis.step")!=plan["analysis_step_sha256"]:
                raise ValueError("N1 structural evidence is stale")
        firmware=json.loads((OUTPUT/"firmware/firmware_manifest.json").read_text())
        verify(OUTPUT/"firmware",firmware["files"])
        for entry in firmware["sources"].values():
            if digest(ROOT/entry["path"])!=entry["sha256"]:
                raise ValueError("N1 firmware packet is stale")
        TARGET.mkdir(parents=True,exist_ok=True)
        for name in ("cad","firmware"):
            shutil.copytree(OUTPUT/name,TARGET/name,dirs_exist_ok=True)
        for name in ("nail_manifest.json","models.json","nail_assembly.png","nail_exploded.png",
                     "nail_gauge_placement.svg","nail_gauge_placement.png","nail_placement.svg",
                     "nail_review_drawings.pdf","nail_bom.csv","nail_firmware.zip",
                     "nail_structural_review.json","nail_structural_screen.svg","nail_structural_screen.png"):
            shutil.copyfile(OUTPUT/name,TARGET/name)
        shutil.copyfile(args.fastener_checks,TARGET/"fastener_checks.json")
        shutil.copyfile(ROOT/"engineering/web/nail-wiring.svg",TARGET/"nail-wiring.svg")
        # The solver decks contain every node, element, boundary and force.
        # Visualization meshes and large raw solver outputs remain preserved
        # in the working runs and can be regenerated using the supplied code.
        with zipfile.ZipFile(TARGET/"nail_structural_inputs.zip","w",zipfile.ZIP_DEFLATED) as archive:
            for index,source in enumerate(review["inputs"]):
                folder=ROOT/source["directory"]
                for name in ("mesh.inp","nail.inp","screen.json","mesh_metadata.json"):
                    archive.write(folder/name,f"mesh_{index}/{name}")
                for path in sorted((folder/"inputs").iterdir()):
                    if path.is_file():
                        archive.write(path,f"mesh_{index}/inputs/{path.name}")
            archive.writestr("README.txt",
                "N1 structural reproduction inputs; no physical measurements.\n"
                "Run CalculiX with -i nail in each mesh directory using the documented local runtime.\n"
                "mesh.inp contains all volume nodes/elements; nail.inp contains supports, pressure-patch loads and outputs.\n"
                "Regenerate the visualization mesh and postprocessing through engineering/scripts/run_nail_fea.py.\n"
                "The model fixes the source support faces and bonds metal interfaces. Real joints, printed frame and hardware qualification require tests.\n")
        (TARGET/"NOTICE.md").write_text(
            "# N1 experimental prototype\n\n"
            "Original ENPIRE finger geometry: Wenli Xiao / NVIDIA ENPIRE. Source provenance remains in engineering/docs/GEOMETRY.md.\n\n"
            "N1 adds a bare steel sensing fork with two shear webs, two fixed carriers and a separately revised PETG frame. "
            "The original TPU and the retained R1 CH2-CH5 interfaces are used. The bridge readout is the unchanged C1.1 PCB. "
            "N1 has its own combined firmware and recording identity.\n\n"
            "The frame is a faceted derivative of the pinned source STL, not the original author's analytic CAD. "
            "CAD, material-around-fastener and numerical checks are digital evidence. "
            "No physical assembly, force accuracy, contact reliability, endurance or robot qualification is reported.\n\n"
            "Structural meshing uses Gmsh 4.15.2; solution uses CalculiX 2.23. "
            "Tool provenance and input decks are retained; the tools themselves are not redistributed.\n")
        sources=[ROOT/"engineering/designs/nail.json",ROOT/"engineering/designs/nail_electronics.json",
                 ROOT/"engineering/scripts/source_brep.py",ROOT/"engineering/scripts/prepare_source_brep.py",
                 ROOT/"engineering/scripts/prototype_cad.py",ROOT/"engineering/scripts/build_b1_parts.py",
                 ROOT/"engineering/scripts/analyze_b1_interfaces.py",ROOT/"engineering/scripts/structural_tools.py",
                 ROOT/"engineering/software/raw_capture.py",ROOT/"engineering/software/c1_protocol.py",
                 ROOT/"engineering/software/c1_force.py",ROOT/"engineering/software/calibrate.py",
                 ROOT/"engineering/prototypes/c1/prototype_snapshot.json",ROOT/"engineering/web/nail-wiring.svg"]
        sources+=list((ROOT/"engineering/scripts").glob("*nail*.py"))
        sources+=list((ROOT/"engineering/software").glob("nail_*.py"))
        sources+=[path for path in (ROOT/"engineering/firmware/nail").iterdir() if path.is_file()]
        sources+=[ROOT/entry["path"] for entry in firmware["sources"].values()]
        snapshot={"schema":"yam-prototype-snapshot/1","id":"NAIL","revision":"N1.1",
                  "status":"digital prototype; physical assembly and qualification pending","physical_specimens_tested":0,
                  "shared_release_sha256":digest(release/"release_manifest.json"),
                  "shared_c1_snapshot_sha256":digest(ROOT/"engineering/prototypes/c1/prototype_snapshot.json"),
                  "source_hashes":{str(path.relative_to(ROOT)):digest(path) for path in sorted(set(sources))},
                  "files":{str(path.relative_to(TARGET)):digest(path) for path in sorted(TARGET.rglob("*"))
                           if path.is_file() and path.name!="prototype_snapshot.json"},
                  "checks":{"cad_parts":len(plan["parts"]),"fastener_surround_checks":8,
                            "preserved_attachment_regions":3,"structural_convergence":True,
                            "physical_qualification":False}}
        (TARGET/"prototype_snapshot.json").write_text(json.dumps(snapshot,indent=2)+"\n")
        record["snapshot"]={"files":len(snapshot["files"]),**snapshot["checks"]}
        print(json.dumps(record["snapshot"],indent=2))


if __name__=="__main__":
    main()
