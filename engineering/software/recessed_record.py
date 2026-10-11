#!/usr/bin/python3
"""Record B3 raw magnetic and nail observations without controlling the robot."""

from pathlib import Path
import sys
from raw_capture import run
from recessed_protocol import PROTOCOL, decode

ROOT = Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    try:
        run("recessed", PROTOCOL, decode,
            ROOT / "engineering/prototypes/recessed/recessed_manifest.json")
    except KeyboardInterrupt:
        print("Operator stopped B3 capture; raw data and incomplete receipt are retained.",
              file=sys.stderr)
        raise SystemExit(130)
