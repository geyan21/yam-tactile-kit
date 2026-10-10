#!/usr/bin/python3
"""Develop the B2 consolidated board from the preserved B1 electrical layout."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT/"build/engineering/tools/mpl-cache")
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
import trimesh

from analyze_baseline_meshes import PARTS
from build_b1_parts import side_outline
from prototype_pcb import Board
from prototype_route import Router
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/b2/pcb"

# RGE pin numbers, deliberately separate from the TSSOP numbers. TI SCPS207H
# figure 4-2 and table 4-1; EP 25 is grounded.
MUX_PIN_NET = {
    1: "SDA0", 2: "SCL0", 3: "SDA1", 4: "SCL1",
    5: "SDA2", 6: "SCL2", 7: "SDA3", 8: "SCL3",
    9: "GND", 10: "SDA4", 11: "SCL4",
    12: "", 13: "", 14: "", 15: "", 16: "", 17: "",
    18: "GND", 19: "SCL", 20: "SDA", 21: "3V3",
    22: "GND", 23: "GND", 24: "RESET", 25: "GND",
}
ADC_PIN_NET = {1: "GND", 2: "", 3: "GND", 4: "T0", 5: "T1",
               6: "VDD_HALF", 7: "CHECK_HALF", 8: "3V3", 9: "SDA", 10: "SCL"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def to_board(yz):
    # Component-side axes: board +u is native -Y; +v is native +Z.
    # KiCad +Y points down, so (-native Y, 40-native Z) preserves handedness.
    return [-float(yz[0]), 40-float(yz[1])]


def head_transform(pose, point):
    dx, dy = point[0]-100, point[1]-100
    native = np.asarray(pose["native_yz_mm"]) + dx*np.asarray(pose["u_yz"]) - dy*np.asarray(pose["v_yz"])
    return to_board(native)


def add_heads(board, b1, layout):
    endpoints = {name: [] for name in ("3V3", *[f"{bus}{i}" for i in range(5) for bus in ("SCL","SDA")])}
    axes = []
    for i, pose in enumerate(layout["sensor_poses"]):
        def net(old):
            return old+str(i) if old in ("SDA","SCL") else old
        def reference(old):
            if old == "U1":
                return "U"+str(i+1)
            if old == "J1":
                return "TP"+str(i+1)
            return old[0]+str(i+1)+old[1:]
        u = pose["u_yz"]
        rotation = math.degrees(math.atan2(u[1], -u[0]))
        for part in b1["components"]:
            pads = [(p["pad"], p["x"]-part["x_mm"], p["y"]-part["y_mm"],
                     p["width"], p["height"], net(p["net"]),
                     part["reference"] != "J1" and not (part["reference"] == "U1" and p["pad"] == 17))
                    for p in b1["pads"] if p["reference"] == part["reference"]]
            board.component(
                reference(part["reference"]), part["value"],
                head_transform(pose, [part["x_mm"], part["y_mm"]]), pads, rotation,
                body=[3,3] if part["reference"] == "U1" else None,
                source="Preserved B1 head; Melexis rev012, pin table and package drawing",
                height=1.05 if part["reference"] == "U1" else .55)
        for old_net, a, b, layer, width in b1["tracks"]:
            board.trace(net(old_net), [head_transform(pose,a), head_transform(pose,b)], layer, width)
        for old_net, x, y, size, drill in b1["vias"]:
            board.via(net(old_net), head_transform(pose,[x,y]), size, drill)
        # B1's wire land for SDA has no layer transition. B2 adds one in that
        # non-paste test land so the shaped arm can use its inner routing layer.
        board.via(f"SDA{i}",board.pad(reference("J1"),4)["center"])
        for x in (-.43, .43):
            for y in (-.43, .43):
                local = [(100+x+dx, 100+y+dy) for dx,dy in
                         ((-.325,-.325),(.325,-.325),(.325,.325),(-.325,.325))]
                board.paste.append(Polygon([head_transform(pose,p) for p in local]))
        port = reference("J1")
        for pin, name in ((1,"3V3"),(3,f"SCL{i}"),(4,f"SDA{i}")):
            endpoints[name].append(board.pad(port,pin)["center"])
        chip = board.pad(reference("U1"),17)["center"]
        if math.dist(chip,to_board(pose["native_yz_mm"])) > 1e-7:
            raise ValueError("Head center moved during board consolidation")
        # Match every transformed pad, not just the package center.
        for p in (p for p in b1["pads"] if p["reference"] == "U1"):
            actual = board.pad(reference("U1"),p["pad"])["center"]
            if math.dist(actual,head_transform(pose,[p["x"],p["y"]])) > 1e-7:
                raise ValueError("Head pin orientation changed")
        axes.append({"id":pose["id"],"reference":reference("U1"),
                     "center_native_mm":pose["pcb_top_origin_native_mm"],
                     "rotation_sensor_to_native":pose["rotation_sensor_to_native"],
                     "kicad_rotation_deg":rotation})
    return endpoints, axes


def add_controller(board, config):
    p = config["pcb"]
    mux = []
    for i in range(6):
        offset = -1.25+.5*i
        mux.extend([
            (i+1,-1.9,offset,.6,.24,MUX_PIN_NET[i+1]),
            (i+7,offset,1.9,.24,.6,MUX_PIN_NET[i+7]),
            (i+13,1.9,-offset,.6,.24,MUX_PIN_NET[i+13]),
            (i+19,-offset,-1.9,.24,.6,MUX_PIN_NET[i+19]),
        ])
    mux.append((25,0,0,2.1,2.1,"GND",False))
    board.component("U10",p["mux_part"],[14.3,17.7],mux,body=[4,4],height=1,
                    source="TI SCPS207H RGE0024C land pattern, 0.5 mm pitch")
    board.via("GND",[14.3,17.7],.6,.3)
    # Address and ground pins join the exposed ground pad inward, leaving
    # the outer escape area available for RESET and bus connections.
    for pin in (9,18,22,23):
        pad = board.pad("U10",pin)
        dx,dy = pad["center"][0]-14.3,pad["center"][1]-17.7
        if abs(dx)>abs(dy):
            inner = [14.3+math.copysign(.8,dx),17.7+dy]
        else:
            inner = [14.3+dx,17.7+math.copysign(.8,dy)]
        board.trace("GND",[pad["center"],inner,[14.3+max(-.8,min(.8,dx)),17.7+max(-.8,min(.8,dy))]])
    for x in (-.4,.4):
        for y in (-.4,.4):
            board.paste.append(box(14.3+x-.34,17.7+y-.34,14.3+x+.34,17.7+y+.34))
    adc = []
    for i in range(5):
        adc.append((i+1,-2.2,-1+.5*i,1.45,.3,ADC_PIN_NET[i+1]))
        adc.append((i+6,2.2,1-.5*i,1.45,.3,ADC_PIN_NET[i+6]))
    board.component("U11",p["nail_adc_part"],[14,26.2],adc,body=[3,3],height=1.1,
                    source="TI SBAS444E DGS0010A land pattern, 0.5 mm pitch")
    parts = [
        ("R100","4.7k 1% 0402",[12,22.5],["3V3","SCL"]),
        ("R101","4.7k 1% 0402",[14.3,22.5],["3V3","SDA"]),
        ("R102","10k 1% 0402",[17,22.5],["3V3","RESET"]),
        ("C100","100nF 16V X7R 0402",[18,18],["3V3","GND"]),
        ("C101","100nF 16V X7R 0402",[18,23.7],["3V3","GND"]),
        ("C102","1uF 10V X7R 0402",[18,20],["3V3","GND"]),
        ("R103","10k 1% 0402",[12,29.1],["3V3","VDD_HALF"]),
        ("R104","10k 1% 0402",[12,30.6],["VDD_HALF","GND"]),
        ("R105","10k 1% 0402",[15,29.1],["3V3","CHECK_HALF"]),
        ("R106","10k 1% 0402",[15,30.6],["CHECK_HALF","GND"]),
        ("R107","10k 1% 0402",[18,29.1],["T0","GND"]),
        ("R108","10k 1% 0402",[18,30.6],["T1","GND"]),
    ]
    for ref,value,center,nets in parts:
        board.resistor(ref,value,center,nets)
    board.wire_port("J1",[9.8,22],["3V3","GND","SCL","SDA"],rotation=90)
    board.wire_port("J2",[14,32.5],["3V3","T0","3V3","T1"])


def branch_fanouts(board):
    """Reserve a staggered escape for all ten mux branch pins before long routes."""
    result = {}
    for pin in (1,2,3,4,5,6):
        pad = board.pad("U10",pin)
        x,y = pad["center"]
        target = [11.45 if pin % 2 else 10.65,y]
        board.trace(pad["net"],[pad["center"],target])
        board.via(pad["net"],target)
        result[pad["net"]] = target
    for pin,target_y in ((7,20.55),(8,21.35),(10,21.35),(11,20.55)):
        pad = board.pad("U10",pin)
        target = [pad["center"][0],target_y]
        board.trace(pad["net"],[pad["center"],target])
        board.via(pad["net"],target)
        result[pad["net"]] = target
    return result


def controller_fanouts(board):
    """Escape every other active IC pin before routing can surround it."""
    targets = {
        ("U10","19"):[15.55,14.8],("U10","20"):[15.05,13.95],
        ("U10","21"):[14.55,14.8],("U10","24"):[13.05,14.8],
        ("U11","4"):[10.7,26.7],("U11","5"):[9.85,27.2],
        ("U11","10"):[17.7,25.2],("U11","9"):[18.5,25.7],
        ("U11","8"):[17.7,26.2],("U11","7"):[18.5,26.7],
        ("U11","6"):[17.7,27.2],
    }
    for (ref,pin),target in targets.items():
        pad = board.pad(ref,pin)
        board.trace(pad["net"],[pad["center"],target])
        board.via(pad["net"],target)
    return targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--placement-only", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT/"engineering/designs/b2.json").read_text())
    layout = json.loads((ROOT/"engineering/concepts/b2_layout.json").read_text())
    b1 = json.loads((ROOT/"engineering/electronics/b1/b1_head.json").read_text())
    basis = json.loads((ROOT/"engineering/release/b1/b1_manifest.json").read_text())
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Develop one B2 board while preserving B1 Hall centers and axes; independent DRC is a separate step") as record:
        native = Polygon(layout["outline_yz_mm"],layout["holes_yz_mm"])
        native = unary_union([native,box(*config["pcb"]["controller_bay_yz_mm"])]).buffer(0)
        original_area = native.area
        frame = trimesh.load_mesh(PARTS["hard_frame"],process=True)
        if digest(PARTS["hard_frame"]) != basis["source_hashes"]["hard"]:
            raise ValueError("Unexpected source frame")
        outer_tpu = Polygon(json.loads((ROOT/"engineering/release/b1/source_interface.json").read_text())["outer_yz"])
        combined = side_outline(frame).union(outer_tpu)
        # The fixed PCB is outside both parts in X. It can bridge internal
        # side windows; those voids are not the external silhouette.
        silhouette = Polygon(combined.exterior.coords)
        # A consolidated circuit needs a continuous routing band; the B1
        # bracket's narrow spine was dimensioned for five wired head boards.
        contour = []
        ys = np.linspace(native.bounds[0]+1.5,config["pcb"]["controller_bay_yz_mm"][2],180)
        for y in ys:
            section = silhouette.intersection(LineString([(y,-10),(y,45)]))
            contour.append((float(y),section.bounds[3]-.4))
        band = Polygon(contour+[(y,z-config["pcb"]["backbone_width_mm"]) for y,z in reversed(contour)])
        native = native.union(band.intersection(silhouette))
        arms = []
        for pose in basis["sensor_poses"]:
            y,z = pose["native_yz_mm"]
            top = native.intersection(LineString([(y,-10),(y,45)])).bounds[3]
            arms.append(LineString([(y,z),(y,top-.8)]).buffer(config["pcb"]["sensor_arm_width_mm"]/2))
        native = unary_union([native,*arms]).intersection(silhouette.buffer(-.01)).buffer(0)
        if native.geom_type != "Polygon":
            raise ValueError("B2 board is disconnected")
        inset = native.buffer(-.3)
        inset_regions = [inset] if inset.geom_type=="Polygon" else list(inset.geoms)
        assigned = [next((i for i,r in enumerate(inset_regions) if r.covers(Point(s["native_yz_mm"]))),-1)
                    for s in basis["sensor_poses"]]
        if len(set(assigned)) != 1 or -1 in assigned:
            raise ValueError(f"Board arms cannot carry a 0.3 mm copper/edge allowance: {assigned}")
        reinforced_area = native.area-original_area
        # Round holes become exact NPTH primitives; retain every other cutout.
        mounts = basis["carrier_mounts"]
        holes = [list(ring.coords) for ring in native.interiors
                 if not any(Polygon(ring).contains(Point(m["center_yz_mm"])) for m in mounts)]
        native = Polygon(native.exterior.coords,holes).simplify(.015,preserve_topology=True)
        outline = affinity.affine_transform(native,[-1,0,0,-1,0,40])
        board = Board("b2_main",outline,config["pcb"]["thickness_mm"],
                      config["pcb"]["clearance_mm"],config["pcb"]["edge_clearance_mm"])
        for mount in mounts:
            board.add_hole(to_board(mount["center_yz_mm"]),config["mechanical"]["board_bore_mm"],
                           config["mechanical"]["clamp_copper_keepout_diameter_mm"])
        endpoints, axes = add_heads(board,b1,basis)
        add_controller(board,config)
        branch_ports = branch_fanouts(board)
        controller_ports = controller_fanouts(board)
        controller_refs = {c["reference"] for c in board.components
                           if c["reference"] in ("U10","U11","J1","J2") or c["reference"][1:].isdigit() and int(c["reference"][1:])>=100}
        for pad in board.pads:
            if pad["reference"] not in controller_refs or not pad["net"]:
                continue
            center = branch_ports[pad["net"]] if pad["reference"]=="U10" and pad["net"] in branch_ports else controller_ports.get(
                (pad["reference"],pad["pad"]),pad["center"])
            endpoints.setdefault(pad["net"],[]).append(center)
        router = Router(board,config["pcb"]["grid_mm"],config["pcb"]["track_width_mm"])
        stem_ports = []
        for index,pose in enumerate(basis["sensor_poses"]):
            for name,offset in ((f"SDA{index}",-.8),(f"SCL{index}",0),("3V3",.8)):
                y = pose["native_yz_mm"][0]+offset
                top = native.intersection(LineString([(y,-10),(y,45)])).bounds[3]
                point = to_board([y,top-1.0])
                board.via(name,point)
                source_pin = 1 if name=="3V3" else (4 if name.startswith("SDA") else 3)
                source_point = board.pad(f"TP{index+1}",source_pin)["center"]
                stem_ports.append({"sensor":pose["id"],"net":name,"head":source_point,"backbone":point})
        checks = {"hall_centers_and_axes_preserved":True,"routed":False,
                  "manufacturing_drc":"not run","physical_boards_tested":0}
        try:
            if not args.placement_only:
                # THT ground and both exposed pads already have a vertical path.
                ground = [p for p in board.pads if p["reference"] in controller_refs and p["net"]=="GND"
                          and not p.get("drill") and p["reference"]!="U10"]
                router.ground(ground)
                for pad in board.pads:
                    if pad["reference"] not in controller_refs or pad["reference"][0] not in ("R","C") or pad["net"]=="GND":
                        continue
                    target = router.escape(pad)
                    endpoints[pad["net"]] = [target if math.dist(p,pad["center"])<1e-7 else p
                                              for p in endpoints[pad["net"]]]
                for net in ("RESET","T0","T1","VDD_HALF","CHECK_HALF","SDA","SCL"):
                    print(f"Routing controller / {net}",flush=True)
                    router.tree(net,endpoints[net])
                power_heads = [p["head"] for p in stem_ports if p["net"]=="3V3"]
                root_power = [p for p in endpoints["3V3"] if all(math.dist(p,q)>1e-7 for q in power_heads)]
                print("Routing controller / 3V3",flush=True)
                router.tree("3V3",root_power)
                # Complete all narrow arms before occupying the shared
                # backbone. Otherwise a greedy long route can fence off a
                # later arm on every signal layer.
                for port in stem_ports:
                    print(f"Routing {port['sensor']} arm / {port['net']}",flush=True)
                    router.connect(port["net"],port["head"],port["backbone"])
                    endpoints[port["net"]] = [
                        port["backbone"] if math.dist(p,port["head"])<1e-7 else p
                        for p in endpoints[port["net"]]]
                net_order = ["3V3"]+[f"{bus}{i}" for i in (4,3,2,1,0) for bus in ("SCL","SDA")]
                endpoints["3V3"] = [controller_ports[("U10","21")],*[p["backbone"] for p in stem_ports if p["net"]=="3V3"]]
                base_tracks,base_vias,base_receipts = list(board.tracks),list(board.vias),list(router.routed)
                attempted_orders = set()
                routing_attempts = []
                for attempt in range(8):
                    signature = tuple(net_order)
                    if signature in attempted_orders:
                        # Deterministic alternate priority, never smaller
                        # clearance or a hidden exemption.
                        tail = net_order[1:]
                        net_order = ["3V3",*tail[1:],tail[0]]
                        signature = tuple(net_order)
                    attempted_orders.add(signature)
                    board.tracks = list(base_tracks);board.vias = list(base_vias)
                    router.routed = list(base_receipts)
                    print(f"Backbone routing attempt {attempt+1}: {', '.join(net_order)}",flush=True)
                    try:
                        for net in net_order:
                            router.tree(net,endpoints[net])
                    except ValueError as error:
                        if not str(error).startswith(("No route","No layer escape","No clear route")):
                            raise
                        routing_attempts.append({"order":list(net_order),"failed_net":net,"reason":str(error)})
                        if attempt==7 or net=="3V3":
                            raise
                        net_order = ["3V3",net,*[n for n in net_order if n not in ("3V3",net)]]
                    else:
                        routing_attempts.append({"order":list(net_order),"complete":True})
                        break
                checks["routing_attempts"] = routing_attempts
                checks["routed"] = True
                checks["removed_redundant_vias"] = board.prune_unused_vias()
        finally:
            if hasattr(router,"last_failure"):
                np.savez_compressed(OUTPUT/"route_failure.npz",**router.last_failure)
            board.zones.append({"net":"GND","layer":"In1.Cu","shape":board.outline})
            board.zones.append({"net":"GND","layer":"B.Cu","shape":board.outline})
            payload = board.write(OUTPUT)
            board.assembly_svg(OUTPUT/"b2_assembly.svg")
            (OUTPUT/"b2_design_checks.json").write_text(json.dumps({
                **checks,"revision":config["revision"],"head_axes":axes,
                "route_receipts":router.routed,"pcb_component_plane_native_x_mm":basis["sensor_pcb_top_x_mm"],
                "pcb_outline_yz_mm":list(native.exterior.coords),
                "pcb_cutouts_yz_mm":[list(r.coords) for r in native.interiors],
                "controller_bay_yz_mm":config["pcb"]["controller_bay_yz_mm"],
                "added_web_area_mm2":reinforced_area,"all_head_regions_connected_after_0_3mm_inset":True,
                "stem_ports":stem_ports,
                "in1_signal_trace_length_mm":sum(math.dist(t["start"],t["end"]) for t in board.tracks if t["layer"]=="In1.Cu"),
                "source_hashes":{name:digest(ROOT/name) for name in (
                    "engineering/designs/b2.json","engineering/scripts/build_b2_pcb.py",
                    "engineering/scripts/prototype_pcb.py","engineering/scripts/prototype_route.py",
                    "engineering/electronics/b1/b1_head.json","engineering/release/b1/b1_manifest.json")},
                "limits":["Copper routing is not electrical or mechanical qualification.",
                          "No assembled B2 or force calibration has been measured.",
                          "Connector wires and fastener heads require installed clearance checks."],
            },indent=2)+"\n")
            record["board"] = {"components":len(payload["components"]),"pads":len(board.pads),
                               "tracks":len(board.tracks),"vias":len(board.vias),**checks}
        print(json.dumps(record["board"],indent=2))


if __name__ == "__main__":
    main()
