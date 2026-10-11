#!/usr/bin/python3
"""Package the N1 firmware and complete BOM, including the reused C1 board."""

import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/prototypes/nail"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    with execution(ROOT/"build/records","Package N1 acquisition code and selected materials while retaining the checked C1 bridge electronics") as record:
        folder=OUTPUT/"firmware";folder.mkdir(parents=True,exist_ok=True)
        local=ROOT/"engineering/firmware/nail"
        shared=ROOT/"engineering/firmware/c1"
        sources={name:local/name for name in ("main.py","ads1115.py","pressure_scan.py","config.json")}
        sources.update({name:shared/name for name in ("ads1232.py","ina219.py")})
        for name,path in sources.items():
            if name.endswith(".py"):
                compile(path.read_text(),str(path),"exec")
            else:
                json.loads(path.read_text())
            shutil.copyfile(path,folder/name)
        manifest={"schema":"yam-nail-firmware/1","protocol":"yam-nail/1","hardware_revision":"N1.1",
                  "physical_devices_tested":0,
                  "files":{name:digest(folder/name) for name in sources},
                  "sources":{name:{"path":str(path.relative_to(ROOT)),"sha256":digest(path)} for name,path in sources.items()},
                  "note":"Copy all six files to a dedicated RP2040 Pico. Shared bridge drivers are retained C1 sources. No force calibration is embedded."}
        (folder/"firmware_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        with zipfile.ZipFile(OUTPUT/"nail_firmware.zip","w",zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.iterdir()):
                if path.is_file():
                    info=zipfile.ZipInfo(path.name,date_time=(2026,10,11,0,0,0))
                    info.compress_type=zipfile.ZIP_DEFLATED
                    archive.writestr(info,path.read_bytes())
        columns=("category","quantity_per_finger_or_shared","item","specification","location","reference","notes")
        rows=[]
        with (ROOT/"engineering/prototypes/c1/c1_bom.csv").open() as stream:
            for row in csv.DictReader(stream):
                if row["category"]=="Electronics":
                    row["category"]="C1 PCB electronics"
                    row["notes"]=(row["notes"]+" Assemble on the retained C1.1 PCB.").strip()
                    rows.append(row)
        def add(category,quantity,item,specification,location,reference,notes=""):
            rows.append(dict(zip(columns,(category,quantity,item,specification,location,reference,notes))))
        add("PCB",1,"C1.1 bridge readout PCB","82 x 64 x 1.6 mm; checked four-layer C1 Gerbers/drills","Wrist/base",
            "../c1/pcb/c1_readout_fabrication.zip","Use the C1 electronics rows above; C1's mechanical parts and axial gauges are not part of N1.")
        add("Controller",1,"Raspberry Pi Pico RP2040","One controller for both nail bridges and four TPU cells","Wrist/base",
            "https://www.raspberrypi.com/products/raspberry-pi-pico/","Use the complete N1 firmware ZIP.")
        add("Gauge",2,"Full shear bridge","OMEGA SGT-2DD/350-SY41; steel compensation; 350 ohm","NL and NR outer web faces",
            "https://assets.dwyeromega.com/pdf/test-and-measurement-equipment/strain-gauges/SGT_Full-Bridge_Shear.pdf",
            "Sold in packs of five. Join like-labeled S+ and S- pads; record lot and supplied gauge data.")
        plan=json.loads((OUTPUT/"nail_manifest.json").read_text())
        for part in plan["parts"]:
            add("Mechanical",1,part["id"],part["material"],part["purpose"],part["step"],
                "Printed metal-part copies are fit witnesses only. Machine and inspect actual metal force parts.")
        add("Retained insert",1,"Original ENPIRE TPU insert","Same recorded print grade/process as the original control","Original three attachment bores",
            "../../docs/GEOMETRY.md","Geometry retained; compare actual compliance after frame and carrier changes.")
        add("Fastener",2,"Left front-clamp screws","M3 x 8; 90-degree flat head, head diameter <=6.0 mm","Left carrier into nail block","N1 drawings",
            "Tap specified 2.5 mm bores M3. Verify actual engagement.")
        add("Fastener",2,"Right front-clamp screws","M3 x 6; 90-degree flat head, head diameter <=6.0 mm","Right carrier into nail block","N1 drawings")
        add("Fastener",2,"Side-mount screws","M3 x 40; 90-degree flat head, head diameter <=6.0 mm","Right carrier through source side axes to threaded left carrier","N1 drawings",
            "Confirm real source stack, threads and free-end projection. Preserve original TPU retention.")
        add("Bonding","shared","Gauge adhesive kit","M-Bond 200 for initial laboratory bonding","Prepared steel web faces",
            "https://micro-measurements.com/node/418","Follow gauge and adhesive preparation/cure instructions; record bonding and cure.")
        add("Protection","shared","Gauge coating","M-Coat A candidate; record actual coating and cure","Bonded gauges",
            "Micro-Measurements coating instructions","Test the complete coated assembly; no sealing or life claim.")
        add("Soft readout",2,"ADS1115 breakout","Adafruit 1085; addresses 0x48 and 0x49; all power/pullups at 3V3","Wrist/base",
            "https://www.adafruit.com/product/1085","Do not substitute ADS1015.")
        add("Soft readout",8,"Divider resistors","10 kohm, 1% or better; four pull-downs and four reference-divider resistors","Wrist/base",
            "Generic electronics supplier","Measure actual values. The four pull-down nominal values must match config.json.")
        add("Soft readout","optional","Range resistors","330 ohm and 1 kohm, 1% or better","TPU pull-down positions",
            "Generic electronics supplier","If required by measured saturation, replace the physical resistor, update config and recalibrate.")
        add("Soft cells",4,"Remote continuity resistors","100 kohm, 1% 0603","At CH2-CH5 foil terminals",
            "Generic electronics supplier","A resistor at the readout board would not check the sensor leads.")
        add("Soft cells","shared strip","Conductive film","0.10 mm pressure-sensitive conductive sheet","Four R1 TPU laminates",
            "https://www.adafruit.com/product/1361","Record supplier, thickness and lot; cut separate cells.")
        add("Soft cells","shared strip","Electrodes and backing","25-35 um bare copper foil and thin polyimide insulation","R1 CH2-CH5 cells",
            "../../docs/BUILD_R1.md","Use the released CH2-CH5 patterns and keep adhesive out of active interfaces.")
        add("Soft cells","shared","Cast saddles and covers","R1 Dragon Skin 10 Slow starting recipe and four supplied saddle molds","TPU contact regions",
            "https://www.smooth-on.com/products/dragon-skin-10-slow/","Record recipe, thickness, cure and surface treatment; use the complete R1 instructions.")
        add("Soft cells","shared","Cell mounting adhesive","R1 documented Sil-Poxy/transfer-film route after adhesion coupons","Saddle, laminate and TPU interfaces",
            "../../docs/BUILD_R1.md","Qualification includes the complete bonded stack.")
        add("Cable",8,"Bridge conductors","Two four-wire bundles with twisted excitation and signal pairs","NL/NR to JA/JB",
            "N1 wiring map","Keep slack; total excitation-loop resistance <=2 ohm per bridge; calibrate installed cables.")
        add("Cable",8,"TPU cell conductors","Fine stranded insulated 34-36 AWG leads","Four separate cell pairs",
            "N1 wiring map","Keep flexing tails out of rigid clamp interfaces.")
        add("Cable",1,"Pico/readout harness","Short 16-pin J1 harness plus short 3V3 I2C branches","Wrist/base",
            "N1 wiring map","Measure common clock and I2C waveforms.")
        add("Test","shared","Bridge dummy resistors","Eight matched 348 or 350 ohm resistors","Electrical-only checks",
            "C1 readout guide","Record dummy data as electrical_dummy.")
        add("Test","shared","Force reference","At least 25 N capacity; documented uncertainty <=0.05 N","Bench",
            "Campaign requirements","Independent reference; use actual readings.")
        add("Test","shared","Displacement measurement","Suitable resolution for the provisional 0.1 mm motion screen","Leading nail and mount",
            "Campaign requirements","Measure the whole installed assembly and the matched original control.")
        with (OUTPUT/"nail_bom.csv").open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader();writer.writerows(rows)
        record["packet"]={"firmware_files":len(sources),"bom_rows":len(rows),"physical_devices_tested":0}
        print(json.dumps(record["packet"],indent=2))


if __name__=="__main__":
    main()
