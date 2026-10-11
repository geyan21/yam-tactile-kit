#!/usr/bin/python3
"""Explore C1 gauge-placement/gain scenarios using a preserved solved mesh."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
from structural_tools import tools,parse_node_tables,axial_strain_sampler,sample_strain
from run_c1_fea import gauge_points
from tactile_kit.records import execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run",type=Path)
    parser.add_argument("--realizations",type=int,default=16)
    parser.add_argument("--output",type=Path)
    args = parser.parse_args()
    if not 4<=args.realizations<=128:
        parser.error("Use 4..128 deterministic scenario realizations")
    folder = args.run.resolve()
    if not folder.is_relative_to(ROOT/"build/engineering/prototypes/c1/fea"):
        parser.error("Select a C1 structural run in this checkout")
    destination = args.output or folder/"tolerance_scenarios.json"
    if destination.exists():
        parser.error("Preserve the earlier scenario report and choose a new --output")
    cfg = json.loads((folder/"inputs/configuration.json").read_text())
    plan = json.loads((folder/"inputs/assembly_manifest.json").read_text())
    screen = json.loads((folder/"screen.json").read_text())
    tables = [t for t in parse_node_tables(folder/"c1.dat") if t["kind"]=="U"]
    loads = np.asarray([row["wrench_about_root_n_nmm"] for row in screen["contact_cases_20n"]]).T
    nominal_weights = np.asarray(screen["simulation_fz_my_weights_v_to_n"])
    with execution(ROOT/"build/records","Evaluate assumed C1 gauge-placement and gain errors on saved FEA fields; no manufactured-unit or force-accuracy claim") as record:
        gmsh,_,_ = tools()
        gmsh.initialize([],readConfigFiles=False,run=False)
        gmsh.option.setNumber("General.Terminal",0)
        try:
            gmsh.open(str(folder/"mesh.msh"))
            tags,coordinates,_ = gmsh.model.mesh.getNodes()
            coordinates = np.asarray(coordinates).reshape(-1,3)
            rng = np.random.default_rng(20261011)
            realizations = []
            for tolerance in (.1,.25):
                for realization in range(args.realizations):
                    offsets = rng.uniform(-tolerance,tolerance,(8,2))
                    gauge_gains = rng.uniform(.999,1.001,8)
                    station_gains = rng.uniform(.999,1.001,2)
                    strains = np.zeros((8,6))
                    for i,gauge in enumerate(plan["gauges"]):
                        shifted = copy.deepcopy(gauge)
                        shifted["center_native_mm"][:2] = (np.asarray(gauge["center_native_mm"][:2])+offsets[i]).tolist()
                        sampler = axial_strain_sampler(gmsh,tags,coordinates,gauge_points(shifted,cfg))
                        for case,table in enumerate(tables):
                            scale = screen["forces_and_moments"][case]["applied_scale_n_or_nmm"]
                            strains[i,case] = sample_strain(sampler,table["rows"])*gauge_gains[i]/scale
                    bridge = np.vstack([(-strains[4*i]+strains[4*i+1]+strains[4*i+2]-strains[4*i+3])/4
                                        for i in range(2)])
                    bridge *= cfg["gauges"]["gauge_factor_assumed"]*cfg["gauges"]["excitation_v"]
                    bridge *= station_gains[:,None]
                    recalibrated = np.linalg.solve(bridge[:,[2,4]].T,[1,0])
                    error_nominal = np.abs(nominal_weights@bridge@loads-20)
                    error_recal = np.abs(recalibrated@bridge@loads-20)
                    realizations.append({
                        "placement_bound_mm":tolerance,"realization":realization,
                        "gauge_offsets_xy_mm":offsets.tolist(),"relative_gains":gauge_gains.tolist(),
                        "relative_station_gains":station_gains.tolist(),
                        "max_normal_contact_error_n_without_recalibration":float(np.max(error_nominal)),
                        "max_normal_contact_error_n_after_simulated_fz_my_recalibration":float(np.max(error_recal)),
                    })
                print(f"Completed {args.realizations} C1 scenarios with placement bound {tolerance} mm",flush=True)
            summaries = []
            for tolerance in (.1,.25):
                rows = [r for r in realizations if r["placement_bound_mm"]==tolerance]
                summary = {"placement_bound_mm":tolerance}
                for key in ("max_normal_contact_error_n_without_recalibration",
                            "max_normal_contact_error_n_after_simulated_fz_my_recalibration"):
                    values = [r[key] for r in rows]
                    summary[key] = {"median":float(np.percentile(values,50)),"p95":float(np.percentile(values,95)),
                                    "maximum":max(values)}
                summaries.append(summary)
            result = {
                "schema":"yam-c1-tolerance-scenarios/1","evidence_kind":"simulation_scenarios",
                "physical_specimens_tested":0,"seed":20261011,
                "assumed_individual_gauge_gain_bound":.001,"assumed_station_gain_bound":.001,
                "scenario_summaries":summaries,"realizations":realizations,
                "source_screen_sha256":hashlib.sha256((folder/"screen.json").read_bytes()).hexdigest(),
                "limits":["Assumed placement/gain errors, not measured manufacturing tolerances or yield.",
                          "The source is a bonded, linear finite-element model. Bonding, thermal drift, glue, cables and real clamps are omitted.",
                          "Simulated per-unit identification uses Fz and My; it does not remove arbitrary cross-axis effects.",
                          "Scenario percentages describe these imposed inputs and do not establish physical force accuracy."],
            }
            destination.parent.mkdir(parents=True,exist_ok=True)
            with destination.open("x") as stream:
                json.dump(result,stream,indent=2);stream.write("\n")
            record["summaries"] = summaries
            print(json.dumps(summaries,indent=2))
        finally:
            gmsh.finalize()


if __name__=="__main__":
    main()
