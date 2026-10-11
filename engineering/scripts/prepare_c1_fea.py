#!/usr/bin/python3
"""Obtain scoped official structural tools inside the kit's generated tool cache."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from urllib.request import Request, urlopen
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution

TOOLS = ROOT/"build/engineering/tools/fea"
DOWNLOADS = {
    "ccx_2.23.tar.bz2":"https://www.dhondt.de/ccx_2.23.tar.bz2",
    "gmsh-4.15.2-Linux64-sdk.tgz":"https://gmsh.info/bin/Linux/gmsh-4.15.2-Linux64-sdk.tgz",
    "libgfortran4_7.5.0-3ubuntu1~18.04_amd64.deb":"https://archive.ubuntu.com/ubuntu/pool/main/g/gcc-7/libgfortran4_7.5.0-3ubuntu1~18.04_amd64.deb",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url,path):
    if path.exists():
        return
    request = Request(url,headers={"User-Agent":"yam-tactile-structural-tools"})
    temporary = path.with_suffix(path.suffix+".partial")
    total = 0
    with urlopen(request,timeout=30) as response, temporary.open("wb") as stream:
        while block := response.read(1024*1024):
            total += len(block)
            if total > 180*1024*1024:
                raise ValueError("Official tool archive exceeds the scoped size limit")
            stream.write(block)
    temporary.replace(path)


def extract(archive,destination):
    destination.mkdir(parents=True,exist_ok=True)
    destination = destination.resolve()
    with tarfile.open(archive) as source:
        members = source.getmembers()
        for member in members:
            target = (destination/member.name).resolve()
            if not target.is_relative_to(destination):
                raise ValueError("Archive path escapes its isolated destination")
            if member.issym():
                linked = (target.parent/member.linkname).resolve()
                if not linked.is_relative_to(destination):
                    raise ValueError("Archive symlink escapes its isolated destination")
            elif not (member.isdir() or member.isfile()):
                raise ValueError("Unexpected special archive member")
        for member in members:
            target = destination/member.name
            if member.isdir():
                target.mkdir(parents=True,exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True,exist_ok=True)
                with source.extractfile(member) as reader, target.open("wb") as writer:
                    shutil.copyfileobj(reader,writer)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
        for member in members:
            if member.issym():
                target = destination/member.name
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.is_symlink():
                    target.unlink()
                elif target.exists():
                    raise ValueError("Refusing to replace a regular file with an archive symlink")
                target.symlink_to(member.linkname)


def main():
    TOOLS.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Cache official CalculiX and Gmsh tools locally for C1 structural checks; no system install or robot connection") as record:
        rows = []
        for name,url in DOWNLOADS.items():
            archive = TOOLS/name
            download(url,archive)
            if name.endswith(".deb"):
                folder = TOOLS/"runtime"
                folder.mkdir(exist_ok=True)
                argv = ["/usr/bin/dpkg-deb","--extract",str(archive),str(folder)]
                process = subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                stdout,stderr = process.communicate(timeout=30)
                record.setdefault("commands",[]).append({"argv":argv,"pid":process.pid,
                    "returncode":process.returncode,"stdout":stdout[-1000:],"stderr":stderr[-1000:]})
                if process.returncode:
                    raise RuntimeError("Local runtime extraction failed: "+stderr)
            else:
                folder = TOOLS/("calculix" if name.startswith("ccx") else "gmsh")
                extract(archive,folder)
            rows.append({"url":url,"archive":name,"sha256":digest(archive),"bytes":archive.stat().st_size})
        solvers = [p for p in (TOOLS/"calculix").rglob("*") if p.is_file() and p.name in ("ccx_2.23","ccx")]
        bindings = list((TOOLS/"gmsh").rglob("gmsh.py"))
        if len(solvers)!=1 or len(bindings)!=1:
            raise ValueError(f"Unexpected tool layout: {len(solvers)} solvers, {len(bindings)} bindings")
        manifest = {"schema":"yam-structural-tools/1","downloads":rows,
                    "calculix":str(solvers[0].relative_to(ROOT)),
                    "gmsh_python_directory":str(bindings[0].parent.relative_to(ROOT)),
                    "runtime_library_directory":str((TOOLS/"runtime/usr/lib/x86_64-linux-gnu").relative_to(ROOT)),
                    "calculix_sha256":digest(solvers[0]),
                    "versions":{"calculix":"2.23","gmsh":"4.15.2"},
                    "note":"Official downloads, pinned versions and local content hashes. No physical sensor result."}
        (TOOLS/"tools.json").write_text(json.dumps(manifest,indent=2)+"\n")
        record["tools"] = manifest
        print(json.dumps(manifest,indent=2))


if __name__=="__main__":
    main()
