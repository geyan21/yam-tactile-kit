#!/usr/bin/python3
"""Screen FB1's actual metal CAD with bonded clamps and a normal-only sensor spring."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "build/engineering/tools/force-button-cad-cache"))
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
sys.path.insert(0, str(ROOT / "src"))
import numpy as np

from tactile_kit.records import execution
from structural_tools import tools, digest, write_set, run_solver, parse_node_tables
from force_button_mechanics import CONFIG, contact_sites


def mesh(gmsh, source, plan, folder, size, leaf_size):
    gmsh.initialize([], readConfigFiles=False, run=False)
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("General.NumThreads", 1)
    gmsh.model.add("fb1_bonded_metals")
    selected = [p for p in plan["parts"] if p["kind"] == "fabricate"
                and p["id"] not in ("fb1_bench_receiver", "fb1_pcb_insulating_film")]
    print("Importing "+str(len(selected))+" metal solids", flush=True)
    volumes = []
    for part in selected:
        path = source / part["step"]
        if digest(path) != part["sha256_step"]:
            raise ValueError("CAD identity changed")
        imported = [v for v in gmsh.model.occ.importShapes(str(path)) if v[0] == 3]
        if len(imported) != 1:
            raise ValueError("Expected one volume per metal part")
        volumes.extend(imported)
    print("Fragmenting bonded material interfaces", flush=True)
    _, mapping = gmsh.model.occ.fragment(volumes[:1], volumes[1:])
    gmsh.model.occ.synchronize()
    if len(mapping) != len(selected):
        raise ValueError("Cannot associate fragmented materials")
    groups, owners = {"AL": set(), "STEEL": set()}, {}
    for part, mapped in zip(selected, mapping):
        tags = {tag for dim, tag in mapped if dim == 3}
        if not tags:
            raise ValueError("A metal part disappeared during fragmentation")
        owners[part["id"]] = sorted(tags)
        groups["STEEL" if part["id"].startswith("fb1_guide_leaf_") else "AL"].update(tags)
    if groups["AL"] & groups["STEEL"]:
        raise ValueError("Steel and aluminum overlap")
    for material, tags in groups.items():
        index = gmsh.model.addPhysicalGroup(3, sorted(tags))
        gmsh.model.setPhysicalName(3, index, material)
    for name, value in {"Mesh.MeshSizeMin": min(.15, leaf_size*.4), "Mesh.MeshSizeMax": size,
                        "Mesh.MeshSizeFromPoints": 0, "Mesh.MeshSizeFromCurvature": 0,
                        "Mesh.MeshSizeExtendFromBoundary": 0, "Mesh.Algorithm3D": 1,
                        "Mesh.ElementOrder": 2, "Mesh.SecondOrderLinear": 1, "Mesh.SaveAll": 0}.items():
        gmsh.option.setNumber(name, value)
    fields = []
    for part in selected:
        if not part["id"].startswith("fb1_guide_leaf_"):
            continue
        lower, upper = np.asarray(part["bounds_mm"])
        tag = gmsh.model.mesh.field.add("Box")
        for key, value in {"XMin": lower[0]-.2, "XMax": upper[0]+.2,
                           "YMin": lower[1]-.2, "YMax": upper[1]+.2,
                           "ZMin": lower[2]-.2, "ZMax": upper[2]+.2,
                           "VIn": leaf_size, "VOut": size, "Thickness": .5}.items():
            gmsh.model.mesh.field.setNumber(tag, key, float(value))
        fields.append(tag)
    field = gmsh.model.mesh.field.add("Min")
    gmsh.model.mesh.field.setNumbers(field, "FieldsList", fields)
    gmsh.model.mesh.field.setAsBackgroundMesh(field)
    print("Generating conforming quadratic tetrahedra with straight midside geometry", flush=True)
    gmsh.model.mesh.generate(3)
    print("Checking mesh size and Jacobians", flush=True)
    node_tags, coordinates, _ = gmsh.model.mesh.getNodes()
    tags = np.asarray(node_tags, dtype=np.int64)
    xyz = np.asarray(coordinates).reshape(-1, 3)
    element_types, element_tags, _ = gmsh.model.mesh.getElements(3)
    if list(element_types) != [11] or len(tags)*3 > 400000:
        raise ValueError("Require C3D10 elements and at most 400,000 displacement DOFs")
    determinants = np.asarray(gmsh.model.mesh.getElementQualities(np.concatenate(element_tags), "minDetJac"))
    if not np.all(np.isfinite(determinants)) or min(determinants) <= 0:
        raise ValueError("Nonpositive high-order Jacobian")
    bonds = []
    for index in range(4):
        leaf_nodes = set()
        for tag in owners["fb1_guide_leaf_"+str(index)]:
            leaf_nodes.update(map(int, gmsh.model.mesh.getNodes(3, tag, includeBoundary=True)[0]))
        for side in ("fixed", "floating"):
            carrier_nodes = set()
            for tag in owners["fb1_"+side+"_carrier"]:
                carrier_nodes.update(map(int, gmsh.model.mesh.getNodes(3, tag, includeBoundary=True)[0]))
            count = len(leaf_nodes & carrier_nodes)
            bonds.append({"leaf": index, "carrier": side, "shared_nodes": count})
            if count < 8:
                raise ValueError("The metal guide clamp does not share a resolved bonded interface")
    gmsh.write(str(folder / "mesh.inp"))
    gmsh.write(str(folder / "mesh.msh"))
    return tags, xyz, int(max(np.concatenate(element_tags)))+1, {
        "nodes": len(tags), "elements": sum(len(e) for e in element_tags), "element": "C3D10",
        "global_size_mm": size, "leaf_size_mm": leaf_size, "minimum_jacobian_determinant": float(min(determinants)),
        "geometry_order": "Straight midside geometry; curved surfaces are represented by the mesh and require convergence",
        "steel_volume_tags": sorted(groups["STEEL"]), "aluminum_volume_tags": sorted(groups["AL"]),
        "bonded_leaf_interfaces": bonds}


def load_stresses(path, expected_steps):
    """Preserve integration-point order for linear load superposition."""
    tables, table = [], None
    for line in path.read_text().splitlines():
        text = line.strip()
        if text.lower().startswith("stresses ") and "for set" in text.lower():
            table = []; tables.append(table)
        elif text and table is not None:
            fields = text.split()
            if len(fields) == 8 and fields[0].isdigit() and fields[1].isdigit():
                table.append([int(fields[0]), int(fields[1]), *[float(v.replace("D", "E")) for v in fields[2:]]])
            else:
                table = None
    # There are separate AL and STEEL sets per step.
    if len(tables) != expected_steps*2 or any(not t for t in tables):
        raise ValueError("Incomplete metal stress output")
    combined = [np.vstack(tables[2*i:2*i+2]) for i in range(expected_steps)]
    if any(a.shape != combined[0].shape or not np.array_equal(a[:, :2], combined[0][:, :2]) for a in combined):
        raise ValueError("Stress point ordering changed")
    return np.stack([a[:, 2:] for a in combined]), combined[0][:, :2], len(tables[0])


def von_mises(stress):
    x, y, z, xy, xz, yz = stress.T
    return np.sqrt(((x-y)**2+(y-z)**2+(z-x)**2)/2+3*(xy*xy+xz*xz+yz*yz))


def reuse_mesh(source, plan_path, folder, size, leaf_size):
    report = json.loads((source / "report.json").read_text())
    if (report["input_sha256"].get(str(plan_path.relative_to(ROOT))) != digest(plan_path)
            or report["input_sha256"].get(str(CONFIG.relative_to(ROOT))) != digest(CONFIG)
            or report["mesh_sha256"] != digest(source / "mesh.inp")
            or report["mesh"]["global_size_mm"] != size or report["mesh"]["leaf_size_mm"] != leaf_size):
        raise ValueError("Mesh reuse requires identical checked CAD, configuration and mesh dimensions")
    tags, xyz, elements, mode = [], [], [], None
    with (source / "mesh.inp").open() as stream:
        for line in stream:
            text = line.strip()
            if text.startswith("*"):
                mode = "node" if text.upper() == "*NODE" else "element" if text.upper().startswith("*ELEMENT") else None
            elif text and mode:
                values = text.split(",")
                if mode == "node":
                    if len(values) != 4:
                        raise ValueError("Unexpected node record")
                    tags.append(int(values[0])); xyz.append([float(v) for v in values[1:]])
                else:
                    elements.append(int(values[0]))
    if len(tags) != report["mesh"]["nodes"] or len(elements) != report["mesh"]["elements"]:
        raise ValueError("Mesh reuse counts differ")
    shutil.copyfile(source / "mesh.inp", folder / "mesh.inp")
    info = dict(report["mesh"])
    info["reused_from"] = str(source.relative_to(ROOT))
    info["reused_report_sha256"] = digest(source / "report.json")
    print("Reusing the identical checked geometric mesh for a different sensor-compliance scenario", flush=True)
    return np.asarray(tags), np.asarray(xyz), max(elements)+1, info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cad_run", type=Path)
    parser.add_argument("--fit-check", type=Path, required=True)
    parser.add_argument("--mesh-mm", type=float, default=2)
    parser.add_argument("--leaf-mm", type=float, default=.65)
    parser.add_argument("--sensor-compliance", type=float, default=.0001)
    parser.add_argument("--reuse-mesh", type=Path)
    args = parser.parse_args()
    source = args.cad_run.resolve()
    if not source.is_relative_to(ROOT / "build") or not 1 <= args.mesh_mm <= 3 or not .3 <= args.leaf_mm <= 1:
        parser.error("Use a generated CAD run and bounded mesh sizes")
    if args.sensor_compliance not in (.0001, .00025, .0005):
        parser.error("Use one of the declared positive sensor-compliance scenarios")
    plan = json.loads((source / "manifest.json").read_text())
    fit = json.loads(args.fit_check.read_text())
    if (not fit["passed_declared_checks"] or not fit.get("sensor_contact", {}).get("passed")
            or fit["source_manifest_sha256"] != digest(source / "manifest.json")):
        raise ValueError("Resolve the assembly fit findings before structural screening")
    if plan["input_sha256"][str(CONFIG.relative_to(ROOT))] != digest(CONFIG):
        raise ValueError("Current configuration differs from the CAD")
    cfg = json.loads(CONFIG.read_text()); m = cfg["mechanism"]
    folder = ROOT / "build/engineering/prototypes/force_button/fea" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Calculate FB1 actual metal-carrier compliance using conforming quadratic elements, bonded leaf clamps and a normal-only sensor spring; preserve all assumptions and numerical evidence") as record:
        folder.mkdir(parents=True, exist_ok=False)
        inputs = [CONFIG, Path(__file__), ROOT / "engineering/scripts/structural_tools.py",
                  ROOT / "engineering/scripts/force_button_mechanics.py", source / "manifest.json", args.fit_check.resolve()]
        for path in inputs:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        gmsh, binary, tool_manifest = tools()
        try:
            if args.reuse_mesh:
                previous = args.reuse_mesh.resolve()
                if not previous.is_relative_to(ROOT / "build/engineering/prototypes/force_button/fea"):
                    raise ValueError("Use an owned FB1 structural result for mesh reuse")
                tags, xyz, next_element, mesh_info = reuse_mesh(previous, source / "manifest.json", folder, args.mesh_mm, args.leaf_mm)
            else:
                tags, xyz, next_element, mesh_info = mesh(gmsh, source, plan, folder, args.mesh_mm, args.leaf_mm)
                gmsh.finalize()
            center = np.asarray(plan["geometry"]["reference_native_mm"])
            cx, cy, _ = center
            root_y = plan["geometry"]["root_plane_y"]
            finger_y = root_y+m["finger_translation_native_mm"][1]
            reference = np.array([cx, finger_y, center[2]])
            selected = {
                "SUPPORT": tags[np.abs(xyz[:, 1]-root_y) < 1e-5],
                "FINGER": tags[np.abs(xyz[:, 1]-finger_y) < 1e-5],
                "SENSOR_TOP": tags[(np.abs(xyz[:, 2]-plan["insulation_top_z_mm"]) < 1e-5)
                                   & (xyz[:, 0] >= cx-1.61) & (xyz[:, 0] <= cx+3.39)
                                   & (np.abs(xyz[:, 1]-cy) <= 2.5)],
                "PLUNGER": tags[(np.abs(np.hypot(xyz[:, 0]-cx, xyz[:, 1]-cy)-1.65) < 1e-5)
                                & (xyz[:, 2] >= -.001) & (xyz[:, 2] <= m["moving_tongue_top_z_mm"]+.001)]}
            if min(map(len, selected.values())) < 8:
                raise ValueError("Unresolved support or sensor load-patch node set")
            if any(set(a) & set(b) for i, a in enumerate(selected.values()) for b in list(selected.values())[i+1:]):
                raise ValueError("Rigid/support node sets overlap")
            nodes = {name: int(max(tags))+1+2*i for i, name in enumerate(("FINGER", "SENSOR_TOP", "PLUNGER"))}
            locations = {"FINGER": reference, "SENSOR_TOP": [cx, cy, plan["insulation_top_z_mm"]],
                         "PLUNGER": [cx, cy, m["moving_tongue_top_z_mm"]]}
            common = "** FB1 linear bonded-metal screen; N, mm, MPa.\n*INCLUDE,INPUT=mesh.inp\n*NODE\n"
            for name, node in nodes.items():
                common += f"{node},"+",".join(map(str, locations[name]))+f"\n{node+1},0,0,0\n"
            for name, values in selected.items():
                common += write_set(name, values)
            output_nodes = [*tags, *[v for n in nodes.values() for v in (n, n+1)]]
            common += write_set("OUTPUT", output_nodes)
            for name, node in nodes.items():
                common += f"*RIGID BODY,NSET={name},REF NODE={node},ROT NODE={node+1}\n"
            common += f"*MATERIAL,NAME=ALUMINUM\n*ELASTIC\n{m['sensor_support_young_mpa_assumed']},0.33\n"
            common += f"*MATERIAL,NAME=SPRINGSTEEL\n*ELASTIC\n{m['guide_young_mpa_assumed']},{m['guide_poisson_assumed']}\n"
            common += "*SOLID SECTION,ELSET=AL,MATERIAL=ALUMINUM\n*SOLID SECTION,ELSET=STEEL,MATERIAL=SPRINGSTEEL\n"
            common += "*BOUNDARY\nSUPPORT,1,3,0\n"
            output_cards = "*NODE PRINT,NSET=OUTPUT\nU\n*NODE PRINT,NSET=SUPPORT\nRF\n*EL PRINT,ELSET=AL\nS\n*EL PRINT,ELSET=STEEL\nS\n*END STEP\n"
            k = 1/args.sensor_compliance
            deck = common+f"*ELEMENT,TYPE=SPRING2,ELSET=SENSOR\n{next_element},{nodes['PLUNGER']},{nodes['SENSOR_TOP']}\n"
            deck += f"*SPRING,ELSET=SENSOR\n3,3\n{k:.9e}\n"
            for i in range(6):
                node = nodes["FINGER"]+(1 if i >= 3 else 0)
                load = 1 if i < 3 else 1000
                deck += f"*STEP\n*STATIC\n*CLOAD,OP=NEW\n{node},{i%3+1},{load}\n"+output_cards
            (folder / "fb1.inp").write_text(deck)
            preload = common+"** Net sensor preload pair; spring omitted because the plunger adjustment establishes this force.\n"
            preload += f"*STEP\n*STATIC\n*CLOAD\n{nodes['SENSOR_TOP']},3,{m['preload_sensor_force_n_assumed']}\n"
            preload += f"{nodes['PLUNGER']},3,{-m['preload_sensor_force_n_assumed']}\n"+output_cards
            (folder / "preload.inp").write_text(preload)
            print(json.dumps({"directory": str(folder.relative_to(ROOT)), "mesh": mesh_info,
                              "patch_nodes": {name: len(values) for name, values in selected.items()}}), flush=True)
            run_solver(binary, folder, "fb1", record, 240)
            run_solver(binary, folder, "preload", record, 120)
            tables = parse_node_tables(folder / "fb1.dat")
            displacements = [t["rows"] for t in tables if t["kind"] == "U"]
            reactions = [t["rows"] for t in tables if t["kind"] == "RF"]
            if len(displacements) != 6 or len(reactions) != 6:
                raise ValueError("Incomplete independent load cases")
            stresses, stress_ids, aluminum_count = load_stresses(folder / "fb1.dat", 6)
            preload_stress, preload_ids, _ = load_stresses(folder / "preload.dat", 1)
            if not np.array_equal(stress_ids, preload_ids):
                raise ValueError("Preload stress points differ")
            for i in range(3, 6):
                stresses[i] /= 1000
            node_xyz = {int(tag): point for tag, point in zip(tags, xyz)}
            compliance = np.zeros((6, 6)); sensor_gain = []
            balances = []
            for i, (u, rf) in enumerate(zip(displacements, reactions)):
                scale = 1 if i < 3 else 1000
                if any(n not in u for n in output_nodes):
                    raise ValueError("Incomplete nodal response")
                compliance[:, i] = np.r_[u[nodes["FINGER"]], u[nodes["FINGER"]+1]]/scale
                sensor_gain.append(k*(u[nodes["PLUNGER"]][2]-u[nodes["SENSOR_TOP"]][2])/scale)
                actual = np.r_[np.sum(list(rf.values()), axis=0),
                               sum((np.cross(node_xyz[n]-reference, force) for n, force in rf.items()), np.zeros(3))]
                residual = actual+np.eye(6)[i]*scale
                balances.append(residual.tolist())
                if max(abs(residual[:3])) > .003 or max(abs(residual[3:])) > .3:
                    raise ValueError("Force or moment equilibrium failed")
            symmetry = float(np.max(abs(compliance-compliance.T))/np.max(abs(compliance)))
            if symmetry > .01 or min(np.linalg.eigvalsh((compliance+compliance.T)/2)) <= 0 or sensor_gain[2] <= 0:
                raise ValueError("Nonreciprocal or nonpositive linear compliance")
            contacts = []
            for site in contact_sites(cfg):
                arm = site["point"]-reference
                wrench = np.r_[0., 0., 20., np.cross(arm, [0., 0., 20.])]
                q = compliance @ wrench
                motion = q[:3]+np.cross(q[3:], arm)
                sensor_increment = float(np.asarray(sensor_gain) @ wrench)
                total_stress = np.tensordot(wrench, stresses, axes=(0, 0))+preload_stress[0]
                vm = von_mises(total_stress)
                contacts.append({"id": site["id"], "wrench_n_nmm": wrench.tolist(),
                                 "added_contact_motion_mm": motion.tolist(), "added_motion_norm_mm": float(np.linalg.norm(motion)),
                                 "modeled_sensor_increment_n": sensor_increment,
                                 "modeled_preloaded_sensor_n": sensor_increment+m["preload_sensor_force_n_assumed"],
                                 "apparent_force_from_root_fz_gain_n": sensor_increment/sensor_gain[2],
                                 "peak_aluminum_integration_stress_mpa": float(max(vm[:aluminum_count])),
                                 "peak_steel_integration_stress_mpa": float(max(vm[aluminum_count:]))})
            result = {"schema": "yam-fb1-bonded-fea/1", "physical_specimens_tested": 0,
                      "mesh": mesh_info, "sensor_compliance_mm_per_n": args.sensor_compliance,
                      "sensor_gain_per_root_wrench": sensor_gain, "compliance_about_finger_mount": compliance.tolist(),
                      "reciprocity_relative_error": symmetry, "reaction_residuals": balances, "contact_cases": contacts,
                      "maximum_added_contact_motion_mm": max(r["added_motion_norm_mm"] for r in contacts),
                      "maximum_root_gain_contact_error_n": max(abs(r["apparent_force_from_root_fz_gain_n"]-20) for r in contacts),
                      "input_sha256": {str(p.relative_to(ROOT)): digest(p) for p in inputs},
                      "mesh_sha256": digest(folder / "mesh.inp"), "solver_deck_sha256": digest(folder / "fb1.inp"),
                      "tools": tool_manifest, "rigid_patch_node_counts": {n: len(v) for n, v in selected.items()},
                      "limits": ["Linear isotropic metals; leaf and backing clamps are perfectly bonded. Screw preload, slip and contact separation are omitted.",
                                 "The sensor/PCB contact patch and plunger-thread bore are rigid local regions. The normal-only spring uses an assumed sensor compliance.",
                                 "The original finger is a rigid lever. Reported motion is adapter addition, not total original-finger deflection.",
                                 "The 2 N preload is assumed. Local stress peaks are mesh-dependent; no strength, buckling, fatigue or overforce rating follows.",
                                 "Stops remain open in this linear solve. Loaded gaps, numerical convergence and physical qualification are separate."]}
            (folder / "report.json").write_text(json.dumps(result, indent=2)+"\n")
            record["result"] = {"directory": str(folder.relative_to(ROOT)), "nodes": mesh_info["nodes"],
                                "maximum_added_contact_motion_mm": result["maximum_added_contact_motion_mm"],
                                "maximum_root_gain_contact_error_n": result["maximum_root_gain_contact_error_n"],
                                "reciprocity_relative_error": symmetry}
            print(json.dumps(record["result"], indent=2))
        finally:
            if gmsh.isInitialized():
                gmsh.finalize()


if __name__ == "__main__":
    main()
