#!/usr/bin/python3
"""Run the complete test discovery and expose failure details as CI annotations."""

import argparse
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from tactile_kit.records import execution


def escape(value):
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="test_*.py", help="Local focused runs may select a pattern; CI uses complete discovery")
    args = parser.parse_args()
    with execution(ROOT/"build/records", "Run the discovered software and clean-source tests; retain failure exit status and publish bounded traceback annotations for diagnosis") as record:
        suite = unittest.defaultTestLoader.discover(str(ROOT/"engineering/tests"), pattern=args.pattern)
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
        for test, traceback in result.failures+result.errors:
            title = escape(test.id()).replace(",", "%2C").replace(":", "%3A")
            print("::error title="+title+"::"+escape(traceback[-8000:]), flush=True)
        if result.testsRun == 0:
            print("::error title=Empty test discovery::No tests were executed.", flush=True)
        record["result"] = {"tests_run": result.testsRun, "failures": len(result.failures),
                            "errors": len(result.errors), "skipped": len(result.skipped),
                            "passed": result.testsRun > 0 and result.wasSuccessful()}
        return 0 if record["result"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
