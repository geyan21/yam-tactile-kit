#!/usr/bin/python3
"""Archive the F1 selected-column study with its adverse and incomplete evidence."""

import argparse
import copy
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pack_run(source, target, label):
    """Retain exact source, logs and vectors; omit derived review images."""
    members = {}
    with target.open("wb") as stream, gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for path in sorted(source.rglob("*")):
                relative = path.relative_to(source)
                if not path.is_file() or "reviews" in relative.parts or "__pycache__" in relative.parts:
                    continue
                if path.is_symlink() or path.suffix.lower() in (".lib", ".zip", ".so", ".cm", ".pyc"):
                    raise ValueError(f"Unexpected vendor/binary file in circuit run: {relative}")
                name = str(Path(label) / relative)
                info = archive.gettarinfo(str(path), arcname=name)
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with path.open("rb") as data:
                    archive.addfile(info, data)
                members[name] = {"sha256": digest(path), "bytes": path.stat().st_size}
    return {"sha256": digest(target), "bytes": target.stat().st_size, "members": members}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--nominal-summary", type=Path, required=True)
    parser.add_argument("--drawing", type=Path, required=True)
    parser.add_argument("--worker-check", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / "engineering/development/f1/readout-study")
    args = parser.parse_args()
    review, summary, drawing, worker, destination = (p.resolve() for p in (
        args.review, args.nominal_summary, args.drawing, args.worker_check, args.destination))
    if not all(p.is_relative_to(ROOT) for p in (review, summary, drawing, worker, destination)):
        parser.error("Use repository-owned sources and destination")
    if destination.exists():
        parser.error("Preserve checkpoints; choose a new destination for a revision")
    evidence = json.loads((review / "review.json").read_text())
    nominal = json.loads((summary / "summary.json").read_text())
    draw = json.loads((drawing / "drawing.json").read_text())
    guard = json.loads((worker / "report.json").read_text())
    cfg_path = ROOT / "engineering/designs/f1_feedback_screen.json"
    if draw["configuration_sha256"] != digest(cfg_path):
        raise ValueError("Drawing does not represent the current candidate")
    if evidence["source_sha256"]["nominal_screen"] != nominal["input_hashes"]["screen"]:
        raise ValueError("Nominal summary differs from evidence review")
    if not guard["passed"]:
        raise ValueError("Failure handling needs its completed/aborted controls")
    sources = {key: ROOT / path for key, path in evidence["source_locations"].items()}
    if digest(sources["nominal"] / "screen.json") != nominal["input_hashes"]["screen"]:
        raise ValueError("Nominal run changed")
    if digest(sources["crosscheck"] / "comparison.json") != evidence["source_sha256"]["crosscheck"]:
        raise ValueError("Cross-check run changed")
    current = json.loads(cfg_path.read_text())
    simulated = json.loads((sources["nominal"] / "inputs/f1_feedback_screen.json").read_text())
    comparison = copy.deepcopy(current)
    comparison["amplifier"]["part"] = simulated["amplifier"]["part"]
    comparison["amplifier"].pop("ordering_source", None)
    comparison["amplifier"].pop("ordering_note", None)
    if comparison != simulated:
        raise ValueError("Circuit changed beyond the documented ordering-code correction")
    with execution(ROOT / "build/records", "Archive F1 readout development evidence, preserving every declared nominal, sine and wire-break case and the incomplete hardware status") as record:
        destination.mkdir(parents=True, exist_ok=False)
        figures, checks, runs, circuits = (destination / name for name in ("visuals", "evidence", "runs", "circuits"))
        for path in (figures, checks, runs, circuits):
            path.mkdir()
        for source, prefix in ((review, "column_link_evidence"), (summary, "feedback_results"),
                              (drawing, "f1_feedback_topology")):
            for suffix in ("png", "svg", "pdf"):
                shutil.copyfile(source / f"{prefix}.{suffix}", figures / f"{prefix}.{suffix}")
        for source, target in (
            (review / "review.json", "evidence_review.json"),
            (summary / "summary.json", "nominal_summary.json"),
            (summary / "cases.csv", "nominal_cases.csv"),
            (sources["crosscheck"] / "comparison.json", "time_domain_crosscheck.json"),
            (worker / "report.json", "worker_failure_handling.json"),
            (drawing / "drawing.json", "drawing.json"),
        ):
            shutil.copyfile(source, checks / target)
        shutil.copyfile(cfg_path, destination / "candidate.json")
        shutil.copyfile(sources["nominal"] / "inputs/f1_feedback_screen.json", destination / "simulated_configuration.json")
        source_case = sources["nominal"] / "case_102"
        for name in ("case.json", "circuit.cir", "physical_transient.cir"):
            shutil.copyfile(source_case / name, circuits / name)
        archive_metadata = {}
        for label, path in sources.items():
            archive_metadata[label] = pack_run(path, runs / f"{label}.tar.gz", label)
        archive_metadata["worker_check"] = pack_run(worker, runs / "worker_check.tar.gz", "worker_check")
        (runs / "contents.json").write_text(json.dumps(archive_metadata, indent=2)+"\n")
        cfg = json.loads(cfg_path.read_text())
        components = [
            ("Amplifier", cfg["amplifier"]["part"], "1", "Selected-column current/sense feedback", cfg["amplifier"]["ordering_source"]),
            ("Current and sense muxes", "ADG706BRUZ", "2", "Share A0-A3; separate enables", cfg["column_multiplexers"]["source"]),
            ("Gain switches", "TMUX1112PWR", "1", "Four active-high switches; select one gain", cfg["gain_selection"]["source"]),
            ("Low-gain compensation switch", "TMUX1102DBVR", "1", "Active-low; SEL=GAIN0", cfg["low_gain_compensation"]["source"]),
            ("Active parking switch", "TMUX1101DBVR", "1", "Active-high; hardware pull-up", cfg["active_park_feedback"]["source"]),
            ("Main ADC candidate", "ADS8866IDGSR", "1", "Not included in the selected-column simulation", cfg["main_adc_candidate"]["source"]),
        ]
        with (destination / "active_components.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["function", "candidate_part", "quantity", "connection_or_limit", "manufacturer_source"])
            writer.writerows(components)
        template = ROOT / "engineering/docs/F1_READOUT_STUDY.md"
        (destination / "README.md").write_text(template.read_text().replace("../development/f1/readout-study/", ""))
        checkpoint = {
            "schema": "yam-f1-readout-study-checkpoint/1",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Selected-column circuit study with unresolved cross-checks; no complete wrist PCB or integrated F1",
            "physical_specimens_tested": 0, "integrated_f1_complete": False,
            "nominal": evidence["nominal"],
            "time_domain_crosscheck": evidence["time_domain_crosscheck"],
            "wire_break_status_counts": evidence["wire_break_study"]["status_counts"],
            "source_locations": {"review": str(review.relative_to(ROOT)), "summary": str(summary.relative_to(ROOT)),
                                 "drawing": str(drawing.relative_to(ROOT)), "worker": str(worker.relative_to(ROOT))},
            "archiver_sha256": digest(Path(__file__)),
            "files_sha256": {str(p.relative_to(destination)): digest(p) for p in sorted(destination.rglob("*")) if p.is_file()},
        }
        (destination / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2)+"\n")
        record["checkpoint"] = {"directory": str(destination.relative_to(ROOT)),
                                "files": len(checkpoint["files_sha256"]),
                                "archive_bytes": {k: v["bytes"] for k, v in archive_metadata.items()},
                                "sha256": digest(destination / "checkpoint.json")}
        print(json.dumps(record["checkpoint"], indent=2))


if __name__ == "__main__":
    main()
