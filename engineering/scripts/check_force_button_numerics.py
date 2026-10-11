#!/usr/bin/python3
"""Verify FB1 beam limiting cases and CalculiX's selected scalar spring element."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
from tactile_kit.records import execution
from force_button_mechanics import CONFIG, beam_end_matrix, guide, support_compliance
from structural_tools import tools, run_solver, parse_node_tables, digest


def main():
    folder = ROOT / "build/engineering/prototypes/force_button/numerical_checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check FB1 beam formulas against independent cantilever/energy limits and verify the exact SPRING2 force/displacement convention with CalculiX") as record:
        folder.mkdir(parents=True, exist_ok=False)
        cfg = json.loads(CONFIG.read_text()); m = cfg["mechanism"]
        length, width, thickness, young, poisson = 100., 8., .4, 200000., .3
        matrix = beam_end_matrix(length, width, thickness, young, poisson)
        displacement = np.linalg.solve(matrix, [0., 0., 1., 0., 0., 0.])
        inertia = width*thickness**3/12
        shear = young/(2*(1+poisson))
        expected = length**3/(3*young*inertia)+length/((5/6)*shear*width*thickness)
        beam_error = abs(displacement[2]/expected-1)
        active = m["sensor_support_active_length_mm"]; overhang = m["sensor_load_overhang_mm"]
        x = np.linspace(0, active, 100001)
        energy = (active+overhang-x)**2
        integral = np.sum((energy[1:]+energy[:-1])*.5*np.diff(x))
        backup_expected = integral/(m["sensor_support_young_mpa_assumed"]*m["sensor_support_width_mm"]*m["sensor_support_thickness_mm"]**3/12)
        backup_error = abs(support_compliance(cfg)[0]/backup_expected-1)
        stiffness, _ = guide(cfg)
        if beam_error > 1e-10 or backup_error > 1e-8 or max(abs(stiffness[2, 3:])) > 1e-7:
            raise ValueError("Independent analytical checks failed")
        _, binary, tool_manifest = tools()
        deck = """** Independent SPRING2 numerical check: 20 N / 10000 N/mm = 0.002 mm.
*NODE
1,0.,0.,0.
2,0.,0.,10.
*ELEMENT,TYPE=SPRING2,ELSET=SENSOR
1,1,2
*SPRING,ELSET=SENSOR
3,3
10000.
*NSET,NSET=OUTPUT
1,2
*NSET,NSET=SUPPORT
1
*BOUNDARY
1,1,3,0.
2,1,2,0.
*STEP
*STATIC
*CLOAD
2,3,20.
*NODE PRINT,NSET=OUTPUT
U
*NODE PRINT,NSET=SUPPORT
RF
*END STEP
"""
        (folder / "spring.inp").write_text(deck)
        run_solver(binary, folder, "spring", record, 45)
        tables = parse_node_tables(folder / "spring.dat")
        u = next(t["rows"] for t in tables if t["kind"] == "U")
        force = next(t["rows"] for t in tables if t["kind"] == "RF")
        if abs(u[2][2]-.002) > 1e-10 or abs(force[1][2]+20) > 1e-8:
            raise ValueError("Scalar spring solver check failed")
        result = {"schema": "yam-fb1-numerics/1", "physical_specimens_tested": 0, "passed": True,
                  "cantilever_relative_error": beam_error, "backup_energy_relative_error": backup_error,
                  "spring_displacement_mm": u[2][2], "spring_reaction_n": force[1][2],
                  "tools": tool_manifest, "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in (
                      Path(__file__), CONFIG, ROOT / "engineering/scripts/force_button_mechanics.py",
                      ROOT / "engineering/scripts/structural_tools.py")},
                  "limits": "Checks formulas and solver conventions. Does not validate the assembled gripper or real sensor."}
        (folder / "report.json").write_text(json.dumps(result, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "passed": True,
                            "cantilever_relative_error": beam_error, "backup_energy_relative_error": backup_error}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
