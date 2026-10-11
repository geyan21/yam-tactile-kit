#!/usr/bin/python3
"""Freeze C1 only after current CAD, electrical and structural checks agree."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/c1"
TARGET = ROOT/"engineering/prototypes/c1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_files(root,entries):
    for name,expected in entries.items():
        if digest(root/name)!=expected:
            raise ValueError("Content changed after checking: "+str(root/name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tolerance-report",type=Path,required=True)
    args = parser.parse_args()
    with execution(ROOT/"build/records","Freeze C1's checked digital build package while retaining all prior prototypes and physical-evidence limits") as record:
        release = ROOT/"engineering/release"
        baseline = json.loads((release/"release_manifest.json").read_text())
        verify_files(ROOT,baseline["source_hashes"]);verify_files(release,baseline["files"])
        b2 = ROOT/"engineering/prototypes/b2"
        previous = json.loads((b2/"prototype_snapshot.json").read_text())
        verify_files(ROOT,previous["source_hashes"]);verify_files(b2,previous["files"])
        plan = json.loads((OUTPUT/"c1_manifest.json").read_text())
        verify_files(ROOT,plan["source_hashes"])
        for part in plan["parts"]:
            for suffix in ("step","stl"):
                if digest(OUTPUT/part[suffix])!=part["sha256_"+suffix]:
                    raise ValueError("C1 CAD export changed")
            if not all(part["checks"].values()):
                raise ValueError("C1 CAD checks incomplete")
        design = json.loads((OUTPUT/"pcb/c1_pcb_design_checks.json").read_text())
        if not design["routed"]:
            raise ValueError("C1 PCB is not routed")
        verify_files(ROOT,design["source_hashes"])
        latest = json.loads((OUTPUT/"pcb/latest_check.json").read_text())
        checked = (OUTPUT/"pcb"/latest["directory"]).resolve()
        if not checked.is_relative_to((OUTPUT/"pcb/checks").resolve()):
            raise ValueError("Unexpected PCB check location")
        receipt = json.loads((checked/"pcb_checks.json").read_text())
        drc = json.loads((checked/"drc.json").read_text())
        if receipt["violations"] or receipt["unconnected"] or drc["violations"] or drc["unconnected_items"]:
            raise ValueError("C1 PCB has unresolved DRC/connectivity findings")
        if digest(OUTPUT/"pcb/c1_readout.kicad_pcb")!=receipt["source_sha256"] or digest(checked/"c1_readout.kicad_pcb")!=receipt["checked_pcb_sha256"]:
            raise ValueError("C1 electrical check is stale")
        verify_files(checked/"manufacturing",receipt["files"])
        review = json.loads((OUTPUT/"c1_structural_review.json").read_text())
        if not review["convergence"]["passed"] or not review["motion_screen_met"]:
            raise ValueError("C1 structural convergence or provisional motion screen is incomplete")
        for source in review["inputs"]:
            if digest(ROOT/source["directory"]/"screen.json")!=source["screen_sha256"]:
                raise ValueError("Structural result changed")
        tolerance = json.loads(args.tolerance_report.read_text())
        if tolerance["source_screen_sha256"]!=review["inputs"][-1]["screen_sha256"]:
            raise ValueError("Tolerance study must use the reviewed fine mesh")
        numerical_root = OUTPUT/"fea/numerical_verification"
        numerical_latest = json.loads((numerical_root/"latest.json").read_text())
        numerical_path = numerical_root/numerical_latest["directory"]/"verification.json"
        numerical = json.loads(numerical_path.read_text())
        if not numerical["passed"]:
            raise ValueError("Numerical pipeline verification failed")
        verify_files(ROOT,numerical["source_hashes"])
        fw = json.loads((OUTPUT/"firmware/firmware_manifest.json").read_text())
        verify_files(OUTPUT/"firmware",fw["files"])
        for name,expected in fw["files"].items():
            if digest(ROOT/"engineering/firmware/c1"/name)!=expected:
                raise ValueError("Firmware package is stale")
        TARGET.mkdir(parents=True,exist_ok=True)
        for name in ("cad","firmware"):
            shutil.copytree(OUTPUT/name,TARGET/name,dirs_exist_ok=True)
        for name in ("c1_manifest.json","models.json","c1_assembly.png","c1_exploded.png",
                     "c1_gauge_placement.svg","c1_review_drawings.pdf","c1_firmware.zip","c1_bom.csv",
                     "c1_structural_review.json","c1_structural_screen.svg","c1_structural_screen.png"):
            shutil.copyfile(OUTPUT/name,TARGET/name)
        shutil.copyfile(args.tolerance_report,TARGET/"c1_tolerance_scenarios.json")
        shutil.copyfile(numerical_path,TARGET/"numerical_verification.json")
        shutil.copyfile(ROOT/"engineering/web/c1-wiring.svg",TARGET/"c1-wiring.svg")
        pcb = TARGET/"pcb";pcb.mkdir(exist_ok=True)
        shutil.copyfile(checked/"c1_readout.kicad_pcb",pcb/"c1_readout.kicad_pcb")
        shutil.copyfile(OUTPUT/"pcb/c1_readout.kicad_pcb",pcb/"c1_readout.source.kicad_pcb")
        for name in ("c1_readout.kicad_dru","c1_readout.json","c1_readout_pin_net.csv",
                     "c1_readout_assembly.svg","c1_pcb_design_checks.json","fp-lib-table"):
            shutil.copyfile(OUTPUT/"pcb"/name,pcb/name)
        for name in ("pcb_checks.json","c1_readout_fabrication.zip"):
            shutil.copyfile(checked/name,pcb/name)
        shutil.copytree(OUTPUT/"pcb/Prototype.pretty",pcb/"Prototype.pretty",dirs_exist_ok=True)
        shutil.copytree(checked/"manufacturing",pcb/"manufacturing",dirs_exist_ok=True)
        (pcb/"drc.json").write_text((checked/"drc.json").read_text().replace(str(ROOT),"<checkout>"))
        # Input decks, meshes and frozen configurations reproduce the reported
        # solves. Large raw .dat outputs are retained in build and regenerated
        # from these inputs, rather than duplicated in every website archive.
        with zipfile.ZipFile(TARGET/"c1_structural_inputs.zip","w",zipfile.ZIP_DEFLATED) as archive:
            for index,source in enumerate(review["inputs"]):
                folder = ROOT/source["directory"]
                for name in ("mesh.inp","mesh.msh","c1.inp","screen.json"):
                    archive.write(folder/name,f"mesh_{index}/{name}")
                for path in sorted((folder/"inputs").iterdir()):
                    if path.is_file():
                        archive.write(path,f"mesh_{index}/inputs/{path.name}")
            archive.writestr("README.txt","C1 linear structural input decks and reported results.\nRun CalculiX with -i c1 in each mesh directory using the documented local runtime.\nRegenerate/postprocess through engineering/scripts/run_c1_fea.py.\nNo physical specimen or force accuracy is represented by these calculations.\n")
        (TARGET/"NOTICE.md").write_text(
            "# C1.1 prototype scope\n\n"
            "The original ENPIRE frame/contact geometry is attributed to Wenli Xiao / NVIDIA. "
            "The unchanged source geometry and provenance remain in engineering/docs/GEOMETRY.md.\n\n"
            "C1.1 adds a transverse metal strain beam, two carriers, clamp caps, alignment and bench fixtures, "
            "dual-bridge readout, raw acquisition and static calibration tools. "
            "The earlier longitudinal C1 coupon remains in engineering/concepts.\n\n"
            "CAD, PCB DRC and structural/numerical checks are digital evidence. "
            "No physical C1 assembly, calibrated accuracy, lifetime or robot qualification is reported. "
            "Structural calculations use ideal bonded clamps and a rigid finger; real joints, wires, "
            "gauge bonding, temperature and motion require measurements.\n\n"
            "Structural mesh generation uses Gmsh 4.15.2 (Geuzaine and Remacle); structural solution uses "
            "CalculiX 2.23 (Dhondt). Official download provenance is retained in the structural reports. "
            "The tools themselves are not redistributed in this package.\n")
        sources = [ROOT/"engineering/designs/c1.json",ROOT/"engineering/designs/c1_electronics.json"]
        sources += list((ROOT/"engineering/scripts").glob("*c1*.py"))
        sources += [ROOT/"engineering/scripts/structural_tools.py",ROOT/"engineering/scripts/verify_structural_numerics.py",
                    ROOT/"engineering/scripts/prototype_cad.py",ROOT/"engineering/scripts/prototype_pcb.py",
                    ROOT/"engineering/scripts/prototype_route.py",ROOT/"engineering/scripts/check_prototype_pcb.py",
                    ROOT/"engineering/web/c1-wiring.svg"]
        sources += list((ROOT/"engineering/firmware/c1").glob("*.py"))
        sources += list((ROOT/"engineering/software").glob("c1_*.py"))
        snapshot = {"schema":"yam-prototype-snapshot/1","id":"C1","revision":"C1.1",
                    "status":"digital prototype; physical assembly and qualification pending","physical_specimens_tested":0,
                    "shared_release_sha256":digest(release/"release_manifest.json"),
                    "source_hashes":{str(p.relative_to(ROOT)):digest(p) for p in sorted(set(sources))},
                    "files":{str(p.relative_to(TARGET)):digest(p) for p in sorted(TARGET.rglob("*"))
                             if p.is_file() and p.name!="prototype_snapshot.json"},
                    "checks":{"cad_parts":len(plan["parts"]),"drc_violations":0,"unconnected_items":0,
                              "numerical_verification":True,"structural_convergence":True,
                              "physical_qualification":False}}
        (TARGET/"prototype_snapshot.json").write_text(json.dumps(snapshot,indent=2)+"\n")
        record["snapshot"] = {"files":len(snapshot["files"]),**snapshot["checks"]}
        print(json.dumps(record["snapshot"],indent=2))


if __name__=="__main__":
    main()
