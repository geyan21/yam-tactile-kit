#!/usr/bin/python3
"""Prepare a reviewable solid basis for the separate nail and recessed-frame designs."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"] = str(ROOT/"build/engineering/tools/cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

from source_brep import convert
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part",choices=("hard_frame","soft_insert"),required=True)
    args = parser.parse_args()
    with execution(ROOT/"build/records","Recover a checked faceted source solid for explicit frame revisions; preserve the original STL and all released designs") as record:
        report = convert(args.part)
        record["conversion"] = report
        print(json.dumps({key:report[key] for key in ("part","source_triangles","solid_faces","volume_difference_mm3","checks")},indent=2))


if __name__=="__main__":
    main()
