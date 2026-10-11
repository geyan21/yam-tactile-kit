#!/usr/bin/python3
"""Prepare C1's firmware archive and procurement list from the checked design."""

from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"engineering/software"))
from c1_protocol import SETTINGS
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/c1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    cfg = json.loads((ROOT/"engineering/designs/c1_electronics.json").read_text())
    pcb = json.loads((OUTPUT/"pcb/c1_readout.json").read_text())
    plan = json.loads((OUTPUT/"c1_manifest.json").read_text())
    if cfg["adc"]["clock_hz"]!=SETTINGS["clock_hz"] or cfg["adc"]["gain"]!=SETTINGS["gain"]:
        raise ValueError("Firmware/decoder and electronic configuration disagree")
    with execution(ROOT/"build/records","Package C1 raw firmware and a component/fixture BOM, with no physical performance claims") as record:
        fw = OUTPUT/"firmware";fw.mkdir(exist_ok=True)
        names = ("main.py","ads1232.py","ina219.py")
        hashes = {}
        for name in names:
            source = ROOT/"engineering/firmware/c1"/name
            compile(source.read_text(),name,"exec")
            shutil.copyfile(source,fw/name)
            hashes[name] = digest(source)
        manifest = {"protocol":"yam-c1/1","revision":"C1.1","files":hashes,"settings":SETTINGS,
                    "gpio":cfg["gpio"],"physical_boards_tested":0,"actuator_control":False,
                    "force_calibrated":False,"note":"Copy all three files to a dedicated RP2040 Pico running MicroPython; verify hardware before force tests."}
        (fw/"firmware_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        with zipfile.ZipFile(OUTPUT/"c1_firmware.zip","w",zipfile.ZIP_DEFLATED) as archive:
            for name in (*names,"firmware_manifest.json"):
                info = zipfile.ZipInfo(name,date_time=(2026,10,11,0,0,0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info,(fw/name).read_bytes())
        rows = []
        def add(kind,quantity,item,specification,where,reference,note=""):
            rows.append([kind,quantity,item,specification,where,reference,note])
        groups = defaultdict(list)
        for component in pcb["components"]:
            value = component["value"]
            if component["reference"].startswith("J"):
                count = sum(p["reference"]==component["reference"] for p in pcb["pads"])
                value += f"; {count} pins"
            groups[value].append(component["reference"])
        refs = {
            "ADS1232IPWR":"https://www.ti.com/lit/ds/symlink/ads1232.pdf",
            "INA219AIDR":"https://www.ti.com/lit/ds/symlink/ina219.pdf",
            "TMUX1101DBVR":"https://www.ti.com/lit/ds/symlink/tmux1101.pdf",
        }
        for value,designators in sorted(groups.items()):
            add("Electronics",len(designators),value,value,"; ".join(designators),refs.get(value,"PCB source and pin/net CSV"),
                "Use at least 16 V rating." if "100nF" in value else
                "Use C0G dielectric and at least 10 V rating for the differential input capacitors." if "C0G" in value else "")
        add("PCB",1,"C1 readout board","82 x 64 x 1.6 mm; four layers; checked C1 Gerbers/drills","Wrist/base","c1_readout_fabrication.zip")
        add("Controller",1,"Raspberry Pi Pico","RP2040; dedicated to the sensor readout","Wrist/base","c1_firmware.zip")
        add("Gauge",8,"Axial foil gauges","CEA-13-062UWA-350; retain lot gauge factor and thermal data","Four on each beam face","https://docs.micro-measurements.com/?id=2512","Grid centers and orientation are in the C1 placement file.")
        add("Bonding","1 shared","Gauge adhesive kit","M-Bond 200 for initial laboratory specimens","Prepared beam faces","https://micro-measurements.com/node/418","Use manufacturer preparation/cure instructions; long-term performance must be characterized.")
        add("Protection","1 shared","Gauge coating","M-Coat A candidate; record coating and cure","Bonded gauges","Micro-Measurements instructions","Test the complete protected assembly.")
        add("Mechanical","choose 1","Fixed carrier","C1 clearance/countersink OR M3 tap-drill variant","Original jaw interface","C1 STEP files","The choice depends on the actual mating jaw.")
        for part in plan["parts"]:
            if part["id"].startswith("c1_fixed_carrier"):
                continue
            shared = "1 shared" if "bench" in part["id"] or "stencil" in part["id"] else 1
            add("Fixture" if shared=="1 shared" else "Mechanical",shared,part["id"],part["material"],
                part["purpose"],part["step"],"Metal force-path parts; printed copies are fit witnesses only." if "aluminum" in part["material"].lower() else "")
        add("Fastener",4,"Beam clamp screws","M4 x 25 fully threaded socket screws","Two at each beam end","C1 assembly drawing","Verify actual engagement and no bottoming.")
        add("Fastener",8,"Small-OD flat washers","M4 DIN 433: approximately 4.3 ID x 8 OD x 0.5 mm","Two stacked per M4 clamp screw","https://www.accu.co.uk/metric-flat-washers/404898-HRDW-M4-A2","Measure the combined 1.0 mm stack; this matches the reserved envelope.")
        add("Fastener",2,"Fixed mount screws","M3 90-degree flat heads, head diameter at most 6.0 mm; length from actual mating thread","Fixed clearance/countersink carrier","C1 build guide","Tap-drill variant instead uses the appropriate mating-jaw fasteners.")
        add("Fastener","2 sets","Floating finger fasteners","M3 hardware within 7 mm diameter and 4.5 mm rear projection","Original finger to floating carrier","C1 build guide","Select actual lengths from stack; preserve source finger retention.")
        add("Cable","8 conductors","Bridge cabling","Two four-wire shielded cables; twisted excitation and signal pairs","Beam to readout","C1 wiring map","Measure excitation-loop resistance; maximum 2 ohms. Keep slack out of the force path.")
        add("Cable",1,"Pico harness","Short 16-way 2.54 mm connection with documented pin mapping","Pico to readout J1","C1 wiring map","Keep clock wiring short and verify waveforms.")
        add("Fixture","1 shared","Force reference","At least 25 N capacity; documented uncertainty at most 0.05 N","Bench","Campaign requirements","L1 is not an independent reference until separately qualified.")
        add("Fixture","1 shared","Displacement measurement","Resolution suitable for a 0.1 mm added-motion screen","Nail and adapter","Campaign requirements","Measure the actual installed assembly.")
        add("Electrical fixture","8 shared","Dummy-bridge resistors","Matched 348 or 350 ohm resistors; four per bridge","JA/JB during board-only checks","C1 build guide","Record as electrical_dummy; never use dummy bridges as physical force-calibration data.")
        with (OUTPUT/"c1_bom.csv").open("w",newline="") as stream:
            writer = csv.writer(stream,lineterminator="\n")
            writer.writerow(["category","quantity_per_finger_or_shared","item","specification","location","reference","notes"])
            writer.writerows(rows)
        record["packet"] = {"firmware_files":len(names),"bom_rows":len(rows),"physical_boards_tested":0}
        print(json.dumps(record["packet"],indent=2))


if __name__=="__main__":
    main()
