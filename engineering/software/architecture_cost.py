#!/usr/bin/python3
"""Evaluate operator-supplied assembly quotes; never invent prices or production yield."""

import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from architecture_math import batch_cost
from tactile_kit.records import execution


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    data=json.loads(args.input.read_text())
    if data.get("schema")!="yam-architecture-quotes/1":parser.error("Unsupported quote schema")
    keys=("unit_parts","yield_fraction","labor_minutes","hourly_rate","fixed_setup","calibration_minutes")
    missing=[f"{option.get('design','unknown')}:{key}" for option in data["options"] for key in keys if option.get(key) is None]
    if missing:parser.error("Supply actual quote/timing assumptions first: "+", ".join(missing))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with execution(args.output.parent/"execution","Calculate costs from declared quotes and timing assumptions, including calibration and rejects") as record:
        rows=[]
        for option in data["options"]:
            for quantity in data["requested_good_units"]:
                if isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<1:
                    raise ValueError("Requested unit quantities must be positive integers")
                rows.append({"design":option["design"],**batch_cost(quantity,**{key:option[key] for key in keys})})
        result={"evidence_kind":"cost_model","currency":data["currency"],"inputs":data,"estimates":rows,
                "limits":"Yield is an assumption and unit count is a planning estimate, not a delivery guarantee. Use separate inputs for quantity-dependent quotations."}
        with args.output.open("x") as stream:json.dump(result,stream,indent=2);stream.write("\n")
        record["estimates"]=len(rows)
        print(json.dumps(rows,indent=2))


if __name__=="__main__":main()
