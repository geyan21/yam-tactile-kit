#!/usr/bin/python3
"""Generate staged center calibration and genuinely held-out load-position trials."""

import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution
OUTPUT=ROOT/"build/engineering/l1"


def make_plan(config):
    levels=[0,.2,.5,1,2,5,10,15,20,15,10,5,2,1,.5,.2,0]
    rows=[]
    for cycle in range(3):
        for index,force in enumerate(levels):
            rows.append({
                "trial_id":f"center_c{cycle+1}_p{index:02d}",
                "group":f"center-cycle-{cycle+1}","split":"train" if cycle<2 else "test",
                "contact_id":"center","u_mm":0,"v_mm":0,
                "target_n":force,"phase":"loading" if index<=8 else "unloading",
            })
    ports=[(u,v) for u in config["bench"]["combined_plate_u_mm"] for v in config["bench"]["combined_plate_v_mm"] if u or v]
    for level_index,force in enumerate((.2,1,2,5,10,20)):
        for port_index,(u,v) in enumerate(ports):
            for suffix,target,phase in (("load",force,"loading"),("release",0,"unloading")):
                rows.append({
                    "trial_id":f"position_f{level_index}_p{port_index}_{suffix}",
                    "group":f"position-port-{port_index}","split":"test",
                    "contact_id":f"u{u}_v{v}","u_mm":u,"v_mm":v,"target_n":target,"phase":phase,
                })
    return {
        "schema":"yam-l1-plan/1","kind":"plan_only","fixture":"combined_load_plate",
        "force_axis":"positive W; align W with finger native +Z",
        "coordinates":"U along cell length from wire end; V transverse; offsets measured from the live-end screw axis",
        "target_force_n":20,"reference_max_uncertainty_n":.05,
        "required_moment_ports_uv_mm":[list(port) for port in ports],
        "instructions":[
            "Verify the unmodified cell with central loads before applying long-lever loads.",
            "Use actual reference readings. The target values are not ground truth.",
            "Proceed from low force upward; stop on slip, contact with a fixed part, or nonrecovering zero shift.",
            "Do not fit new force gains at each position. All displaced positions are held out.",
            "These trials qualify a cell/fixture condition only; repeat integrated-finger, orientation, dynamic and task tests.",
        ],
        "trials":rows,
    }


def make_finger_plan(sites):
    """Reuse the cell sensitivity; record an explicit unloaded zero at one pose."""
    rows=[]
    for index in range(3):
        rows.append({
            "trial_id":f"unloaded_zero_{index+1}","group":"explicit-unloaded-zero",
            "split":"train","contact_id":"unloaded","u_mm":0,"v_mm":0,
            "target_n":0,"phase":"explicit_unloaded_zero",
        })
    for level_index,force in enumerate((.2,.5,1,2,5,10,15,20)):
        for site in sites:
            for suffix,target,phase in (("load",force,"loading"),("release",0,"unloading")):
                rows.append({
                    "trial_id":f"finger_f{level_index}_{site['id']}_{suffix}",
                    "group":f"finger-{site['id']}","split":"test","contact_id":site["id"],
                    "u_mm":site["u_mm"],"v_mm":site["v_mm"],"native_xyz_mm":site["native_xyz_mm"],
                    "target_n":target,"phase":phase,
                })
    return {
        "schema":"yam-l1-plan/1","kind":"plan_only","fixture":"integrated_enpire_l1",
        "force_axis":"positive W; align reference force with finger native +Z",
        "coordinates":"U=-native Y and V=+native X, relative to the live-end screw axis",
        "target_force_n":20,"reference_max_uncertainty_n":.05,
        "required_contacts":sites,"sensitivity_refit_permitted":False,
        "instructions":[
            "First complete the cell/plate calibration and preserve its report.",
            "Install the original finger and carrier. Set a stationary pose and remove every external contact.",
            "The first three trials explicitly record the unloaded zero in this pose. The slope remains fixed.",
            "Keep the same pose and apply force along +native Z at the labeled contact sites.",
            "All loaded finger trials are held out. No location-dependent or automatic zero correction is allowed.",
            "Stop on interference, slipping hardware, permanent deformation or loss of zero return.",
        ],
        "trials":rows,
    }


def main():
    config=json.loads((ROOT/"engineering/designs/l1.json").read_text())
    result=make_plan(config)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Prepare explicit force and moment trial IDs without creating measurements") as record:
        (OUTPUT/"l1_bench_plan.json").write_text(json.dumps(result,indent=2)+"\n")
        sites=json.loads((OUTPUT/"contact_sites.json").read_text())["sites"]
        integrated=make_finger_plan(sites)
        (OUTPUT/"l1_finger_plan.json").write_text(json.dumps(integrated,indent=2)+"\n")
        record["planned_trials"]={"cell_plate":len(result["trials"]),"integrated_finger":len(integrated["trials"])}
        print(json.dumps({"planned_trials":record["planned_trials"],"physical_measurements_created":0},indent=2))


if __name__=="__main__":
    main()
