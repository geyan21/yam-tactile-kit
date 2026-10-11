#!/usr/bin/python3
"""Cache selected TI circuit-model archives for review; do not execute them."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

MODELS = {
    "opa392_pspice": "https://www.ti.com/lit/zip/SBOMBK2",
    "opa392_tina": "https://www.ti.com/lit/zip/SBOMBK3",
    "opa320_pspice": "https://www.ti.com/lit/zip/SBOM437",
}


def fetch(name, output):
    url = MODELS[name]
    with urlopen(Request(url, headers={"User-Agent": "yam-f1-analog-model-review"}), timeout=30) as response:
        final = urlsplit(response.url)
        if final.scheme != "https" or final.hostname != "www.ti.com":
            raise ValueError("Unexpected model-source redirect")
        content = response.read(4*1024*1024+1)
        final_url = response.url
    if len(content) > 4*1024*1024 or not content.startswith(b"PK"):
        raise ValueError("Expected the selected bounded ZIP model archive")
    folder = output / name
    folder.mkdir()
    (folder / "vendor_archive.zip").write_bytes(content)
    members = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if len(archive.infolist()) > 100 or sum(p.file_size for p in archive.infolist()) > 16*1024*1024:
            raise ValueError("Model archive exceeds the review limits")
        for member in archive.infolist():
            name_in_zip = PurePosixPath(member.filename.replace("\\", "/"))
            if name_in_zip.is_absolute() or ".." in name_in_zip.parts:
                raise ValueError("Unexpected archive member path")
            if member.is_dir():
                continue
            members.append({"name": member.filename, "bytes": member.file_size})
            # Only model/license/document text is extracted for review. Binary
            # editor project files remain inside the original unopened archive.
            if name_in_zip.suffix.lower() not in (".lib", ".cir", ".txt", ".mod", ".mdl"):
                continue
            data = archive.read(member)
            data.decode("utf-8", errors="strict")
            target = folder / Path(*name_in_zip.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    return {"model": name, "url": url, "final_url": final_url,
            "archive_sha256": hashlib.sha256(content).hexdigest(),
            "folder": str(folder.relative_to(ROOT)), "members": members,
            "executed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+", choices=sorted(MODELS))
    args = parser.parse_args()
    folder = ROOT / "build/engineering/prototypes/f1/model_sources" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Fetch explicitly selected official TI amplifier model archives and extract only bounded text for review") as record:
        folder.mkdir(parents=True, exist_ok=False)
        results = []; failures = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {name: pool.submit(fetch, name, folder) for name in dict.fromkeys(args.models)}
            for name, future in pending.items():
                try:
                    results.append(future.result())
                except Exception as error:
                    failures[name] = type(error).__name__+": "+str(error)
        receipt = {"models": results, "failures": failures,
                   "note": "Private model cache. Preserve original models; publish circuit sources, model provenance and numerical results separately."}
        (folder / "collection.json").write_text(json.dumps(receipt, indent=2)+"\n")
        record["collection"] = receipt
        print(json.dumps(receipt, indent=2))
        if failures:
            raise RuntimeError("Some selected model archives could not be read")


if __name__ == "__main__":
    main()
