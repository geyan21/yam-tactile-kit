#!/usr/bin/python3
"""Make searchable text and passive CAD references from the selected working cache."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--pdf")
    parser.add_argument("--page", type=int)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--crop", nargs=4, type=float)
    args = parser.parse_args()
    source = args.folder.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/force_button/sources"):
        parser.error("Select an owned Honeywell source-cache directory")
    if bool(args.pdf) != bool(args.page) or args.page is not None and not 1 <= args.page <= 40:
        parser.error("Select a PDF filename and page 1..40 together")
    if not 100 <= args.dpi <= 400 or args.crop and (not args.pdf or not all(0 <= v <= 1 for v in args.crop)):
        parser.error("Use 100..400 dpi and optional crop fractions within a selected page")
    collection = json.loads((source / "collection.json").read_text())
    output = source / "reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Extract searchable manufacturer text and passive STEP references from the selected FMA cache; preserve original documents and do not execute package content") as record:
        output.mkdir(parents=True, exist_ok=False)
        record["commands"] = []
        for document in collection["documents"]:
            path = source / document["file"]
            if digest(path) != document["sha256"]:
                raise ValueError("Source document changed")
            if path.suffix == ".pdf":
                command = ["/usr/bin/pdftotext", "-layout", str(path), str(output / (path.stem+".txt"))]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                row = {"command": command, "pid": process.pid}; record["commands"].append(row)
                try:
                    stdout, stderr = process.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    record["intentional_stop_requests"].append(f"Stop owned PDF-text process {process.pid}: 30 second bound")
                    process.kill(); process.communicate(); raise
                row.update({"exit_code": process.returncode, "stderr": stderr[-1000:]})
                if process.returncode:
                    raise RuntimeError("PDF text extraction failed")
            elif path.suffix == ".zip":
                with zipfile.ZipFile(path) as archive:
                    entries = archive.infolist()
                    if len(entries) > 100 or sum(e.file_size for e in entries) > 32*1024*1024:
                        raise ValueError("Unexpected CAD archive size")
                    index = []
                    for item in entries:
                        relative = PurePosixPath(item.filename.replace("\\", "/"))
                        if relative.is_absolute() or ".." in relative.parts:
                            raise ValueError("Unsafe CAD archive path")
                        index.append({"name": item.filename, "bytes": item.file_size})
                        if relative.suffix.lower() in (".stp", ".step", ".igs", ".iges") and not item.is_dir():
                            target = output / "cad" / Path(*relative.parts)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(item) as reader, target.open("wb") as writer:
                                shutil.copyfileobj(reader, writer)
                    (output / (path.stem+"_index.json")).write_text(json.dumps(index, indent=2)+"\n")
        if args.pdf:
            pdf = source / args.pdf
            if pdf not in [source / d["file"] for d in collection["documents"]] or pdf.suffix != ".pdf":
                parser.error("Select one of this cache's PDFs")
            command = ["/usr/bin/pdftoppm", "-f", str(args.page), "-singlefile", "-r", str(args.dpi), "-png",
                       str(pdf), str(output / ("page_"+str(args.page)))]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            row = {"command": command, "pid": process.pid}; record["commands"].append(row)
            try:
                _, stderr = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                record["intentional_stop_requests"].append(f"Stop owned PDF-render process {process.pid}: 30 second bound")
                process.kill(); process.communicate(); raise
            row.update({"exit_code": process.returncode, "stderr": stderr[-1000:]})
            if process.returncode:
                raise RuntimeError("PDF rendering failed")
            if args.crop:
                from PIL import Image
                image = Image.open(output / ("page_"+str(args.page)+".png"))
                image.crop(tuple(int(v*(image.width if i%2 == 0 else image.height)) for i, v in enumerate(args.crop))).save(output / "detail.png")
        result = {"directory": str(output.relative_to(ROOT)),
                  "files": {str(p.relative_to(output)): digest(p) for p in output.rglob("*") if p.is_file()}}
        (output / "review.json").write_text(json.dumps(result, indent=2)+"\n")
        record["result"] = result
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
