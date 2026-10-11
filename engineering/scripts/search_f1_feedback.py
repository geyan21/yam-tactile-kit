#!/usr/bin/python3
"""Compare explicit F1 compensation candidates without changing circuit goals."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import CONFIG, make_case, save_case, run_case, analyze, digest


def create_case(folder, cfg, model, transient):
    g, load = (3, 25) if transient else (0, 250000)
    capacitance, scale = 3, 2
    deck, case = make_case(cfg, model, g, load, capacitance, scale, transient)
    folder.mkdir()
    return save_case(folder, deck, case)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    args = parser.parse_args()
    model = args.model.resolve()
    base = json.loads(CONFIG.read_text())
    folder = ROOT / "build/engineering/prototypes/f1/compensation_searches" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Compare F1 compensation values against both limiting stability and strong-load settling requirements") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        for path in (Path(__file__), CONFIG, ROOT / "engineering/scripts/screen_f1_feedback.py",
                     ROOT / "engineering/scripts/run_f1_spice_case.py", ROOT / "engineering/scripts/f1_spice.py",
                     ROOT / "engineering/scripts/check_f1_opa_model.py"):
            shutil.copyfile(path, inputs / path.name)
        candidates = []
        for index, (rin, riso, cpark, cf0) in enumerate(itertools.product(
                (50, 100, 200, 300), (.1, 10, 47), (10, 15), (470, 1000))):
            cfg = copy.deepcopy(base)
            cfg["sense_input_resistance_ohm"] = rin
            cfg["output_isolation_ohm"] = riso
            cfg["local_park_feedback"]["capacitance_pf"] = cpark
            cfg["gain_selection"]["branches"][0]["feedback_capacitance_pf"] = cf0
            root = folder / f"candidate_{index:03d}"
            root.mkdir()
            (root / "configuration.json").write_text(json.dumps(cfg, indent=2)+"\n")
            case = create_case(root / "stability", cfg, model, False)
            candidates.append({"id": index, "root": root, "configuration": cfg, "case": case,
                               "values": {"rin_ohm": rin, "riso_ohm": riso, "park_pf": cpark, "gain0_cf_pf": cf0}})
        record["workers"] = []
        stable = []; all_results = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {pool.submit(run_case, c["root"] / "stability"): c for c in candidates}
            for future in as_completed(pending):
                c = pending[future]
                receipt, error = future.result(); record["workers"].append(receipt)
                row = {"id": c["id"], **c["values"]}
                if error:
                    row["worker_error"] = error
                else:
                    result = analyze(c["case"], c["root"] / "stability", c["configuration"])
                    row["stability"] = result
                    if result["passed"]:
                        stable.append(c)
                all_results.append(row)
        print(f"Completed {len(candidates)} stability candidates; {len(stable)} meet the declared margin", flush=True)
        by_id = {r["id"]: r for r in all_results}
        # Only candidates meeting the same stability criterion advance.
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {}
            for c in stable:
                case = create_case(c["root"] / "settling", c["configuration"], model, True)
                pending[pool.submit(run_case, c["root"] / "settling")] = (c, case)
            for future in as_completed(pending):
                c, case = pending[future]
                receipt, error = future.result(); record["workers"].append(receipt)
                row = by_id[c["id"]]
                if error:
                    row["settling_worker_error"] = error
                else:
                    row["settling"] = analyze(case, c["root"] / "settling", c["configuration"])
                    row["both_limiting_screens_passed"] = row["settling"]["passed"]
                print(json.dumps({"id": c["id"], "both_passed": row.get("both_limiting_screens_passed", False)}), flush=True)
        accepted = [r for r in all_results if r.get("both_limiting_screens_passed")]
        report = {"schema": "yam-f1-compensation-search/1", "physical_evidence": False,
                  "status": "Candidate comparison; full parameter grid and hardware checks still required",
                  "base_configuration_sha256": digest(CONFIG), "vendor_model_sha256": digest(model),
                  "results": sorted(all_results, key=lambda r: r["id"]), "accepted_candidate_ids": [r["id"] for r in accepted]}
        (folder / "search.json").write_text(json.dumps(report, indent=2)+"\n")
        record["summary"] = {"candidates": len(candidates), "stable": len(stable), "accepted": len(accepted)}
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), **record["summary"]}, indent=2))


if __name__ == "__main__":
    main()
