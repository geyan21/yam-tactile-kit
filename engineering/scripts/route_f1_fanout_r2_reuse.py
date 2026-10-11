#!/usr/bin/python3
"""Route R2 while reusing existing same-net vias without drilling new holes."""

import argparse
import copy
from datetime import datetime, timezone
import json
import math
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
from screen_f1_feedback import digest

KICAD_PYTHON = ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/python3.11"


class FanoutRouter(WristRouter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.temporary_endpoints = {}

    def endpoint_layers(self, net, point):
        key = (net, tuple(point))
        if key in self.temporary_endpoints:
            return tuple(i for i, layer in enumerate(self.signal_layers)
                         if layer == self.temporary_endpoints[key])
        return super().endpoint_layers(net, point)

    def obstacles(self, net):
        free, via_free, inside, forbidden = super().obstacles(net)
        # The inherited new-hole mask correctly excludes existing drills.
        # Reusing an already present same-net through-via is a different
        # operation. Board.via() deduplicates an exact same-net coordinate.
        for via in self.board.vias:
            if via["net"] != net:
                continue
            x, y = via["center"]
            ix, iy = round((x-self.x0)/self.grid), round((y-self.y0)/self.grid)
            if not (0 <= ix < self.nx and 0 <= iy < self.ny):
                continue
            if math.dist(self.coordinate(ix, iy), via["center"]) > 1e-7:
                continue
            if free[:, iy, ix].all():
                via_free[iy, ix] = True
        return free, via_free, inside, forbidden


def make_router(board, config):
    router = FanoutRouter(board, grid=config["routing_grid_mm"], width=config["signal_trace_mm"],
                         via_diameter=config["via_diameter_mm"], via_drill=config["via_drill_mm"])
    router.signal_layers = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
    router.layer_cost = (1, 8, 1, 1)
    return router


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement_run", type=Path)
    parser.add_argument("--maximum-attempts", type=int, default=8)
    args = parser.parse_args()
    source = args.placement_run.resolve()
    if not source.is_relative_to(ROOT) or not 1 <= args.maximum_attempts <= 12:
        parser.error("Use a repository-owned placement and 1–12 bounded attempts")
    spec_path = source / "specification.json"
    spec = json.loads(spec_path.read_text())
    name = spec["name"]
    if name != "f1_fanout_r2" or not json.loads((source / "placement_check.json").read_text())["passed"]:
        raise ValueError("Use a checked R2 placement")
    native_path = source / "placement" / (name+".json")
    data = json.loads(native_path.read_text())
    if digest(source / "placement" / (name+".kicad_pcb")) != data["pcb_sha256"]:
        raise ValueError("Placement changed after geometry extraction")
    config_path = source / "inputs/engineering/designs/f1_fanout_development.json"
    config = json.loads(config_path.read_text())
    folder = source / "via_reuse_routing_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Route complete F1 R2 nets with bounded priority repair; retain every unsuccessful order and never exclude a required connection") as record:
        folder.mkdir(parents=True, exist_ok=False)
        paths = [spec_path, native_path, config_path, Path(__file__),
                 ROOT / "engineering/scripts/f1_board_routes.py", ROOT / "engineering/scripts/route_f1_wrist.py",
                 ROOT / "engineering/scripts/prototype_route.py", ROOT / "engineering/scripts/prototype_pcb.py",
                 ROOT / "engineering/scripts/write_f1_fanout_r2.py", ROOT / "engineering/scripts/f1_native_pcb.py"]
        hashes = {}
        for path in paths:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            hashes[str(path.relative_to(ROOT))] = digest(path)
        base = NativeBoardGeometry(data)
        router = make_router(base, config)
        by_key = {(p["reference"], p["pad"]): p for p in base.pads}
        def pin_for(ref, net):
            found = [key for key, pad in by_key.items() if key[0] == ref and pad["net"] == net]
            if len(found) != 1:
                raise ValueError(f"Expected exactly one {ref}/{net} land")
            return found[0]
        columns = sorted([p for p in base.pads if p["reference"].startswith("J")
                          and p["reference"].endswith("C") and p["net"]],
                         key=lambda p: int(p["net"][1:-2]))
        for p in columns:
            link = base.pad("RK"+p["net"][:-2], "1")
            router.direct(p["net"], p["center"], link["center"], "B.Cu", .2)
        escapes = {}
        pads = [p for p in base.pads if p["net"]
                and not (p["reference"].startswith("RKC") and p["pad"] == "1")]
        pads.sort(key=lambda p: (0 if p["reference"] == "JW" else 1 if p["reference"] == "UT" else 2,
                                p["reference"], int(p["pad"])))
        for p in pads:
            router.width = .5 if p["net"].startswith("R") and p["net"].endswith("_I") and p["reference"] != "JW" else .15
            escapes[(p["reference"], p["pad"])] = router.escape(p)
        # Near-pad vias alone were repeatedly enclosed by later through-vias.
        # Extend every mux signal/power escape on a known inner layer before
        # long wiring. The finished endpoint is a real routed trace endpoint.
        stubs = []
        mux_pads = sorted((p for p in pads if p["reference"] == "UT"),
                          key=lambda p: (p["center"][1], p["center"][0]))
        for p in mux_pads:
            if p["net"] == "GND":
                continue
            key = (p["reference"], p["pad"])
            top = int(p["pad"]) >= 15
            layer = "In2.Cu" if top else "In1.Cu"
            end = [p["center"][0], 8.0 if top else 26.0]
            router.signal_layers, router.layer_cost = (layer,), (1,)
            router.width = .15
            router.temporary_endpoints[(p["net"], tuple(end))] = layer
            try:
                router.connect(p["net"], escapes[key], end, time_limit_s=30)
            finally:
                router.temporary_endpoints.clear()
            escapes[key] = end
            stubs.append({"reference": p["reference"], "pad": p["pad"], "net": p["net"],
                          "end_mm": end, "layer": layer, **router.routed[-1]})
            (folder / "partial_base.json").write_text(json.dumps(
                {"input_hashes": hashes, "mux_escape_stubs": stubs, **base.payload()}, indent=2)+"\n")
            print("Reserved mux escape:", p["net"], layer, flush=True)
        router.signal_layers, router.layer_cost = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"), (1, 8, 1, 1)
        def endpoint(key):
            return escapes.get(key, by_key[key]["center"])
        groups = {}
        def task(a, b, width, reason):
            net = by_key[a]["net"]
            if not net or net != by_key[b]["net"]:
                raise ValueError("Task connects different nets")
            groups.setdefault(net, []).append({"a": a, "b": b, "width_mm": width, "reason": reason})
        for row in range(4):
            net = f"R{row}_I"
            star = (f"RKR{row}", "1")
            task(pin_for("JW", net), star, .5, "row current to distribution land")
            for site in range(6):
                task(star, pin_for(f"J{site}R", net), .5, "row branch")
        for p in columns:
            key, net = (p["reference"], p["pad"]), p["net"]
            task(pin_for("UT", net), key, .15, "switched test at sensor pickup")
            task(pin_for("JW", net), key, .15, "column current")
        for stem in [f"C{i}" for i in range(16)]+[f"R{i}" for i in range(4)]:
            task(pin_for("JW", stem+"_S"), ("RK"+stem, "2"), .15, "separate sense")
        for net in ("+3V3", "A0", "A1", "A2", "A3", "TEST_EN", "TEST_D"):
            nodes = [key for key, pad in by_key.items() if pad["net"] == net]
            connected = [nodes.pop(0)]
            while nodes:
                _, ai, bi = min((math.dist(endpoint(a), endpoint(b)), ai, bi)
                                 for ai, a in enumerate(connected) for bi, b in enumerate(nodes))
                new = nodes.pop(bi)
                task(connected[ai], new, .15, "test/power service")
                connected.append(new)
        priorities = ["C5_S", "C12_I", "A1", "A2", "TEST_EN", "A3", "A0",
                      "+3V3", "TEST_D", "C4_S", "C6_S",
                      "R0_I", "R1_I", "R2_I", "R3_I"]
        order = priorities+[net for net in groups if net not in priorities]
        base_report = {**base.payload(), "endpoints": [
            {"reference": key[0], "pad": key[1], "point": value} for key, value in sorted(escapes.items())],
                       "input_hashes": hashes, "tasks_by_net": groups, "mux_escape_stubs": stubs,
                       "existing_via_reuse": "Only exact same-net coordinates with clear track masks; the native writer deduplicates existing holes."}
        (folder / "base_escapes.json").write_text(json.dumps(base_report, indent=2)+"\n")
        history = []
        successful = None
        for attempt in range(args.maximum_attempts):
            trial = folder / f"attempt_{attempt+1:02d}"
            trial.mkdir()
            board = copy.deepcopy(base)
            router = make_router(board, config)
            begun = time.monotonic()
            completed = []
            current_net = None
            payload_path = trial / "routing.json"
            def save(status, error=None):
                payload = {"schema": "yam-f1-r2-via-reuse-routing/1", "status": status,
                           "input_hashes": hashes, "net_order": order.copy(), "completed": completed,
                           "base_escapes_sha256": digest(folder / "base_escapes.json"),
                           "elapsed_s": time.monotonic()-begun, "physical_specimens_tested": 0,
                           **board.payload()}
                if error:
                    payload["error"] = {"net": current_net, "type": type(error).__name__, "message": str(error)}
                payload_path.write_text(json.dumps(payload, indent=2)+"\n")
            print(f"Attempt {attempt+1}: {len(groups)} complete nets, {sum(map(len, groups.values()))} required branches", flush=True)
            try:
                for current_net in order:
                    for item in groups[current_net]:
                        router.width = item["width_mm"]
                        router.connect(current_net, endpoint(item["a"]), endpoint(item["b"]), time_limit_s=40)
                        completed.append({**item, **router.routed[-1]})
                    save("routing_in_progress")
                    if len(completed) % 10 == 0 or current_net in priorities:
                        print(f"  {current_net}: {len(completed)} branches, {len(board.tracks)} segments, {len(board.vias)} vias", flush=True)
                board.zones.append({"net": "GND", "layer": "In1.Cu", "shape": board.outline.buffer(-board.edge)})
                board.prune_unused_vias()
                save("all_connections_routed_independent_drc_pending")
                successful = trial
                history.append({"attempt": attempt+1, "passed_routing": True, "branches": len(completed)})
                break
            except (ValueError, RuntimeError, TimeoutError) as error:
                save("failed_partial_routes_preserved", error)
                history.append({"attempt": attempt+1, "passed_routing": False, "failed_net": current_net,
                                "branches": len(completed), "message": str(error)})
                print(f"  Preserved failure on {current_net}: {error}", flush=True)
                # Start again from the unchanged pad escapes; moving the
                # blocked net first is a complete reroute, not deleted work.
                order.remove(current_net)
                order.insert(0, current_net)
            finally:
                (folder / "attempts.json").write_text(json.dumps(history, indent=2)+"\n")
        record["attempts"] = {"directory": str(folder.relative_to(ROOT)), "history": history}
        if successful is None:
            raise RuntimeError("Bounded R2 routing attempts ended without a complete board; failures retained")
        command = [str(KICAD_PYTHON), str(ROOT / "engineering/scripts/write_f1_fanout_r2.py"),
                   str(spec_path), str(successful / "board"), "--routing", str(successful / "routing.json")]
        with (successful / "native.log").open("w") as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            record["native"] = {"command": command, "pid": process.pid}
            try:
                code = process.wait(timeout=50)
            except subprocess.TimeoutExpired:
                record["native"]["intentional_stop"] = "50 second limit on owned native writer"
                process.terminate()
                process.wait(timeout=5)
                raise
        record["native"]["exit_code"] = code
        if code:
            raise RuntimeError((successful / "native.log").read_text()[-3000:])
        record["result"] = {"directory": str(successful.relative_to(ROOT)), "tracks": len(board.tracks),
                            "vias": len(board.vias), "independent_drc_pending": True}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
