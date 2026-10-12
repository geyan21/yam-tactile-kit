#!/usr/bin/python3
"""Prepare the physical build queue and completion audit from the verified kit."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution

SITE = "https://geyan21.github.io/yam-tactile-kit/"
CODES = {"R1": "R1", "L1": "L1", "B1": "B1", "B2": "B2", "C1": "C1",
         "NAIL": "N1", "RECESSED": "B3", "F1": "F1", "CAPACITIVE": "K1",
         "PNEUMATIC": "P1", "O1": "O1", "FORCE_BUTTON": "FB1"}


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication-report", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    args = parser.parse_args()
    publication_path = args.publication_report.resolve()
    archive_path = args.source_archive.resolve()
    publication = json.loads(publication_path.read_text())
    expected = publication["release_assets"]["enpire-source.zip"]
    if (publication.get("published_verified") is not True or not publication.get("main_matches")
            or not expected.get("published_checksum_matches")):
        raise ValueError("Use the successful publication verification")
    folder = ROOT/"build/physical_campaign"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Prepare all 36 planned specimen IDs and a physical-evidence audit from the exact published source; no hardware operation or invented measurements") as record:
        archive_hash = digest(archive_path)
        if archive_hash != expected["published_sha256"]:
            raise ValueError("The source archive differs from the verified release")
        with zipfile.ZipFile(archive_path) as archive:
            inputs = {}
            for relative in ("engineering/campaign/requirements.json", "engineering/design_catalog.json"):
                data = archive.read(relative)
                if (ROOT/relative).read_bytes() != data:
                    raise ValueError("Working campaign differs from published source: "+relative)
                inputs[relative] = json.loads(data)
        plan = inputs["engineering/campaign/requirements.json"]
        catalog = {item["id"]: item for item in inputs["engineering/design_catalog.json"]["designs"]}
        designs = plan["designs"]
        if {item["id"] for item in designs} != set(CODES) or set(catalog) != set(CODES):
            raise ValueError("The handoff must cover the same twelve designs")
        copies = plan["requirements"]["pilot_independent_specimens_per_design"]
        if copies != 3:
            raise ValueError("Review a changed physical replication requirement")
        # These records describe the reported campaign. They do not search
        # arbitrary lab storage or infer that a physical trial passed/failed.
        if (plan["evidence_policy"]["physical_specimens_tested"] != 0
                or any(item["physical_evidence"] != "missing" for item in designs)):
            raise ValueError("Physical evidence is now reported; audit it before issuing an empty queue")
        rows, guides = [], {}
        for item in designs:
            design = catalog[item["id"]]
            page = design["slug"]+".html"
            if publication["pages"].get(page, {}).get("matches_prepared_hosted_page") is not True:
                raise ValueError("Published design page was not verified: "+page)
            build_pages = [Path(urlsplit(resource[2]).path).name for resource in design["resources"]]
            build_pages = [name for name in build_pages if name.startswith("build-") and name.endswith(".html")]
            if not build_pages:
                raise ValueError("No concrete build guide for "+item["id"])
            guides[item["id"]] = SITE+build_pages[0]
            for number in range(1, copies+1):
                rows.append({"specimen_id": f"{CODES[item['id']]}-{number:02d}", "design_id": item["id"],
                             "status": "planned_not_built", "operator": "", "build_guide": guides[item["id"]],
                             "assembly_record": "", "raw_measurements": "", "validation_report": "",
                             "assembly_minutes": "", "force_rmse_n": "", "contact_miss_upper_95": "",
                             "false_contact_upper_95": "", "added_tip_motion_mm_at_20n": "",
                             "failures_and_rework": "", "decision": "not_evaluated"})
        if len(rows) != 36 or len({row["specimen_id"] for row in rows}) != 36:
            raise ValueError("Incomplete or duplicated specimen queue")
        gates = [
            {"requirement": "Separate design pages, CAD, BOMs, code, documentation and visuals",
             "state": "digital_delivery_verified",
             "evidence": {"publication_report_sha256": digest(publication_path),
                          "source_archive_sha256": expected["published_sha256"],
                          "source_commit": publication["expected_commit"]},
             "scope_limit": "Delivered design files do not prove that the parts have been fabricated or assembled."},
            {"requirement": "Build all twelve designs with three independent specimens each",
             "state": "physical_evidence_missing", "planned_specimens": len(rows),
             "reported_tested_specimens": 0,
             "needed": "Dated assembly records, material/component identities, actual fit checks and specimen photographs."},
            {"requirement": "Reliable contact at 0.2 N and false-contact probability <=1%",
             "state": "physical_evidence_missing",
             "needed": "Raw independent labelled presentations, frozen thresholds, held-out outcomes and per-condition confidence bounds."},
            {"requirement": "Force feedback through 20 N per finger",
             "state": "physical_evidence_missing",
             "needed": "Calibrated force reference, complete loading/unloading and mixed-contact coverage, held-out errors and unavailable readings."},
            {"requirement": "Thin-tip access, added motion, recovery and precision tasks",
             "state": "physical_evidence_missing",
             "needed": "Measured installed thickness/opening loss, reference-relative tip motion and fixed-protocol task trials."},
            {"requirement": "Interference, drift, long holds, wear and replacement",
             "state": "physical_evidence_missing",
             "needed": "Identified no-contact motion/pose/cable/temperature conditions, repeated-load and surface-replacement records."},
            {"requirement": "Determine which designs are good",
             "state": "not_decidable_from_current_evidence",
             "needed": "Complete physical gates plus actual assembly/rework/calibration time and failed-build counts. Do not rank missing measurements."},
        ]
        audit = {"schema": "yam-physical-campaign-handoff/1",
                 "created_utc": datetime.now(timezone.utc).isoformat(),
                 "objective": plan["objective"], "goal_complete": False,
                 "previous_goal_turn_classification": "progress: twelve-design publication completed and verified",
                 "evidence_scope": "Published source, recorded campaign state and supplied publication verification; no lab-storage or hardware discovery is inferred.",
                 "requirements": gates, "required_test_categories": plan["requirements"]["required_tests"],
                 "per_design_physical_state": {item["id"]: "not_evaluated" for item in designs},
                 "planned_specimens": len(rows), "operator": None, "measurement_location": None,
                 "next_required_action": "Assign the student/operator, fabricate and assemble identified specimens, and record physical measurements using the published protocols.",
                 "blocking_dependency": "Physical fabrication/assembly and test evidence are not available in the reported campaign.",
                 "inputs": {"publication_report": str(publication_path), "publication_report_sha256": digest(publication_path),
                            "source_archive": str(archive_path), "source_archive_sha256": archive_hash,
                            "generator_sha256": digest(Path(__file__))}}
        folder.mkdir(parents=True)
        (folder/"completion_audit.json").write_text(json.dumps(audit, indent=2)+"\n")
        with (folder/"specimen_queue.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
        lines = [
            "# Physical build and comparison handoff",
            "",
            "**36 planned specimens; no physical results are entered.** The digital packages are published, but the goal is not complete until the designs are built and measured.",
            "",
            "Operator: unassigned. Shared measurement location: unassigned.",
            "",
            "## Start the build campaign",
            "",
            "1. Assign the student/operator and the experiment directory. Use the exact published revision below.",
            "2. Obtain/fabricate the parts from each linked BOM and build guide. Record real material lots, electronics and build time.",
            "3. Assemble each planned specimen separately. Check actual drive fit, leading-tip access, power, raw sensing and failure behavior before load testing.",
            "4. Run the shared force/contact/precision protocol. Keep calibration and evaluation sessions separate, and retain failed builds, rework and unavailable readings.",
            "5. Enter record paths and measured results in `specimen_queue.csv`. Blank metrics mean unmeasured, not zero error.",
            "",
            "## All twelve designs",
            "",
            "| Design | Planned specimen IDs | Build instructions |",
            "|---|---|---|",
        ]
        for item in designs:
            identifiers = ", ".join(row["specimen_id"] for row in rows if row["design_id"] == item["id"])
            lines.append(f"| {CODES[item['id']]} | {identifiers} | [Build guide]({guides[item['id']]}) |")
        lines += [
            "",
            f"[Common test and comparison plan]({SITE}build-all.html)",
            "",
            "Use 0, 0.2, 0.5, 1, 2, 5, 10, 15 and 20 N per finger with the specified independent reference. The plan also requires no-contact disturbances, nail/soft-surface edges and mixtures, tip motion, task access, wear, recovery and build practicality.",
            "",
            "The proposed force targets are <=0.5 N held-out RMSE and the stated per-trial error rule. Contact confirmation uses 300 independent presentations per label/region with a one-sided 95% bound; adjacent frames are not independent trials. The provisional added-motion screen is 0.1 mm at 20 N.",
            "",
            "A repeated recording or a renamed specimen is not another independent build. Follow each design's capture and validation procedure; a CAD check or synthetic fixture cannot fill a physical-results cell.",
            "",
            f"Published source revision: `{publication['expected_commit']}`.",
            f"Source archive SHA-256: `{expected['published_sha256']}`.",
            "",
            "`completion_audit.json` records the remaining evidence for each requirement. No design is designated a physical winner.",
        ]
        (folder/"HANDOFF.md").write_text("\n".join(lines)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "planned_specimens": len(rows),
                            "designs": len(designs), "physical_results_entered": 0,
                            "goal_complete": False,
                            "files_sha256": {p.name: digest(p) for p in sorted(folder.iterdir())}}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
