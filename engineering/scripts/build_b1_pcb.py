#!/usr/bin/python3
"""Generate an editable two-layer B1 MLX90393 head, explicit netlist and assembly SVG."""

import csv
import json
from pathlib import Path
import re
import sys
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution

DEST = ROOT / "engineering/electronics/b1"
NETS = {"": 0, "3V3": 1, "GND": 2, "SCL": 3, "SDA": 4}
PIN_NET = {1: "", 2: "3V3", 3: "SCL", 4: "GND", 5: "SDA", 6: "", 7: "",
           8: "3V3", 9: "GND", 10: "GND", 11: "GND", 12: "GND", 13: "GND",
           14: "GND", 15: "3V3", 16: "GND", 17: "GND"}
PIN_NAMES = {1: "INT (unused)", 2: "MS/CS", 3: "SCL", 4: "NC→GND", 5: "SDA",
             6: "MISO (unused)", 7: "INT/TRIG (unused)", 8: "VDD_IO",
             9: "NC→GND", 10: "NC→GND", 11: "A1", 12: "A0", 13: "VSS",
             14: "NC→GND", 15: "VDD", 16: "NC→GND", 17: "Exposed pad"}


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    library=DEST/"B1.pretty";library.mkdir(exist_ok=True)
    (DEST/"fp-lib-table").write_text('(fp_lib_table (lib (name "B1") (type "KiCad") (uri "${KIPRJMOD}/B1.pretty") (options "") (descr "Embedded B1 head footprints")))\n')
    with execution(ROOT / "build/records", "Generate B1 editable PCB and explicit pin/net records for subsequent independent KiCad DRC") as record:
        board = ['(kicad_pcb (version 20240108) (generator "pcbnew")',
                 '(general (thickness 0.8)) (paper "A4")',
                 '(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (32 "B.Adhes" user) (33 "F.Adhes" user)'
                 ' (34 "B.Paste" user) (35 "F.Paste" user) (36 "B.SilkS" user "b.silkscreen")'
                 ' (37 "F.SilkS" user "f.silkscreen") (38 "B.Mask" user) (39 "F.Mask" user)'
                 ' (44 "Edge.Cuts" user) (46 "B.CrtYd" user) (47 "F.CrtYd" user)'
                 ' (48 "B.Fab" user) (49 "F.Fab" user))',
                 '(setup (pad_to_mask_clearance 0.025))']
        board += [f'(net {index} "{name}")' for name, index in NETS.items()]
        pads = []; tracks = []; vias = []; components = []

        def footprint(ref, value, x, y, items):
            components.append({"reference": ref, "value": value, "x_mm": x, "y_mm": y, "rotation_deg": 0})
            lines = [f'(footprint "B1:{ref}" (layer "F.Cu") (at {x} {y}) (attr smd)',
                     f'(property "Reference" "{ref}" (at 0 -1) (layer "F.Fab") (effects (font (size 0.6 0.6) (thickness 0.1))))',
                     f'(property "Value" "{value}" (at 0 1) (layer "F.Fab") hide (effects (font (size 0.5 0.5) (thickness 0.1))))']
            for number, dx, dy, width, height, net, paste in items:
                layers = '"F.Cu" "F.Mask"' + (' "F.Paste"' if paste else "")
                lines.append(f'(pad "{number}" smd rect (at {dx} {dy}) (size {width} {height}) (layers {layers})'
                             f' (net {NETS[net]} "{net}"))')
                pads.append({"reference": ref, "pad": number, "x": x+dx, "y": y+dy,
                             "width": width, "height": height, "net": net})
            lines.append(")")
            board.extend(lines)
            pattern="\n".join(lines).replace(f'(footprint "B1:{ref}"',f'(footprint "{ref}"',1).replace(f"(at {x} {y})","(at 0 0)",1)
            pattern=re.sub(r' \(net \d+ "[^"]*"\)',"",pattern)
            (library/f"{ref}.kicad_mod").write_text(pattern+"\n")

        # Manufacturer top view (Fig. 27) rotated 90° so Hall X is board +u,
        # Hall Y is board +v (-KiCad Y), Hall Z is out of the component side.
        qfn = []
        locations = {}
        for i in range(4):
            locations[i+1] = (1.4, .75-i*.5)
            locations[i+5] = (.75-i*.5, -1.4)
            locations[i+9] = (-1.4, -.75+i*.5)
            locations[i+13] = (-.75+i*.5, 1.4)
        for number, (x, y) in locations.items():
            width, height = (.6, .25) if number in (*range(1,5), *range(9,13)) else (.25, .6)
            qfn.append((number, x, y, width, height, PIN_NET[number], True))
        qfn.append((17, 0, 0, 1.7, 1.7, "GND", False))
        footprint("U1", "MLX90393SLW-ABA-011", 100, 100, qfn)
        # Four reduced stencil apertures over EP; ordinary plated via must be
        # tented from the underside. Inspect EP solder fill in the first panel.
        for x in (-.43, .43):
            for y in (-.43, .43):
                board.append(f'(gr_rect (start {100+x-.325} {100+y-.325}) (end {100+x+.325} {100+y+.325})'
                             ' (stroke (width 0) (type default)) (fill solid) (layer "F.Paste"))')
        for ref, value, x, y, left, right in (
            ("C1", "100nF 16V X7R 0402", 102.9, 101., "3V3", "GND"),
            ("C2", "100nF 16V X7R 0402", 97.2, 99.3, "GND", "3V3"),
            ("R1", "10k 1% 0402", 97.2, 97.9, "3V3", "SCL"),
            ("R2", "10k 1% 0402", 103., 98.35, "3V3", "SDA"),
        ):
            footprint(ref, value, x, y, [(1,-.5,0,.55,.55,left,True), (2,.5,0,.55,.55,right,True)])
        footprint("J1", "Solder wires 3V3 GND SCL SDA", 100, 96.8,
                  [(i+1, x, 0, .9, 1., net, False) for i,(x,net) in enumerate(
                      zip((-2.4,-.8,.8,2.4),("3V3","GND","SCL","SDA")))])

        def trace(net, points, layer="F.Cu", width=.15):
            for start, end in zip(points, points[1:]):
                tracks.append((net, start, end, layer, width))
                board.append(f'(segment (start {start[0]} {start[1]}) (end {end[0]} {end[1]})'
                             f' (width {width}) (layer "{layer}") (net {NETS[net]}))')

        def via(net, x, y, size=.45, drill=.2):
            vias.append((net, x, y, size, drill))
            board.append(f'(via (at {x} {y}) (size {size}) (drill {drill}) (layers "F.Cu" "B.Cu") (net {NETS[net]}))')

        # NC and address pins connect inward to the ground pad, never to VDD.
        for number, net in PIN_NET.items():
            if net == "GND" and number != 17:
                dx, dy = locations[number]
                inner=(100+dx*.5,100+dy) if abs(dx)>abs(dy) else (100+dx,100+dy*.5)
                trace(net, [(100+dx,100+dy),inner])
        via("GND",100,100,.6,.3)
        # Signal routes.
        trace("SDA",[(100.75,98.6),(100.75,97.75),(102.4,97.75),(102.4,96.8)])
        trace("SDA",[(102.4,97.75),(103.5,97.75),(103.5,98.35)])
        trace("SCL",[(101.4,99.75),(102.1,99.75)])
        via("SCL",102.1,99.75)
        trace("SCL",[(102.1,99.75),(101.4,97.45),(100.8,97.45),(100.8,96.8)],"B.Cu")
        via("SCL",100.8,96.8)
        trace("SCL",[(97.7,97.9),(98.15,97.9)])
        via("SCL",98.15,97.9)
        trace("SCL",[(98.15,97.9),(98.4,97.45),(100.8,97.45)],"B.Cu")
        # Power rails and local decoupling.
        trace("3V3",[(101.4,100.25),(101.95,100.25),(101.95,102.05),(102.4,102.05),(102.4,101.)])
        trace("3V3",[(100.25,101.4),(100.25,102.05),(101.95,102.05)])
        trace("3V3",[(102.4,101.),(102.4,100.45)])
        via("3V3",102.4,100.45)
        trace("3V3",[(99.25,98.6),(99.25,98.05),(98.75,98.05)])
        via("3V3",98.75,98.05)
        trace("3V3",[(97.7,99.3),(97.7,99.85)])
        via("3V3",97.7,99.85)
        via("3V3",97.6,96.8)
        trace("3V3",[(97.6,96.8),(96.7,97.2),(96.7,97.9)])
        trace("3V3",[(97.6,96.8),(96.25,98.1),(96.25,101.2),(102.4,101.2),(102.4,100.45)],"B.Cu")
        trace("3V3",[(97.7,99.85),(97.7,101.2)],"B.Cu")
        trace("3V3",[(98.75,98.05),(98.75,99.5),(97.7,99.85)],"B.Cu")
        trace("3V3",[(102.5,98.35),(102.5,98.85)])
        via("3V3",102.5,98.85)
        trace("3V3",[(102.5,98.85),(102.75,99.3),(102.75,100.45),(102.4,100.45)],"B.Cu")
        via("GND",99.2,96.8)
        for net, x, y, vx, vy in (("GND",103.4,101.,103.4,100.25),
                                  ("GND",96.7,99.3,97.15,100.35)):
            trace(net,[(x,y),(vx,vy)]); via(net,vx,vy)
        trace("GND",[(97.15,100.35),(98.6,100.25)])
        board.append('(zone (net 2) (net_name "GND") (layer "B.Cu") (hatch edge 0.5)'
                     ' (connect_pads (clearance 0.15)) (min_thickness 0.15) (fill yes (thermal_gap 0.2) (thermal_bridge_width 0.2))'
                     ' (polygon (pts (xy 96 96) (xy 104 96) (xy 104 102.4) (xy 96 102.4))))')
        board.append('(gr_rect (start 96 96) (end 104 102.4) (stroke (width 0.05) (type default)) (fill none) (layer "Edge.Cuts"))')
        # Small pin-one mark, kept clear of pads and board edges.
        board.append('(gr_circle (center 101.8 100.9) (end 101.87 100.9) (stroke (width 0.1) (type default)) (fill none) (layer "F.SilkS"))')
        board.append(")")
        (DEST / "b1_head.kicad_pcb").write_text("\n".join(board)+"\n")
        (DEST / "b1_head.kicad_dru").write_text(
            '(version 1)\n(rule "B1 minimum clearance" (constraint clearance (min 0.15mm)))\n'
            '(rule "B1 copper to edge" (constraint edge_clearance (min 0.15mm)))\n'
            '(rule "B1 track width" (constraint track_width (min 0.15mm)))\n'
            '(rule "B1 via drill" (constraint hole_size (min 0.20mm)))\n'
            '(rule "B1 plated via diameter" (constraint via_diameter (min 0.45mm)))\n')
        with (DEST / "b1_head_pin_net.csv").open("w", newline="") as stream:
            writer=csv.writer(stream,lineterminator="\n"); writer.writerow(["reference","pad","signal","net"])
            writer.writerows(("U1", number, PIN_NAMES[number], net or "unconnected") for number,net in PIN_NET.items())
            for pad in pads:
                if pad["reference"] != "U1":
                    writer.writerow([pad["reference"],pad["pad"],pad["net"],pad["net"]])
        manifest = {"revision": "B1.0", "board_mm": [8,6.4,.8], "layers": 2,
                    "components": components, "pads": pads, "vias": vias, "tracks": tracks,
                    "sensor_local_axes_in_pcb_uv": {"X":[1,0,0],"Y":[0,1,0],"Z":[0,0,1]},
                    "sensor_u_v_mapping": "u = KiCad +X, v = KiCad -Y, w out of component face",
                    "pin1": "Right side, lowest pad in top view; small dot adjacent",
                    "source": "Melexis 3901090393 rev012 pp7,36-38; pinout Fig27 rotated 90 degrees",
                    "status": "Generated source; release requires independent KiCad DRC, net and pad-count checks",
                    "physical_boards_tested": 0}
        (DEST / "b1_head.json").write_text(json.dumps(manifest,indent=2)+"\n")
        colors={"GND":"#426078","3V3":"#b8573d","SDA":"#9866a5","SCL":"#278f7f","":"#aab3b6"}
        svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 560">',
             '<rect width="1000" height="560" fill="#fff"/>',
             '<g font-family="sans-serif" fill="#173f45">',
             '<text x="35" y="35" font-size="23">B1 · identical 8 × 6.4 mm sensor heads · top component view</text>',
             '<text x="35" y="63" font-size="14">Editable two-layer PCB. Confirm DRC receipt and pin 1 before fabrication. No assembled board is pictured.</text>']
        scale=62
        def point(x,y):return ((x-96)*scale+60,(y-96)*scale+105)
        svg.append('<rect x="60" y="105" width="496" height="396.8" rx="3" fill="#ecf4ee" stroke="#173f45"/>')
        for net,start,end,layer,width in tracks:
            x1,y1=point(*start); x2,y2=point(*end)
            svg.append(f'<path d="M{x1} {y1}L{x2} {y2}" stroke="{colors[net]}" stroke-width="{width*scale}" opacity="{.45 if layer=="B.Cu" else .9}"/>')
        for pad in pads:
            x,y=point(pad["x"],pad["y"]); w=pad["width"]*scale; h=pad["height"]*scale
            svg.append(f'<rect x="{x-w/2}" y="{y-h/2}" width="{w}" height="{h}" fill="{colors[pad["net"]]}" stroke="white" stroke-width="1"/>')
            if pad["reference"]=="U1" and pad["pad"]!=17:
                svg.append(f'<text x="{x}" y="{y+3}" text-anchor="middle" font-size="9" fill="white">{pad["pad"]}</text>')
        for net,x,y,size,drill in vias:
            x,y=point(x,y)
            svg.append(f'<circle cx="{x}" cy="{y}" r="{size*scale/2}" fill="{colors[net]}"/><circle cx="{x}" cy="{y}" r="{drill*scale/2}" fill="white"/>')
        for i,net in enumerate(("3V3","GND","SCL","SDA")):
            x,y=point(97.6+1.6*i,96)
            svg.append(f'<text x="{x}" y="{y-12}" text-anchor="middle" font-size="13">{net}</text>')
        texts=["Five copies per finger","U1: MLX90393SLW-ABA-011","C1/C2: 100 nF 0402","R1/R2: 10 kΩ 0402","J1: four solder wires","A0 = A1 = GND → 0x0C","Select one TCA9548A branch","Solid core leads are unsuitable","for repeated cable flexing.","","u / Hall X →","v / Hall Y ↑","Hall Z out of this view","Opaque traces: front copper","Faded traces: back copper","Ground plane omitted here."]
        for i,text in enumerate(texts):
            svg.append(f'<text x="610" y="{112+i*23}" font-size="16">{escape(text)}</text>')
        svg.append('<text x="35" y="530" font-size="14">Scale is schematic on screen; order from Gerbers and drill files. Use the checked KiCad source for dimensions.</text></g></svg>')
        (DEST / "b1_head_assembly.svg").write_text("\n".join(svg))
        record["generated"]={"components":len(components),"pads":len(pads),"tracks":len(tracks),"vias":len(vias)}
        print(json.dumps(record["generated"],indent=2))


if __name__ == "__main__":
    main()
