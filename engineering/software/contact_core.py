"""Shared contact decisions for actual R1/L1 frames; no force or robot qualification."""

from collections import deque
import hashlib
import json
import math
import statistics

from signals import decode as decode_r1
from l1_protocol import decode as decode_l1

FEATURE_SPEC = {
    "statistic": "rolling_median",
    "lookback_us": 100000,
    "minimum_samples": 4,
    "minimum_span_us": 60000,
    "maximum_gap_us": 40000,
    "evaluation_span_us": 300000,
}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def configuration(frame,sensor):
    if sensor=="R1":
        return {"protocol":"yam-r1/1","pull_down_ohm":list(frame["pull_down_ohm"]),"continuity_ohm":frame["continuity_ohm"]}
    return {"protocol":"yam-l1/1","gain":frame["gain"],"rate_sps":frame["rate_sps"],"ldo_nominal_v":4.2}


class ContactWindow:
    """The same bounded lookback is used during training, evaluation and live display."""
    def __init__(self,sensor,expected_configuration=None):
        if sensor not in {"R1","L1"}:raise ValueError("Expected R1 or L1")
        self.sensor=sensor
        self.configuration=expected_configuration
        self.previous=None
        self.samples=deque()
        self.start_us=None

    def fault(self,reason):
        self.samples.clear();self.start_us=None;self.previous=None
        return {"status":"fault","features":None,"flags":[reason],"device_us":None}

    def feed(self,frame):
        try:
            item=(decode_r1 if self.sensor=="R1" else decode_l1)(frame)
            stamp=item["device_us"]+(item.get("scan_us",0))
            config=configuration(frame,self.sensor)
            flags=list(item["flags"])
            if self.configuration is None:self.configuration=config
            if config!=self.configuration:flags.append("readout_configuration_changed")
            if self.previous:
                seq,previous_us=self.previous
                if item["seq"]!=seq+1 or stamp<=previous_us:
                    flags.append("sequence_or_time_discontinuity")
                elif stamp-previous_us>FEATURE_SPEC["maximum_gap_us"]:
                    flags.append("frame_gap")
            self.previous=(item["seq"],stamp)
            if not item["valid"] or flags:
                self.samples.clear();self.start_us=None
                return {"status":"fault","features":None,"flags":flags,"device_us":stamp}
            values=item["conductance_us"] if self.sensor=="R1" else [item["raw_counts"]]
            if self.start_us is None:self.start_us=stamp
            self.samples.append((stamp,values))
            while self.samples and self.samples[0][0]<stamp-FEATURE_SPEC["lookback_us"]:
                self.samples.popleft()
            if stamp-self.start_us<FEATURE_SPEC["lookback_us"]:
                return {"status":"warming_up","features":None,"flags":[],"device_us":stamp}
            if len(self.samples)<FEATURE_SPEC["minimum_samples"] or stamp-self.samples[0][0]<FEATURE_SPEC["minimum_span_us"]:
                return {"status":"fault","features":None,"flags":["insufficient_samples_in_lookback"],"device_us":stamp}
            return {
                "status":"ready","device_us":stamp,"flags":[],
                "features":[statistics.median(values[index] for _,values in self.samples) for index in range(len(values))],
                "window_samples":len(self.samples),"window_span_us":stamp-self.samples[0][0],
            }
        except (ValueError,TypeError,KeyError) as error:
            return self.fault(str(error))


def extract_trial(records,sensor,expected_configuration=None):
    window=ContactWindow(sensor,expected_configuration)
    first_us=None;last_us=None;features=[];flags=[];frames=0
    for record in records:
        if record.get("stage")!="capture":continue
        if "frame" not in record:
            flags.append(record.get("error","non_sample_event_during_capture"))
            window.fault(flags[-1]);continue
        result=window.feed(record["frame"]);frames+=1
        stamp=result["device_us"]
        if stamp is not None:
            if first_us is None:first_us=stamp
            last_us=stamp
        if result["status"]=="fault":
            flags.extend(result["flags"]);continue
        if first_us is None or stamp is None:continue
        elapsed=stamp-first_us
        if result["status"]=="ready" and FEATURE_SPEC["lookback_us"]<=elapsed<=FEATURE_SPEC["lookback_us"]+FEATURE_SPEC["evaluation_span_us"]:
            features.append(result["features"])
    required=FEATURE_SPEC["lookback_us"]+FEATURE_SPEC["evaluation_span_us"]
    if first_us is None or last_us is None or last_us-first_us<required:
        flags.append("incomplete_capture_duration")
    if not features:flags.append("no_complete_decision_windows")
    return {
        "available":not flags,"flags":sorted(set(flags)),"windows":features,
        "configuration":window.configuration,"frames":frames,
        "first_device_us":first_us,"last_device_us":last_us,
    }


def check_model(model):
    if model.get("schema")!="yam-contact-model/1" or model.get("evidence_kind")!="physical":
        raise ValueError("A model fitted to a recorded physical training session is required")
    if model.get("feature_spec")!=FEATURE_SPEC:raise ValueError("Contact feature definition changed")
    sensor=model.get("sensor")
    if sensor not in {"R1","L1"}:raise ValueError("Unknown sensor")
    thresholds=model.get("thresholds")
    if not isinstance(thresholds,list) or not thresholds:raise ValueError("No frozen thresholds")
    channels=[]
    for item in thresholds:
        channel=item.get("channel")
        if not isinstance(channel,int) or isinstance(channel,bool) or channel not in range(6 if sensor=="R1" else 1):
            raise ValueError("Invalid threshold channel")
        if item.get("polarity") not in {-1,1} or not finite(item.get("threshold")):
            raise ValueError("Invalid threshold")
        if sensor=="R1" and item["polarity"]!=1:raise ValueError("R1 contact must increase conductance")
        channels.append(channel)
    if len(channels)!=len(set(channels)):raise ValueError("Duplicate threshold channels")
    if not isinstance(model.get("configuration"),dict):raise ValueError("Missing readout configuration")
    return model


def classify(features,model):
    """No trial label, region, target force or reference value enters this function."""
    check_model(model)
    if len(features)!=(6 if model["sensor"]=="R1" else 1) or not all(finite(value) for value in features):
        raise ValueError("Invalid contact features")
    active=[item["channel"] for item in model["thresholds"]
            if item["polarity"]*(features[item["channel"]]-item["threshold"])>=0]
    return {"contact":bool(active),"active_channels":active}


def fit_thresholds(rows,sensor,channels):
    """Use every training window; require separation rather than discarding outliers."""
    thresholds=[]
    for channel in channels:
        quiet=[window[channel] for row in rows if not row["contact_expected"] for window in row["extracted"]["windows"]]
        positive=[window[channel] for row in rows if row["contact_expected"] and
                  (sensor=="L1" or row["train_channel"]==channel) for window in row["extracted"]["windows"]]
        if not quiet or not positive:raise ValueError(f"Missing training class for channel {channel}")
        polarity=1 if sensor=="R1" or statistics.median(positive)>statistics.median(quiet) else -1
        highest_quiet=max(polarity*value for value in quiet)
        lowest_contact=min(polarity*value for value in positive)
        if lowest_contact<=highest_quiet:
            raise ValueError(f"Training contact and quiet signals overlap on channel {channel}; preserve the failure and inspect the sensor")
        thresholds.append({
            "channel":channel,"polarity":polarity,
            "threshold":polarity*(highest_quiet+lowest_contact)/2,
            "training_highest_quiet_signed":highest_quiet,"training_lowest_contact_signed":lowest_contact,
            "units":"microsiemens" if sensor=="R1" else "ADC_counts",
        })
    return thresholds


def reference_flags(row,uncertainty):
    before=row["reference_before_n"];after=row["reference_after_n"]
    if not finite(before) or not finite(after) or not finite(uncertainty) or not 0<uncertainty<=.05:
        return ["invalid_reference"]
    flags=[]
    if abs(after-before)>.02:flags.append("reference_changed_during_capture")
    if row["contact_expected"]:
        if min(before,after)-uncertainty<=0:flags.append("contact_not_resolved_by_reference")
        if max(before,after)+uncertainty>.2+1e-12:flags.append("reference_upper_bound_exceeds_0p2n")
    elif max(abs(before),abs(after))>uncertainty:
        flags.append("unloaded_reference_not_zero")
    return flags


def binomial_cdf(k,n,p):
    if p<=0:return 1.0
    if p>=1:return float(k>=n)
    logs=[math.lgamma(n+1)-math.lgamma(i+1)-math.lgamma(n-i+1)+i*math.log(p)+(n-i)*math.log1p(-p)
          for i in range(k+1)]
    largest=max(logs)
    return min(1.0,math.exp(largest)*sum(math.exp(value-largest) for value in logs))


def failure_upper_bound(errors,trials,confidence=.95):
    """One-sided Clopper–Pearson upper bound, from the binomial CDF."""
    if not isinstance(errors,int) or not isinstance(trials,int) or isinstance(errors,bool) or isinstance(trials,bool) or not 0<=errors<=trials:
        raise ValueError("Invalid event counts")
    if not 0<confidence<1:raise ValueError("Invalid confidence")
    if not trials:return None
    if errors==trials:return 1.0
    alpha=1-confidence
    if errors==0:return -math.expm1(math.log(alpha)/trials)
    lo,hi=0.0,1.0
    for _ in range(70):
        mid=(lo+hi)/2
        if binomial_cdf(errors,trials,mid)>alpha:lo=mid
        else:hi=mid
    return (lo+hi)/2


def summarize_outcome(rows,contact_expected):
    selected=[row for row in rows if row["contact_expected"] is contact_expected]
    unavailable=sum(not row["available"] for row in selected)
    observed_errors=sum(row["available"] and any(value is not contact_expected for value in row["decisions"]) for row in selected)
    total=len(selected);conservative=unavailable+observed_errors
    return {
        "trials":total,"observed_errors":observed_errors,"unavailable_trials":unavailable,
        "conservative_errors":conservative,
        "conservative_error_rate":conservative/total if total else None,
        "upper_error_bound_95":failure_upper_bound(conservative,total),
    }
