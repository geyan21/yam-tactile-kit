"""Contact tests use invented software inputs only; no hardware result is created."""

import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"engineering/software"))
from contact_bench import make_plan
from contact_core import (FEATURE_SPEC, ContactWindow, classify, extract_trial,
                          failure_upper_bound, fit_thresholds, reference_flags)
from contact_io import bind_model, load_session
from contact_report import fit, evaluate
from tactile_kit.records import execution

CASES={"schema":"yam-contact-cases/1","scope":"SOFTWARE UNIT FIXTURE ONLY","regions":[
    {"id":"center","train_channel":0,"instruction":"Invented test case"},
    {"id":"gap","train_channel":None,"instruction":"Invented held-out case"},
]}


def frame(sensor,seq,contact=False):
    if sensor=="L1":
        return {"type":"sample","protocol":"yam-l1/1","seq":seq,"device_us":seq*12500,
                "raw_counts":28000 if contact else 20000,"bridge_v":4.2,"bridge_current_ma":4.2,
                "gain":128,"rate_sps":80,"errors":[],"startup_check_passed":True,
                "startup_equivalent_ohm":500,"transport_and_supply_valid":True}
    return {"type":"sample","protocol":"yam-r1/1","seq":seq,"device_us":seq*20000,"scan_us":8000,
            "raw":[5280 if contact else 2400,*([2400]*5),13200,13200],
            "offset_us":[1000,1000,3000,3000,5000,5000,7000,7000],
            "pull_down_ohm":[10000]*6,"continuity_ohm":100000,"errors":[]}


def extracted(sensor="L1",contact=False,base=0):
    return extract_trial([{"stage":"capture","frame":frame(sensor,base+i,contact)} for i in range(50)],sensor)


def fixture(phase="train",repeats=20,sensor="L1"):
    cases=CASES["regions"][:1] if phase=="train" else CASES["regions"]
    plan=make_plan(cases,phase,repeats,123)
    metadata={"schema":"yam-contact-session/1","evidence_kind":"physical","phase":phase,
              "sensor":sensor,"specimen":"SOFTWARE_FIXTURE","pose_id":"FIXTURE_POSE","variant":"TEST_ONLY",
              "channels":[0],"feature_spec":FEATURE_SPEC,"reference_uncertainty_n":.01,
              "cases":copy.deepcopy(CASES),"cases_sha256":"not-an-experiment","plan":plan,
              "plan_sha256":"not-an-experiment","transfer_experiment":False,"model_sha256":"not-an-experiment"}
    raw_quiet=extracted(sensor,False);raw_contact=extracted(sensor,True)
    rows=[]
    for trial in plan["trials"]:
        force=.18 if trial["contact_expected"] else 0
        rows.append({**trial,"reference_before_n":force,"reference_after_n":force,
                     "reference_flags":[],"available":True,
                     "extracted":copy.deepcopy(raw_contact if trial["contact_expected"] else raw_quiet)})
    return metadata,rows


def disk_session(path,phase,model=None):
    metadata,rows=fixture(phase)
    plan_bytes=(json.dumps(metadata["plan"])+"\n").encode()
    cases_bytes=(json.dumps(CASES)+"\n").encode()
    metadata["plan_sha256"]=hashlib.sha256(plan_bytes).hexdigest()
    metadata["cases_sha256"]=hashlib.sha256(cases_bytes).hexdigest()
    if model:
        model_bytes=json.dumps(model).encode()
        metadata["model_sha256"]=hashlib.sha256(model_bytes).hexdigest()
        metadata["model_frozen_before_collection"]=True
        (path/"frozen_model.json").write_bytes(model_bytes)
    (path/"plan.json").write_bytes(plan_bytes);(path/"cases.json").write_bytes(cases_bytes)
    (path/"session.json").write_text(json.dumps(metadata))
    with (path/"trials.jsonl").open("w") as stream:
        for index,row in enumerate(rows):
            name=row["trial_id"]+".jsonl"
            raw="".join(json.dumps({"stage":"capture","frame":frame("L1",index*1000+i,row["contact_expected"])})+"\n" for i in range(50))
            (path/name).write_text(raw)
            for key in ("extracted","reference_flags","available"):row.pop(key)
            row["raw_file"]=name;row["raw_sha256"]=hashlib.sha256(raw.encode()).hexdigest()
            stream.write(json.dumps(row)+"\n")
    return metadata,rows


class ContactTests(unittest.TestCase):
    def test_real_protocol_shapes_produce_bounded_windows(self):
        for sensor in ("R1","L1"):
            value=extracted(sensor)
            self.assertTrue(value["available"])
            self.assertGreater(len(value["windows"]),5)

    def test_decoder_fault_does_not_become_clear_contact(self):
        window=ContactWindow("L1")
        for index in range(12):window.feed(frame("L1",index))
        bad=frame("L1",12);bad["bridge_current_ma"]=0
        result=window.feed(bad)
        self.assertEqual(result["status"],"fault");self.assertIsNone(result["features"])

    def test_clock_gap_invalidates_inference(self):
        window=ContactWindow("L1")
        window.feed(frame("L1",0))
        bad=frame("L1",1);bad["device_us"]=100000
        self.assertIn("frame_gap",window.feed(bad)["flags"])

    def test_changed_resistors_reject_r1_window(self):
        window=ContactWindow("R1");window.feed(frame("R1",0))
        bad=frame("R1",1);bad["pull_down_ohm"][0]=1000
        self.assertIn("readout_configuration_changed",window.feed(bad)["flags"])

    def test_short_capture_is_not_accepted(self):
        self.assertFalse(extract_trial([{"stage":"capture","frame":frame("L1",i)} for i in range(10)],"L1")["available"])

    def test_positive_force_requires_reference_upper_below_target(self):
        self.assertTrue(reference_flags({"contact_expected":True,"reference_before_n":.2,"reference_after_n":.2},.01))
        self.assertFalse(reference_flags({"contact_expected":True,"reference_before_n":.18,"reference_after_n":.18},.01))

    def test_fit_and_classification_for_both_readouts(self):
        for sensor in ("R1","L1"):
            metadata,rows=fixture(sensor=sensor);model=fit(metadata,rows)
            self.assertFalse(classify(extracted(sensor,False)["windows"][0],model)["contact"])
            self.assertTrue(classify(extracted(sensor,True)["windows"][0],model)["contact"])

    def test_negative_l1_polarity_supported(self):
        metadata,rows=fixture()
        for row in rows:
            if row["contact_expected"]:
                row["extracted"]["windows"]=[[12000] for _ in row["extracted"]["windows"]]
        model=fit(metadata,rows)
        self.assertEqual(model["thresholds"][0]["polarity"],-1)
        self.assertTrue(classify([12000],model)["contact"])

    def test_overlapping_training_is_not_trimmed(self):
        metadata,rows=fixture()
        next(row for row in rows if row["contact_expected"])["extracted"]["windows"]=[[19000]]
        with self.assertRaisesRegex(ValueError,"overlap"):fit(metadata,rows)

    def test_twenty_perfect_trials_are_not_a_one_percent_demonstration(self):
        model=fit(*fixture())
        result=evaluate(*fixture("test"),model)
        self.assertTrue(result["observed_rate_screen_met"])
        self.assertFalse(result["per_metric_95_bound_below_1pct"])
        self.assertFalse(result["robot_gripper_qualified"])

    def test_three_hundred_perfect_trials_have_tight_per_metric_bound(self):
        model=fit(*fixture())
        result=evaluate(*fixture("test",300),model)
        self.assertTrue(result["per_metric_95_bound_below_1pct"])
        self.assertFalse(result["robot_gripper_qualified"])

    def test_overlapping_windows_are_not_counted_as_independent_trials(self):
        model=fit(*fixture());result=evaluate(*fixture("test"),model)
        self.assertEqual(result["regions"][0]["loaded"]["trials"],20)
        self.assertGreater(len(result["trials"][0]["decisions"]),5)

    def test_faults_are_preserved_and_counted_conservatively(self):
        model=fit(*fixture());metadata,rows=fixture("test")
        row=next(row for row in rows if not row["contact_expected"])
        row["available"]=False;row["extracted"]["flags"]=["bridge_excitation_current"]
        result=evaluate(metadata,rows,model)
        self.assertFalse(result["observed_rate_screen_met"])
        summary=next(value for value in result["regions"] if value["region_id"]==row["region_id"])["clear"]
        self.assertEqual(summary["unavailable_trials"],1);self.assertEqual(summary["conservative_errors"],1)

    def test_unseen_gap_miss_is_not_hidden_by_center_success(self):
        model=fit(*fixture());metadata,rows=fixture("test")
        for row in rows:
            if row["region_id"]=="gap" and row["contact_expected"]:
                row["extracted"]["windows"]=[[20000] for _ in row["extracted"]["windows"]]
        result=evaluate(metadata,rows,model)
        self.assertFalse(result["observed_rate_screen_met"])
        self.assertEqual(next(region for region in result["regions"] if region["region_id"]=="gap")["loaded"]["observed_errors"],20)

    def test_stopped_session_cannot_pass(self):
        model=fit(*fixture());metadata,rows=fixture("test")
        result=evaluate(metadata,rows[:-1],model)
        self.assertFalse(result["plan_complete"]);self.assertFalse(result["observed_rate_screen_met"])

    def test_transfer_needs_explicit_flag_and_never_changes_threshold(self):
        model=fit(*fixture());before=copy.deepcopy(model)
        with self.assertRaises(ValueError):bind_model(model,"L1","SOFTWARE_FIXTURE","OTHER_POSE","OTHER", [0])
        bind_model(model,"L1","SOFTWARE_FIXTURE","OTHER_POSE","OTHER",[0],True)
        self.assertEqual(model,before)

    def test_known_exact_binomial_cases(self):
        self.assertAlmostEqual(failure_upper_bound(0,1),.95)
        self.assertAlmostEqual(failure_upper_bound(1,2),math.sqrt(.95))
        self.assertGreater(failure_upper_bound(0,100),.029)
        self.assertLess(failure_upper_bound(0,300),.01)
        self.assertIsNone(failure_upper_bound(0,0))

    def test_raw_records_recompute_and_frozen_model_is_checked(self):
        model=fit(*fixture())
        with tempfile.TemporaryDirectory(prefix="contact-software-test-") as directory:
            path=Path(directory);disk_session(path,"test",model)
            metadata,rows,frozen=load_session(path,"test")
            self.assertTrue(evaluate(metadata,rows,frozen)["observed_rate_screen_met"])
            frozen["thresholds"][0]["threshold"]+=1
            (path/"frozen_model.json").write_text(json.dumps(frozen))
            with self.assertRaisesRegex(ValueError,"frozen"):load_session(path,"test")

    def test_replayed_raw_interval_is_unavailable(self):
        model=fit(*fixture())
        with tempfile.TemporaryDirectory(prefix="contact-software-test-") as directory:
            path=Path(directory);_,rows=disk_session(path,"test",model)
            first=path/rows[0]["raw_file"];second=path/rows[1]["raw_file"]
            second.write_bytes(first.read_bytes());rows[1]["raw_sha256"]=rows[0]["raw_sha256"]
            (path/"trials.jsonl").write_text("".join(json.dumps(row)+"\n" for row in rows))
            _,loaded,_=load_session(path,"test")
            self.assertFalse(loaded[1]["available"])
            self.assertIn("device_restart_or_replayed_trial",loaded[1]["extracted"]["flags"])

    def test_plan_only_session_cannot_become_measurements(self):
        with tempfile.TemporaryDirectory(prefix="contact-software-test-") as directory:
            path=Path(directory);metadata,_=disk_session(path,"train")
            metadata["evidence_kind"]="plan_only";(path/"session.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError,"Physical"):load_session(path,"train")

    def test_synthetic_data_cannot_become_a_physical_model(self):
        metadata,rows=fixture();metadata["evidence_kind"]="synthetic"
        with self.assertRaisesRegex(ValueError,"Physical"):fit(metadata,rows)

    def test_gap_cannot_enter_threshold_training(self):
        metadata,rows=fixture();rows[0]["train_channel"]=None
        with self.assertRaisesRegex(ValueError,"held out"):fit(metadata,rows)

    def test_saved_setup_previews_without_serial_or_physical_records(self):
        with execution(ROOT/"build/records","Verify the saved contact-setup CLI produces plans without opening a sensor port") as record:
            record["commands"]=[]
            with tempfile.TemporaryDirectory(prefix="contact-cli-software-test-") as directory:
                directory=Path(directory)
                for sensor,channels,expected in (("L1",None,240),("R1","0,1",80)):
                    setup={"schema":"yam-contact-setup/1","sensor":sensor,"channels":channels,
                           "specimen":"SOFTWARE_ONLY","variant":"TEST","pose_id":"TEST",
                           "operator":"SOFTWARE_TEST","reference_id":"NO_HARDWARE","reference_uncertainty_n":.01,
                           "fixture":"Software-only CLI verification","port":""}
                    source=directory/f"{sensor}-setup.json";source.write_text(json.dumps(setup))
                    output=directory/sensor
                    command=[sys.executable,str(ROOT/"engineering/software/contact_bench.py"),"--setup",str(source),
                             "--phase","train","--output",str(output),"--plan-only"]
                    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                    entry={"command":command,"pid":process.pid};record["commands"].append(entry)
                    try:stdout,stderr=process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        record["intentional_stop_requests"].append(f"Stop owned plan-preview PID {process.pid}: timeout")
                        process.kill();process.communicate();self.fail("Contact plan preview timed out")
                    entry.update({"exit_code":process.returncode,"stdout":stdout,"stderr":stderr})
                    self.assertEqual(process.returncode,0,stderr)
                    metadata=json.loads((output/"session.json").read_text())
                    self.assertEqual(metadata["evidence_kind"],"plan_only")
                    self.assertEqual(len(metadata["plan"]["trials"]),expected)
                    self.assertFalse((output/"trials.jsonl").exists())


if __name__=="__main__":
    unittest.main()
