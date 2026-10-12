#!/usr/bin/python3
"""Extract F1 fanout port networks and record the routed copper resistance scenarios."""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_routed_copper import CopperNetwork, effective_resistance
from screen_f1_feedback import digest

BOARD = ROOT / "engineering/development/f1/r3/pcb/f1_fanout_r3.json"
TARGET = ROOT / "engineering/designs/f1_fanout_manufacturing_targets.json"
FOILS = ROOT / "engineering/development/f1/fitted-foils-r3/provenance/artwork.json"


def numerical_controls():
    rho = .00001724; width = .5; thickness = .035
    def pad(ref, x, layer):
        return {"reference": ref, "pad": "1", "net": "TEST", "center": [x, 0.],
                "size": [.1, .2], "rotation": 0., "layers": [layer]}
    track = {"net": "TEST", "start": [0., 0.], "end": [10., 0.], "width": width, "layer": "F.Cu"}
    board = {"tracks": [track], "pads": [pad("A", 0., "F.Cu"), pad("B", 10., "F.Cu")], "vias": []}
    expected = rho*9.9/(width*thickness)
    results = []
    for duplicate in (False, True):
        board["tracks"] = [dict(track)]*(2 if duplicate else 1)
        net = CopperNetwork(board, "TEST", rho, thickness, 1, .020, 1.)
        observed = effective_resistance(net.reduce([("A", "1"), ("B", "1")]), 0, 1)
        results.append({"kind": "duplicate_overlap" if duplicate else "one_strip",
                       "expected": expected, "observed": observed})
    board["tracks"] = [
        {**track, "end": [5., 0.]},
        {**track, "start": [5., 0.], "layer": "B.Cu"}]
    board["pads"] = [pad("A", 0., "F.Cu"), pad("B", 10., "B.Cu")]
    board["vias"] = [{"net": "TEST", "center": [5., 0.], "diameter": .45, "drill": .2}]
    net = CopperNetwork(board, "TEST", rho, thickness, 1, .020, 1.)
    expected_via = expected+rho/(math.pi*.2*.020)
    observed = effective_resistance(net.reduce([("A", "1"), ("B", "1")]), 0, 1)
    results.append({"kind": "one_barrel", "expected": expected_via, "observed": observed})
    if any(abs(row["observed"]/row["expected"]-1) > 1e-9 for row in results):
        raise ValueError("Routed metal controls failed")
    return results


def main():
    board = json.loads(BOARD.read_text()); targets = json.loads(TARGET.read_text())
    if digest(BOARD.with_suffix(".kicad_pcb")) != board["pcb_sha256"]:
        raise ValueError("Native fanout PCB identity changed")
    metadata = json.loads(FOILS.read_text())
    connectors = {entry["metadata"]["site"]: entry["metadata"]["connector"]
                  for entry in metadata["boards"] if entry["metadata"]["role"] == "rows"}
    resistivity = targets["resistance_screen"]["copper_resistivity_ohm_mm_at_20c"]
    heat = 1+targets["resistance_screen"]["copper_temperature_coefficient_per_c"]*30
    scenarios = {
        "nominal": {"rho": resistivity, "copper_mm": .035, "width_factor": 1., "via_wall_mm": .020, "via_length_mm": 1.0},
        "hot_minimum": {"rho": resistivity*heat, "copper_mm": .0315, "width_factor": .8, "via_wall_mm": .020, "via_length_mm": 1.1}}
    folder = ROOT / "build/engineering/prototypes/f1/routed_network_reviews" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Build F1 current-net port models from the checked fanout's actual traces, pads and vias; retain row sensing at its real pickup rather than assuming a star distribution") as record:
        folder.mkdir(parents=True)
        record["run_directory"] = str(folder.relative_to(ROOT))
        inputs = [BOARD, BOARD.with_suffix(".kicad_pcb"), TARGET, FOILS, Path(__file__),
                  ROOT / "engineering/scripts/f1_routed_copper.py"]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        controls = numerical_controls()
        rows = []
        for scenario, values in scenarios.items():
            for net in [f"R{i}_I" for i in range(4)]+[f"C{i}_I" for i in range(16)]:
                pads = [p for p in board["pads"] if p["net"] == net]
                cable = next(p for p in pads if p["reference"] == "JW")
                is_row = net.startswith("R"); number = int(net[1:-2])
                pick = (("RKR" if is_row else "RKC")+str(number), "1")
                ports = [(cable["reference"], cable["pad"]), pick]
                branches = {}
                if is_row:
                    for site, connector in sorted(connectors.items()):
                        p = next(p for p in pads if p["reference"] == connector)
                        branches[site] = len(ports); ports.append((p["reference"], p["pad"]))
                else:
                    p = next(p for p in pads if p["reference"].startswith("J") and p["reference"].endswith("C"))
                    branches["electrode"] = len(ports); ports.append((p["reference"], p["pad"]))
                network = CopperNetwork(board, net, values["rho"], values["copper_mm"],
                                        values["width_factor"], values["via_wall_mm"], values["via_length_mm"])
                reduced = network.reduce(ports)
                entry = {"scenario": scenario, "net": net, "ports": [list(p) for p in ports],
                         "cable_port": 0, "sense_pickoff_port": 1, "branch_ports": branches,
                         "conductance_matrix_s": reduced.tolist(),
                         "original_nodes": len(network.matrix), "tracks": network.track_count,
                         "vias": network.via_count,
                         "cable_to_pickoff_ohm": effective_resistance(reduced, 0, 1),
                         "pickoff_to_branch_ohm": {key: effective_resistance(reduced, 1, value) for key, value in branches.items()}}
                rows.append(entry)
                (folder / "partial.json").write_text(json.dumps(rows, indent=2)+"\n")
                print(scenario+" "+net+": "+str(len(ports))+" ports", flush=True)
        report = {"schema": "yam-f1-routed-port-network/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "scenarios": scenarios, "networks": rows, "controls": controls,
                  "limits": ["PCB centre-line resistor model with ideal equipotential pads; 2D pad and junction spreading are not solved.",
                             "Via-star pair approximation uses the full board thickness; actual interlayer positions and branching barrel fields are not given.",
                             "The 50 °C, reduced copper/width and 20 µm via-wall scenarios require fabrication confirmation.",
                             "This is not a measured board, complete array response or force/contact calibration."]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "networks": len(rows), "controls_passed": True}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
