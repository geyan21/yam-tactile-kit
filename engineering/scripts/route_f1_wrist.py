#!/usr/bin/python3
"""Route a checked F1 wrist placement while preserving local analog connections."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

from shapely.geometry import Point
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_board_routes import NativeBoardGeometry, TwoFaceRouter
from prototype_route import Router
from screen_f1_feedback import digest

KICAD_PYTHON = ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/python3.11"


class WristRouter(TwoFaceRouter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.signal_layers = ("F.Cu", "In2.Cu", "B.Cu")
        self.layer_cost = (1, 1.5, 1)

    def obstacles(self, net):
        # Same conservative drill spacing as TwoFaceRouter, rasterized once
        # after combining the drill envelopes instead of once per hole.
        free, via_free, inside, forbidden = Router.obstacles(self, net)
        holes = [Point(via["center"]).buffer(via["drill"]/2+self.via_drill/2+.25+self.guard)
                 for via in self.board.vias]
        for pad in self.board.pads:
            if pad.get("through_hole"):
                radius = max(pad["drill_mm"])/2+self.via_drill/2+.25+self.guard
                holes.append(Point(pad["center"]).buffer(radius))
        if holes:
            via_free &= ~self.mask(unary_union(holes))
        return free, via_free, inside, forbidden

    def escape(self, pad):
        if pad.get("through_hole"):
            return pad["center"]
        return super().escape(pad)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement_run", type=Path)
    parser.add_argument("--resume-routing", type=Path,
                        help="Preserved routing JSON for the identical placement")
    args = parser.parse_args()
    source = args.placement_run.resolve()
    if not source.is_relative_to(ROOT):
        parser.error("Use a repository-owned placement run")
    if not json.loads((source / "placement_check.json").read_text())["passed"]:
        raise ValueError("Resolve all placement findings before routing")
    spec = json.loads((source / "specification.json").read_text())
    config = json.loads((source / "inputs/f1_wrist_development.json").read_text())
    data = json.loads((source / "placement/f1_wrist.json").read_text())
    if digest(source / "placement/f1_wrist.kicad_pcb") != data["pcb_sha256"]:
        raise ValueError("Placed board changed after native geometry extraction")
    previous_run = args.resume_routing.resolve() if args.resume_routing else None
    if previous_run and not previous_run.is_relative_to(ROOT):
        parser.error("Resume only a repository-owned saved routing result")
    folder = source / "routing_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Route F1 wrist analog nets first, reserve surface-pad exits and preserve the internal ground plane; retain any partial failure") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        paths = [Path(__file__), ROOT / "engineering/scripts/f1_wrist_native.py",
                 ROOT / "engineering/scripts/f1_board_routes.py", ROOT / "engineering/scripts/prototype_route.py",
                 ROOT / "engineering/scripts/prototype_pcb.py", source / "specification.json",
                 source / "inputs/f1_wrist_development.json", source / "placement/f1_wrist.json"]
        hashes = {}
        for path in paths:
            target = inputs / path.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target); hashes[str(path.relative_to(ROOT))] = digest(path)
        board = NativeBoardGeometry(data)
        router = WristRouter(board, grid=config["routing_grid_mm"], width=config["signal_trace_mm"],
                             via_diameter=config["via_diameter_mm"], via_drill=config["via_drill_mm"])
        by_key = {(p["reference"], p["pad"]): p for p in board.pads}
        nets = {}
        for key, pad in by_key.items():
            if pad["net"]:
                nets.setdefault(pad["net"], []).append(key)
        parent = {key: key for key in by_key}
        def root(key):
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key
        def union(a, b):
            parent[root(a)] = root(b)
        escapes = {}
        progress = []
        if previous_run:
            shutil.copyfile(previous_run, inputs / "resume_routing.json")
            previous = json.loads(previous_run.read_text())
            for path in (source / "specification.json", source / "placement/f1_wrist.json"):
                if previous["input_hashes"].get(str(path.relative_to(ROOT))) != digest(path):
                    raise ValueError("Saved routing used different placement geometry")
            for track in previous["tracks"]:
                board.trace(track["net"], [track["start"], track["end"]], track["layer"], track["width"])
            for via in previous["vias"]:
                board.via(via["net"], via["center"], via["diameter"], via["drill"])
            progress = list(previous["progress"])
            for item in progress:
                if item["kind"] == "connection":
                    union(tuple(item["a"]), tuple(item["b"]))
            if previous.get("endpoints"):
                for item in previous["endpoints"]:
                    escapes[(item["reference"], item["pad"])] = item["point"]
            else:
                # Older checkpoints retain the actual pad-to-via traces.
                # Recover only endpoints connected by those saved traces.
                for key, pad in by_key.items():
                    if pad.get("through_hole"):
                        escapes[key] = pad["center"]
                        continue
                    for track in board.tracks:
                        if track["net"] != pad["net"]:
                            continue
                        if math.dist(track["start"], pad["center"]) < 1e-6:
                            end = track["end"]
                        elif math.dist(track["end"], pad["center"]) < 1e-6:
                            end = track["start"]
                        else:
                            continue
                        if any(v["net"] == pad["net"] and math.dist(v["center"], end) < 1e-6 for v in board.vias):
                            escapes[key] = end
                            break
                for key in by_key:
                    if key not in escapes:
                        other = next((k for k in escapes if root(k) == root(key)), None)
                        if other is not None:
                            escapes[key] = escapes[other]
            record["resume"] = {"source": str(previous_run.relative_to(ROOT)), "sha256": digest(previous_run),
                                "tracks": len(board.tracks), "vias": len(board.vias)}
        started = time.monotonic()
        def save(status, error=None):
            report = {"schema": "yam-f1-wrist-routing/1", "status": status, "input_hashes": hashes,
                      "elapsed_s": time.monotonic()-started, "progress": progress,
                      "resumed_from": str(previous_run.relative_to(ROOT)) if previous_run else None,
                      "resumed_from_sha256": digest(previous_run) if previous_run else None,
                      "endpoints": [{"reference": key[0], "pad": key[1], "point": value}
                                    for key, value in sorted(escapes.items())],
                      "physical_boards_tested": 0, **board.payload()}
            report["inner_ground_layer_signal_length_mm"] = {
                net: sum(math.dist(t["start"], t["end"]) for t in board.tracks if t["layer"] == "In1.Cu" and t["net"] == net)
                for net in {t["net"] for t in board.tracks if t["layer"] == "In1.Cu"}
            }
            if error:
                report["error"] = type(error).__name__+": "+str(error)
            (folder / "routing.json").write_text(json.dumps(report, indent=2)+"\n")
            record["routing"] = {"directory": str(folder.relative_to(ROOT)), "status": status,
                                 "tracks": len(board.tracks), "vias": len(board.vias), "steps": len(progress)}
        def note(kind, **values):
            item = {"step": len(progress), "kind": kind, **values}
            progress.append(item)
            if kind != "escape" or len(progress) % 20 == 0:
                save("routing_in_progress")
                print(json.dumps(item), flush=True)
        def endpoint(key):
            return escapes.get(key, by_key[key]["center"])
        def connect(a, b, width=.15, local=False, reason="net"):
            if root(a) == root(b):
                return
            first, second = by_key[a], by_key[b]
            if not first["net"] or first["net"] != second["net"]:
                raise ValueError(f"Connection joins different nets: {a}/{b}")
            before = router.width
            router.width = width
            common = set(first["layers"]).intersection(second["layers"])
            face = next((s for s in ("F.Cu", "B.Cu") if s in common), None)
            direct = False
            if face and a not in escapes and b not in escapes:
                try:
                    router.direct(first["net"], endpoint(a), endpoint(b), face, width)
                    direct = True
                except ValueError:
                    pass
            if not direct:
                original_layers, original_costs = router.signal_layers, router.layer_cost
                if local and face:
                    router.signal_layers, router.layer_cost = (face,), (1,)
                try:
                    try:
                        router.connect(first["net"], endpoint(a), endpoint(b), time_limit_s=30)
                    except ValueError as error:
                        if local or "No route" not in str(error):
                            raise
                        # Permit an expensive, short ground-layer crossing
                        # only when all three normal signal layers are blocked.
                        router.signal_layers = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")
                        router.layer_cost = (1, 20, 1.5, 1)
                        router.connect(first["net"], endpoint(a), endpoint(b), time_limit_s=30)
                        note("inner_ground_layer_crossing", net=first["net"],
                             a=list(a), b=list(b), review_required=True)
                finally:
                    router.signal_layers, router.layer_cost = original_layers, original_costs
            router.width = before
            union(a, b)
            note("connection", net=first["net"], a=list(a), b=list(b), reason=reason,
                 direct=direct, local_face=face if local else None)
        def complete_net(net, local=False):
            keys = nets[net]
            while len({root(k) for k in keys}) > 1:
                _, a, b = min((math.dist(endpoint(a), endpoint(b)), a, b) for a in keys for b in keys
                              if a < b and root(a) != root(b))
                width = .4 if net in ("+3V3", "+5V", "VREF33") or (net.startswith("R") and net.endswith("_I")) else .15
                connect(a, b, width, local, "local analog" if local else "remaining net")
        digital = {"SPI_SCK", "SPI_MISO", "SPI_MOSI", "ADC_CONV", "MON_CS", "CUR_EN", "SNS_EN", "TEST_EN", "PARK"}
        digital |= {f"A{i}" for i in range(4)} | {f"ROW{i}" for i in range(4)} | {f"GAIN{i}" for i in range(4)}
        local_nets = []
        for net, keys in nets.items():
            if net in digital or net in ("GND", "+3V3", "+5V", "VREF33", "VBIAS", "VEXCITE"):
                continue
            if net.startswith("ROW") and net.endswith("_CMD"):
                continue
            if any(key[0] in ("JW", "JP1", "JP2") for key in keys):
                continue
            layers = set.intersection(*(set(by_key[key]["layers"]) for key in keys))
            span = max((math.dist(by_key[a]["center"], by_key[b]["center"]) for a in keys for b in keys), default=0)
            if span <= 18 and any(face in layers for face in ("F.Cu", "B.Cu")):
                local_nets.append(net)

        def reserve_exits():
            # Reserve every connection leaving a local circuit block, rather
            # than discovering an enclosed supply/sense pin after routing it.
            selected = {}
            for net, keys in nets.items():
                if net in local_nets:
                    continue
                if net == "GND" or len({root(k) for k in keys}) > 1:
                    for key in keys:
                        selected.setdefault(root(key), []).append(key)
            groups = sorted(selected.values(), key=lambda keys: (
                0 if any(k[0] == "JW" for k in keys) else
                1 if len(keys) == 1 and keys[0][0].startswith("U") else 2, keys[0]))
            for keys in groups:
                # A connected chip/capacitor pair needs one escape, not an
                # unnecessary extra via at every already-connected land.
                known = next((escapes[k] for k in keys if k in escapes), None)
                chosen = None
                if known is None:
                    candidates = sorted(keys, key=lambda k: (
                        0 if by_key[k].get("through_hole") else
                        1 if k[0].startswith(("R", "C")) else 2, k))
                    for key in candidates:
                        pad = by_key[key]
                        router.width = .2 if pad["net"] in ("GND", "+3V3", "+5V") else .15
                        try:
                            known = router.escape(pad)
                            chosen = key
                            break
                        except ValueError as error:
                            if "No via escape" not in str(error):
                                raise
                    if known is None:
                        raise ValueError(f"No exit for connected pad group: {keys}")
                for key in keys:
                    escapes[key] = known
                note("escape", pad=list(chosen) if chosen else list(keys[0]), net=by_key[keys[0]]["net"],
                     connected_pads=len(keys), reused=chosen is None)

        try:
            if not previous_run:
                # Short supply-to-bypass connections get explicit surface routes.
                for ref, pin, cap, cap_pin in spec["power_bypass_pairs"]:
                    connect((ref, pin), (cap, cap_pin), .25, True, "local supply bypass")
                for ref in ("UBIAS", "UEXC", "UAB"):
                    connect((ref, "1"), (ref, "4"), .15, True, "local unity feedback")
                reserve_exits()
                for index in range(4):
                    for pin in ("1", "2"):
                        connect((f"RTIA{index}", pin), (f"CTIA{index}", pin), .15, True, "parallel gain resistor/capacitor")
                for net in sorted(local_nets):
                    complete_net(net, True)
                # Reference sense pickup links connect to the ADC pads explicitly.
                connect(("RREFS", "2"), ("UADC", "1"), .25, reason="ADC reference sense pickup")
                connect(("RGNDS", "2"), ("UADC", "5"), .25, reason="ADC ground sense pickup")
                reserve_exits()
            analog_first = ("TIA_FB", "COMP_MID", "SENSE_D", "AMP_OUT", "OUTPUT_BUS", "CURRENT_D",
                            "VBIAS", "VEXCITE", "VREF_SENSE", "REF_GND_SENSE", "VREF33")
            order = [name for name in analog_first if name in nets]
            order += [name for name in sorted(nets) if name not in order and name != "GND"]
            for net in order:
                complete_net(net)
                note("net_complete", net=net)
            board.zones.append({"net": "GND", "layer": "In1.Cu", "shape": board.outline.buffer(-board.edge)})
            removed = board.prune_unused_vias()
            note("prune_unused_vias", removed=removed)
            save("all_connections_routed_independent_drc_pending")
            command = [str(KICAD_PYTHON), str(ROOT / "engineering/scripts/f1_wrist_native.py"),
                       str(source / "specification.json"), str(folder / "board"),
                       "--routing", str(folder / "routing.json")]
            with (folder / "native.log").open("w") as stream:
                process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
                record["native"] = {"command": command, "pid": process.pid}
                try:
                    code = process.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    record["native"]["intentional_stop"] = "50 second limit on owned native writer"
                    process.terminate(); process.wait(timeout=5)
                    raise
            record["native"]["exit_code"] = code
            if code:
                raise RuntimeError((folder / "native.log").read_text()[-4000:])
        except Exception as error:
            save("failed_partial_routing_preserved", error)
            print("Preserved failed routing:", folder, flush=True)
            raise
        print(json.dumps(record["routing"], indent=2))


if __name__ == "__main__":
    main()
