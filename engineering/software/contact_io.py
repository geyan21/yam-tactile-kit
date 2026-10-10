"""Integrity and scope checks shared by the contact recorder and analyzers."""

import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from contact_core import FEATURE_SPEC, check_model, extract_trial, reference_flags


def selected_cases(path,sensor,channels,phase,region_ids=None):
    payload=json.loads(path.read_text())
    if payload.get("schema")!="yam-contact-cases/1":raise ValueError("Unknown contact-case format")
    cases=payload["regions"]
    ids=[case["id"] for case in cases]
    if len(ids)!=len(set(ids)) or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",name) for name in ids):
        raise ValueError("Case IDs must be unique and safe filenames")
    if region_ids and not set(region_ids)<=set(ids):raise ValueError("Unknown requested contact region")
    for case in cases:
        channel=case["train_channel"]
        if channel is not None and (not isinstance(channel,int) or isinstance(channel,bool) or channel not in range(6)):
            raise ValueError("Invalid R1 training channel")
    selected=[case for case in cases if not region_ids or case["id"] in region_ids]
    if phase=="train":
        selected=[case for case in selected if case["train_channel"] is not None and
                  (sensor=="L1" or case["train_channel"] in channels)]
    if not selected:raise ValueError("No contact cases selected")
    if phase=="train" and sensor=="R1" and not set(channels)<={case["train_channel"] for case in selected}:
        raise ValueError("Every enabled R1 channel needs its center-contact training case")
    return payload,selected


def bind_model(model,sensor,specimen,pose,variant,channels,transfer=False):
    check_model(model)
    if model["sensor"]!=sensor or model["specimen"]!=specimen:
        raise ValueError("The model belongs to another sensor or specimen")
    if sorted(item["channel"] for item in model["thresholds"])!=sorted(channels):
        raise ValueError("Enabled channels differ from the frozen model")
    if not transfer and (model["pose_id"]!=pose or model["variant"]!=variant):
        raise ValueError("Pose or material/assembly variant changed; use an explicit transfer experiment")
    return model


def load_session(directory,phase):
    metadata=json.loads((directory/"session.json").read_text())
    if metadata.get("schema")!="yam-contact-session/1" or metadata.get("evidence_kind")!="physical":
        raise ValueError("Physical contact records are required; plans and software fixtures are not measurements")
    if metadata.get("phase")!=phase or metadata.get("feature_spec")!=FEATURE_SPEC:
        raise ValueError("Session phase or feature definition changed")
    plan_bytes=(directory/"plan.json").read_bytes()
    if hashlib.sha256(plan_bytes).hexdigest()!=metadata["plan_sha256"]:
        raise ValueError("Saved contact plan changed")
    plan=json.loads(plan_bytes)
    if plan!=metadata["plan"]:raise ValueError("Embedded and saved plans differ")
    if plan.get("schema")!="yam-contact-plan/1" or plan.get("phase")!=phase:
        raise ValueError("Unknown contact plan")
    cases_bytes=(directory/"cases.json").read_bytes()
    if hashlib.sha256(cases_bytes).hexdigest()!=metadata["cases_sha256"] or json.loads(cases_bytes)!=metadata["cases"]:
        raise ValueError("Declared contact cases changed")
    model=None
    if phase=="test":
        model_bytes=(directory/"frozen_model.json").read_bytes()
        if hashlib.sha256(model_bytes).hexdigest()!=metadata["model_sha256"]:
            raise ValueError("The model frozen before collection changed")
        model=bind_model(json.loads(model_bytes),metadata["sensor"],metadata["specimen"],
                         metadata["pose_id"],metadata["variant"],metadata["channels"],metadata["transfer_experiment"])
        if metadata.get("model_frozen_before_collection") is not True:
            raise ValueError("Model was not frozen before the evaluation")
    rows=[json.loads(line) for line in (directory/"trials.jsonl").read_text().splitlines() if line.strip()]
    planned=plan["trials"]
    repeats=plan.get("repeats_per_label_and_region")
    if not isinstance(repeats,int) or isinstance(repeats,bool) or not 20<=repeats<=10000:
        raise ValueError("Invalid planned repetition count")
    declared={case["id"]:case for case in metadata["cases"]["regions"]}
    planned_counts={}
    for trial in planned:
        if type(trial.get("contact_expected")) is not bool or trial.get("region_id") not in declared:
            raise ValueError("Invalid planned contact class or region")
        if trial["train_channel"]!=declared[trial["region_id"]]["train_channel"]:
            raise ValueError("Training-channel mapping changed")
        if phase=="train" and trial["train_channel"] is None:
            raise ValueError("Leading edges and gaps are held out of threshold training")
        key=(trial["region_id"],trial["contact_expected"])
        planned_counts[key]=planned_counts.get(key,0)+1
    if not planned_counts or any(
        planned_counts.get((region,label),0)!=repeats
        for region,_ in planned_counts for label in (False,True)
    ):
        raise ValueError("Each planned region needs the fixed count of both contact classes")
    if len(rows)>len(planned) or [row["trial_id"] for row in rows]!=[row["trial_id"] for row in planned[:len(rows)]]:
        raise ValueError("Recorded trials are not the planned prefix; do not remove or reorder failures")
    if len({trial["trial_id"] for trial in planned})!=len(planned):
        raise ValueError("Duplicate plan IDs")
    expected_config=model["configuration"] if model else None
    previous_end=None
    for row,expected in zip(rows,planned):
        if any(row[key]!=expected[key] for key in ("trial_id","region_id","contact_expected","train_channel")):
            raise ValueError("Trial labels differ from the frozen plan")
        if type(row["contact_expected"]) is not bool:
            raise ValueError("A contact label must be boolean")
        name=row["raw_file"]
        if Path(name).name!=name or name!=row["trial_id"]+".jsonl":
            raise ValueError("Unexpected raw filename")
        content=(directory/name).read_bytes()
        if hashlib.sha256(content).hexdigest()!=row["raw_sha256"]:
            raise ValueError(f"Raw records changed: {name}")
        records=[json.loads(line) for line in content.splitlines() if line.strip()]
        extracted=extract_trial(records,metadata["sensor"],expected_config)
        if expected_config is None and extracted["configuration"] is not None:
            expected_config=extracted["configuration"]
        if previous_end is not None and extracted["first_device_us"] is not None and extracted["first_device_us"]<=previous_end:
            extracted["available"]=False
            extracted["flags"].append("device_restart_or_replayed_trial")
        if extracted["last_device_us"] is not None:previous_end=extracted["last_device_us"]
        flags=reference_flags(row,metadata["reference_uncertainty_n"])
        row["reference_flags"]=flags
        row["extracted"]=extracted
        row["available"]=extracted["available"] and not flags
    return metadata,rows,model
