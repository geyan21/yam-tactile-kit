#!/usr/bin/python3
"""Draw only the B1 board-fit geometry saved by its generator."""

import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"]=str(ROOT/"build/engineering/tools/mpl-cache")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from build_b1_parts import footprint
from tactile_kit.records import execution


def main():
    directory=ROOT/"build/engineering/b1"
    seed=json.loads((directory/"layout_seed.json").read_text())
    with execution(ROOT/"build/records","Inspect B1 board-fit constraints against the retrieved hard-frame and TPU outlines") as record:
        fig,ax=plt.subplots(figsize=(13,7))
        for key,label,color in (("hard_outline_yz","Hard-frame outline","#657c89"),("tpu_outline_yz","TPU outline","#6f9f4b")):
            points=np.asarray(seed[key]);ax.plot(points[:,0],points[:,1],label=label,color=color)
        for magnet in seed["magnets"]:
            y,z=magnet["native_xyz_mm"][1:];angle=np.deg2rad(magnet["front_tangent_angle_deg"])
            ax.plot(y,z,"o",color="#ab6335");ax.text(y,z+1,magnet["id"])
            inward=np.array([-np.sin(angle),np.cos(angle)])
            for distance in (0,2,4,6):
                region,_,_=footprint(np.array([y,z])+inward*distance,angle,seed["pcb_bounds_relative_to_chip_uv_mm"],.45)
                points=np.asarray(region.exterior.coords);ax.plot(points[:,0],points[:,1],alpha=.45)
        for anchor in seed["anchors"]:
            y,z=anchor["center_yz_mm"];ax.add_patch(plt.Circle((y,z),4,fill=False,linestyle=":",color="#a26353"))
        ax.set_aspect("equal");ax.grid(alpha=.15);ax.legend()
        ax.set_xlabel("Native Y (mm)");ax.set_ylabel("Native Z (mm)")
        ax.set_title("B1 placement inspection — board candidates at 0, 2, 4 and 6 mm inward offsets")
        fig.tight_layout();fig.savefig(directory/"layout_inspection.png",dpi=160);plt.close(fig)
        record["image"]=str(directory/"layout_inspection.png")
        print(record["image"])


if __name__=="__main__":
    main()
