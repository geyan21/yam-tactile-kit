#!/usr/bin/python3
"""Run a bounded local Freerouting study with explicit F1 row-width rules."""

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest

BINARY = ROOT / "build/engineering/tools/freerouting/2.5.0/native/freerouting-cli"
BINARY_SHA = "1cf75b007af551818ff2e15d6bef3cdefe1119decb2cb29527589c797af186f1"


def parse(text):
    text = text.replace('(string_quote ")', "(string_quote __DOUBLE_QUOTE__)")
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text)
    stack, result = [], None
    for token in tokens:
        if token == "(":
            item = []
            if stack:
                stack[-1].append(item)
            stack.append(item)
        elif token == ")":
            if not stack:
                raise ValueError("Unbalanced DSN")
            result = stack.pop()
        else:
            if not stack:
                raise ValueError("DSN atom outside a list")
            stack[-1].append(token)
    if stack or not result or result[0] != "pcb":
        raise ValueError("Incomplete DSN board")
    return result


def emit(node):
    if isinstance(node, str):
        return node
    return "("+" ".join(emit(value) for value in node)+")"


def row_rules(text, omit_component_drawings=False, planning_clearance_mm=None):
    tree = parse(text)
    unit = next(item for item in tree if isinstance(item, list) and item[0] == "unit")
    if unit != ["unit", "um"]:
        raise ValueError("Review width conversion for this DSN unit")
    network = next(item for item in tree if isinstance(item, list) and item[0] == "network")
    structure = next(item for item in tree if isinstance(item, list) and item[0] == "structure")
    structure_before = copy.deepcopy(structure)
    omitted = 0
    if omit_component_drawings:
        library = next(item for item in tree if isinstance(item, list) and item[0] == "library")
        for image in library[1:]:
            if not isinstance(image, list) or image[0] != "image":
                continue
            before = len(image)
            image[:] = [item for item in image if not (
                isinstance(item, list) and item and item[0] == "outline")]
            omitted += before-len(image)
    nets_before = [copy.deepcopy(item) for item in network[1:] if item[0] == "net"]
    classes = [item for item in network[1:] if item[0] == "class"]
    if len(classes) != 1:
        raise ValueError("Review non-default source net classes")
    default = classes[0]
    rows = [f"R{i}_I" for i in range(4)]
    if not all(name in default[2:] for name in rows):
        raise ValueError("Expected all four row-current nets")
    options = [copy.deepcopy(item) for item in default[2:] if isinstance(item, list)]
    rule = next(item for item in options if item[0] == "rule")
    width = next(item for item in rule[1:] if item[0] == "width")
    if float(width[1]) != 150:
        raise ValueError("Signal rule is not the exported 0.15 mm target")
    width[1] = "500"
    default[:] = [item for item in default if not isinstance(item, str) or item not in rows]
    row_class = ["class", "F1_ROWS", *rows, *options]
    network.append(row_class)
    if planning_clearance_mm is not None:
        if not .15 <= planning_clearance_mm <= .3:
            raise ValueError("Planning clearance must preserve or strengthen the 0.15 mm requirement")
        for net_class in (default, row_class):
            rules = next(item for item in net_class if isinstance(item, list) and item[0] == "rule")
            clearance = next(item for item in rules[1:] if item[0] == "clearance")
            clearance[1] = f"{planning_clearance_mm*1000:g}"
    if [item for item in network[1:] if item[0] == "net"] != nets_before:
        raise ValueError("Rule adjustment changed a net or pin membership")
    if structure != structure_before:
        raise ValueError("Do not change the board boundary or routing keepouts")
    result = emit(tree).replace("(string_quote __DOUBLE_QUOTE__)", '(string_quote ")')+"\n"
    return result, {"nets_preserved": len(nets_before), "row_current_width_mm": .5,
                    "signal_width_mm": .15, "clearance_mm": .15,
                    "planning_clearance_mm": planning_clearance_mm or .15,
                    "row_nets": rows, "no_ignored_net_classes": True,
                    "nonrouting_component_drawings_omitted": omitted,
                    "board_boundary_and_keepouts_unchanged": True,
                    "drawing_workaround_basis": "Freerouting v2.5.0 ComponentOutline.isObstacle returns false; only library/image/outline drawings are omitted from the local exchange to avoid its native serialization error. Native PCB geometry remains unchanged.",
                    "drawing_source": "https://raw.githubusercontent.com/freerouting/freerouting/v2.5.0/src/main/java/app/freerouting/board/model/items/ComponentOutline.java"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_directory", type=Path)
    parser.add_argument("--seconds", type=int, default=240)
    parser.add_argument("--omit-component-drawings", action="store_true")
    parser.add_argument("--jvm-bundle", action="store_true")
    parser.add_argument("--name", choices=("f1_fanout_r2", "f1_fanout_r3"), default="f1_fanout_r2")
    parser.add_argument("--no-neckdown", action="store_true")
    parser.add_argument("--no-optimize", action="store_true")
    parser.add_argument("--planning-clearance-mm", type=float)
    parser.add_argument("--reserve-ground-layer", action="store_true")
    args = parser.parse_args()
    source = args.export_directory.resolve()
    if not source.is_relative_to(ROOT / "build") or not 30 <= args.seconds <= 600:
        parser.error("Use a generated export and a 30–600 second bound")
    executable = BINARY
    environment = dict(os.environ)
    tool_identity = {"kind": "native", "sha256": BINARY_SHA}
    if args.jvm_bundle:
        bundle_path = ROOT / "build/engineering/tools/freerouting/2.5.0/jvm-bundle.json"
        bundle = json.loads(bundle_path.read_text())
        if bundle["archive_sha256"] != "e8ffca14914e5307a2fa9aea723fb93d11b99bebda20d126472da5460c03196e":
            raise ValueError("Unexpected bundled runtime provenance")
        for name, expected in bundle["files_sha256"].items():
            if digest(ROOT / name) != expected:
                raise ValueError("Bundled runtime file changed: "+name)
        for name, expected in bundle["links"].items():
            if os.readlink(ROOT / name) != expected:
                raise ValueError("Bundled runtime link changed")
        executable = ROOT / bundle["launcher"]
        environment["JAVA_TOOL_OPTIONS"] = "-Xmx1024m -XX:ActiveProcessorCount=2 -Djava.awt.headless=true"
        tool_identity = {"kind": "official_bundled_jvm", "manifest_sha256": digest(bundle_path),
                         "launcher_sha256": digest(executable), "jar_sha256": digest(ROOT / bundle["jar"]),
                         "java_options": environment["JAVA_TOOL_OPTIONS"]}
    elif digest(BINARY) != BINARY_SHA:
        raise ValueError("Native router differs from the checked official release")
    dsn_path = source / (args.name+".dsn")
    exported = json.loads((source / "report.json").read_text())
    if digest(dsn_path) != exported["dsn_sha256"]:
        raise ValueError("Native export changed")
    folder = ROOT / "build/engineering/prototypes/f1/freerouting_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Route every F1 R2 net locally with explicit row/signal widths, one optimization thread, no API service and no application analytics; preserve failures and native outputs") as record:
        folder.mkdir(parents=True, exist_ok=False)
        for path in (dsn_path, source / "report.json", Path(__file__)):
            shutil.copyfile(path, folder / ("source_"+path.name))
        changed, rules = row_rules(dsn_path.read_text(), args.omit_component_drawings, args.planning_clearance_mm)
        stem = "f1_r2" if args.name == "f1_fanout_r2" else "f1_r3"
        target = folder / (stem+"_input.dsn")
        target.write_text(changed)
        (folder / "rules.json").write_text(json.dumps(rules, indent=2)+"\n")
        output = folder / (stem+"_output.ses")
        command = [str(executable), "-de", str(target), "-do", str(output),
                   "--gui.enabled=false", "--api_server.enabled=false", "-da",
                   "--user_data_path="+str(folder / "tool-data"),
                   "--logging.file.location="+str(folder / "tool-logs"),
                   "--router.autorouter.max_passes=30", "-mt", "1", "-l", "en"]
        if args.no_neckdown:
            command.append("--router.automatic_neckdown=false")
        if args.no_optimize:
            command.append("--router.optimizer.enabled=false")
        if args.reserve_ground_layer:
            tree = parse(dsn_path.read_text())
            structure = next(item for item in tree if isinstance(item, list) and item[0] == "structure")
            layers = [item[1] for item in structure if isinstance(item, list) and item[0] == "layer"]
            if layers != ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]:
                raise ValueError("Review routing-layer order before reserving the ground layer")
            command.append("--router.layers.routable=true,false,true,true")
        rules["automatic_neckdown_disabled"] = args.no_neckdown
        rules["optimization_enabled"] = not args.no_optimize
        rules["reserved_ground_layer"] = "In1.Cu" if args.reserve_ground_layer else None
        (folder / "rules.json").write_text(json.dumps(rules, indent=2)+"\n")
        started = time.monotonic()
        with (folder / "router.log").open("w") as stream:
            process = subprocess.Popen(command, cwd=folder, env=environment, stdout=stream, stderr=subprocess.STDOUT)
            receipt = {"command": command, "pid": process.pid, "tool_identity": tool_identity}
            record["router"] = receipt
            code = None
            worker_exception = False
            while time.monotonic()-started < args.seconds:
                try:
                    code = process.wait(timeout=min(20, max(1, args.seconds-(time.monotonic()-started))))
                    break
                except subprocess.TimeoutExpired:
                    print(f"Local route still running; {time.monotonic()-started:.0f} seconds", flush=True)
                    log_tail = (folder / "router.log").read_text(errors="replace")[-20000:]
                    if "Exception in thread" in log_tail or "UnsupportedFeatureError" in log_tail:
                        worker_exception = True
                        break
            if code is None:
                receipt["intentional_stop"] = ("Owned routing worker reported an exception; stop the waiting application"
                                               if worker_exception else
                                               f"{args.seconds} second limit on this owned native router")
                process.terminate()
                try:
                    code = process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    receipt["forced_stop_after_terminate_timeout"] = True
                    process.kill()
                    code = process.wait(timeout=5)
        receipt["exit_code"] = code
        report = {"schema": "yam-f1-freerouting-attempt/1", "source_export": exported,
                  "router": receipt, "rules": rules, "elapsed_s": time.monotonic()-started,
                  "input_dsn_sha256": digest(target), "physical_specimens_tested": 0,
                  "worker_exception_detected": worker_exception,
                  "session_exists": output.is_file(),
                  "session_sha256": digest(output) if output.is_file() else None,
                  "native_import_and_independent_drc_pending": True}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "exit_code": code,
                            "session_exists": report["session_exists"], "independent_drc_pending": True}
        print(json.dumps(record["result"], indent=2))
        if code or not output.is_file():
            print((folder / "router.log").read_text()[-4000:])
            raise RuntimeError("Local routing attempt did not produce a successful session")


if __name__ == "__main__":
    main()
