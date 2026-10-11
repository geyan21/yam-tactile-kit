#!/usr/bin/python3
"""Generate F1 wrist circuit pin tables and check a concrete PCB placement."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from screen_f1_feedback import digest
from develop_f1_fanout import transform

KICAD_PYTHON = ROOT / "build/engineering/tools/b1-kicad/AppDir/bin/python3.11"
CONFIG = ROOT / "engineering/designs/f1_wrist_development.json"
LIBRARIES = {
    "opamp": "Package_TO_SOT_SMD.pretty/SOT-23-5.kicad_mod",
    "mux16": "Package_SO.pretty/TSSOP-28_4.4x9.7mm_P0.65mm.kicad_mod",
    "switch4": "Package_SO.pretty/TSSOP-16_4.4x5mm_P0.65mm.kicad_mod",
    "rows4": "Package_SO.pretty/TSSOP-20_4.4x6.5mm_P0.65mm.kicad_mod",
    "adc": "Package_SO.pretty/MSOP-10_3x3mm_P0.5mm.kicad_mod",
    "reference": "Package_SO.pretty/MSOP-8_3x3mm_P0.65mm.kicad_mod",
    "monitor": "Package_SO.pretty/SOIC-16_3.9x9.9mm_P1.27mm.kicad_mod",
    "header": "Connector_PinSocket_2.54mm.pretty/PinSocket_1x20_P2.54mm_Vertical.kicad_mod",
}


def component(ref, value, center, pins, family, body, side="F", rotation=0, source="", height=1.2):
    return {"reference": ref, "value": value, "center_mm": center, "nets": pins,
            "library": LIBRARIES.get(family, family), "body_envelope_mm": body,
            "side": side, "rotation_deg": rotation, "source": source, "height_mm": height}


def passive(ref, value, center, nets, side="F", rotation=0, capacitor=False, large=False):
    family = ("Capacitor_SMD.pretty/C_1210_3225Metric.kicad_mod" if large else
              "Capacitor_SMD.pretty/C_0603_1608Metric.kicad_mod" if capacitor else
              "Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod")
    body = [-1.6, -1.25, 1.6, 1.25] if large else [-.8, -.4, .8, .4]
    return component(ref, value, center, {"1": nets[0], "2": nets[1]}, family, body,
                     side, rotation, height=2.5 if large else .9)


def specification(cfg, feedback, rows, adc, fanout):
    parts = []
    def add(part):
        parts.append(part)
    def r(ref, value, xy, nets, side="F", rotation=0):
        add(passive(ref, value, xy, nets, side, rotation))
    def c(ref, value, xy, nets, side="F", rotation=0, large=False):
        add(passive(ref, value, xy, nets, side, rotation, True, large))
    def op(ref, part, xy, positive, negative, output, side="F"):
        add(component(ref, part, xy, {"1": output, "2": "GND", "3": positive,
                      "4": negative, "5": "+3V3"}, "opamp", [-.9, -1.55, .9, 1.55],
                      side, source="https://www.ti.com/lit/ds/symlink/"+("opa320-q1.pdf" if "320" in part else "opa392.pdf")))
    # These are physical Pico header numbers, checked against the official pinout.
    gpio_pins = {0: 1, 1: 2, 2: 4, 3: 5, 4: 6, 5: 7, 6: 9, 7: 10,
                 8: 11, 9: 12, 10: 14, 11: 15, 12: 16, 13: 17, 14: 19, 15: 20,
                 16: 21, 17: 22, 18: 24, 19: 25, 20: 26}
    pico = {pin: "GND" for pin in (3, 8, 13, 18, 23, 28, 33, 38)}
    pico.update({36: "+3V3", 40: "+5V"})
    for net, gpio in cfg["controller"]["gpio"].items():
        pico[gpio_pins[gpio]] = net
    for ref, side in (("JP1", "left"), ("JP2", "right")):
        pins = cfg["controller"][side+"_header_physical_pico_pins"]
        add(component(ref, "1x20 female socket 2.54 mm; Pico header", cfg["controller"][side+"_header_datum_mm"],
                      {str(i+1): pico.get(pin, "") for i, pin in enumerate(pins)}, "header",
                      [-1.3, -1.3, 1.3, 49.56], height=8.5,
                      source=cfg["controller"]["source"]))
    link = fanout["wrist_link"]
    mating = cfg["connector"]
    add(component("JW", link["part"], mating["center_mm"],
                  {str(i+1): net for i, net in enumerate(reversed(link["pins"]))},
                  link["library"], link["body_envelope_mm"], rotation=mating["rotation_deg"],
                  source=link["source"], height=link["closed_height_mm"]))
    # Current/sense muxes retain the manufacturer's complete physical pin map.
    for ref, suffix, center, drain, enable in (
            ("UCI", "_I", [75, 24], "CURRENT_D", "CUR_EN"),
            ("UCS", "_S", [75, 46], "SENSE_D", "SNS_EN")):
        pins = dict(fanout["test_mux"]["pins"])
        for pin, net in pins.items():
            if net.startswith("C") and net.endswith("_I"):
                pins[pin] = net[:-2]+suffix
        pins["17"], pins["27"] = enable, drain
        add(component(ref, "ADG706BRUZ", center, pins, "mux16", [-2.25, -4.9, 2.25, 4.9],
                      source=fanout["test_mux"]["source"]))
        c("C"+ref, "100n X7R 10V", [center[0]-2, center[1]-7], ["+3V3", "GND"], rotation=90)
    row_pins = {"1": "ROW0", "2": "VEXCITE", "3": "ROW0_CMD", "4": "VBIAS",
                "5": "GND", "6": "GND", "7": "VBIAS", "8": "ROW1_CMD", "9": "VEXCITE",
                "10": "ROW1", "11": "ROW2", "12": "VEXCITE", "13": "ROW2_CMD",
                "14": "VBIAS", "15": "", "16": "+3V3", "17": "VBIAS",
                "18": "ROW3_CMD", "19": "VEXCITE", "20": "ROW3"}
    add(component("URSEL", rows["selection"]["part"], [49, 44], row_pins, "rows4",
                  [-2.25, -3.3, 2.25, 3.3], rotation=90, source=rows["selection"]["source"]))
    c("CRSEL", "100n X7R 10V", [49, 39.5], ["+3V3", "GND"])
    rf = rows["feedback"]
    for index, (x, y) in enumerate(((40, 14), (57, 14), (40, 31), (57, 31))):
        prefix = f"ROW{index}"
        op(f"UR{index}", "OPA392DBVR", [x, y], prefix+"_CMD", prefix+"_FB", prefix+"_OUT")
        c(f"CDR{index}", "100n X7R 10V", [x+2, y-3.5], ["+3V3", "GND"], rotation=90)
        r(f"RBIAS{index}", "1M", [x-3.5, y], [prefix+"_CMD", "VBIAS"], rotation=90)
        r(f"RISO{index}", f"{rf['output_isolation_ohm']:g}", [x+4, y], [prefix+"_OUT", f"R{index}_I"])
        r(f"RSNS{index}", f"{rf['sense_input_series_ohm']:g}", [x+4, y+3], [f"R{index}_S", prefix+"_FB"])
        c(f"CFB{index}", f"{rf['local_capacitance_pf']:g}p C0G", [x-3, y+4], [prefix+"_OUT", prefix+"_FB"])
        r(f"RFB{index}", "100M", [x+1, y+4], [prefix+"_OUT", prefix+"_FB"])
        r(f"RMON{index}", "4.7k", [x+4, y+6], [prefix+"_OUT", prefix+"_MON"])
        c(f"CMON{index}", "10n X7R 10V", [x+4, y+9], [prefix+"_MON", "GND"])
    # Local TIA topology follows the saved selected-column study.
    op("UTIA", feedback["amplifier"]["part"], [54, 60], "VBIAS", "TIA_FB", "AMP_OUT")
    c("CDTIA", "100n X7R 10V", [55.8, 57.5], ["+3V3", "GND"], rotation=90)
    gain_pins = {"1": "GAIN0", "2": "OUTPUT_BUS", "3": "GAIN_BRANCH0", "4": "",
                 "5": "GND", "6": "GAIN_BRANCH3", "7": "OUTPUT_BUS", "8": "GAIN3",
                 "9": "GAIN2", "10": "OUTPUT_BUS", "11": "GAIN_BRANCH2", "12": "",
                 "13": "+3V3", "14": "GAIN_BRANCH1", "15": "OUTPUT_BUS", "16": "GAIN1"}
    add(component("UGAIN", "TMUX1112PWR", [62, 55], gain_pins, "switch4",
                  [-2.25, -2.55, 2.25, 2.55], source=feedback["gain_selection"]["source"]))
    c("CDGAIN", "100n X7R 10V", [67.5, 55], ["+3V3", "GND"])
    locations = [([54.5, 50.5], [54.5, 53.5]), ([68.5, 50.5], [68.5, 53.5]),
                 ([68.5, 58.5], [68.5, 61.5]), ([61, 61], [64.5, 61])]
    for branch, (rp, cp) in zip(feedback["gain_selection"]["branches"], locations):
        index = branch["id"]
        nets = [f"GAIN_BRANCH{index}", "CURRENT_D"]
        r(f"RTIA{index}", f"{branch['resistance_ohm']:g} 0.1%", rp, nets)
        c(f"CTIA{index}", f"{branch['feedback_capacitance_pf']:g}p C0G", cp, nets)
    r("ROUT", "0.1", [53, 63], ["AMP_OUT", "OUTPUT_BUS"])
    r("RPARK", "100M", [50, 64.5], ["AMP_OUT", "SENSE_D"])
    c("CLOCAL", "15p C0G", [50.5, 58], ["AMP_OUT", "TIA_FB"])
    r("RBOOST", "680", [45, 66.5], ["SENSE_D", "COMP_MID"])
    r("RINPUT", "300", [49, 67], ["COMP_MID", "TIA_FB"])
    c("CCURRENT", "3.3n C0G", [61, 64.5], ["CURRENT_D", "GND"])
    for ref, value, xy, dnet, snet, select in (
            ("UBYP", "TMUX1102DBVR", [46, 62], "SENSE_D", "COMP_MID", "GAIN0"),
            ("UPARK", "TMUX1101DBVR", [57.5, 68], "AMP_OUT", "PARK_LINK", "PARK")):
        add(component(ref, value, xy, {"1": dnet, "2": snet, "3": "GND", "4": select, "5": "+3V3"},
                      "opamp", [-.9, -1.55, .9, 1.55], source=feedback["active_park_feedback"]["source"]))
    r("RACTIVEPARK", "1k", [53, 69], ["PARK_LINK", "TIA_FB"])
    c("CDBYP", "100n X7R 10V", [48.5, 60.5], ["+3V3", "GND"], rotation=90)
    c("CDPARK", "100n X7R 10V", [61, 68], ["+3V3", "GND"])
    # Main ADC filter has both differential and common-mode charge reservoirs.
    op("UAB", adc["buffer"]["part"], [74, 64], "OUTPUT_BUS", "ADC_BUFFER", "ADC_BUFFER")
    c("CDAB", "100n X7R 10V", [75.8, 60.5], ["+3V3", "GND"], rotation=90)
    adc_pins = {"1": "VREF33", "2": "ADC_AVDD", "3": "AINP", "4": "AINN", "5": "GND",
                "6": "ADC_CONV", "7": "SPI_MISO", "8": "SPI_SCK", "9": "+3V3", "10": "+3V3"}
    add(component("UADC", adc["adc"]["part"], [82, 63.5], adc_pins, "adc", [-1.55, -1.55, 1.55, 1.55],
                  source=adc["adc"]["source"]))
    r("RADCP", "22 0.1%", [77.5, 63.5], ["ADC_BUFFER", "AINP"], rotation=90)
    r("RADCN", "22 0.1%", [80, 68], ["GND", "AINN"])
    c("CADCD", "2.2n C0G", [82, 67], ["AINP", "AINN"], rotation=90)
    c("CADCP", "2.2n C0G", [77, 67.5], ["AINP", "GND"], rotation=90)
    c("CADCN", "2.2n C0G", [86.5, 63.5], ["AINN", "GND"], rotation=90)
    r("RAVDD", "2.2", [79, 57], ["+3V3", "ADC_AVDD"])
    c("CAVDD", "1u X7R 10V", [80, 60], ["ADC_AVDD", "GND"])
    c("CDVDD", "1u X7R 10V", [85, 59], ["+3V3", "GND"], rotation=90)
    c("CREF", "22u X7R 25V; effective 10-47u verified", [84, 54.5], ["REF_CAP", "GND"], large=True)
    r("RREFESR", "0.047 1%", [79, 54.5], ["VREF33", "REF_CAP"])
    # Separate reference sense paths meet the ADC reference/ground through links.
    r("RREFS", "0 sense pickup", [80, 61], ["VREF_SENSE", "VREF33"], side="B")
    r("RGNDS", "0 sense pickup", [80, 65.5], ["REF_GND_SENSE", "GND"], side="B")
    ref_pins = {"1": "+5V", "2": "+5V", "3": "+5V", "4": "REF_FILT",
                "5": "VREF_SENSE", "6": "VREF33", "7": "GND", "8": "REF_GND_SENSE"}
    add(component("UREF", adc["reference"]["part"], [74, 61], ref_pins, "reference",
                  [-1.55, -1.55, 1.55, 1.55], side="B", source=adc["reference"]["source"]))
    c("CFILT", "2.2u X7R 10V; effective >=1u", [71, 65], ["REF_FILT", "GND"], side="B")
    c("CREFIN1", "100n X7R 10V", [78, 57.5], ["+5V", "GND"], side="B", rotation=-90)
    c("CREFIN2", "1u X7R 10V", [74, 56.5], ["+5V", "GND"], side="B")
    # Static bias sources live on the rear face between the Pico's sockets.
    bias = cfg["bias"]
    for label, yy, top, bottom, output in (
            ("BIAS", 36, bias["bias_top_ohm"], bias["bias_bottom_ohm"], "VBIAS"),
            ("EXC", 52, bias["excite_top_ohm"], bias["excite_bottom_ohm"], "VEXCITE")):
        node, buffered = label+"_DIV", label+"_BUFFER"
        r("R"+label+"T", f"{top:g} 0.01% 10ppm/K", [13, yy-5], ["VREF33", node], "B", 90)
        r("R"+label+"B", f"{bottom:g} 0.01% 10ppm/K", [17, yy-5], [node, "GND"], "B", 90)
        c("C"+label+"IN", "100n X7R 10V", [21, yy-5], [node, "GND"], "B", 90)
        op("U"+label, "OPA392DBVR", [17, yy], node, buffered, buffered, "B")
        c("CD"+label, "100n X7R 10V", [17, yy-2.8], ["+3V3", "GND"], "B")
        r("R"+label+"OUT", "47", [21, yy], [buffered, output], "B", 90)
        c("C"+label+"OUT", "100n X7R 10V", [21, yy+4], [output, "GND"], "B")
    mon = cfg["monitor"]
    mon_pins = {str(i+1): net for i, net in enumerate(mon["channels"])}
    mon_pins.update({"9": "GND", "10": "MON_CS", "11": "SPI_MOSI", "12": "SPI_MISO",
                     "13": "SPI_SCK", "14": "GND", "15": "+3V3", "16": "+3V3"})
    add(component("UMON", mon["part"], [53, 26], mon_pins, "monitor",
                  [-2, -5, 2, 5], side="B", source=mon["source"], height=1.75))
    c("CDMON", "100n X7R 10V", [48, 20.5], ["+3V3", "GND"], "B", -90)
    c("CBMON", "1u X7R 10V", [48, 24], ["+3V3", "GND"], "B", -90)
    for prefix, net, xy in (("B", "VBIAS", [47, 33]), ("E", "VEXCITE", [53, 34])):
        monitor = "BIAS_MON" if prefix == "B" else "EXCITE_MON"
        r("RM"+prefix, "4.7k", xy, [net, monitor], "B")
        c("CM"+prefix, "10n X7R 10V", [xy[0], xy[1]+3], [monitor, "GND"], "B")
    for prefix, source, net, x in (("V5", "+5V", "+5V_DIV2", 41), ("V3", "+3V3", "+3V3_DIV2", 35)):
        r("R"+prefix+"T", "10k 0.1%", [x, 34], [source, net], "B")
        r("R"+prefix+"B", "10k 0.1%", [x, 37], [net, "GND"], "B")
        c("C"+prefix, "10n X7R 10V", [x, 40], [net, "GND"], "B")
    down = [f"ROW{i}" for i in range(4)] + [f"A{i}" for i in range(4)] + ["CUR_EN", "SNS_EN", "TEST_EN"]
    for index, net in enumerate(down):
        r("PD_"+net, "100k", [4, 14+4*index], [net, "GND"], "B", 90)
    for index, net in enumerate([f"GAIN{i}" for i in range(4)]):
        r("PD_"+net, "100k", [30.5, 14+4*index], [net, "GND"], "B", 90)
    for index, net in enumerate(("PARK", "MON_CS", "ADC_CONV")):
        r("PU_"+net, "100k", [30.5, 34+4*index], [net, "+3V3"], "B", 90)
    r("PD_MISO", "100k", [30.5, 54], ["SPI_MISO", "GND"], "B", 90)
    c("CBULK3", "10u X7R 10V", [31, 8], ["+3V3", "GND"])
    c("CBULK5", "4.7u X7R 10V", [26, 7], ["+5V", "GND"])
    overrides = cfg.get("component_position_overrides_mm", {})
    if set(overrides)-{part["reference"] for part in parts}:
        raise ValueError("Position override names an unknown part")
    for part in parts:
        if part["reference"] in overrides:
            part["center_mm"] = overrides[part["reference"]]
    width, height = cfg["board_size_mm"]
    bypass = [(f"UR{i}", "5", f"CDR{i}", "1") for i in range(4)]
    bypass += [
        ("UCI", "1", "CUCI", "1"), ("UCS", "1", "CUCS", "1"),
        ("URSEL", "16", "CRSEL", "1"), ("UTIA", "5", "CDTIA", "1"),
        ("UGAIN", "13", "CDGAIN", "1"), ("UBYP", "5", "CDBYP", "1"),
        ("UPARK", "5", "CDPARK", "1"), ("UAB", "5", "CDAB", "1"),
        ("UADC", "2", "CAVDD", "1"), ("UADC", "10", "CDVDD", "1"),
        ("UREF", "1", "CREFIN1", "1"), ("UBIAS", "5", "CDBIAS", "1"),
        ("UEXC", "5", "CDEXC", "1"), ("UMON", "16", "CDMON", "1"),
    ]
    return {"schema": "yam-f1-wrist-specification/1", "name": cfg["name"],
            "thickness_mm": cfg["thickness_mm"], "clearance_mm": cfg["clearance_mm"],
            "edge_mm": cfg["copper_to_edge_mm"],
            "outline_xy_mm": [[0, 0], [width, 0], [width, height], [0, height], [0, 0]],
            "label_position_mm": cfg["label_position_mm"], "parts": parts, "holes": cfg["mount_holes"],
            "power_bypass_pairs": bypass,
            "component_keepouts": [{"id": "Pico daughterboard", "side": "F",
                                    "bounds_mm": cfg["controller"]["module_component_keepout_xy_mm"],
                                    "allowed_references": ["JP1", "JP2"]}],
            "physical_specimens_tested": 0, "status": "Circuit placement awaiting routing and complete integration"}


def check_placement(spec, actual):
    outline = Polygon(spec["outline_xy_mm"])
    bodies = {p["reference"]: transform(box(*p["body_envelope_mm"]), p) for p in spec["parts"]}
    failures = []
    for part in spec["parts"]:
        ref, body = part["reference"], bodies[part["reference"]]
        if not outline.covers(body):
            failures.append({"kind": "body_outside_board", "reference": ref})
        for hole in spec["holes"]:
            if body.distance(Point(hole["center_mm"])) < hole["copper_keepout_diameter_mm"]/2:
                failures.append({"kind": "mount_clearance", "reference": ref, "hole": hole["center_mm"]})
        for keepout in spec["component_keepouts"]:
            if part["side"] == keepout["side"] and ref not in keepout["allowed_references"] and body.intersects(box(*keepout["bounds_mm"])):
                failures.append({"kind": "module_clearance", "reference": ref})
    for index, a in enumerate(spec["parts"]):
        for b in spec["parts"][index+1:]:
            if a["side"] == b["side"] and bodies[a["reference"]].intersection(bodies[b["reference"]]).area > 1e-8:
                failures.append({"kind": "body_overlap", "a": a["reference"], "b": b["reference"]})
    courts = actual.get("courtyards", [])
    if len(courts) != len(spec["parts"]):
        failures.append({"kind": "missing_native_courtyard"})
    for index, a in enumerate(courts):
        for b in courts[index+1:]:
            if a["side"] == b["side"] and box(*a["bounds_mm"]).intersection(box(*b["bounds_mm"])).area > 1e-8:
                failures.append({"kind": "native_courtyard_overlap", "a": a["reference"], "b": b["reference"]})
    pads = actual["pads"]
    shapes = []
    for p in pads:
        w, h = p["size"]
        shape = affinity.rotate(box(-w/2, -h/2, w/2, h/2), -p["rotation"], origin=(0, 0))
        shape = affinity.translate(shape, *p["center"])
        shapes.append(shape)
        if not outline.buffer(-spec["edge_mm"]).covers(shape):
            failures.append({"kind": "pad_edge", "reference": p["reference"], "pad": p["pad"]})
    tree = STRtree(shapes)
    for i, shape in enumerate(shapes):
        for candidate in tree.query(shape.buffer(spec["clearance_mm"])):
            j = int(candidate)
            if j <= i or not set(pads[i]["layers"]).intersection(pads[j]["layers"]):
                continue
            if pads[i]["net"] and pads[i]["net"] == pads[j]["net"]:
                continue
            gap = shape.distance(shapes[j])
            if gap < spec["clearance_mm"]-1e-6:
                failures.append({"kind": "pad_clearance", "a": [pads[i]["reference"], pads[i]["pad"]],
                                 "b": [pads[j]["reference"], pads[j]["pad"]], "gap_mm": gap})
    by_key = {(p["reference"], p["pad"]): p for p in pads}
    bypass_distances = []
    for ref, pin, cap, cap_pin in spec["power_bypass_pairs"]:
        first, second = by_key[(ref, pin)], by_key[(cap, cap_pin)]
        distance = math.dist(first["center"], second["center"])
        bypass_distances.append({"ic": ref, "capacitor": cap, "pad_distance_mm": distance})
        if first["net"] != second["net"] or distance > 3.5:
            failures.append({"kind": "power_bypass_placement", "ic": ref, "capacitor": cap,
                             "pad_distance_mm": distance})
    return {"passed": not failures, "failures": failures, "parts": len(spec["parts"]),
            "pads": len(pads), "power_bypass_placement": bypass_distances, "physical_evidence": False,
            "limits": "Nominal bodies, pads and mounting envelopes only; routing, thermal, analog operation and robot fit remain."}


def draw(spec, actual, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as PlotPolygon
    fig, axes = plt.subplots(1, 2, figsize=(15, 7), layout="constrained")
    for ax, side in zip(axes, ("F", "B")):
        ax.add_patch(PlotPolygon(spec["outline_xy_mm"], facecolor="#edf4ed", edgecolor="#355849"))
        for part in spec["parts"]:
            if part["side"] != side:
                continue
            shape = transform(box(*part["body_envelope_mm"]), part)
            ax.add_patch(PlotPolygon(list(shape.exterior.coords), facecolor="#c0d1e3", edgecolor="#526477", lw=.6))
            ax.text(*part["center_mm"], part["reference"], ha="center", va="center", fontsize=5)
        for keepout in spec["component_keepouts"]:
            if keepout["side"] == side:
                shape = box(*keepout["bounds_mm"])
                ax.add_patch(PlotPolygon(list(shape.exterior.coords), fill=False, edgecolor="#9c7144", ls="--"))
                ax.text(shape.centroid.x, shape.centroid.y, keepout["id"], rotation=90, ha="center", color="#84633e")
        for hole in spec["holes"]:
            shape = Point(hole["center_mm"]).buffer(hole["diameter_mm"]/2)
            ax.add_patch(PlotPolygon(list(shape.exterior.coords), facecolor="white", edgecolor="#333"))
        ax.set(aspect="equal", xlim=(-1, 91), ylim=(76, -1), xlabel="PCB x (mm)", ylabel="PCB y (mm)")
        ax.set_title("Front · controller and signal stages" if side == "F" else "Rear · references and monitors, viewed through board")
    fig.suptitle("F1 wrist-board development placement · not a routed or physically tested board")
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(path.with_suffix("."+suffix), dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    config_path = args.config.resolve()
    if not config_path.is_relative_to(ROOT):
        parser.error("Use repository-owned configuration")
    cfg = json.loads(config_path.read_text())
    paths = [ROOT / cfg[name] for name in ("feedback_candidate", "row_candidate", "adc_candidate", "fanout_candidate")]
    stages = [json.loads(path.read_text()) for path in paths]
    folder = ROOT / "build/engineering/prototypes/f1/wrist_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Develop the F1 wrist circuit, physical Pico header mapping and component placement before routing") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = folder / "inputs"; inputs.mkdir()
        for path in [config_path, *paths, Path(__file__), ROOT / "engineering/scripts/f1_wrist_native.py"]:
            shutil.copyfile(path, inputs / path.name)
        spec = specification(cfg, *stages)
        refs = [part["reference"] for part in spec["parts"]]
        if len(set(refs)) != len(refs):
            raise ValueError("Duplicate component designators")
        spec["input_hashes"] = {str(path.relative_to(ROOT)): digest(path) for path in [config_path, *paths, Path(__file__)]}
        spec_path = folder / "specification.json"
        spec_path.write_text(json.dumps(spec, indent=2)+"\n")
        command = [str(KICAD_PYTHON), str(ROOT / "engineering/scripts/f1_wrist_native.py"),
                   str(spec_path), str(folder / "placement")]
        with (folder / "native.log").open("w") as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            record["native"] = {"command": command, "pid": process.pid}
            try:
                code = process.wait(timeout=50)
            except subprocess.TimeoutExpired:
                record["native"]["intentional_stop"] = "50 second limit on owned native placement worker"
                process.terminate(); process.wait(timeout=5)
                raise
        record["native"]["exit_code"] = code
        if code:
            raise RuntimeError((folder / "native.log").read_text()[-4000:])
        actual = json.loads((folder / "placement/f1_wrist.json").read_text())
        review = check_placement(spec, actual)
        (folder / "placement_check.json").write_text(json.dumps(review, indent=2)+"\n")
        draw(spec, actual, folder / "placement_review")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), **review}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
