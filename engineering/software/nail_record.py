#!/usr/bin/python3
"""Record N1 nail bridges and four TPU cells, preserving each acquisition interval."""

from pathlib import Path
import sys
from raw_capture import run
from nail_protocol import PROTOCOL,decode

ROOT=Path(__file__).resolve().parents[2]


if __name__=="__main__":
    try:
        run("nail",PROTOCOL,decode,ROOT/"engineering/prototypes/nail/nail_manifest.json")
    except KeyboardInterrupt:
        print("Operator stopped N1 capture; raw data and its incomplete receipt are retained.",file=sys.stderr)
        raise SystemExit(130)
