#!/usr/bin/python3
"""Analytical carrier-compliance screen; explicitly excludes load-cell and joint compliance."""

import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
sys.path.insert(0,str(ROOT/"src"))
from tactile_kit.records import execution

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUTPUT=ROOT/"build/engineering/l1"


def screen(config,interface,deck,plate):
    force=20.0
    # Explicit screening assumptions, not measured properties of a produced part.
    young=69000.0  # N/mm²
    poisson=.33
    shear=young/(2*(1+poisson))
    cell=config["load_cell"];a=config["adapter"];pose=cell["pose"]
    live_y=pose["native_y_wire_end_mm"]-cell["mount_hole_offsets_from_wire_end_mm"][1]
    root_face=interface["mount_plane"]["native_y_mm"]+config["finger_shift_native_y_mm"]
    root_mid=root_face+plate/2
    tip_y=interface["mount_plane"]["native_y_mm"]-interface["distal_lever_from_mount_mm"]+config["finger_shift_native_y_mm"]
    span=root_mid-live_y
    finger_lever=root_mid-tip_y
    width=cell["width_mm"]+2*(a["cell_end_side_clearance_mm"]+a["end_locator_wall_mm"])
    inertia=width*deck**3/12
    # Castigliano result for a returning cantilever carrying a rigid offset finger.
    bending=force*(span**3/3-finger_lever*span**2+finger_lever**2*span)/(young*inertia)
    ratio=deck/width
    torsion_constant=width*deck**3*(1/3-.21*ratio*(1-ratio**4/12))
    transverse_lever=abs(-24.7108135223-(pose["native_x_min_mm"]+cell["width_mm"]/2))
    torsion=force*transverse_lever**2*span/(shear*torsion_constant)
    deck_mid_z=pose["native_z_bottom_mm"]+cell["height_mm"]+a["floating_spacer_mm"]+deck/2
    plate_span=deck_mid_z-interface["bolt_centers_native_xz_mm"][0][1]
    # Conservative effective width through the narrowed top of the real root profile.
    plate_inertia=22*plate**3/12
    plate_rotation=force*finger_lever*plate_span/(young*plate_inertia)
    plate_tip=plate_rotation*finger_lever
    rail_stress=force*finger_lever/(width*deck**2/6)
    return {
        "deck_mm":deck,"root_plate_mm":plate,"rail_span_mm":span,"rigid_finger_lever_mm":finger_lever,
        "rail_bending_tip_mm":bending,"rail_torsion_tip_mm":torsion,"root_plate_rotation_tip_mm":plate_tip,
        "screen_sum_mm":bending+torsion+plate_tip,"nominal_rail_bending_stress_mpa":rail_stress,
    }


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Screen L1 carrier thickness against added tip compliance under a 20 N load") as record:
        config=json.loads((ROOT/"engineering/designs/l1.json").read_text())
        interface=json.loads((OUTPUT/"root_interface.json").read_text())
        rows=[screen(config,interface,deck,plate) for plate in (5,8) for deck in (4,6,8,10,12)]
        selected=screen(config,interface,config["adapter"]["floating_deck_thickness_mm"],config["adapter"]["floating_root_plate_thickness_mm"])
        report={
            "kind":"analytical_screen_not_hardware_validation",
            "assumptions":{"youngs_modulus_mpa":69000,"poisson_ratio":.33,"root_plate_effective_width_mm":22,
                "force_n":20,"carrier_only_design_budget_mm":.25},
            "selected":selected,"variants":rows,
            "omitted":["load-cell translation and rotation","fastener and joint compliance","local notches and holes",
                       "fixed-carrier deformation","original finger compliance","dynamics","manufacturing variability"],
            "interpretation":"Use this to reject an obviously flexible carrier. Validate complete added compliance with a force reference and displacement measurement.",
        }
        (OUTPUT/"stiffness_screen.json").write_text(json.dumps(report,indent=2)+"\n")
        fig,ax=plt.subplots(figsize=(8,4.5),constrained_layout=True)
        for plate in (5,8):
            subset=[row for row in rows if row["root_plate_mm"]==plate]
            ax.plot([row["deck_mm"] for row in subset],[row["screen_sum_mm"] for row in subset],"o-",label=f"{plate} mm root plate")
        ax.axhline(.25,color="#97632c",linestyle="--",label="0.25 mm carrier screening budget")
        ax.set_xlabel("Solid return-rail thickness (mm)");ax.set_ylabel("Estimated added tip deflection (mm)")
        ax.set_title("20 N carrier screen — cell, joints and finger excluded")
        ax.grid(alpha=.2);ax.legend()
        fig.savefig(OUTPUT/"stiffness_screen.svg");fig.savefig(OUTPUT/"stiffness_screen.png",dpi=180)
        record["selected_screen"]=selected
        print(json.dumps({"selected":selected,"baseline_4mm_5mm":rows[0],"physical_tested":False},indent=2))


if __name__=="__main__":
    main()
