#!/usr/bin/python3
"""Extract bounded readable passages from the two downloaded O1 supplier pages."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution
from fetch_optical_camera_sources import Text
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    args = parser.parse_args()
    source = args.sources.resolve()
    if not source.is_relative_to(ROOT/"build"):
        parser.error("Use the saved manufacturer references")
    folder = ROOT/"build/engineering/prototypes/optical/readout_reviews"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records", "Read limited supplier text about ADS1115 power/interface and silicone adhesive cure; keep this reference review separate from any physical test") as record:
        folder.mkdir(parents=True)
        result = {}
        for name, terms in (("adafruit1085", ("2V", "5.5", "16-bit", "860", "STEMMA", "pull")),
                            ("sil_poxy", ("24", "cure", "substrates", "plastic", "minute"))):
            path = source/(name+".html")
            parser = Text(); parser.feed(path.read_text())
            text = " ".join(parser.parts)
            excerpts = []
            for term in terms:
                match = re.search(re.escape(term), text, re.I)
                if match:
                    excerpts.append({"term": term, "text": text[max(0, match.start()-100):match.end()+350]})
            result[name] = {"source_sha256": digest(path), "excerpts": excerpts}
        (folder/"report.json").write_text(json.dumps(result, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "sources": result}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
