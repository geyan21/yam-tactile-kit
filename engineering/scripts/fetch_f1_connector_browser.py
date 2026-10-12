#!/usr/bin/python3
"""Try the public FH12 download in an isolated, bounded ordinary browser session."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

PRODUCT = "https://www.hirose.com/en/product/p/CL0528-0030-8-98"
DOWNLOAD = PRODUCT+"/documents?path=%2Fapi%2Fv1%2Fproducts%2FCL0528-0030-8-98%2Fdocuments%2Fmodel_3d_step%2Fcontent"


def main():
    folder = ROOT / "build/engineering/prototypes/f1/connector_browser_sources" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Try only the official public FH12 product page and its offered STEP link in a fresh browser profile; do not log in, solve challenges or disable security checks") as record:
        folder.mkdir(parents=True)
        downloads = folder / "downloads"; downloads.mkdir()
        profile = folder / "profile"; (profile / "Default").mkdir(parents=True)
        (profile / "Default/Preferences").write_text(json.dumps({
            "download": {"default_directory": str(downloads), "prompt_for_download": False, "directory_upgrade": True},
            "safebrowsing": {"enabled": True}
        })+"\n")
        record["commands"] = []; record["run_directory"] = str(folder.relative_to(ROOT))
        for name, url, budget in (("product", PRODUCT, 3000), ("download", DOWNLOAD, 15000)):
            command = ["/usr/bin/google-chrome-stable", "--headless", "--disable-background-networking",
                       "--no-first-run", "--no-default-browser-check",
                       "--user-data-dir="+str(profile), "--virtual-time-budget="+str(budget), "--dump-dom", url]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            item = {"argv": command, "pid": process.pid}; record["commands"].append(item)
            try:
                stdout, stderr = process.communicate(timeout=45)
            except subprocess.TimeoutExpired:
                record["intentional_stop_requests"].append(f"Stop owned browser {process.pid}: 45 second public-source bound")
                process.kill(); stdout, stderr = process.communicate()
                item["timed_out"] = True
            (folder / (name+".html")).write_text(stdout)
            (folder / (name+".stderr.txt")).write_text(stderr)
            item["exit_code"] = process.returncode
            print("Finished public source attempt: "+name, flush=True)
            # A challenge or sign-in remains a stopping condition for this
            # source attempt, not permission to work around access controls.
            if any(marker in stdout.lower() for marker in ("verify you are human", "captcha", "access denied")):
                item["challenge_detected"] = True
                break
        files = []
        archives = [p for p in downloads.iterdir() if p.is_file() and p.suffix.lower() == ".zip"]
        for archive_path in archives:
            if archive_path.stat().st_size > 10*1024*1024:
                raise ValueError("Unexpectedly large source archive")
            with zipfile.ZipFile(archive_path) as archive:
                if len(archive.infolist()) > 100 or sum(i.file_size for i in archive.infolist()) > 32*1024*1024:
                    raise ValueError("Unexpected source archive contents")
                for item in archive.infolist():
                    path = PurePosixPath(item.filename.replace("\\", "/"))
                    if path.is_absolute() or ".." in path.parts:
                        raise ValueError("Unsafe vendor archive path")
                    if item.is_dir() or path.suffix.lower() not in (".stp", ".step"):
                        continue
                    content = archive.read(item)
                    if not content.lstrip().startswith(b"ISO-10303-21"):
                        raise ValueError("Invalid STEP header")
                    target = folder / "cad" / Path(*path.parts)
                    target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
                    files.append({"path": str(target.relative_to(ROOT)), "sha256": hashlib.sha256(content).hexdigest(),
                                  "bytes": len(content)})
        report = {"product_url": PRODUCT, "requested_download_url": DOWNLOAD,
                  "step_files": files, "download_succeeded": bool(files),
                  "physical_evidence": False, "source_images_and_vendor_geometry_for_working_review_only": True}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))
        if not files:
            raise RuntimeError("The public browser attempt did not yield a validated STEP file; preserve this result")


if __name__ == "__main__":
    main()
