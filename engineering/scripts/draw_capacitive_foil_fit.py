#!/usr/bin/python3
"""Render the saved K1 formed-foil candidates on the original finger."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from mpl_toolkits.mplot3d import proj3d
import numpy as np
import trimesh
from tactile_kit.records import execution
from capacitive_geometry import CONFIG
from screen_f1_feedback import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fit_run", type=Path)
    args = parser.parse_args()
    source = args.fit_run.resolve()
    if not source.is_relative_to(ROOT / "build/engineering/prototypes/capacitive/foil_fit"):
        parser.error("Select an owned K1 formed-foil run")
    cfg = json.loads(CONFIG.read_text())
    folder = source / "visuals" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Render only the saved K1 source/foil/stiffener/solder-envelope geometry to review proposed tail access; no physical hardware is depicted") as record:
        folder.mkdir(parents=True, exist_ok=False)
        originals = [(key, trimesh.load_mesh(ROOT / cfg["basis"][key], process=True)) for key in ("hard_frame", "soft_insert")]
        parts = []
        for site in range(6):
            for role in ("foil", "stiffener", "joint_1", "joint_2"):
                path = source / "cad" / f"k1_ch{site}_{role}.stl"
                if not path.is_file():
                    raise ValueError("Wait for all candidate CAD exports before drawing")
                parts.append({"site": site, "role": role, "mesh": trimesh.load_mesh(path, process=True),
                              "file": str(path.relative_to(ROOT)), "sha256": digest(path)})
        fig = plt.figure(figsize=(14, 7), layout="constrained")
        for number, nail_only in ((121, False), (122, True)):
            ax = fig.add_subplot(number, projection="3d")
            shown = [p for p in parts if not nail_only or p["site"] < 2]
            vertices = np.vstack([p["mesh"].vertices for p in shown])
            low, high = vertices.min(axis=0), vertices.max(axis=0)
            for key, mesh in originals:
                triangles = mesh.triangles
                if nail_only:
                    centres = triangles.mean(axis=1)
                    keep = np.all((centres >= low-8) & (centres <= high+8), axis=1)
                    triangles = triangles[keep]
                ax.add_collection3d(Poly3DCollection(triangles[:, :, [1, 2, 0]], facecolor="#929e9c",
                                                     edgecolor="none", alpha=.12, rasterized=True))
            for item in shown:
                mesh = item["mesh"]
                color = {"foil": "#468c78", "stiffener": "#7987b2", "joint_1": "#d6a059", "joint_2": "#d6a059"}[item["role"]]
                ax.add_collection3d(Poly3DCollection(mesh.triangles[:, :, [1, 2, 0]], facecolor=color,
                                                     edgecolor="none", alpha=.9, rasterized=True))
            ax.set(xlim=(low[1]-5, high[1]+5), ylim=(low[2]-5, high[2]+5), zlim=(low[0]-5, high[0]+5),
                   xlabel="Native Y (mm)", ylabel="Native Z (mm)", zlabel="Native X (mm)")
            ax.set_box_aspect((high-low)[[1, 2, 0]]+10)
            ax.view_init(elev=24, azim=-60)
            for item in shown:
                if item["role"] != "foil":
                    continue
                center = item["mesh"].bounds.mean(axis=0)[[1, 2, 0]]
                x, y, _ = proj3d.proj_transform(*center, ax.get_proj())
                ax.annotate("CH"+str(item["site"]), (x, y), xytext=(4, 13), textcoords="offset points",
                            fontsize=9, zorder=1000, bbox={"fc": "white", "ec": "#91a296", "alpha": .9})
            ax.set_title("Nail terminal detail" if nail_only else "All six formed foil candidates", fontsize=11)
        fig.suptitle("K1 formed flex candidates · green foil, blue stiffener, gold solder/wire envelope\n"
                     "Source frame shown transparent · collision checks and physical assembly remain separate", fontsize=12)
        for suffix in ("png", "pdf"):
            fig.savefig(folder / ("formed_foil_candidates."+suffix), dpi=160)
        plt.close(fig)
        report = {"physical_specimens_tested": 0,
                  "source_cad": [{k: v for k, v in p.items() if k != "mesh"} for p in parts],
                  "status": "Candidate geometry visualization; does not establish fit or functionality"}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "parts_shown": len(parts)}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
