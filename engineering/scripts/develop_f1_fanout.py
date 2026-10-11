#!/usr/bin/python3
"""Build and check F1's two-sided fanout placement before copper routing."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

from shapely import affinity
from shapely.geometry import Polygon, Point, box

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

KICAD_PYTHON = ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/python3.11"
CONFIG = ROOT / "engineering/designs/f1_fanout_development.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def transform(shape, part):
    if part.get("side", "F") == "B":
        shape = affinity.scale(shape, xfact=-1, yfact=1, origin=(0, 0))
    shape = affinity.rotate(shape, -part.get("rotation_deg", 0), origin=(0, 0))
    return affinity.translate(shape, *part["center_mm"])


def passive(ref, value, center, nets, side="F", rotation=0, kind="resistor", source=""):
    library = ("Capacitor_SMD.pretty/C_0402_1005Metric.kicad_mod" if kind == "capacitor"
               else "Resistor_SMD.pretty/R_0402_1005Metric.kicad_mod")
    return {"reference": ref, "value": value, "center_mm": center,
            "side": side, "rotation_deg": rotation, "library": library,
            "body_envelope_mm": [-.5, -.25, .5, .25], "height_mm": .55,
            "source": source, "nets": {"1": nets[0], "2": nets[1]}}


def specification(config, placement):
    board = Polygon([[-y, 44-z] for y, z in placement["contoured_board_native_yz_mm"]])
    # Remove tiny source facets within an inward margin. Recheck the result
    # against the screened contour so simplification cannot add material in
    # the assumed contact/access band.
    outline = board.buffer(-.04, join_style="mitre").simplify(.01)
    if not outline.is_valid or not board.buffer(1e-8).covers(outline):
        raise ValueError("Simplified outline escaped the checked placement region")
    parts = []
    sensor = config["sensor_connector"]
    pairs = placement["adjusted_connector_pairs"]
    for patch, pair in enumerate(config["patch_to_connector_pair"]):
        y, z = pairs[pair]["datum_yz_mm"]
        for kind, side, pins in (
                ("R", "F", sensor["row_pins"]),
                ("C", "B", sensor["column_pins_by_patch"][patch])):
            pads = [{"pad": str(p+1), "center_mm": [(p-2.5)*sensor["signal_pitch_mm"],
                      sensor["signal_pad_y_mm"]], "size_mm": sensor["signal_pad_size_mm"]}
                    for p in range(6)]
            pads += [{"pad": f"MP{i+1}", "center_mm": center,
                      "size_mm": sensor["mount_pad_size_mm"]}
                     for i, center in enumerate(sensor["mount_pad_centers_mm"])]
            ref = f"J{patch}{kind}"
            parts.append({
                "reference": ref, "value": sensor["part"], "center_mm": [-y, 44-z],
                "side": side, "rotation_deg": 0, "pads": pads,
                "nets": {str(p+1): pins.get(str(p+1), "") for p in range(6)},
                "body_envelope_mm": sensor["body_envelope_mm"],
                "courtyard_mm": [-6.05, -2.75, 6.05, 4.65],
                "height_mm": sensor["closed_height_mm"], "source": sensor["source"],
                "patch": patch, "electrode": "rows" if kind == "R" else "columns"
            })
            if kind == "C":
                for pin, net in pins.items():
                    local_x = (int(pin)-1-2.5)*sensor["signal_pitch_mm"]
                    dx, dy = config["sense_pickoff"]["column_link_center_offset_pcb_mm"]
                    # Flip mirrors connector X, but leaves its local Y.
                    center = [-y-local_x+dx, 44-z+sensor["signal_pad_y_mm"]+dy]
                    # Rotation -90 after a backside X flip puts pad 1 below
                    # the component centre, nearest the sensor contact.
                    # Native pad verification below checks the actual result.
                    parts.append(passive(
                        "RK"+net[:-2], "0 ohm sense pickoff", center,
                        [net, net[:-2]+"_S"], side="B", rotation=-90))
    link = config["wrist_link"]
    parts.append({
        "reference": "JW", "value": link["part"], "library": link["library"],
        "center_mm": link["center_pcb_mm"], "rotation_deg": link["rotation_deg"],
        "side": link["side"], "height_mm": link["closed_height_mm"],
        "body_envelope_mm": link["body_envelope_mm"], "source": link["source"],
        "nets": {str(i+1): net for i, net in enumerate(link["pins"])}
    })
    mux = config["test_mux"]
    parts.append({
        "reference": "UT", "value": mux["part"], "library": mux["library"],
        "center_mm": mux["center_pcb_mm"], "rotation_deg": mux["rotation_deg"],
        "side": "F", "height_mm": mux["height_mm"],
        "body_envelope_mm": mux["body_envelope_mm"], "source": mux["source"],
        "nets": mux["pins"]
    })
    for row, center in enumerate(config["sense_pickoff"]["row_link_centers_pcb_mm"]):
        parts.append(passive(f"RKR{row}", "0 ohm sense pickoff", center,
                             [f"R{row}_I", f"R{row}_S"], rotation=90))
    # Front-side service circuitry above/between the connector footprints.
    parts.extend([
        passive("CT1", "100 nF X7R 10 V", [36.5, 2.0], ["+3V3", "GND"], kind="capacitor"),
        passive("CT2", "1 uF X7R 10 V", [36.5, 4.0], ["+3V3", "GND"], kind="capacitor"),
        passive("RT", "10.0k 0.1% 25ppm/K", [36.5, 6.0], ["+3V3", "TEST_D"], rotation=90),
    ])
    for i, net in enumerate(("A0", "A1", "A2", "A3", "TEST_EN")):
        parts.append(passive(f"RP{i}", "100k", [51+i*2, 4.0], [net, "GND"], rotation=90))
    return {
        "schema": "yam-f1-board-specification/1", "name": config["name"],
        "thickness_mm": config["pcb_thickness_mm"], "clearance_mm": config["clearance_mm"],
        "edge_mm": config["copper_to_edge_mm"], "outline_xy_mm": list(outline.exterior.coords),
        "parts": parts, "holes": config["mount_holes"],
        "physical_specimens_tested": 0, "status": "Placement implementation awaiting routing and complete circuit/fit checks"
    }


def placement_check(spec, actual):
    outline = Polygon(spec["outline_xy_mm"])
    bodies = {p["reference"]: transform(box(*p["body_envelope_mm"]), p) for p in spec["parts"]}
    parts = {p["reference"]: p for p in spec["parts"]}
    failures = []
    for ref, body in bodies.items():
        if not outline.covers(body):
            failures.append({"kind": "body_outside_board", "reference": ref,
                            "area_mm2": body.difference(outline).area})
        for hole in spec["holes"]:
            distance = body.distance(Point(hole["center_mm"])) - hole["copper_keepout_diameter_mm"]/2
            if distance < 0:
                failures.append({"kind": "body_in_mount_envelope", "reference": ref, "gap_mm": distance})
    for i, a in enumerate(spec["parts"]):
        for b in spec["parts"][i+1:]:
            if a["side"] == b["side"] and bodies[a["reference"]].intersection(bodies[b["reference"]]).area > 1e-8:
                failures.append({"kind": "body_overlap", "a": a["reference"], "b": b["reference"]})
    pad_geometry = {}
    for p in actual["pads"]:
        w, h = p["size"]
        shape = affinity.rotate(box(-w/2, -h/2, w/2, h/2), -p["rotation"], origin=(0, 0))
        shape = affinity.translate(shape, *p["center"])
        pad_geometry[(p["reference"], p["pad"])] = shape
        if not outline.buffer(-spec["edge_mm"]).covers(shape):
            failures.append({"kind": "pad_edge", "reference": p["reference"], "pad": p["pad"]})
    pickoffs = []
    for p in actual["pads"]:
        if not p["reference"].endswith("C") or not p["reference"].startswith("J") or not p["net"]:
            continue
        link = next(p2 for p2 in actual["pads"] if p2["reference"] == "RK"+p["net"][:-2] and p2["pad"] == "1")
        gap = pad_geometry[(p["reference"], p["pad"])].distance(pad_geometry[(link["reference"], link["pad"])])
        entry_above = link["center"][1] < p["center"][1]
        if not entry_above or not .14 <= gap <= .55:
            failures.append({"kind": "sense_pickoff_placement", "net": p["net"], "gap_mm": gap})
        pickoffs.append({"current_pad": [p["reference"], p["pad"]],
                        "sense_link_pad": [link["reference"], "1"], "gap_mm": gap})
    return {"schema": "yam-f1-fanout-placement-check/1", "passed": not failures,
            "failure_count": len(failures), "failures": failures,
            "parts": len(spec["parts"]), "pads": len(actual["pads"]),
            "column_pickoffs": pickoffs, "physical_specimens_tested": 0,
            "limits": "Nominal board/part envelopes and native pad placement only. Carrier, mated flex, open latches, circuit operation and real drive are not covered."}


def draw(spec, actual, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as PlotPolygon
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    for ax, side in zip(axes, ("F", "B")):
        ax.add_patch(PlotPolygon(spec["outline_xy_mm"], facecolor="#eef5ee", edgecolor="#294932"))
        for part in spec["parts"]:
            if part["side"] != side:
                continue
            body = transform(box(*part["body_envelope_mm"]), part)
            ax.add_patch(PlotPolygon(list(body.exterior.coords), facecolor="#bacade", edgecolor="#475569", alpha=.6))
            x, y = part["center_mm"]
            ax.text(x, y, part["reference"], ha="center", va="center", fontsize=7)
        for p in actual["pads"]:
            if p["layers"] != [side+".Cu"]:
                continue
            w, h = p["size"]
            shape = affinity.rotate(box(-w/2, -h/2, w/2, h/2), -p["rotation"], origin=(0, 0))
            shape = affinity.translate(shape, *p["center"])
            ax.add_patch(PlotPolygon(list(shape.exterior.coords), facecolor="#b88732"))
        for hole in spec["holes"]:
            ax.add_patch(PlotPolygon(list(Point(hole["center_mm"]).buffer(hole["diameter_mm"]/2).exterior.coords),
                                    facecolor="white", edgecolor="#374151"))
        ax.set(xlim=(12, 77), ylim=(38, -2), aspect="equal", xlabel="PCB x = -native Y (mm)")
        ax.set_title("Outer row face — F.Cu" if side == "F" else "Inner column face — B.Cu, viewed through board")
        ax.grid(alpha=.15)
    axes[0].set_ylabel("PCB y = 44 - native Z (mm)")
    fig.suptitle("F1 fanout placement development • copper routing and installed assembly pending", fontsize=12)
    fig.tight_layout()
    fig.savefig(path.with_suffix(".png"), dpi=170)
    fig.savefig(path.with_suffix(".svg"))
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text())
    placement_path = ROOT / config["placement_result"]
    if digest(placement_path) != config["placement_result_sha256"]:
        raise ValueError("Placement result changed; review and update the selected input")
    placement = json.loads(placement_path.read_text())
    if not placement["contoured_candidate_screen_passed"]:
        raise ValueError("Use a passed placement candidate")
    for name, expected in placement["source_hashes"].items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"Placement input changed: {name}; regenerate/recheck first")
    folder = ROOT / "build/engineering/prototypes/f1/fanout_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Develop F1 two-sided fanout board with exact pad/net assignments and independent native transforms") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"
        inputs.mkdir()
        paths = [config_path, placement_path, Path(__file__), ROOT / "engineering/scripts/f1_native_pcb.py"]
        hashes = {}
        for path in paths:
            relative = path.relative_to(ROOT)
            target = inputs / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            hashes[str(relative)] = digest(path)
        spec = specification(config, placement)
        spec["input_hashes"] = hashes
        spec_path = folder / "specification.json"
        spec_path.write_text(json.dumps(spec, indent=2)+"\n")
        command = [str(KICAD_PYTHON), str(ROOT / "engineering/scripts/f1_native_pcb.py"),
                   str(spec_path), str(folder / "placement")]
        with (folder / "native_placement.log").open("w") as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            record["command"] = {"argv": command, "pid": process.pid}
            try:
                code = process.wait(timeout=50)
            except subprocess.TimeoutExpired:
                record["command"]["intentional_stop"] = "50 s limit for this owned placement worker"
                process.terminate(); process.wait(timeout=10)
                raise
        record["command"]["returncode"] = code
        if code:
            print((folder / "native_placement.log").read_text()[-5000:])
            raise RuntimeError(f"Native placement worker exited {code}; preserved {folder}")
        actual = json.loads((folder / "placement" / (config["name"]+".json")).read_text())
        report = placement_check(spec, actual)
        (folder / "placement_check.json").write_text(json.dumps(report, indent=2)+"\n")
        draw(spec, actual, folder / "placement_review")
        record["placement_check"] = report
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), **report}, indent=2))
        if not report["passed"]:
            raise ValueError("Resolve preserved placement findings before routing")


if __name__ == "__main__":
    main()
