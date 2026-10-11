#!/usr/bin/python3
"""Screen K1 range and compliance assumptions without inventing force calibration."""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/capacitive-matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon as PlotPolygon
import numpy as np
from scipy.optimize import brentq

from tactile_kit.records import execution
from capacitive_geometry import CONFIG, load as load_geometry, posts, reference_footprints, offsets, unrolled
from screen_f1_feedback import digest

EPSILON_PF_PER_MM = .0088541878128


def compression(force, post_area, modulus):
    if force == 0:
        return 1.
    # Nominal compression force of independent incompressible neo-Hookean
    # columns. End friction, base deformation, plate bending and contact
    # constraints are deliberately not smuggled into a bulk tensile modulus.
    shear = modulus/3
    return brentq(lambda stretch: post_area*shear*(stretch**-2-stretch)-force, .01, 1)


def capacitance(area, post_area, stretch, cfg):
    d, flex = cfg["dielectric"], cfg["flex"]
    expanded_area = post_area/stretch
    if expanded_area >= area:
        raise ValueError("The assumed posts would coalesce; no further extrapolation")
    height = d["post_height_mm"]*stretch
    common = d["base_mm"]/d["relative_permittivity_assumed_at_25khz"]
    common += flex["coverlay_each_mm"]/flex["coverlay_relative_permittivity_assumed"]
    post_path = common+height/d["relative_permittivity_assumed_at_25khz"]
    air_path = common+height
    return EPSILON_PF_PER_MM*(expanded_area/post_path+(area-expanded_area)/air_path)


def main():
    cfg, surfaces = load_geometry()
    material = cfg["dielectric"]
    inputs = [CONFIG, Path(__file__), ROOT / "engineering/scripts/capacitive_geometry.py",
              ROOT / "engineering/scripts/f1_surfaces.py",
              *[ROOT / cfg["basis"][key] for key in ("r1_manifest", "nail_coordinates")]]
    output = ROOT / "build/engineering/prototypes/capacitive/screens" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Screen proposed K1 post-sheet capacitance and compliance against explicit material scenarios and actual finger footprints; do not convert these predictions into sensor calibration") as record:
        output.mkdir(parents=True, exist_ok=False)
        for path in inputs:
            target = output / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        footprints = [(f"CH{s.site}",
                       unrolled(s.body, s, offsets(s.site, cfg)["post_base_middle"]),
                       unrolled(s.active, s, offsets(s.site, cfg)["post_base_middle"])) for s in surfaces]
        footprints.append(("REF", *reference_footprints(cfg)))
        results = []
        fig, axes = plt.subplots(2, 4, figsize=(14, 8), layout="constrained")
        for index, (name, body, active) in enumerate(footprints):
            centers = posts(active, cfg)
            area = len(centers)*math.pi*(material["post_diameter_mm"]/2)**2
            c0 = capacitance(active.area, area, 1., cfg)
            cases = []
            for modulus in material["uniform_post_modulus_mpa_screen"]:
                case = {"post_modulus_mpa_assumed": modulus, "loads": []}
                for force in (0.2, 1, 5, 10, 15, 20):
                    stretch = compression(force, area, modulus)
                    travel = material["post_height_mm"]*(1-stretch)
                    stopped = material["post_height_mm"]*stretch <= material["minimum_post_height_at_stop_mm"]
                    cap = None if stopped else capacitance(active.area, area, stretch, cfg)
                    case["loads"].append({"force_n_model_input": force, "uniform_travel_mm": travel,
                                          "would_reach_stop": stopped, "capacitance_pf_if_unstopped": cap,
                                          "delta_pf_if_unstopped": None if cap is None else cap-c0})
                cases.append(case)
            results.append({"site": name, "body_area_mm2": body.area, "active_area_mm2": active.area,
                            "posts": centers, "post_count": len(centers), "initial_post_area_mm2": area,
                            "initial_post_area_fraction": area/active.area, "nominal_unloaded_capacitance_pf": c0,
                            "uniform_scenarios": cases})
            ax = axes.flat[index]
            ax.add_patch(PlotPolygon(body.exterior.coords, fc="#eef2e8", ec="#557267"))
            ax.add_patch(PlotPolygon(active.exterior.coords, fc="#cddcd3", ec="#496b6d"))
            for center in centers:
                ax.add_patch(Circle(center, material["post_diameter_mm"]/2, fc="#b99461", ec="none"))
            ax.autoscale_view(); ax.invert_yaxis()
            ax.set(aspect="equal", xlabel="U (mm)", ylabel="Developed base arc (mm)",
                   title=f"{name}: {len(centers)} posts · {c0:.2f} pF model")
        axes.flat[-1].axis("off")
        axes.flat[-1].text(0, .9, "K1 development geometry\n\n0 physical specimens\nNo force calibration\n\nPost constraints and plate\nbending remain to be checked.",
                           va="top", fontsize=12)
        fig.suptitle("K1 capacitive finger · proposed silicone post sheets\n"
                     "Six contact regions plus two copies of the protected reference", fontsize=14)
        for suffix in ("png", "pdf", "svg"):
            fig.savefig(output / ("post_layout."+suffix), dpi=160)
        plt.close(fig)
        ref = results[-1]["nominal_unloaded_capacitance_pf"]
        headroom, shield = [], []
        for row in results[:6]:
            for case in row["uniform_scenarios"]:
                for load in case["loads"]:
                    cap = load["capacitance_pf_if_unstopped"]
                    headroom.append({"site": row["site"], "modulus_mpa": case["post_modulus_mpa_assumed"],
                                     "force_n": load["force_n_model_input"],
                                     "would_reach_stop": load["would_reach_stop"],
                                     "difference_to_reference_pf": None if cap is None else cap-ref,
                                     "within_fdc_range": cap is not None and abs(cap-ref) < cfg["readout"]["fdc_full_scale_pf"]})
        for bank in cfg["readout"]["banks"]:
            # Deliberately pessimistic grounded-CIN scenario for reviewing
            # guard geometry. This is not a solved parasitic network.
            guard_area = sum(unrolled(surfaces[site].body, surfaces[site], offsets(site, cfg)["shield_center"])
                             .buffer(-cfg["flex"]["shield_plane_edge_inset_mm"]).area for site in bank["sites"])
            foil = EPSILON_PF_PER_MM*cfg["flex"]["polyimide_relative_permittivity_assumed"]*guard_area/cfg["flex"]["polyimide_core_mm"]
            cable = 3*cfg["readout"]["maximum_candidate_sensor_cable_m"]*cfg["readout"]["cable_capacitance_pf_per_m_assumed"]
            total = foil+cable+cfg["readout"]["board_shield_load_allowance_pf_assumed"]
            shield.append({"bank": bank["bank"], "guard_copper_area_mm2": guard_area,
                           "grounded_CIN_foil_capacitance_pf_screen": foil,
                           "cable_pf_assumed": cable, "total_pf_screen": total,
                           "below_400pf_screen": total < cfg["readout"]["fdc_maximum_shield_load_pf"]})
        flex_height = 2*cfg["flex"]["copper_each_mm"]+cfg["flex"]["polyimide_core_mm"]+2*cfg["flex"]["coverlay_each_mm"]
        height_common = flex_height+material["base_mm"]+material["post_height_mm"]+cfg["body"]["spreader_thickness_mm"]
        report = {"schema": "yam-k1-electromechanical-screen/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                  "cells": results, "headroom": headroom, "shield_estimates": shield,
                  "nominal_added_nail_mm": cfg["body"]["nail_mounting_mm"]+height_common+cfg["body"]["nail_cover_mm"],
                  "nominal_added_tpu_mm": cfg["body"]["tpu_mounting_mm"]+cfg["body"]["tpu_rigid_saddle_mm"]+height_common+cfg["body"]["tpu_cover_mm"],
                  "scope": "A model sensitivity screen, not a force rating or proof of installed performance",
                  "limits": [
                      "Independent uniform post compression omits end constraint, base-layer strain, viscoelasticity, adhesion and finite plate bending.",
                      "Bulk tensile data must not be substituted for measured microstructure compression; the modulus sweep exposes this uncertainty.",
                      "Fringing fields, cable/PCB parasitics, dielectric loss, temperature and humidity are not solved.",
                      "Protected references may help track drift but do not guarantee cancellation of spatially different thermal or mechanical changes.",
                      "Finite/contact-area loading, edge loads, stops, retention, source motion and physical 20 N/contact tests remain."
                  ]}
        (output / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(output.relative_to(ROOT)), "cells": len(results),
                            "post_count_by_cell": {r["site"]: r["post_count"] for r in results},
                            "unloaded_capacitance_pf": {r["site"]: r["nominal_unloaded_capacitance_pf"] for r in results},
                            "stopped_scenarios": sum(r["would_reach_stop"] for r in headroom),
                            "fdc_range_failures": sum(not r["within_fdc_range"] and not r["would_reach_stop"] for r in headroom),
                            "shield_estimates": shield, "nominal_added_nail_mm": report["nominal_added_nail_mm"],
                            "nominal_added_tpu_mm": report["nominal_added_tpu_mm"]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
