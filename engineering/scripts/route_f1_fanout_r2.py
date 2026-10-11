#!/usr/bin/python3
"""Route the separate F1 R2 fanout with reversed upper connectors."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_board_routes import NativeBoardGeometry
from route_f1_wrist import WristRouter

KICAD_PYTHON = ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/python3.11"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement_run", type=Path)
    args = parser.parse_args()
    source = args.placement_run.resolve()
    if not source.is_relative_to(ROOT):
        parser.error("Use a repository-owned placement run")
    spec = json.loads((source / "specification.json").read_text())
    name = spec["name"]
    if name != "f1_fanout_r2":
        raise ValueError("This writer is only for the separate R2 fanout")
    native_path = source / "placement" / (name + ".json")
    data = json.loads(native_path.read_text())
    config_path = source / "inputs/engineering/designs/f1_fanout_development.json"
    config = json.loads(config_path.read_text())
    if not json.loads((source / "placement_check.json").read_text())["passed"]:
        raise ValueError("Resolve placement findings before routing")
    if digest(source / "placement" / (name+".kicad_pcb")) != data["pcb_sha256"]:
        raise ValueError("Placed native board differs from its geometry manifest")
    folder = source / "routing_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Route the F1 fanout's explicit current, sense and test nets on both PCB faces") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"
        inputs.mkdir()
        paths = [Path(__file__), ROOT / "engineering/scripts/f1_board_routes.py",
                 ROOT / "engineering/scripts/f1_native_pcb.py",
                 ROOT / "engineering/scripts/write_f1_fanout_r2.py",
                 ROOT / "engineering/scripts/route_f1_wrist.py",
                 ROOT / "engineering/scripts/prototype_pcb.py",
                 ROOT / "engineering/scripts/prototype_route.py", native_path,
                 source / "specification.json", config_path]
        hashes = {}
        for path in paths:
            relative = path.relative_to(ROOT)
            target = inputs / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            hashes[str(relative)] = digest(path)
        board = NativeBoardGeometry(data)
        router = WristRouter(board, grid=config["routing_grid_mm"],
                               width=config["signal_trace_mm"],
                               via_diameter=config["via_diameter_mm"], via_drill=config["via_drill_mm"])
        # The checked mask optimization is shared with the wrist router;
        # the fanout retains the original four-layer routing costs.
        router.signal_layers = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
        router.layer_cost = (1, 8, 1, 1)
        progress = []
        started = time.monotonic()
        output = folder / "routing.json"

        def save(status, error=None):
            payload = {"schema": "yam-f1-routing-development/1", "status": status,
                       "input_hashes": hashes, "progress": progress,
                       "elapsed_s": round(time.monotonic()-started, 3),
                       "physical_specimens_tested": 0, **board.payload()}
            if error:
                payload["error"] = type(error).__name__+": "+str(error)
            output.write_text(json.dumps(payload, indent=2)+"\n")
            record["routing"] = {"directory": str(folder.relative_to(ROOT)), "status": status,
                                 "completed_steps": len(progress), "tracks": len(board.tracks), "vias": len(board.vias)}

        def note(kind, **values):
            progress.append({"step": len(progress), "kind": kind, **values})
            save("routing_in_progress")
            print(json.dumps(progress[-1]), flush=True)

        def pad(ref, number):
            return board.pad(ref, number)

        def pin_for(ref, net):
            matches = [p for p in board.pads if p["reference"] == ref and p["net"] == net]
            if len(matches) != 1:
                raise ValueError(f"Expected one {net} land on {ref}, found {len(matches)}")
            return matches[0]

        escape_points = {}

        def endpoint(p):
            return escape_points.get((p["reference"], p["pad"]), p["center"])

        def connect(a, b, width=.15, reason="signal"):
            if not a["net"] or a["net"] != b["net"]:
                raise ValueError(f"Invalid endpoint nets {a['net']}/{b['net']}")
            router.width = width
            router.connect(a["net"], endpoint(a), endpoint(b), time_limit_s=40)
            note("connection", start_pad=[a["reference"], a["pad"]],
                 end_pad=[b["reference"], b["pad"]], width_mm=width, reason=reason,
                 **router.routed[-1])

        try:
            # Pickoffs connect to the actual sensor-connector pad before any
            # long route. No implicit copper net ties or virtual shorts.
            sensor_columns = [p for p in board.pads if p["reference"].startswith("J")
                              and p["reference"].endswith("C") and p["net"]]
            for p in sorted(sensor_columns, key=lambda x: int(x["net"][1:-2])):
                other = pad("RK"+p["net"][:-2], "1")
                router.direct(p["net"], p["center"], other["center"], "B.Cu", .2)
                note("short_pickoff", net=p["net"], sensor=[p["reference"], p["pad"]],
                     link=[other["reference"], "1"])

            # Reserve contact/sense exits before broad row routes can enclose
            # a later pad. The prior attempt demonstrated this at J2C/C5_I.
            # Pickoff pad 1 already connects directly to its connector pad.
            # Every introduced via avoids paste on either populated face.
            small = [p for p in board.pads if p["net"]
                     and not (p["reference"].startswith("RKC") and p["pad"] == "1")]
            small.sort(key=lambda p: (0 if p["reference"] == "JW" else
                                      1 if p["reference"] == "UT" else 2,
                                      p["reference"], int(p["pad"])))
            for p in small:
                row_branch = p["net"].startswith("R") and p["net"].endswith("_I") and p["reference"] != "JW"
                router.width = .5 if row_branch else .15
                target = router.escape(p)
                escape_points[(p["reference"], p["pad"])] = target
                note("escape", reference=p["reference"], pad=p["pad"], net=p["net"], target_mm=target)

            # Reserve control and supply paths while every small service-pad
            # escape is still open. Long current/sense branches otherwise
            # enclosed A1/A2 in the preceding preserved attempts.
            for net in ("+3V3", "A0", "A1", "A2", "A3", "TEST_EN", "TEST_D"):
                nodes = [p for p in board.pads if p["net"] == net]
                connected = [nodes.pop(0)]
                while nodes:
                    import math
                    _, a, index = min((math.dist(endpoint(a), endpoint(b)), ai, bi)
                                     for ai, a in enumerate(connected) for bi, b in enumerate(nodes))
                    new = nodes.pop(index)
                    connect(connected[a], new, .15, "reserved test/power service")
                    connected.append(new)

            # Reserve the test mux's constrained lower-pad routes before long
            # branches enclose its escape vias beside a mounting keepout.
            # The first R2 attempt failed at C12_I after the other branches.
            column_by_number = {int(p["net"][1:-2]): p for p in sensor_columns}
            test_order = [12, 13, 11, 14, 10, 15, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
            for number in test_order:
                p = column_by_number[number]
                connect(pin_for("UT", p["net"]), p, .15,
                        "reserve test-mux escape to the sensor pickup")

            # All row branch routes begin at the measured distribution land.
            # Parallel/merged same-net copper can reduce the DC path resistance,
            # which will be assessed from the final copper network.
            for row in range(4):
                net = f"R{row}_I"
                star = pad(f"RKR{row}", "1")
                connect(pin_for("JW", net), star, .5, "row current to distribution land")
                for patch in (0, 1, 2, 3, 4, 5):
                    connect(star, pin_for(f"J{patch}R", net), .5, "row distribution branch")

            for p in sorted(sensor_columns, key=lambda x: int(x["net"][1:-2])):
                net = p["net"]
                connect(pin_for("JW", net), p, .15, "column current to sensor connector")

            for name in [f"C{i}" for i in range(16)] + [f"R{i}" for i in range(4)]:
                connect(pin_for("JW", name+"_S"), pad("RK"+name, "2"),
                        .15, "separate high-impedance sense conductor")

            for p in board.pads:
                if p["net"] == "GND" and (p["reference"], p["pad"]) not in escape_points:
                    router.width = .15
                    target = router.escape(p)
                    escape_points[(p["reference"], p["pad"])] = target
                    note("ground_escape", reference=p["reference"], pad=p["pad"], target_mm=target)
            board.zones.append({"net": "GND", "layer": "In1.Cu", "shape": board.outline.buffer(-board.edge)})
            removed = board.prune_unused_vias()
            note("prune_redundant_vias", removed=removed)
            save("all_connections_routed_independent_drc_pending")
            command = [str(KICAD_PYTHON), str(ROOT / "engineering/scripts/write_f1_fanout_r2.py"),
                       str(source / "specification.json"), str(folder / "board"), "--routing", str(output)]
            with (folder / "native_board.log").open("w") as stream:
                process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
                record["native_writer"] = {"argv": command, "pid": process.pid}
                try:
                    code = process.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    record["native_writer"]["intentional_stop"] = "50 s limit on this owned native board writer"
                    process.terminate(); process.wait(timeout=10)
                    raise
            record["native_writer"]["returncode"] = code
            if code:
                print((folder / "native_board.log").read_text()[-4000:])
                raise RuntimeError(f"Native board writer exited {code}")
        except Exception as error:
            save("failed_partial_routes_preserved", error)
            print("Preserved routing attempt:", folder, flush=True)
            raise
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), "tracks": len(board.tracks),
                          "vias": len(board.vias), "independent_drc_pending": True}, indent=2))


if __name__ == "__main__":
    main()
