#!/usr/bin/python3
"""Render the saved PCB primitives for scoped layout review, without changing them."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT/"build/engineering/tools/mpl-cache")
sys.path.insert(0,str(ROOT/"src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon as PlotPolygon, Circle, Rectangle
from matplotlib.transforms import Affine2D
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("--name",required=True)
    parser.add_argument("--net")
    args = parser.parse_args()
    data = json.loads((args.source/f"{args.name}.json").read_text())
    with execution(ROOT/"build/records","Render saved PCB copper to examine a routing failure without changing the board") as record:
        fig,axes = plt.subplots(3,1,figsize=(16,15),layout="constrained")
        bounds = [(7,96,10,45),(40,59,13,33),(8,22,12,35)]
        colors = {"F.Cu":"#b3543d","B.Cu":"#416bb0","In2.Cu":"#797c35","In1.Cu":"#8e5097"}
        for ax,limits in zip(axes,bounds):
            ax.add_patch(PlotPolygon(data["outline_xy_mm"],facecolor="#f3f7f0",edgecolor="#535d55"))
            for t in data["tracks"]:
                highlighted = not args.net or t["net"] == args.net
                ax.plot([t["start"][0],t["end"][0]],[t["start"][1],t["end"][1]],
                        color=colors[t["layer"]],lw=2 if highlighted else 1,alpha=1 if highlighted else .4)
            for p in data["pads"]:
                x,y = p["center"];w,h = p["size"]
                patch = Rectangle((-w/2,-h/2),w,h,facecolor="#c69946",edgecolor="#604b30",lw=.3)
                patch.set_transform(Affine2D().rotate_deg(-p["rotation"]).translate(x,y)+ax.transData)
                ax.add_patch(patch)
            for v in data["vias"]:
                ax.add_patch(Circle(v["center"],v["diameter"]/2,facecolor="#526965",edgecolor="#243d30",lw=.3))
            for h in data["holes"]:
                ax.add_patch(Circle(h["center"],h["diameter"]/2,facecolor="white",edgecolor="#667"))
            for c in data["components"]:
                if c["reference"].startswith("U"):
                    ax.text(*c["center_mm"],c["reference"],ha="center",va="center",fontsize=12,clip_on=True)
            if args.net:
                for p in data["pads"]:
                    if p["net"] == args.net:
                        ax.annotate(f'{p["reference"]}.{p["pad"]}',p["center"],xytext=(5,10),
                                    textcoords="offset points",fontsize=8,color="#8d2332")
            ax.set_xlim(limits[:2]);ax.set_ylim(limits[3],limits[2])
            ax.set_aspect("equal");ax.grid(alpha=.2)
            ax.set_xlabel("KiCad X (mm)");ax.set_ylabel("KiCad Y (mm)")
        axes[0].set_title("Full B2 PCB · component-side copper overlay · physical hardware not pictured")
        axes[1].set_title("Middle head / narrow arm")
        axes[2].set_title("Multiplexer and nail ADC region")
        target = args.source/f"{args.name}_review.png"
        fig.savefig(target,dpi=140)
        failure = args.source/"route_failure.npz"
        if failure.exists():
            with np.load(failure) as values:
                grid = float(values["grid"]);ox,oy = values["origin"]
                shape = values["free"].shape
                extent = [ox,ox+grid*shape[2],oy+grid*shape[1],oy]
                fig2,ax2 = plt.subplots(shape[0],1,figsize=(16,4*shape[0]),layout="constrained")
                names = ("F.Cu","In1.Cu","In2.Cu","B.Cu") if shape[0]==4 else ("F.Cu","In2.Cu","B.Cu")
                for i,ax in enumerate(ax2):
                    colors = np.zeros((*shape[1:],3))
                    colors[:] = [.18,.18,.18]
                    colors[values["free"][i]] = [.86,.86,.8]
                    colors[values["reached"][i]] = [.3,.8,.6]
                    ax.imshow(colors,extent=extent,interpolation="nearest")
                    ax.plot(*values["start"],"rx");ax.plot(*values["end"],"bx")
                    ax.set_title(names[i]+" · green reachable; beige free but unreached")
                    ax.set_xlim(8,58);ax.set_ylim(34,12)
                fig2.savefig(args.source/"route_failure.png",dpi=140)
        record["output"] = str(target)
        print(target)


if __name__ == "__main__":
    main()
