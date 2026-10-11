#!/usr/bin/python3
"""Screen actual K1 foil load, bonded-stop tolerances and retainer bypass sensitivity."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/capacitive-cad-cache"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import brentq
from shapely.geometry import Polygon
from tactile_kit.records import execution
from capacitive_geometry import CONFIG, load, offsets, unrolled, posts
from capacitive_cell_geometry import MECHANICS
from screen_capacitive_k1 import capacitance, EPSILON_PF_PER_MM
from screen_f1_feedback import digest

PLAN = ROOT / "engineering/designs/capacitive_assembly_screen.json"
HARNESS = ROOT / "engineering/designs/capacitive_harness.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("foils", type=Path)
    args = parser.parse_args()
    source = args.foils.resolve(); artwork = json.loads((source / "report.json").read_text())
    for name, expected in artwork["input_sha256"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Foil inputs changed")
    cfg, surfaces = load(); mechanics = json.loads(MECHANICS.read_text())
    plan = json.loads(PLAN.read_text()); harness = json.loads(HARNESS.read_text())
    cable = harness["signal_cable"]
    folder = ROOT / "build/engineering/prototypes/capacitive/assembly_screens" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Screen the new K1 actual foil/cable shield budget and uniform-post response with bonded-stop and retainer uncertainty; preserve failing assumptions as findings") as record:
        folder.mkdir(parents=True)
        inputs = [CONFIG, MECHANICS, PLAN, HARNESS, Path(__file__), source / "report.json",
                  ROOT / "engineering/scripts/screen_capacitive_k1.py", ROOT / "engineering/scripts/capacitive_geometry.py"]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        foil_rows = {}
        for entry in artwork["boards"]:
            path = source / entry["file"]
            if digest(path) != entry["sha256"]:
                raise ValueError("Foil geometry changed")
            data = json.loads(path.read_text())
            # Conservative whole-foil area, including edge margins and
            # copper-free regions. It bounds the real back-shield area.
            area = Polygon(data["outline_flat_mm"]).area
            foil_rows[entry["site"]] = {"whole_foil_area_mm2_bound": area}
        shield = []
        for bank in cfg["readout"]["banks"]:
            area = sum(foil_rows[f"CH{site}"]["whole_foil_area_mm2_bound"] for site in bank["sites"])
            area += foil_rows["REF"]["whole_foil_area_mm2_bound"]
            length = (len(bank["sites"])*cable["sensor_finished_length_max_mm"]+cable["reference_finished_length_max_mm"])/1000
            wire_pf = length*cable["capacitance_max_pf_per_m"]
            foil_pf = EPSILON_PF_PER_MM*cfg["flex"]["polyimide_relative_permittivity_assumed"]*area/cfg["flex"]["polyimide_core_mm"]
            worst_foil = EPSILON_PF_PER_MM*cfg["flex"]["polyimide_relative_permittivity_max_screen"]*area/cfg["flex"]["polyimide_core_min_mm_screen"]
            extra = wire_pf+cfg["readout"]["board_shield_load_allowance_pf_assumed"]
            shield.append({"bank": bank["bank"], "actual_whole_foil_area_mm2_bound": area,
                           "cable_length_m_bound": length, "cable_capacitance_pf_bound": wire_pf,
                           "nominal_total_pf_screen": foil_pf+extra,
                           "minimum_core_max_permittivity_pf_screen": worst_foil+extra,
                           "below_joined_shield_planning_limit": worst_foil+extra < cfg["readout"]["joined_shield_planning_limit_pf"],
                           "scope": "Grounded-CIN parallel-plate bound using the complete foil outlines, plus maximum-length specified cable and a board allowance; not a measured network."})
        rows = []
        for surface in surfaces:
            active = unrolled(surface.active, surface, offsets(surface.site, cfg)["post_base_middle"])
            count = len(posts(active, cfg)); area = count*math.pi*(cfg["dielectric"]["post_diameter_mm"]/2)**2
            h = cfg["dielectric"]["post_height_mm"]; c0 = capacitance(active.area, area, 1, cfg)
            for modulus in cfg["dielectric"]["uniform_post_modulus_mpa_screen"]:
                for stiffness in mechanics["cover"]["parallel_stiffness_n_per_mm_cases"]:
                    def at(force):
                        stretch = brentq(lambda l: area*modulus/3*(l**-2-l)+stiffness*h*(1-l)-force, .01, 1)
                        return h*(1-stretch), capacitance(active.area, area, stretch, cfg), stiffness*h*(1-stretch)
                    travel, cap, bypass = at(plan["maximum_normal_load_n"])
                    _, contact_cap, _ = at(plan["minimum_contact_load_n"])
                    stop_cases = []
                    for film in plan["stop_film_mm_cases"]:
                        for adhesive in plan["stop_adhesive_mm_cases"]:
                            available = cfg["dielectric"]["base_mm"]+h-film-adhesive
                            stop_cases.append({"film_mm": film, "adhesive_mm_assumed": adhesive,
                                               "available_travel_mm": available, "would_reach_stop_at_20n": travel >= available})
                    signal = contact_cap-c0
                    rows.append({"site": surface.site, "posts": count, "modulus_mpa_assumed": modulus,
                                 "cover_stiffness_n_per_mm_assumed": stiffness,
                                 "uniform_travel_20n_mm": travel, "cover_force_20n_n": bypass,
                                 "capacitance_20n_pf": cap, "delta_at_0p2n_pf": signal,
                                 "planning_signal_in_resolution_steps": signal/plan["converter_resolution_pf_datasheet"],
                                 "passes_five_step_signal_screen": signal >= plan["illustrative_contact_signal_resolution_multiple"]*plan["converter_resolution_pf_datasheet"],
                                 "stop_cases": stop_cases})
        signal_findings = [row for row in rows if not row["passes_five_step_signal_screen"]]
        stop_findings = [{"site": row["site"], "modulus_mpa": row["modulus_mpa_assumed"],
                          "cover_stiffness_n_per_mm": row["cover_stiffness_n_per_mm_assumed"],
                          "cases": [c for c in row["stop_cases"] if c["would_reach_stop_at_20n"]]}
                         for row in rows if any(c["would_reach_stop_at_20n"] for c in row["stop_cases"])]
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
        for site in range(6):
            selected = [r for r in rows if r["site"] == site and r["cover_stiffness_n_per_mm_assumed"] == 0]
            axes[0].loglog([r["modulus_mpa_assumed"] for r in selected],
                           [r["planning_signal_in_resolution_steps"] for r in selected], "o-", label=f"CH{site}")
            axes[1].plot([r["modulus_mpa_assumed"] for r in selected],
                         [r["uniform_travel_20n_mm"] for r in selected], "o-", label=f"CH{site}")
        axes[0].axhline(5, ls="--", color="#9d534d")
        axes[0].set(xlabel="Assumed post modulus (MPa)", ylabel="0.2 N signal / 0.5 fF resolution",
                   title="Rigid-plate signal sensitivity")
        nominal_stop = cfg["dielectric"]["base_mm"]+cfg["dielectric"]["post_height_mm"]-mechanics["stop"]["film_nominal_mm"]-mechanics["stop"]["adhesive_nominal_mm"]
        smallest_stop = cfg["dielectric"]["base_mm"]+cfg["dielectric"]["post_height_mm"]-max(plan["stop_film_mm_cases"])-max(plan["stop_adhesive_mm_cases"])
        axes[1].axhline(nominal_stop, ls="--", color="#897556")
        axes[1].axhline(smallest_stop, ls="--", color="#9d534d")
        axes[1].set(xscale="log", xlabel="Assumed post modulus (MPa)", ylabel="Predicted uniform travel at 20 N (mm)",
                   title="Nominal stop and thick-bond scenario")
        axes[0].legend(loc="lower left"); axes[1].legend(loc="lower left")
        fig.suptitle("K1 planning sensitivity · lower motion and larger signal compete\nUniform posts, zero cover stiffness in this plot · not measured performance", fontsize=12)
        for suffix in ("png", "pdf"):
            fig.savefig(folder / ("assembly_sensitivity."+suffix), dpi=160)
        plt.close(fig)
        report = {"schema": "yam-k1-assembly-screen/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "foil_area_bounds": foil_rows, "shield": shield, "uniform_cases": rows,
                  "signal_planning_failures": len(signal_findings), "stop_scenario_findings": stop_findings,
                  "limits": plan["limits"], "status": "Model scenarios for build/test decisions; no physical pass assigned"}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "shield": shield,
                            "signal_planning_failures": len(signal_findings),
                            "stop_scenario_findings": len(stop_findings), "physical_specimens_tested": 0}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
