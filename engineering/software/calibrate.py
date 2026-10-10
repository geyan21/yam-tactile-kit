#!/usr/bin/python3
"""Fit monotonic single-cell calibration; hold complete load cycles out of training."""

from __future__ import annotations

import argparse
from bisect import bisect_right
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution


def isotonic_knots(points):
    """Pool adjacent violating blocks; repeated conductance gets one weighted target."""
    grouped = {}
    for conductance,force in points:
        if not math.isfinite(conductance) or not math.isfinite(force) or conductance < 0 or force < 0:
            raise ValueError("Invalid calibration point")
        grouped.setdefault(conductance,[]).append(force)
    xs=sorted(grouped)
    if len(xs)<3:
        raise ValueError("Need at least three distinct conductance values")
    blocks=[]
    for index,x in enumerate(xs):
        values=grouped[x]
        blocks.append([index,index,sum(values),len(values)])
        while len(blocks)>1 and blocks[-2][2]/blocks[-2][3] > blocks[-1][2]/blocks[-1][3]:
            last=blocks.pop();previous=blocks.pop()
            blocks.append([previous[0],last[1],previous[2]+last[2],previous[3]+last[3]])
    ys=[0.0]*len(xs)
    for first,last,total,count in blocks:
        for index in range(first,last+1):
            ys[index]=total/count
    if max(ys)-min(ys)<.1:
        raise ValueError("Calibration has no useful monotonic force range")
    return list(zip(xs,ys))


def predict(knots,value,guard_us=0.0):
    """Permit only a declared signal guard band; never clamp the upper force."""
    if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):
        return None
    if not math.isfinite(guard_us) or guard_us<0:
        return None
    if value < knots[0][0]-guard_us or value > knots[-1][0]+guard_us:
        return None
    if value < knots[0][0]:
        index=1
        while index<len(knots)-1 and knots[index][1]==knots[0][1]:
            index+=1
        x0,y0=knots[0];x1,y1=knots[index]
        return max(0.0,y0+(value-x0)*(y1-y0)/(x1-x0))
    if value > knots[-1][0]:
        index=len(knots)-2
        while index>0 and knots[index][1]==knots[-1][1]:
            index-=1
        x0,y0=knots[index];x1,y1=knots[-1]
        return y1+(value-x1)*(y1-y0)/(x1-x0)
    index=bisect_right([item[0] for item in knots],value)-1
    if index==len(knots)-1:
        return knots[-1][1]
    x0,y0=knots[index];x1,y1=knots[index+1]
    return y0+(value-x0)*(y1-y0)/(x1-x0)


def analyze(rows):
    if not rows:
        raise ValueError("No trials supplied")
    if any(row.get("evidence_kind")!="physical" for row in rows):
        raise ValueError("This report requires physical trial records; synthetic tests are kept separate")
    specimens={row["specimen"] for row in rows}
    if len(specimens)!=1:
        raise ValueError("Calibrate one identified specimen at a time; cross-unit transfer is a separate experiment")
    ids=[row["trial_id"] for row in rows]
    if len(set(ids))!=len(ids):
        raise ValueError("Duplicate trial identifiers")
    reports=[]
    for channel in range(6):
        selected=[row for row in rows if row.get("valid") is True and row["channel"]==channel]
        train=[row for row in selected if row["split"]=="train"]
        test=[row for row in selected if row["split"]=="test"]
        train_groups={row["group"] for row in train}; test_groups={row["group"] for row in test}
        if train_groups & test_groups:
            raise ValueError(f"CH{channel}: load-cycle leakage between train and test")
        if len(train_groups)<2 or len(test_groups)<1:
            reports.append({"channel":channel,"status":"insufficient complete groups"})
            continue
        # A group is a full loading/unloading cycle, not a convenient subset.
        ranges={row.get("range_n") for row in selected}
        if len(ranges)!=1 or not ranges.issubset({5,20}):
            raise ValueError("Mixed or missing force-range settings")
        maximum_n=next(iter(ranges))
        configurations={tuple(row.get("pull_down_ohm",[])) for row in selected}
        if len(configurations)!=1 or any(len(value)!=6 for value in configurations):
            raise ValueError("Mixed or missing pull-down resistor configuration")
        if any(row.get("continuity_ohm")!=100000 for row in selected):
            raise ValueError("Missing or mixed continuity-resistor configuration")
        probes={row.get("probe","unspecified test fixture") for row in selected}
        materials={row.get("material","unspecified test fixture") for row in selected}
        if len(probes)!=1 or len(materials)!=1:
            raise ValueError("Mixed probe or material configurations; analyze the defined condition separately")
        expected=([0,.2,.5,1,2,5,2,1,.5,.2,0] if maximum_n==5 else
              [0,.2,.5,1,2,5,10,15,20,15,10,5,2,1,.5,.2,0])
        complete=True
        for group in train_groups | test_groups:
            group_rows=sorted((row for row in selected if row["group"]==group),key=lambda row:row["trial_id"])
            if len(group_rows)!=len(expected) or [row.get("target_n") for row in group_rows]!=expected:
                complete=False
        if not complete:
            reports.append({"channel":channel,"status":"incomplete or rejected load-cycle trials"})
            continue
        if any(not math.isfinite(row["reference_uncertainty_n"]) or not 0 < row["reference_uncertainty_n"] <= .05 for row in selected):
            raise ValueError("Reference uncertainty missing or exceeds the pilot protocol")
        if any(not math.isfinite(row["reference_n"]) or row["reference_n"]<0 or not math.isfinite(row["conductance_us"]) for row in selected):
            raise ValueError("Invalid numeric trial data")
        if max(row["reference_n"] for row in train)<maximum_n or max(row["reference_n"] for row in test)<maximum_n:
            reports.append({"channel":channel,"status":"requested load range incomplete","meets_requested_range":False})
            continue
        # Aggregate repeated nominal loads before fitting. Interpolating every
        # noisy repeat can create artificial endpoint plateaus.
        fit_points=[]
        for target in sorted({row["target_n"] for row in train}):
            same_load=[row for row in train if row["target_n"]==target]
            fit_points.append((statistics.median(r["conductance_us"] for r in same_load),
                               statistics.median(r["reference_n"] for r in same_load)))
        knots=isotonic_knots(fit_points)
        noise=[row.get("conductance_stdev_us",0.0) or 0.0 for row in train]
        if any(not math.isfinite(value) or value<0 for value in noise):
            raise ValueError("Invalid training-window noise estimate")
        resistor=next(iter(configurations))[channel]
        gmax=knots[-1][0]*1e-6
        # Engineering guard: eight ADC counts propagated through the divider
        # at 3.0 V, or four times measured training noise; cap at 5% of span.
        quantization_guard=8*.000125*(1+gmax*resistor)**2/(3.0*resistor)*1e6
        guard=min(.05*(knots[-1][0]-knots[0][0]),max(4*max(noise),quantization_guard))
        predictions=[{"trial_id":r["trial_id"],"phase":r["phase"],"reference_n":r["reference_n"],
            "predicted_n":predict(knots,r["conductance_us"],guard),
            "outside_training_knots":not knots[0][0]<=r["conductance_us"]<=knots[-1][0]} for r in test]
        errors=[p["predicted_n"]-p["reference_n"] for p in predictions if p["predicted_n"] is not None]
        outside=sum(p["predicted_n"] is None for p in predictions)
        if not errors:
            reports.append({"channel":channel,"status":"all held-out readings outside calibration range","knots":knots})
            continue
        report={
            "channel":channel,"knots":knots,"train_groups":sorted(train_groups),"test_groups":sorted(test_groups),
            "train_trials":len(train),"test_trials":len(test),"out_of_range_trials":outside,
            "held_out_rmse_n":math.sqrt(statistics.mean(e*e for e in errors)),
            "held_out_max_abs_error_n":max(abs(e) for e in errors),
            "predictions":predictions,
            "range_n":maximum_n,"meets_requested_range":maximum_n==20,
            "probe":next(iter(probes)),"material":next(iter(materials)),
            "pull_down_ohm":list(next(iter(configurations))),
            "continuity_ohm":100000,
            "signal_guard_us":guard,
            "guard_band_trials":sum(p["outside_training_knots"] and p["predicted_n"] is not None for p in predictions),
        }
        error_bounds_met=all(p["predicted_n"] is not None and abs(p["predicted_n"]-p["reference_n"]) <= max(.5,.1*p["reference_n"]) for p in predictions)
        threshold=.25 if maximum_n==5 else .5
        met=outside==0 and error_bounds_met and report["held_out_rmse_n"]<=threshold
        report["status"]=(f"{maximum_n} N static criterion met" if met else f"{maximum_n} N static criterion not met")
        reports.append(report)
    return {
        "schema":"yam-calibration/1","specimen":next(iter(specimens)),
        "evidence_kind":"physical","channels":reports,
        "closed_loop_validated":False,
        "requested_per_finger_range_n":20,
        "limitations":[
            "This static single-zone calibration does not establish total grip force for arbitrary contact geometry.",
            "End-of-hold reference readings bound slow drift only; they are not synchronized dynamic ground truth.",
            "Contact threshold, 60-second creep, off-axis response, transfer to other units, wear, and task tests remain separate gates.",
            "Calibration validity is restricted to this specimen, assembly, cover, probe, orientation, and electrical settings.",
            "A small signal guard band is derived only from training noise and ADC quantization; it is not a statistical confidence bound. Upper force predictions are not clamped to the target.",
        ],
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    rows=[json.loads(line) for line in (args.session/"trials.jsonl").read_text().splitlines() if line.strip()]
    with execution(args.session/"execution","Fit physical single-cell calibration with whole-cycle holdout; preserve original measurements") as record:
        report=analyze(rows)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open("x") as stream:
            json.dump(report,stream,indent=2,allow_nan=False);stream.write("\n")
        record["report"]=str(args.output)
        print(json.dumps({r["channel"]:r["status"] for r in report["channels"]},indent=2))


if __name__=="__main__":
    main()
