"""Build a static, offline site and a bounded source archive from this kit only."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import shutil
import zipfile

from .calibration import fit_and_evaluate, read_samples
from .model import evaluate, validate
from .render import concept_svg, guide_content


SOURCE_DIRS = ("docs", "examples", "hardware", "scripts", "src", "tests", "web", ".github")
SOURCE_FILES = ("README.md", "VERSION", ".gitignore")


def encoded_json(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def source_files(root: Path) -> dict[str, bytes]:
    result = {}
    for name in SOURCE_FILES:
        result[name] = (root / name).read_bytes()
    for directory in SOURCE_DIRS:
        for path in sorted((root / directory).rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Refusing a symlink in exported source: {path.relative_to(root)}")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def archive_source(root: Path, downloads: Path, design: dict, calibration: bytes, repository_url: str) -> dict:
    files = source_files(root)
    files["reproduction/design.json"] = encoded_json(design)
    files["reproduction/calibration.csv"] = calibration
    files["reproduction/build.json"] = encoded_json({"repository_url": repository_url})
    manifest = {
        "schema_version": 1,
        "version": (root / "VERSION").read_text().strip(),
        "scope": "Only the kit source and the current build inputs; generated outputs and runtime logs excluded.",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
    }
    archive = downloads / "yam-tactile-kit.zip"
    downloads.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, data in sorted({**files, "SOURCE_MANIFEST.json": encoded_json(manifest)}.items()):
            entry = zipfile.ZipInfo(f"yam-tactile-kit/{name}", date_time=(2026, 10, 10, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            bundle.writestr(entry, data)
    (downloads / "source-manifest.json").write_bytes(encoded_json(manifest))
    return {
        "source_files": len(files),
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "archive_bytes": archive.stat().st_size,
    }


def build(root: Path, output: Path, design_path: Path, calibration_path: Path, repository_url: str = "") -> dict:
    if repository_url and not repository_url.startswith("https://github.com/"):
        raise ValueError("repository_url must be empty or an https://github.com/ URL")
    design = validate(json.loads(design_path.read_text(encoding="utf-8")))
    summary = evaluate(design)
    calibration = fit_and_evaluate(read_samples(calibration_path))
    calibration["input_sha256"] = hashlib.sha256(calibration_path.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    site = output / "site"
    assets = site / "assets"
    downloads = site / "downloads"
    assets.mkdir(parents=True, exist_ok=True)
    downloads.mkdir(parents=True, exist_ok=True)
    for name in ("style.css", "model.js", "app.js"):
        shutil.copyfile(root / "web" / name, assets / name)
    for name, content in (("design-summary.json", summary), ("calibration-report.json", calibration)):
        (output / name).write_bytes(encoded_json(content))
        (downloads / name).write_bytes(encoded_json(content))
    svg = concept_svg(design, summary)
    (output / "finger-concept.svg").write_text(svg, encoding="utf-8")
    (downloads / "finger-concept.svg").write_text(svg, encoding="utf-8")
    shutil.copyfile(root / "docs/yam_force_finger_concept.svg", assets / "original-concept.svg")
    shutil.copyfile(root / "hardware/bom.csv", downloads / "bom.csv")
    shutil.copyfile(root / "hardware/measurements.template.json", downloads / "measurements.template.json")
    shutil.copyfile(root / "hardware/data-contract.example.json", downloads / "data-contract.example.json")
    (downloads / "build-design.json").write_bytes(encoded_json(design))
    (downloads / "calibration-input.csv").write_bytes(calibration_path.read_bytes())
    artifact = archive_source(root, downloads, design, calibration_path.read_bytes(), repository_url)
    references = json.loads((root / "web/references.json").read_text(encoding="utf-8"))
    data = {
        "version": (root / "VERSION").read_text().strip(),
        "design": design,
        "summary": summary,
        "calibration": calibration,
        "references": references,
        "repository_url": repository_url,
        "archive": artifact,
    }
    javascript = "window.TACTILE_KIT_DATA = " + json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c") + ";\n"
    (assets / "data.js").write_text(javascript, encoding="utf-8")
    for name in ("index.html", "guide.html"):
        content = (root / "web" / name).read_text(encoding="utf-8")
        if name == "guide.html":
            sections, navigation = guide_content(root)
            content = content.replace("<!-- GUIDE_CONTENT -->", sections).replace("<!-- GUIDE_NAV -->", navigation)
        content = content.replace("{{VERSION}}", html.escape(data["version"]))
        (site / name).write_text(content, encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    site_archive = output / "yam-tactile-site.zip"
    with zipfile.ZipFile(site_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(site.rglob("*")):
            if path.is_file():
                entry = zipfile.ZipInfo(
                    "yam-tactile-site/" + path.relative_to(site).as_posix(),
                    date_time=(2026, 10, 10, 0, 0, 0),
                )
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                bundle.writestr(entry, path.read_bytes())
    receipt = {
        "schema_version": 1,
        "version": data["version"],
        "geometry_status": design["geometry_status"],
        "calibration_data_kind": calibration["dataset_kind"],
        "hardware_validated": False,
        "site_archive_sha256": hashlib.sha256(site_archive.read_bytes()).hexdigest(),
        **artifact,
    }
    (output / "build-receipt.json").write_bytes(encoded_json(receipt))
    return receipt
