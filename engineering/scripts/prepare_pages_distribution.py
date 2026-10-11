#!/usr/bin/python3
"""Keep the offline packet complete and stage a smaller hosted Pages site."""

import argparse
import hashlib
import html
import json
from pathlib import Path
import posixpath
import re
import shutil
import sys
from urllib.parse import unquote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from check_site import verify_entries

REPOSITORY = "geyan21/yam-tactile-kit"
ARCHIVES = ("enpire-source.zip", "enpire-designs.zip", "enpire-site.zip", "enpire-engineering-kit.zip")
ALIASES = {
    "yam-tactile-complete.zip": "enpire-engineering-kit.zip",
    "yam-tactile-kit.zip": "enpire-source.zip",
    "yam-tactile-designs.zip": "enpire-designs.zip",
    "yam-tactile-site.zip": "enpire-site.zip",
}


def rewrite_html(content, relative, replacements):
    def replace(match):
        attribute, quote, raw = match.groups()
        url = urlsplit(html.unescape(raw))
        if url.scheme or url.netloc:
            return match.group(0)
        target = posixpath.normpath(str(relative.parent / unquote(url.path)))
        if target not in replacements:
            return match.group(0)
        full = urlsplit(replacements[target])
        destination = urlunsplit((full.scheme, full.netloc, full.path, url.query, url.fragment))
        return attribute+"="+quote+html.escape(destination, quote=True)+quote
    return re.sub(r'''(href|src)=(["'])(.*?)\2''', replace, content, flags=re.DOTALL)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            result.update(chunk)
    return result.hexdigest()


def prepare(site, hosted, downloads, commit, maximum_bytes=950_000_000, source_root=ROOT):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Use the full immutable Git commit SHA")
    if hosted.exists() or downloads.exists():
        raise ValueError("Preserve staged outputs; use a fresh destination")
    tag = "kit-"+commit[:12]
    base = f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    hosted.mkdir(parents=True)
    downloads.mkdir(parents=True)
    assets = {}
    for name in ARCHIVES:
        source = site / "downloads" / name
        if not source.is_file():
            raise ValueError(f"Build and verify the complete offline packet first: {name}")
        shutil.copyfile(source, downloads / name)
        assets[name] = {"sha256": digest(source), "bytes": source.stat().st_size, "url": base+name}
    packet_names = {name: name for name in ARCHIVES} | ALIASES
    replacements = {"downloads/"+name: base+target for name, target in packet_names.items()}
    # Development and prototype CAD remain available at this exact commit.
    # Keep the interactive JSON, figures and offline downloads local. This
    # avoids serving the same large CAD solids twice on the bounded Pages site.
    offloaded = {}
    for site_prefix, repository_prefix in (
            ("assets/development", "engineering/development"),
            ("assets/prototypes", "engineering/prototypes"),
            ("downloads/prototypes", "engineering/prototypes")):
        source_folder = site / site_prefix
        for path in sorted(source_folder.rglob("*")) if source_folder.is_dir() else []:
            if not path.is_file() or path.suffix.lower() not in (".step", ".stp", ".stl"):
                continue
            relative = path.relative_to(site)
            source_relative = Path(repository_prefix) / path.relative_to(source_folder)
            source = source_root / source_relative
            if not source.is_file() or digest(path) != digest(source):
                raise ValueError("CAD must match its immutable repository source: "+str(relative))
            url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{source_relative.as_posix()}"
            replacements[relative.as_posix()] = url
            offloaded[relative.as_posix()] = {"source": source_relative.as_posix(), "url": url,
                                             "bytes": path.stat().st_size, "sha256": digest(path)}
    for path in sorted(site.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(site)
        if relative.as_posix() in replacements:
            continue
        target = hosted / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".html":
            target.write_text(rewrite_html(path.read_text(), relative, replacements))
        elif relative == Path("assets/data.js"):
            # The main page creates its CAD table in JavaScript. Give that
            # code the same immutable URLs used by the static design pages.
            mapping = json.dumps(replacements, separators=(",", ":")).replace("</", "<\\/")
            target.write_text(path.read_text()+"\nwindow.KIT_HOSTED_LINKS="+mapping+";\n")
        elif relative == Path("assets/design-catalog.json"):
            content = path.read_text()
            for old, new in replacements.items():
                content = content.replace('"'+old+'"', '"'+new+'"')
            target.write_text(content)
        else:
            shutil.copyfile(path, target)
    checksum_path = downloads / "SHA256SUMS.txt"
    checksum_path.write_text("".join(f"{assets[name]['sha256']}  {name}\n" for name in ARCHIVES))
    assets[checksum_path.name] = {"sha256": digest(checksum_path), "bytes": checksum_path.stat().st_size,
                                "url": base+checksum_path.name}
    entries = {str(p.relative_to(hosted)): p.read_bytes() for p in hosted.rglob("*") if p.is_file()}
    links = verify_entries(entries)
    size = sum(len(content) for content in entries.values())
    if size > maximum_bytes:
        raise ValueError(f"Hosted site exceeds the {maximum_bytes} byte staging bound: {size}")
    notes = (
        f"Reproducible engineering packet from `{commit}`.\n\n"
        "The current digital prototype packages and separately labeled development modules are included. "
        "No physical specimens, measured winner, or 20 N hardware qualification are claimed.\n\n"
        "- `enpire-engineering-kit.zip`: complete source and offline visual website.\n"
        "- `enpire-source.zip`: editable source, CAD, electronics, code, documents and evidence.\n"
        "- `enpire-designs.zip`: design artifacts and checked development modules.\n"
        "- `enpire-site.zip`: offline website and its local downloads.\n"
        "- `SHA256SUMS.txt`: SHA-256 checksums for all four packets.\n\n"
        "The current visual guide is at https://geyan21.github.io/yam-tactile-kit/ . "
        "Large packet links on that guide point to these versioned assets. "
        "Development and prototype STEP/STL links point to immutable files at this repository commit. "
        "The downloadable website retains local links for offline use.\n"
    )
    (downloads / "release-notes.md").write_text(notes)
    manifest = {"schema": "yam-pages-distribution/1", "repository": REPOSITORY, "commit": commit,
                "release_tag": tag, "release_title": "Engineering kit "+commit[:12],
                "assets": assets, "hosted_bytes": size, "hosted_local_links_checked": links,
                "offloaded_repository_cad": offloaded,
                "offloaded_repository_bytes": sum(item["bytes"] for item in offloaded.values()),
                "offline_site_unchanged": True, "physical_specimens_tested": 0}
    (downloads / "distribution.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--site", type=Path, default=ROOT / "build/site")
    parser.add_argument("--hosted", type=Path, default=ROOT / "build/pages-site")
    parser.add_argument("--downloads", type=Path, default=ROOT / "build/download-distribution")
    args = parser.parse_args()
    paths = [p.resolve() for p in (args.site, args.hosted, args.downloads)]
    if not all(p.is_relative_to(ROOT / "build") for p in paths):
        parser.error("Use generated directories under this repository's build folder")
    with execution(ROOT / "build/records", "Stage a size-checked Pages website and immutable GitHub Release packet assets without changing the verified offline package") as record:
        result = prepare(*paths, args.commit)
        record["result"] = result
        print(json.dumps({"release_tag": result["release_tag"], "hosted_bytes": result["hosted_bytes"],
                          "local_links_checked": result["hosted_local_links_checked"],
                          "assets": {name: item["bytes"] for name, item in result["assets"].items()}}, indent=2))


if __name__ == "__main__":
    main()
