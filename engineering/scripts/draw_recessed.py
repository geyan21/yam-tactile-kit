#!/usr/bin/python3
"""Render B3 CAD, sensor placement and the recessed mounting stack."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT / "build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"] = str(ROOT / "build/engineering/tools/cache")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Polygon as PatchPolygon, Circle, Rectangle
import numpy as np
from shapely.geometry import Polygon
import trimesh
import draw_l1
from prototype_cad import yz_prism, x_cylinder, packed, digest
from tactile_kit.records import execution

OUTPUT = ROOT / "build/engineering/prototypes/recessed"
COLORS = {"frame": "#657c89", "b1tpu": "#a8bd80", "magnet": "#cc8047",
          "plug": "#e1bf67", "pcb": "#48967e", "backer": "#2e746e",
          "spacer": "#78afa1", "electronics": "#8374a2", "nail": "#d69936",
          "hardware": "#555f66", "tool": "#78afa1"}
EXPLODE = {"b1tpu": (-10, 0, -8), "magnet": (2, 0, -8), "plug": (6, 0, -8),
           "nail": (0, 0, -10), "pcb": (16, 0, 0), "electronics": (16, 0, 0),
           "spacer": (8, 0, 0), "backer": (30, 0, 0), "hardware": (40, 0, 0)}


def mesh_of(shape):
    vertices, faces = shape.tessellate(.03, .1)
    return trimesh.Trimesh(vertices=[v.toTuple() for v in vertices], faces=faces, process=True)


def components(plan, cfg):
    pieces = []
    b1 = json.loads((ROOT / "engineering/release/b1/models.json").read_text())[0]
    for row in b1["components"]:
        if row["group"] in ("b1tpu", "magnet", "plug"):
            pieces.append((row["group"], row["name"],
                           trimesh.Trimesh(vertices=row["vertices"], faces=row["faces"], process=True)))
    r1 = json.loads((ROOT / "engineering/release/models.json").read_text())[0]
    for row in r1["components"]:
        if row["group"] == "laminate" and row["name"].startswith(("CH0 ", "CH1 ")):
            pieces.append(("nail", row["name"].replace("CH0", "T0").replace("CH1", "T1"),
                           trimesh.Trimesh(vertices=row["vertices"], faces=row["faces"], process=True)))
    for part in plan["parts"]:
        name = part["id"]
        group = ("frame" if name == "recessed_hard_frame" else
                 "pcb" if part["kind"] == "reference_only" else
                 "backer" if name == "recessed_removable_backer" else "spacer")
        pieces.append((group, name, trimesh.load_mesh(OUTPUT / part["stl"], process=True)))
    for row in plan["component_envelopes"]:
        body = yz_prism(Polygon(row["body_yz_mm"]),
                        plan["pcb_component_plane_x_mm"] - row["height_mm"], row["height_mm"])
        pieces.append(("electronics", row["reference"] + " package envelope", mesh_of(body)))
    m = cfg["mechanical"]
    for i, mount in enumerate(plan["supports"]):
        y, z = mount["center_yz_mm"]
        head = x_cylinder(plan["backer_outer_x_mm"], m["reserved_head_height_mm"],
                          y, z, m["reserved_head_diameter_mm"] / 2)
        pieces.append(("hardware", f"Mount {i + 1}: reserved M3 head", mesh_of(head)))
    return pieces


def stack_figure(plan):
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), layout="constrained")
    ax = axes[0]
    # S0 local X stack. TPU moves along X; the electronic board stays rigid.
    ax.add_patch(Rectangle((-3.6, -1.5), 3.6, 3, color=COLORS["b1tpu"], alpha=.7))
    ax.add_patch(Rectangle((-2.15, -.8), 1, 1.6, color=COLORS["magnet"]))
    ax.add_patch(Rectangle((4.95, -.9), 1.05, 1.8, color=COLORS["electronics"]))
    ax.add_patch(Rectangle((6, -2.4), .8, 4.8, color=COLORS["pcb"]))
    ax.add_patch(Rectangle((6.9, -2.4), 1.2, 4.8, color=COLORS["backer"]))
    for x, text, y in ((-1.8, "Magnet in TPU", 3.1), (5.45, "MLX90393", 4.0),
                      (6.4, "0.8 mm PCB", -3.2), (7.5, "1.2 mm backer", -4.3)):
        ax.annotate(text, (x, 0), xytext=(x, y), ha="center",
                    arrowprops={"arrowstyle": "->"}, fontsize=9)
    ax.annotate("TPU side-motion assumption: +2 mm", xy=(2, 1.3), xytext=(-3, 5.4),
                arrowprops={"arrowstyle": "->"}, fontsize=9)
    ax.axvline(2.05, ls="--", color="#936d39", label="Bound with 0.05 mm model allowance")
    ax.set_title("At S0 · native X cross-section\nIllustrates the stack; Y/Z scale is schematic")
    ax.set_xlim(-5, 10); ax.set_ylim(-5.5, 7); ax.set_aspect("equal")
    ax.set_xlabel("Native X (mm)"); ax.legend(fontsize=8)
    ax = axes[1]
    # Actual positive-radius outline of one spacer; mirror for the lower half.
    outline = [(4, 1.6), (6.65, 1.6), (6.65, 2.425), (6, 2.425),
              (6, 3.5), (5.3, 3.5), (4.2, 2.4), (4, 2.4)]
    for sign in (-1, 1):
        ax.add_patch(PatchPolygon([(x, sign * r) for x, r in outline],
                                  facecolor=COLORS["spacer"], edgecolor="#32675f"))
        ax.add_patch(Rectangle((6, sign * 2.5 if sign > 0 else -4.3), .8, 1.8,
                               color=COLORS["pcb"], alpha=.7))
        ax.add_patch(Rectangle((6.9, sign * 1.6 if sign > 0 else -4.3), 1.2, 2.7,
                               color=COLORS["backer"], alpha=.7))
    ax.plot([4, 4], [-2.4, 2.4], color="#465c68", lw=3)
    ax.set_title("Both mounts · actual radial spacer section\n4.8 mm foot → 7 mm clamping flange")
    ax.set_xlim(2.5, 9); ax.set_ylim(-5, 5); ax.set_aspect("equal")
    ax.set_xlabel("Native X (mm)"); ax.set_ylabel("Radius from screw axis (mm)")
    ax.text(4.2, -4.6, "M3 bore Ø3.2 · PCB shoulder Ø4.85 × 0.65", fontsize=8)
    for ax in axes:
        ax.grid(alpha=.2)
    fig.suptitle("B3.1 · fixed electronics beside compliant TPU", fontsize=15)
    return fig


def main():
    config_path = ROOT / "engineering/designs/recessed.json"
    cfg = json.loads(config_path.read_text())
    plan = json.loads((OUTPUT / "recessed_manifest.json").read_text())
    layout = json.loads((ROOT / "engineering/prototypes/b2/pcb/b2_design_checks.json").read_text())
    review = json.loads((OUTPUT / "recessed_clearance_review.json").read_text())
    for name, expected in plan["source_hashes"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Stale B3 CAD: " + name)
    with execution(ROOT / "build/records", "Render B3 actual CAD, both nail cells, magnetometers, recess and dimensioned spacer; no specimen photograph") as record:
        pieces = components(plan, cfg)
        draw_l1.COLORS.update(COLORS)
        with PdfPages(OUTPUT / "recessed_review_drawings.pdf") as pdf:
            for exploded in (False, True):
                shown = []
                for group, _, source in pieces:
                    mesh = source.copy()
                    if exploded:
                        mesh.apply_translation(EXPLODE.get(group, (0, 0, 0)))
                    shown.append((group, mesh))
                fig = plt.figure(figsize=(13, 6.8))
                ax = fig.add_axes((.02, .19, .96, .67))
                ax.imshow(draw_l1.depth_image(shown, width=1700, height=700)); ax.set_axis_off()
                fig.suptitle("B3.1 · " + ("exploded recessed assembly" if exploded else "recessed board beside the compliant insert"),
                             fontsize=18, color="#203f46")
                fig.text(.04, .12, "Revised frame · B1 TPU + four magnets · two N0 nail pads · B2 PCB · tapered spacers · backer", fontsize=10)
                fig.text(.04, .075, "Actual CAD and package/head envelopes. Cable loops, coatings and seating film are omitted.", fontsize=10)
                fig.text(.04, .04, "Experimental digital prototype · physical build, force calibration and 20 N qualification pending", fontsize=9)
                fig.savefig(OUTPUT / ("recessed_exploded.png" if exploded else "recessed_assembly.png"), dpi=150)
                pdf.savefig(fig); plt.close(fig)
            fig, ax = plt.subplots(figsize=(13, 6), layout="constrained")
            draw_l1.projected(ax, [(group, mesh) for group, _, mesh in pieces
                                   if group in ("frame", "b1tpu")], 1, 2, .2)
            ax.add_patch(PatchPolygon(plan["common_pocket_yz_mm"], facecolor="#c58d4d",
                                       edgecolor="#95672f", alpha=.3))
            ax.add_patch(PatchPolygon(layout["pcb_outline_yz_mm"], facecolor=COLORS["pcb"],
                                       edgecolor="#276954", alpha=.3))
            for hole in layout["pcb_cutouts_yz_mm"]:
                ax.add_patch(PatchPolygon(hole, facecolor="white", edgecolor="#4c8277", alpha=.7))
            for row in plan["magnet_locations"]:
                _, y, z = row["native_xyz_mm"]
                ax.add_patch(Circle((y, z), 1.5, facecolor=COLORS["magnet"]))
                ax.annotate(row["id"], (y, z), xytext=(0, -20), textcoords="offset points", ha="center")
            for row in plan["sensor_poses"]:
                _, y, z = row["die_center_native_mm"]
                ax.plot(y, z, "+", color="#5b4383", markersize=11)
                ax.text(y, z + 3, row["id"], ha="center", color="#5b4383")
            ax.annotate("T0 + T1\nN0 films on both nail prongs", (-108, -3), xytext=(-100, -13),
                        arrowprops={"arrowstyle": "->"}, ha="center", fontsize=10)
            ax.annotate("S4 reference\nalso sees the magnets", (-25, 22), xytext=(-50, 34),
                        arrowprops={"arrowstyle": "->"}, ha="center", fontsize=10)
            ax.set_xlim(-123, 1); ax.set_ylim(-18, 40); ax.set_aspect("equal")
            ax.set_title("B3 sensing locations · 5 × MLX90393SLW-ABA-011 + 2 × N0 nail pads\nPCB component plane X=6.00 mm; magnets stay in the retained B1 cartridge")
            fig.savefig(OUTPUT / "recessed_placement.svg"); pdf.savefig(fig); plt.close(fig)
            fig = stack_figure(plan)
            fig.savefig(OUTPUT / "recessed_stack.svg")
            fig.savefig(OUTPUT / "recessed_stack.png", dpi=150)
            pdf.savefig(fig); plt.close(fig)
            fig = plt.figure(figsize=(8.27, 11.69))
            lines = [
                "B3.1 review · millimeters · manufacture from STEP masters",
                "",
                "Print one revised frame, one backer and two identical spacers.",
                "PCB: retained B2.1 four-layer board; 0.8 mm nominal thickness.",
                "Component face X=6.00; recess floor X=4.45.",
                "Both spacer seats X=4.00; foot Ø4.80 × 0.20.",
                "Taper length 1.10 to Ø7.00; full flange length 0.70.",
                "PCB locating shoulder Ø4.85 × 0.65; central bore Ø3.20.",
                "Board hole Ø5.00; backer inside X=6.90, outside X=8.10.",
                "Seat film 0.10; keep leads out of the bearing annuli.",
                "",
                f"Added global width: {review['added_width_mm_with_reserved_heads_excluding_wires']:.3f} with reserved heads.",
                "Head allowance Ø6.00 × 2.40; wires excluded; no added reach.",
                "Select actual nonmagnetic M3 screw length from the measured stack.",
                "",
                "Use four retained B1 3 × 1 mm N48 discs, north toward +X.",
                "Five MLX90393SLW-ABA-011 ICs use GAIN_SEL=5, RES=1.",
                "Nominal 25 C conversion: X/Y 0.501, Z 0.807 µT/count.",
                "Two N0 nail cells retain 100 kΩ resistors at the pads.",
                "Use B3's complete five-file firmware; do not reuse B2 scaling.",
                "",
                "Check actual drive fit through full opening in both jaw positions.",
                "The prescribed +2 mm side-motion bound is not a 20 N rating.",
                "Print compliance, clamps, cable loops and strength are untested.",
                "Protected source geometry does not establish unchanged stiffness.",
                "No physical contact/force accuracy or specimen yield is reported.",
            ]
            fig.text(.06, .95, "\n".join(lines), va="top", fontsize=10, linespacing=1.55, family="monospace")
            pdf.savefig(fig); plt.close(fig)
        models = [{
            "id": "recessed_assembly", "title": "B3.1 · recessed magnetic board",
            "coordinates": "native_mm", "assembly": True,
            "components": [packed(mesh, name, group, COLORS[group], EXPLODE.get(group, (0, 0, 0)))
                           for group, name, mesh in pieces],
            "note": "Actual revised frame/support CAD, retained B1 TPU/magnets and N0 nail pads, B2 board and component/head envelopes. Cables and coatings are omitted; physical assembly and qualification remain pending.",
        }]
        for part in plan["parts"]:
            models.append({"id": part["id"], "title": part["id"].replace("_", " "),
                           "coordinates": "native_mm",
                           "components": [packed(trimesh.load_mesh(OUTPUT / part["stl"], process=True),
                                                 part["purpose"], "tool", COLORS["tool"])],
                           "note": part["purpose"] + " " + part["material"]})
        (OUTPUT / "models.json").write_text(json.dumps(models, separators=(",", ":")) + "\n")
        receipt = {
            "source_hashes": {str(path.relative_to(ROOT)): digest(path) for path in (
                config_path, OUTPUT / "recessed_manifest.json",
                OUTPUT / "recessed_clearance_review.json", Path(__file__),
                ROOT / "engineering/scripts/draw_l1.py", ROOT / "engineering/scripts/prototype_cad.py",
                ROOT / "engineering/release/b1/models.json", ROOT / "engineering/release/models.json",
                ROOT / "engineering/prototypes/b2/pcb/b2_design_checks.json")},
            "files": {name: digest(OUTPUT / name) for name in (
                "models.json", "recessed_assembly.png", "recessed_exploded.png",
                "recessed_placement.svg", "recessed_stack.svg", "recessed_stack.png",
                "recessed_review_drawings.pdf")},
        }
        (OUTPUT / "visual_inputs.json").write_text(json.dumps(receipt, indent=2) + "\n")
        record["rendered"] = {"assembly_components": len(pieces), "models": len(models),
                              "physical_photographs": 0}
        print(json.dumps(record["rendered"], indent=2))


if __name__ == "__main__":
    main()
