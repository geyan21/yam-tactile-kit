#!/usr/bin/python3
"""Generate C1's two-bridge wrist readout using an explicit pin/net design."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

from shapely import affinity
from shapely.geometry import box
from prototype_pcb import Board
from prototype_route import Router
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/c1/pcb"


def passive(board,ref,value,point,nets,rotation=0,size="0402"):
    if size=="0402":
        board.resistor(ref,value,point,nets,rotation)
    else:
        pitch,pad,body = ((2.2,(1.2,1.4),(2.0,1.25)) if size=="0805"
                          else (3.2,(1.8,2.0),(3.2,1.6)))
        board.component(ref,value,point,[(1,-pitch/2,0,*pad,nets[0]),(2,pitch/2,0,*pad,nets[1])],
                        rotation,body=list(body),height=.8)


def header(board,ref,point,nets,rows=1):
    pads = []
    if rows==1:
        for i,net in enumerate(nets):
            pads.append((i+1,0,(i-(len(nets)-1)/2)*2.54,1.8,1.8,net,False))
        body = [2.54,len(nets)*2.54]
    else:
        for i,net in enumerate(nets):
            pads.append((i+1,(-1 if i%2==0 else 1)*1.27,
                         (i//2-(len(nets)//2-1)/2)*2.54,1.8,1.8,net,False))
        body = [8.9,len(nets)//2*2.54+5.0]
    board.component(ref,"2.54mm through-hole header",point,pads,body=body,height=8)
    for pad in board.pads:
        if pad["reference"]==ref:
            pad["drill"] = 1.0


def channel(board,index,cy):
    name = ("A","B")[index];x = 34
    def n(s):
        return name+"_"+s
    adc_nets = {
        1:"3V3",2:"GND",3:n("CLK"),4:"",5:"GND",6:"GND",7:"GND",8:"GND",
        9:n("CAP9"),10:n("CAP10"),11:n("AP"),12:n("AN"),13:"GND",14:"GND",
        15:"GND",16:n("E"),17:"GND",18:n("VA"),19:"3V3",20:"3V3",21:"3V3",
        22:"PDWN",23:"SER_CLK",24:n("DOUT_RAW"),
    }
    pads = []
    for i in range(12):
        pads.append((i+1,-2.9,-3.575+.65*i,1.5,.45,adc_nets[i+1]))
        pads.append((i+13,2.9,3.575-.65*i,1.5,.45,adc_nets[i+13]))
    board.component("U"+name,"ADS1232IPWR",[x,cy],pads,rotation=270,body=[4.4,7.8],height=1.2,
                    source="TI SBAS350H: PW-24 pinout and land pattern")
    header(board,"J"+name,[7,cy-1.5],[n("E"),"GND",n("SP"),n("SN")])
    # INA219 SOIC has a different pin order from its SOT-23 version.
    monitor = {1:"GND",2:"GND" if index==0 else "3V3",3:"SDA",4:"SCL",5:"3V3",6:"GND",7:n("E"),8:n("VA")}
    pins = []
    for i in range(4):
        pins.append((i+1,-2.75,-1.905+1.27*i,1.55,.6,monitor[i+1]))
        pins.append((i+5,2.75,1.905-1.27*i,1.55,.6,monitor[i+5]))
    board.component("U"+name+"MON","INA219AIDR",[15,cy-13],pins,rotation=270,body=[3.91,4.9],height=1.75,
                    source="TI SBOS448G: D/SOIC-8 pinout")
    passive(board,"R"+name+"SH","0.1ohm 1% 1206",[16.27,cy-7.7],[n("E"),n("VA")],size="1206")
    passive(board,"R"+name+"SUP","10ohm 0805",[20,cy-17.2],["5V",n("VA")],size="0805")
    passive(board,"C"+name+"SUP","10uF 10V X7R 0805",[24,cy-17],[n("VA"),"GND"],size="0805")
    passive(board,"C"+name+"MON","100nF 16V X7R 0402",[11,cy-10.6],["3V3","GND"])
    mux = [(1,-1.3,-.95,1.1,.6,n("SHUNTED")),(2,-1.3,0,1.1,.6,n("SP")),
           (3,-1.3,.95,1.1,.6,"GND"),(4,1.3,.95,1.1,.6,n("SHUNT")),
           (5,1.3,-.95,1.1,.6,n("VA"))]
    board.component("U"+name+"SW","TMUX1101DBVR",[15,cy+1],mux,body=[1.6,2.9],height=1.45,
                    source="TI SCDS410D: DBV-5 pinout and land pattern")
    passive(board,"R"+name+"CAL","1M 0.1% 0402",[11,cy-2.5],[n("E"),n("SHUNTED")])
    passive(board,"R"+name+"SEL","100k 1% 0402",[19.5,cy+2],[n("SHUNT"),"GND"])
    passive(board,"C"+name+"SW","100nF 16V X7R 0402",[18.5,cy-1.5],[n("VA"),"GND"])
    # Flare the fine-pitch analog input pins to a 1 mm pair pitch for the RC filter.
    passive(board,"R"+name+"P","100ohm 1% 0402",[x-3.3,cy-7.7],[n("SP"),n("AP")],rotation=270)
    passive(board,"R"+name+"N","100ohm 1% 0402",[x-4.3,cy-7.7],[n("SN"),n("AN")],rotation=270)
    passive(board,"C"+name+"DIF","10nF C0G 0402",[x-3.8,cy-5.2],[n("AN"),n("AP")])
    passive(board,"C"+name+"PGA","100nF X7R 0402",[x-1.8,cy-5.2],[n("CAP10"),n("CAP9")])
    passive(board,"R"+name+"BP","10M 1% 0402",[x-.8,cy-9.7],[n("VA"),n("AP")])
    passive(board,"R"+name+"BN","10M 1% 0402",[x-7.8,cy-9.7],["GND",n("AN")])
    passive(board,"C"+name+"REF","100nF X7R 0402",[x-1.95,cy+5.3],["GND",n("E")])
    passive(board,"C"+name+"AV","100nF X7R 0402",[x+.4,cy+5.3],[n("VA"),"GND"])
    passive(board,"C"+name+"DV","100nF X7R 0402",[x+6.4,cy-2.9],["3V3","GND"])
    passive(board,"R"+name+"OUT","33ohm 0402",[x+8,cy+2.9],[n("DOUT_RAW"),n("DOUT")])
    # Direct analog interconnects are deliberately short and stay on F.Cu.
    for pin,net,flared_x,ref in ((11,n("AP"),x-3.3,"R"+name+"P"),(12,n("AN"),x-4.3,"R"+name+"N")):
        point = board.pad("U"+name,pin)["center"]
        board.trace(net,[point,[point[0],cy-4.1],[flared_x,cy-4.4],board.pad(ref,2)["center"]],width=.2)
    for pin,net,flared_x,cap_pin in ((9,n("CAP9"),x-1.3,2),(10,n("CAP10"),x-2.3,1)):
        point = board.pad("U"+name,pin)["center"]
        board.trace(net,[point,[point[0],cy-4.1],[flared_x,cy-4.4],board.pad("C"+name+"PGA",cap_pin)["center"]],width=.2)


def component_checks(board):
    regions = []
    for c in board.components:
        if "body_mm" not in c:
            continue
        w,h = c["body_mm"]
        shape = affinity.rotate(box(-w/2,-h/2,w/2,h/2),-c["rotation_deg"],origin=(0,0))
        shape = affinity.translate(shape,*c["center_mm"])
        if not board.outline.covers(shape):
            raise ValueError("Component body leaves board: "+c["reference"])
        for ref,other in regions:
            if shape.intersection(other).area>1e-7:
                raise ValueError(f"Component bodies overlap: {c['reference']} and {ref}")
        for pad in board.pads:
            if pad["reference"]!=c["reference"] and shape.intersection(pad["shape"]).area>1e-7:
                raise ValueError(f"Component body overlaps another land: {c['reference']} / {pad['reference']}.{pad['pad']}")
        regions.append((c["reference"],shape))
    for net in board.nets:
        if net and sum(pad["net"]==net for pad in board.pads)<2:
            raise ValueError("A declared net has only one terminal: "+net)
    return len(regions)


def route(board,config):
    p = config["pcb"]
    router = Router(board,grid=.1,width=p["minimum_signal_width_mm"],
                    via_diameter=p["via_diameter_mm"],via_drill=p["via_drill_mm"])
    # In1.Cu remains a continuous ground reference for the analog channels.
    router.signal_layers = ("F.Cu","In2.Cu","B.Cu")
    router.layer_cost = (1,1,1)
    ground = [pad for pad in board.pads if pad["net"]=="GND" and not pad.get("drill")]
    router.ground(ground)
    endpoints = {}
    complete_nets = {name+"_"+net for name in ("A","B") for net in ("CAP9","CAP10")}
    def included(pad):
        if pad["net"] in ("","GND") or pad["net"] in complete_nets:
            return False
        if pad["reference"] in ("UA","UB") and pad["pad"] in ("11","12"):
            return False
        if pad["reference"] in ("CADIF","CBDIF"):
            return False
        return True
    for pad in board.pads:
        if not included(pad):
            continue
        endpoints.setdefault(pad["net"],[]).append(pad["center"])
    # Small lands need a reserved escape before the long buses are routed.
    for pad in board.pads:
        if not included(pad) or pad.get("drill"):
            continue
        if pad["reference"].startswith("U") and pad["pad"] in ("9","10","11","12"):
            continue  # already connected to the analog RC/PGA network
        target = router.escape(pad)
        endpoints[pad["net"]] = [target if math.dist(point,pad["center"])<1e-7 else point for point in endpoints[pad["net"]]]
    order = sorted(endpoints,key=lambda n:(n in ("5V","3V3","SDA","SCL","PDWN","SER_CLK","ADC_CLK"),len(endpoints[n]),n))
    for net in order:
        print("Routing C1 "+net,flush=True)
        router.tree(net,endpoints[net])
    removed = board.prune_unused_vias()
    return {"routes":router.routed,"removed_redundant_vias":removed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--placement-only",action="store_true")
    args = parser.parse_args()
    cfg = json.loads((ROOT/"engineering/designs/c1_electronics.json").read_text())
    p = cfg["pcb"]
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Develop the C1 dual-bridge readout with explicit ADC pinout, short analog connections and separate ground plane") as record:
        board = Board("c1_readout",box(0,0,p["width_mm"],p["height_mm"]),p["thickness_mm"],
                      p["minimum_clearance_mm"],p["edge_clearance_mm"])
        for x in (3,p["width_mm"]-3):
            for y in (3,p["height_mm"]-3):
                board.add_hole([x,y],2.7,5.5)
        channel(board,0,21);channel(board,1,49)
        header(board,"J1",[71,32],cfg["digital_connector"],rows=2)
        passive(board,"RCLK_A","33ohm 0402",[64,20],["ADC_CLK","A_CLK"])
        passive(board,"RCLK_B","33ohm 0402",[64,22],["ADC_CLK","B_CLK"])
        passive(board,"RPDWN","100k 0402",[64,40],["PDWN","GND"])
        passive(board,"RSDA","4.7k 0402",[64,44],["3V3","SDA"])
        passive(board,"RSCL","4.7k 0402",[64,46],["3V3","SCL"])
        passive(board,"C5","10uF 10V X7R 0805",[64,50],["5V","GND"],size="0805")
        passive(board,"C3","1uF 10V X7R 0402",[64,53],["3V3","GND"])
        checked = component_checks(board)
        checks = {"components_checked_for_body_overlap":checked,"routed":False,"physical_boards_tested":0}
        try:
            if not args.placement_only:
                checks.update(route(board,cfg));checks["routed"] = True
        finally:
            board.zones.append({"net":"GND","layer":"In1.Cu","shape":board.outline})
            board.zones.append({"net":"GND","layer":"B.Cu","shape":board.outline})
            board.write(OUTPUT)
            board.assembly_svg(OUTPUT/"c1_readout_assembly.svg")
            checks["source_pcb_sha256"] = hashlib.sha256((OUTPUT/"c1_readout.kicad_pcb").read_bytes()).hexdigest()
            checks["source_hashes"] = {
                name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                for name in ("engineering/designs/c1_electronics.json","engineering/scripts/build_c1_pcb.py",
                             "engineering/scripts/prototype_pcb.py","engineering/scripts/prototype_route.py")
            }
            (OUTPUT/"c1_pcb_design_checks.json").write_text(json.dumps(checks,indent=2)+"\n")
            record["checks"] = {"components":len(board.components),"pads":len(board.pads),
                                "tracks":len(board.tracks),"vias":len(board.vias),"routed":checks["routed"]}
        print(json.dumps(record["checks"],indent=2))


if __name__=="__main__":
    main()
