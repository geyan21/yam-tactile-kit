#!/usr/bin/python3
"""Screen the actual metal nail and its supports under finite contact patches."""

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
os.environ["OPENBLAS_NUM_THREADS"]="1"
os.environ["OMP_NUM_THREADS"]="1"
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import numpy as np
from structural_tools import tools,digest,write_set,run_solver,parse_node_tables
from tactile_kit.records import execution

OUTPUT=ROOT/"build/engineering/prototypes/nail"
SITES=[("left_tip",[-3.8,-10.5]),("right_tip",[3.8,-10.5]),
       ("left_shoulder",[-7,-1]),("right_shoulder",[7,-1]),("rear_center",[0,5])]


def pressure_patch(gmsh,tags,xyz,origin,axes,center,radius):
    """Consistent quadratic-surface loads from a fixed physical disk quadrature."""
    by_id={int(tag):index for index,tag in enumerate(tags)}
    radial,weights=np.polynomial.legendre.leggauss(5)
    nodal={}
    for t,radial_weight in zip((radial+1)/2,weights/2):
        r=radius*np.sqrt(t)
        for index in range(32):
            theta=2*np.pi*(index+.5)/32
            local=np.r_[np.asarray(center)+r*np.array([np.cos(theta),np.sin(theta)]),0.]
            point=origin+local@axes
            _,kind,node_tags,u,v,w=gmsh.model.mesh.getElementByCoordinates(*point,dim=2,strict=True)
            if kind!=9:
                raise ValueError("Nail pressure point is not in a quadratic surface triangle")
            components,values,orientations=gmsh.model.mesh.getBasisFunctions(kind,[u,v,w],"Lagrange")
            values=np.asarray(values)
            coordinates=np.asarray([xyz[by_id[int(tag)]] for tag in node_tags])
            if components!=1 or orientations!=1 or len(values)!=len(node_tags):
                raise ValueError("Unexpected surface interpolation basis")
            if abs(values.sum()-1)>1e-8 or np.linalg.norm(values@coordinates-point)>1e-6:
                raise ValueError("Pressure interpolation does not reproduce position and unit load")
            for tag,value in zip(node_tags,values*radial_weight/32):
                nodal[int(tag)]=nodal.get(int(tag),0.)+float(value)
    target=origin+np.r_[center,0.]@axes
    centroid=sum((xyz[by_id[tag]]*value for tag,value in nodal.items()),np.zeros(3))
    if abs(sum(nodal.values())-1)>1e-8 or np.linalg.norm(centroid-target)>1e-6:
        raise ValueError("Pressure patch changed its resultant or moment")
    return {"node_weights":nodal,"centroid_native_mm":centroid.tolist(),
            "radius_mm":radius,"quadrature_points":160}


def stresses(path,expected):
    tables=[];current=None
    with path.open() as stream:
        for line in stream:
            text=line.strip();lower=text.lower()
            if lower.startswith("stresses ") and "for set" in lower and "time" in lower:
                current=[];tables.append(current);continue
            if not text:
                continue
            fields=text.split()
            if current is not None and len(fields)==8 and fields[0].isdigit() and fields[1].isdigit():
                current.append([float(value.replace("D","E").replace("d","e")) for value in fields[2:]])
            else:
                current=None
    if len(tables)!=expected or any(not table for table in tables):
        raise ValueError("Missing integration-point stress output")
    return [np.asarray(table) for table in tables]


def von_mises(stress):
    x,y,z,xy,xz,yz=stress.T
    return np.sqrt(((x-y)**2+(y-z)**2+(z-x)**2)/2+3*(xy*xy+xz*xz+yz*yz))


def refinement_boxes(config,plan,origin,axes,size,local_size):
    n=config["nail"];result=[]
    for center in n["web_native_x_centers_mm"]:
        x=center-origin[0]
        bounds=[[x-n["web_thickness_mm"]/2-.1,x+n["web_thickness_mm"]/2+.1],
                [n["web_free_end_local_y_mm"]-1,n["web_fixed_boundary_local_y_mm"]+1],
                [n["web_lower_local_z_mm"]-1,n["web_lower_local_z_mm"]+n["web_height_mm"]+1]]
        corners=np.array([[a,b,c] for a in bounds[0] for b in bounds[1] for c in bounds[2]])@axes+origin
        low,high=corners.min(axis=0),corners.max(axis=0)
        result.append(dict(zip(("XMin","YMin","ZMin"),map(float,low)))|
                      dict(zip(("XMax","YMax","ZMax"),map(float,high)))|
                      {"VIn":local_size,"VOut":size,"Thickness":1})
    # Resolve the thin leading prongs as well as the webs. The rest of the
    # carriers retain the declared global mesh scale.
    corners=np.array([[x,y,z] for x in (-6.5,6.5) for y in (-12.3,-7.5) for z in (-.1,3)])@axes+origin
    low,high=corners.min(axis=0),corners.max(axis=0)
    result.append(dict(zip(("XMin","YMin","ZMin"),map(float,low)))|
                  dict(zip(("XMax","YMax","ZMax"),map(float,high)))|
                  {"VIn":local_size,"VOut":size,"Thickness":1})
    return result


def create_reviewed_mesh(folder,record,size,local_size,boxes,optimizer):
    request={"global_mm":size,"local_mm":local_size,"refinements":boxes,"optimizer":optimizer}
    (folder/"inputs/mesh_request.json").write_text(json.dumps(request,indent=2)+"\n")
    worker=ROOT/"engineering/scripts/nail_mesh_worker.py"
    shutil.copyfile(worker,folder/"inputs/nail_mesh_worker.py")
    argv=[sys.executable,str(worker),str(folder)]
    started=time.monotonic()
    with (folder/"mesh_worker.log").open("x") as stream:
        process=subprocess.Popen(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        entry={"argv":argv,"pid":process.pid,"log":str((folder/"mesh_worker.log").relative_to(ROOT))}
        record["mesh_worker"]=entry
        try:
            code=process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            record["intentional_stop_requests"].append(f"Stop this run's mesh worker PID {process.pid}: 180 s limit")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)
            raise
    entry.update({"returncode":code,"elapsed_s":time.monotonic()-started})
    if code:
        raise RuntimeError("N1 mesher failed; preserved log:\n"+(folder/"mesh_worker.log").read_text()[-4500:])
    return json.loads((folder/"mesh_metadata.json").read_text())


def analyze(folder,cfg,plan,tags,xyz,cases,patches,tip_nodes):
    tables=parse_node_tables(folder/"nail.dat")
    displacements=[table for table in tables if table["kind"]=="U"]
    reactions=[table for table in tables if table["kind"]=="RF"]
    if len(displacements)!=len(cases) or len(reactions)!=len(cases):
        raise ValueError("Incomplete nail solver output")
    stress=stresses(folder/"nail.dat",len(cases))
    by_id={int(tag):index for index,tag in enumerate(tags)}
    reference=np.array([-7.5,-75.26417028511005,0.])
    rows=[]
    for case,u,rf,sigma in zip(cases,displacements,reactions,stress):
        if any(int(tag) not in u["rows"] for tag in tags):
            raise ValueError("Missing nail nodal displacements")
        forces={int(tag):np.asarray(value) for tag,value in case["nodal_forces"].items()}
        applied=sum(forces.values(),np.zeros(3))
        applied_moment=sum((np.cross(xyz[by_id[tag]]-reference,value) for tag,value in forces.items()),np.zeros(3))
        reaction=sum((np.asarray(value) for value in rf["rows"].values()),np.zeros(3))
        moment=sum((np.cross(xyz[by_id[tag]]-reference,value) for tag,value in rf["rows"].items()),np.zeros(3))
        force_error=float(np.linalg.norm(applied+reaction))
        moment_error=float(np.linalg.norm(applied_moment+moment))
        if force_error>.002 or moment_error>.2:
            raise ValueError("Nail force/moment equilibrium failed")
        tip=np.array([u["rows"][int(tag)] for tag in tip_nodes])
        patch_motion={}
        for name,patch in patches.items():
            patch_motion[name]=sum((np.asarray(u["rows"][tag])*weight
                                   for tag,weight in patch["node_weights"].items()),np.zeros(3)).tolist()
        vm=von_mises(sigma)
        rows.append({"id":case["id"],"kind":case["kind"],"applied_force_native_n":applied.tolist(),
                     "moment_about_reference_nmm":applied_moment.tolist(),
                     "reaction_force_residual_n":force_error,"reaction_moment_residual_nmm":moment_error,
                     "max_leading_tip_normal_motion_mm":float(np.max(np.abs(tip[:,2]))),
                     "max_leading_tip_motion_magnitude_mm":float(np.max(np.linalg.norm(tip,axis=1))),
                     "patch_mean_displacement_native_mm":patch_motion,
                     "max_integration_point_von_mises_mpa":float(np.max(vm)),
                     "p99_integration_point_von_mises_mpa":float(np.percentile(vm,99))})
    normal=[row for row in rows if row["kind"]=="normal_20n"]
    maximum=max(row["max_leading_tip_normal_motion_mm"] for row in normal)
    return {"schema":"yam-nail-structural-screen/1","evidence_kind":"linear_FEA_screen_only",
            "physical_specimens_tested":0,"force_accuracy_qualified":False,
            "max_leading_tip_normal_motion_mm_at_20n":maximum,
            "provisional_motion_target_mm":cfg["structural_screen"]["provisional_tip_motion_target_mm_at_20n"],
            "motion_screen_met":maximum<=cfg["structural_screen"]["provisional_tip_motion_target_mm_at_20n"],
            "cases":rows,"reference_native_xyz_mm":reference.tolist(),
            "scope":"Metal nail plus ideal bonded carriers, including the actual thin leading prongs. Printed frame and real clamp compliance are omitted.",
            "limits":cfg["structural_screen"]["limits"]+[
                "Contact loads use fixed physical disk quadrature and quadratic surface interpolation. Stress peaks do not establish strength or fatigue allowables.",
                "No internal foil-grid coordinates or physical bridge calibration are supplied by this structural screen.",
                "The off-axis 5 N and equal/opposite loading cases are additional modeling scenarios, not user-specified force ratings."]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh-mm",type=float,default=1.5)
    parser.add_argument("--web-mm",type=float,default=.7)
    parser.add_argument("--solve-timeout",type=int,default=600)
    parser.add_argument("--mesh-optimizer",choices=("direct","elastic","elastic-direct"),default="elastic-direct")
    args=parser.parse_args()
    if not .5<=args.mesh_mm<=3 or not .35<=args.web_mm<=args.mesh_mm or not 30<=args.solve_timeout<=900:
        parser.error("Use bounded mesh sizes and a 30..900 s solver limit")
    cfg=json.loads((ROOT/"engineering/designs/nail.json").read_text())
    plan=json.loads((OUTPUT/"nail_manifest.json").read_text())
    for name,expected in plan["source_hashes"].items():
        if digest(ROOT/name)!=expected:
            raise ValueError("Nail geometry source changed: "+name)
    geometry=OUTPUT/plan["analysis_step"]
    if digest(geometry)!=plan["analysis_step_sha256"]:
        raise ValueError("Nail analysis STEP changed")
    parent=OUTPUT/"fea"/f"mesh_{str(args.mesh_mm).replace('.','p')}_web_{str(args.web_mm).replace('.','p')}"
    folder=parent/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT/"build/records","Screen the new nail and its actual leading prongs with consistent finite contact patches; preserve all inputs and exclude physical-accuracy claims") as record:
        folder.mkdir(parents=True,exist_ok=False)
        inputs=folder/"inputs";inputs.mkdir()
        sources={"configuration.json":ROOT/"engineering/designs/nail.json",
                 "assembly_manifest.json":OUTPUT/"nail_manifest.json","analysis.step":geometry,
                 "run_nail_fea.py":Path(__file__),"structural_tools.py":ROOT/"engineering/scripts/structural_tools.py",
                 "tools.json":ROOT/"build/engineering/tools/fea/tools.json"}
        for name,path in sources.items():
            shutil.copyfile(path,inputs/name)
        gmsh,binary,tool_manifest=tools()
        origin=np.asarray(plan["nail_plane_origin_native_mm"])
        axes=np.asarray(plan["nail_plane_axes_native"])
        try:
            boxes=refinement_boxes(cfg,plan,origin,axes,args.mesh_mm,args.web_mm)
            mesh=create_reviewed_mesh(folder,record,args.mesh_mm,args.web_mm,boxes,args.mesh_optimizer)
            gmsh.initialize([],readConfigFiles=False,run=False)
            gmsh.option.setNumber("General.Terminal",0)
            gmsh.option.setNumber("General.NumThreads",1)
            gmsh.open(str(folder/"mesh.msh"))
            all_tags,coordinates,_=gmsh.model.mesh.getNodes()
            coordinates=np.asarray(coordinates).reshape(-1,3)
            _,_,connectivity=gmsh.model.mesh.getElements(3)
            used=np.unique(np.concatenate(connectivity))
            selected=np.isin(all_tags,used)
            tags=np.asarray(all_tags,dtype=np.int64)[selected]
            xyz=coordinates[selected]
            fixed=set()
            for mount in plan["mounts"]:
                y,z=mount["center_native_yz_mm"]
                on=np.abs(xyz[:,0]-mount["contact_plane_x_mm"])<1e-5
                on&=np.hypot(xyz[:,1]-y,xyz[:,2]-z)<=cfg["mount"]["post_radius_mm"]+1e-5
                selected=tags[on]
                if len(selected)<6:
                    raise ValueError("A nail support face has too few mesh nodes")
                fixed.update(map(int,selected))
            local=(xyz-origin)@axes.T
            tip_nodes=tags[(np.abs(local[:,2])<1e-5)&(local[:,1]<-7.5)]
            if len(tip_nodes)<12:
                raise ValueError("Thin leading-prong mesh is incomplete")
            patches={name:pressure_patch(gmsh,tags,xyz,origin,axes,point,
                                        cfg["structural_screen"]["nominal_contact_patch_radius_mm"])
                     for name,point in SITES}
            cases=[]
            for name,patch in patches.items():
                cases.append({"id":name+"_20n","kind":"normal_20n",
                              "nodal_forces":{tag:[0,0,20*weight] for tag,weight in patch["node_weights"].items()}})
            for axis in (0,1):
                direction=np.eye(3)[axis]*5
                cases.append({"id":("Fx","Fy")[axis]+"_5n","kind":"off_axis_scenario",
                              "nodal_forces":{tag:(direction*weight).tolist() for tag,weight in patches["rear_center"]["node_weights"].items()}})
            torque={}
            for name,sign in (("left_tip",1),("right_tip",-1)):
                for tag,weight in patches[name]["node_weights"].items():
                    torque.setdefault(tag,[0,0,0])[2]+=sign*10*weight
            cases.append({"id":"opposed_tip_forces","kind":"zero_net_force_scenario","nodal_forces":torque})
            lines=["** Nail metal assembly; N, mm, MPa\n*INCLUDE,INPUT=mesh.inp\n",
                   write_set("ALL",tags),write_set("SUPPORT",sorted(fixed)),
                   "*MATERIAL,NAME=STEEL\n*ELASTIC\n",
                   f'{cfg["nail"]["elastic_modulus_mpa_assumed"]:.9g},{cfg["nail"]["poisson_ratio_assumed"]:.9g}\n',
                   "*SOLID SECTION,ELSET=SOLID,MATERIAL=STEEL\n*BOUNDARY\nSUPPORT,1,3\n"]
            for case in cases:
                lines+=["*STEP\n*STATIC\n1,1\n*CLOAD,OP=NEW\n"]
                for tag,force in case["nodal_forces"].items():
                    for axis,value in enumerate(force,1):
                        if abs(value)>1e-14:
                            lines.append(f"{tag},{axis},{value:.12g}\n")
                lines+=["*NODE PRINT,NSET=ALL\nU\n*NODE PRINT,NSET=SUPPORT\nRF\n",
                        "*EL PRINT,ELSET=SOLID\nS\n*END STEP\n"]
            (folder/"nail.inp").write_text("".join(lines))
            (inputs/"contact_patches.json").write_text(json.dumps(patches,indent=2)+"\n")
            (inputs/"loads.json").write_text(json.dumps(cases,indent=2)+"\n")
            print(json.dumps({"mesh":mesh,"fixed_nodes":len(fixed),"tip_face_nodes":len(tip_nodes),"load_cases":len(cases)}),flush=True)
            run_solver(binary,folder,"nail",record,timeout=args.solve_timeout)
            result=analyze(folder,cfg,plan,tags,xyz,cases,patches,tip_nodes)
            result["mesh"]=mesh
            result["patches"]={name:{key:value for key,value in patch.items() if key!="node_weights"}
                               for name,patch in patches.items()}
            result["source_hashes"]={str(path.relative_to(ROOT)):digest(path) for path in
                                     (Path(__file__),ROOT/"engineering/scripts/structural_tools.py",
                                      ROOT/"engineering/scripts/nail_mesh_worker.py",
                                      ROOT/"engineering/designs/nail.json",OUTPUT/"nail_manifest.json")}
            result["tools"]=tool_manifest
            (folder/"screen.json").write_text(json.dumps(result,indent=2)+"\n")
            (parent/"latest.json").write_text(json.dumps({"directory":folder.name,"screen_sha256":digest(folder/"screen.json")},indent=2)+"\n")
            record["result"]={"directory":str(folder.relative_to(ROOT)),
                              "max_tip_motion_mm_at_20n":result["max_leading_tip_normal_motion_mm_at_20n"],
                              "motion_screen_met":result["motion_screen_met"]}
            print(json.dumps(record["result"],indent=2))
        finally:
            if gmsh.isInitialized():
                gmsh.finalize()


if __name__=="__main__":
    main()
