#!/usr/bin/python3
"""Check the bonded C1 adapter under independent force and moment load cases."""

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ["MPLCONFIGDIR"] = str(ROOT/"build/engineering/tools/mpl-cache")
os.environ["XDG_CACHE_HOME"] = str(ROOT/"build/engineering/tools/cache")
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import numpy as np
from shapely.geometry import Point,Polygon
from structural_tools import tools,digest,write_set,create_mesh,run_solver,parse_node_tables,axial_strain_sampler,sample_strain
from c1_iteration_inputs import save_inputs
from tactile_kit.records import execution

OUTPUT = ROOT/"build/engineering/prototypes/c1"
CASES = ("Fx","Fy","Fz","Mx","My","Mz")


def stress_tables(path):
    tables = [];current = None
    with path.open() as stream:
        for line in stream:
            text = line.strip();lower = text.lower()
            if lower.startswith("stresses ") and "for set" in lower and "time" in lower:
                current = [];tables.append(current)
                continue
            if not text:
                continue
            fields = text.split()
            if current is not None and len(fields)==8 and fields[0].isdigit() and fields[1].isdigit():
                current.append([int(fields[0]),int(fields[1]),*[float(v.replace("D","E")) for v in fields[2:]]])
            else:
                current = None
    if len(tables)!=6:
        raise ValueError(f"Expected six integration-point stress tables; got {len(tables)}")
    arrays = [np.asarray(table,dtype=float) for table in tables]
    if any(a.shape!=arrays[0].shape or not np.array_equal(a[:,:2],arrays[0][:,:2]) for a in arrays):
        raise ValueError("Stress integration point ordering changed across cases")
    return np.stack([a[:,2:]/(1 if i<3 else 1000) for i,a in enumerate(arrays)])


def von_mises(stress):
    x,y,z,xy,xz,yz = stress.T
    return np.sqrt(((x-y)**2+(y-z)**2+(z-x)**2)/2+3*(xy*xy+xz*xz+yz*yz))


def gauge_points(gauge,config):
    g = config["gauges"]
    q,w = np.polynomial.legendre.leggauss(11)
    x,y,z = gauge["center_native_mm"]
    z += -1e-4 if gauge["face"]=="top" else 1e-4
    return [([x+a*g["grid_length_mm"]/2,y+b*g["grid_width_mm"]/2,z],wa*wb/4)
            for a,wa in zip(q,w) for b,wb in zip(q,w)]


def analyze(folder,config,plan,tags,xyz,samplers,root,rotation):
    tables = parse_node_tables(folder/"c1.dat")
    u_tables = [t for t in tables if t["kind"]=="U"]
    rf_tables = [t for t in tables if t["kind"]=="RF"]
    if len(u_tables)!=6 or len(rf_tables)!=6:
        raise ValueError(f"Incomplete solver output: {len(u_tables)} displacement tables, {len(rf_tables)} force tables")
    xyz_map = {int(tag):point for tag,point in zip(tags,xyz)}
    ref = np.asarray(plan["root_reference_native_mm"])
    response = []
    bridge_factor = config["gauges"]["gauge_factor_assumed"]*config["gauges"]["excitation_v"]
    for i,(u,rf) in enumerate(zip(u_tables,rf_tables)):
        if any(int(tag) not in u["rows"] for tag in tags) or root not in u["rows"] or rotation not in u["rows"]:
            raise ValueError("Missing mesh or rigid-reference displacements")
        scale = 1 if i<3 else 1000
        applied = np.eye(6)[i]*scale
        force = np.sum(list(rf["rows"].values()),axis=0)
        moment = sum((np.cross(xyz_map[tag]-ref,value) for tag,value in rf["rows"].items()),np.zeros(3))
        force_residual = np.linalg.norm(force+applied[:3])
        moment_residual = np.linalg.norm(moment+applied[3:])
        if force_residual>.002 or moment_residual>.2:
            raise ValueError(f"Reaction residuals exceed screen limits: {CASES[i]} {force_residual}, {moment_residual}")
        strain = [sample_strain(sampler,u["rows"])/scale for sampler in samplers]
        volts = []
        for station in range(2):
            # R1 top A, R2 bottom A, R3 bottom B, R4 top B.
            r1,r2,r3,r4 = strain[4*station:4*station+4]
            volts.append(bridge_factor*(-r1+r2+r3-r4)/4)
        response.append({
            "case":CASES[i],"applied_scale_n_or_nmm":scale,
            "reaction_force_residual_n":force_residual,"reaction_moment_residual_nmm":moment_residual,
            "gauge_strain_per_unit":strain,"bridge_volts_per_unit":volts,
            "root_translation_per_unit":np.asarray(u["rows"][root]).tolist(),
            "root_rotation_per_unit":np.asarray(u["rows"][rotation]).tolist(),
        })
        response[-1]["root_translation_per_unit"] = (np.asarray(u["rows"][root])/scale).tolist()
        response[-1]["root_rotation_per_unit"] = (np.asarray(u["rows"][rotation])/scale).tolist()
    b = config["beam"]
    spacing = b["gauge_stations_mm_from_fixed_boundary"][1]-b["gauge_stations_mm_from_fixed_boundary"][0]
    sensitivity = bridge_factor*6*spacing/(b["youngs_modulus_mpa_assumed"]*b["width_mm"]*b["thickness_mm"]**2)
    matrix = np.asarray([r["bridge_volts_per_unit"] for r in response]).T
    ideal_weights = np.array([1,-1])/sensitivity
    # FEA-only identification of Fz and My. This is not a physical calibration.
    signal_matrix = matrix[:,[2,4]]
    fitted_weights = np.linalg.solve(signal_matrix.T,[1,0])
    stresses = stress_tables(folder/"c1.dat")
    contacts = []
    for site in plan["contact_sites"]:
        point = np.asarray(site["native_xyz_mm"])
        wrench = np.r_[0,0,20,np.cross(point-ref,[0,0,20])]
        voltage = matrix@wrench
        translations = np.asarray([r["root_translation_per_unit"] for r in response]).T@wrench
        rotations = np.asarray([r["root_rotation_per_unit"] for r in response]).T@wrench
        displacement = translations+np.cross(rotations,point-ref)
        vm = von_mises(np.tensordot(wrench,stresses,axes=(0,0)))
        contacts.append({
            "id":site["id"],"wrench_about_root_n_nmm":wrench.tolist(),
            "bridge_voltage_v":voltage.tolist(),
            "force_from_ideal_beam_screen_n":float(ideal_weights@voltage),
            "force_from_simulation_fz_my_weights_n":float(fitted_weights@voltage),
            "added_tip_displacement_mm":displacement.tolist(),
            "added_normal_displacement_mm":float(displacement[2]),
            "max_integration_point_von_mises_mpa":float(np.max(vm)),
            "p99_integration_point_von_mises_mpa":float(np.percentile(vm,99)),
        })
    return {
        "evidence_kind":"linear_FEA_screen_only","forces_and_moments":response,
        "ideal_differential_sensitivity_v_per_n":sensitivity,
        "analytical_weights_v_to_n":ideal_weights.tolist(),
        "simulation_fz_my_weights_v_to_n":fitted_weights.tolist(),
        "force_equivalent_response_per_unit":list(ideal_weights@matrix),
        "simulation_compensated_force_equivalent_response_per_unit":list(fitted_weights@matrix),
        "contact_cases_20n":contacts,
        "max_added_normal_displacement_mm":max(abs(c["added_normal_displacement_mm"]) for c in contacts),
        "max_ideal_force_error_n":max(abs(c["force_from_ideal_beam_screen_n"]-20) for c in contacts),
        "max_simulation_force_error_n":max(abs(c["force_from_simulation_fz_my_weights_n"]-20) for c in contacts),
        "max_integration_point_von_mises_mpa":max(c["max_integration_point_von_mises_mpa"] for c in contacts),
        "stress_scope":"Linear bonded-model integration-point stresses. Local corner peaks and real contact/preload require separate assessment; no strength or fatigue rating.",
        "physical_specimens_tested":0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh-mm",type=float,default=2.0)
    parser.add_argument("--solve-timeout",type=int,default=240)
    parser.add_argument("--gauge-mesh-mm",type=float)
    args = parser.parse_args()
    if not .5<=args.mesh_mm<=4 or not 30<=args.solve_timeout<=900:
        parser.error("Mesh size must be 0.5..4 mm and solve timeout 30..900 seconds")
    if args.gauge_mesh_mm is not None and not .35<=args.gauge_mesh_mm<=args.mesh_mm:
        parser.error("Local gauge mesh must be 0.35 mm or larger and no coarser than the global mesh")
    config = json.loads((ROOT/"engineering/designs/c1.json").read_text())
    plan = json.loads((OUTPUT/"c1_manifest.json").read_text())
    for name,expected in plan["source_hashes"].items():
        if digest(ROOT/name)!=expected:
            raise ValueError(f"Stale C1 geometry: {name}")
    geometry = OUTPUT/plan["analysis_geometry"]["file"]
    if digest(geometry)!=plan["analysis_geometry"]["sha256"]:
        raise ValueError("Analysis STEP changed")
    size_folder = OUTPUT/"fea"/("mesh_"+str(args.mesh_mm).replace(".","p"))
    if args.gauge_mesh_mm is not None:
        size_folder = size_folder.with_name(size_folder.name+"_gauge_"+str(args.gauge_mesh_mm).replace(".","p"))
    folder = size_folder/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    folder.mkdir(parents=True,exist_ok=True)
    with execution(ROOT/"build/records","Screen C1's actual bonded CAD with 3D quadratic elements, six independent loads and gauge-area strain averages") as record:
        record["preserved_inputs"] = save_inputs(folder,geometry)
        gmsh,binary,tool_manifest = tools()
        try:
            refinements = []
            if args.gauge_mesh_mm is not None:
                for gauge in plan["gauges"]:
                    x,y,z = gauge["center_native_mm"]
                    dx = config["gauges"]["grid_length_mm"]/2+1
                    dy = config["gauges"]["grid_width_mm"]/2+1
                    refinements.append({"XMin":x-dx,"XMax":x+dx,"YMin":y-dy,"YMax":y+dy,
                                        "ZMin":z-2,"ZMax":z+2,"VIn":args.gauge_mesh_mm,
                                        "VOut":args.mesh_mm,"Thickness":1})
            tags,xyz,mesh_info = create_mesh(gmsh,geometry,folder,args.mesh_mm,refinements=refinements)
            interface = json.loads((ROOT/"engineering/release/l1/root_interface.json").read_text())
            region = max(interface["mount_plane"]["regions"],key=lambda p:p["area_mm2"])
            profile = Polygon(region["outer"],region["holes"]).buffer(.002)
            def nodes_on(plane):
                return [int(tag) for tag,p in zip(tags,xyz) if abs(p[1]-plane)<1e-5 and profile.covers(Point(p[0],p[2]))]
            support = nodes_on(plan["fixed_mount_plane_y_mm"])
            front = nodes_on(plan["floating_mount_plane_y_mm"])
            if len(support)<15 or len(front)<15 or set(support)&set(front):
                raise ValueError("Invalid root-face constraint sets")
            root = int(max(tags))+1;rotation = root+1
            samplers = [axial_strain_sampler(gmsh,tags,xyz,gauge_points(gauge,config)) for gauge in plan["gauges"]]
            mesh_text = (folder/"mesh.inp").read_text()
            if not "*ELSET" in mesh_text.upper() or "SOLID" not in mesh_text:
                raise ValueError("Missing physical volume element set")
            deck = "** C1.1 bonded adapter linear screen. Units N, mm, MPa.\n*INCLUDE,INPUT=mesh.inp\n"
            deck += f"*NODE\n{root},"+",".join(map(str,plan["root_reference_native_mm"]))+f"\n{rotation},0,0,0\n"
            deck += write_set("SUPPORT",support)+write_set("FINGER",front)+write_set("OUTPUT",[*tags,root,rotation])
            deck += f"*RIGID BODY,NSET=FINGER,REF NODE={root},ROT NODE={rotation}\n"
            deck += "*MATERIAL,NAME=AL6061\n*ELASTIC\n"+f'{config["beam"]["youngs_modulus_mpa_assumed"]},{config["beam"]["poisson_ratio_assumed"]}\n'
            deck += "*SOLID SECTION,ELSET=SOLID,MATERIAL=AL6061\n*BOUNDARY\nSUPPORT,1,3,0\n"
            for i,name in enumerate(CASES):
                node = root if i<3 else rotation;dof = i%3+1;load = 1 if i<3 else 1000
                deck += f"** {name}\n*STEP\n*STATIC\n*CLOAD,OP=NEW\n{node},{dof},{load}\n"
                deck += "*NODE PRINT,NSET=OUTPUT\nU\n*NODE PRINT,NSET=SUPPORT\nRF\n*EL PRINT,ELSET=SOLID\nS\n*END STEP\n"
            (folder/"c1.inp").write_text(deck)
            print(json.dumps({"mesh":mesh_info,"fixed_nodes":len(support),"loaded_face_nodes":len(front)}),flush=True)
            run_solver(binary,folder,"c1",record,args.solve_timeout)
            report = analyze(folder,config,plan,tags,xyz,samplers,root,rotation)
            report.update({"mesh":mesh_info,"tools":tool_manifest,
                           "gauge_area_quadrature_order":11,
                           "geometry_sha256":digest(geometry),"deck_sha256":digest(folder/"c1.inp"),
                           "input_hashes":{name:digest(ROOT/name) for name in (
                               "engineering/designs/c1.json","engineering/scripts/run_c1_fea.py",
                               "engineering/scripts/structural_tools.py")},
                           "limits":["Linear isotropic aluminum; bonded clamp interfaces and rigid jaw/finger root faces.",
                                     "No bolt preload, friction/slip, gauge/adhesive reinforcement, plasticity, fatigue or thermal drift.",
                                     "Original finger is represented as a rigid lever for added adapter motion.",
                                     "Simulation-derived weights are never a substitute for measured force calibration.",
                                     "Mesh convergence and independent numerical verification are required before using the screen."]})
            (folder/"screen.json").write_text(json.dumps(report,indent=2)+"\n")
            (size_folder/"latest.json").write_text(json.dumps({"directory":folder.name,"screen_sha256":digest(folder/"screen.json")},indent=2)+"\n")
            record["result"] = {"mesh":mesh_info,
                                "max_added_normal_displacement_mm":report["max_added_normal_displacement_mm"],
                                "max_ideal_force_error_n":report["max_ideal_force_error_n"],
                                "max_simulation_force_error_n":report["max_simulation_force_error_n"]}
            print(json.dumps(record["result"],indent=2))
        finally:
            gmsh.finalize()


if __name__=="__main__":
    main()
