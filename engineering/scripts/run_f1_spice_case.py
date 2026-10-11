#!/usr/bin/python3
"""Run one saved F1 circuit study in an isolated synchronous ngspice worker."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_spice import Spice, LIBRARY, CODE_MODELS


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("--output", type=Path, help="New result directory for replaying a saved case")
    parser.add_argument("--model", type=Path, help="Same-hash vendor model in a newly prepared F1 cache")
    args = parser.parse_args()
    case_path = args.case.resolve()
    if not case_path.is_relative_to(ROOT):
        parser.error("Use a repository-owned circuit case")
    case = json.loads(case_path.read_text())
    if args.output:
        output = args.output.resolve()
    elif case_path.is_relative_to(ROOT / "build"):
        output = case_path.parent / "output"
    else:
        output = (ROOT / "build/engineering/prototypes/f1/case_replays"
                  / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") / case_path.parent.name)
    if not output.is_relative_to(ROOT / "build"):
        parser.error("Keep generated case results inside the repository build tree")
    with execution(ROOT / "build/records", "Run one explicit F1 circuit/model case with no hardware access") as record:
        output.mkdir(parents=True, exist_ok=False)
        netlist_path = case_path.parent / case["netlist"]
        if not netlist_path.resolve().is_relative_to(case_path.parent):
            raise ValueError("Circuit must be in its case directory")
        netlist = netlist_path.read_text().splitlines()
        inputs = {"case": digest(case_path), "netlist": digest(netlist_path),
                  "worker": digest(Path(__file__)), "interface": digest(ROOT / "engineering/scripts/f1_spice.py"),
                  "ngspice_library": digest(LIBRARY)}
        inputs["code_models"] = {str(path.relative_to(ROOT)): digest(path) for path in CODE_MODELS}
        model_lines = []
        if case.get("vendor_model"):
            model_path = args.model.resolve() if args.model else ROOT / case["vendor_model"]["path"]
            if not model_path.resolve().is_relative_to(ROOT / "build/engineering/prototypes/f1/model_sources"):
                raise ValueError("Select a model from the bounded F1 review cache")
            model = model_path.read_text()
            if digest(model_path) != case["vendor_model"]["sha256"]:
                raise ValueError("Vendor model differs from its reviewed revision")
            if any(line.lstrip().lower().startswith((".include", ".inc ", ".lib ", ".control", ".endc"))
                   for line in model.splitlines()):
                raise ValueError("Unexpected external file/control directive in vendor model")
            inputs["vendor_model"] = digest(model_path)
            model_lines = model.splitlines()
            netlist = netlist[:1] + model_lines + netlist[1:]
        simulator = Spice(output / "ngspice.log")
        if case.get("pspice_compatibility", False):
            # The model is supplied inline through the C interface. PSA
            # translates the complete deck; PS only translates include files.
            simulator.command("set ngbehavior=psa")
        simulator.circuit(netlist)
        if case.get("matrix_solver") == "klu":
            simulator.command("option klu")
        results = {}
        operations = []
        for analysis in case["analyses"]:
            if analysis.get("action") == "load_netlist":
                relative = analysis["netlist"]
                next_path = (case_path.parent / relative).resolve()
                if not next_path.is_relative_to(case_path.parent):
                    raise ValueError("Additional circuit must remain in its case directory")
                expected = case.get("additional_netlist_hashes", {}).get(relative)
                if expected != digest(next_path):
                    raise ValueError("Additional circuit differs from its recorded source")
                next_deck = next_path.read_text().splitlines()
                netlist = next_deck[:1]+model_lines+next_deck[1:]
                simulator.command("destroy all")
                simulator.command("remcirc")
                simulator.circuit(netlist)
                if case.get("matrix_solver") == "klu":
                    simulator.command("option klu")
                inputs.setdefault("additional_netlists", {})[relative] = digest(next_path)
                operations.append({"load_netlist": relative})
                continue
            if analysis.get("action") == "set_dc":
                source = analysis["source"]
                value = float(analysis["value"])
                if not re.fullmatch(r"[vi][a-z0-9_]+", source) or not math.isfinite(value) or abs(value) > 10:
                    raise ValueError("Unexpected DC source update")
                simulator.command(f"alter @{source}[dc] = {value:.17g}")
                operations.append({"source": source, "dc_value": value})
                continue
            command = analysis["command"]
            # Commands are analysis-only, with numeric values and circuit names.
            if not re.fullmatch(r"(?:op|(?:ac|tran|dc) [A-Za-z0-9_.:+\- ]+)", command):
                raise ValueError("Unexpected simulator command")
            seed = analysis["name"] == "park_release_dc" and case.get("bias_seed_mode", "nodeset") == "nodeset"
            if seed:
                simulator.command("save all")
            simulator.command(command)
            plot = simulator.lib.ngSpice_CurPlot().decode("ascii")
            kind = command.split()[0]
            if not plot.startswith(kind):
                raise RuntimeError(f"Analysis did not create its expected plot: {kind}/{plot}")
            vectors = {}
            for name in analysis["vectors"]:
                values = simulator.vector(name)
                if kind == "op" and len(values) != 1:
                    raise ValueError("Operating-point analysis did not return one solved point")
                is_complex = any(isinstance(value, complex) for value in values)
                vectors[name] = {"complex": is_complex, "values": (
                    [[value.real, value.imag] for value in values] if is_complex else values)}
            words = command.split()
            if kind == "tran":
                times = simulator.vector("time")
                if times[-1] < float(words[2])*(1-1e-9):
                    raise RuntimeError(f"Transient stopped before its requested endpoint: {times[-1]}/{words[2]}")
            if kind == "ac":
                frequencies = simulator.vector("frequency")
                last = frequencies[-1].real if isinstance(frequencies[-1], complex) else frequencies[-1]
                if abs(last/float(words[4])-1) > 1e-6:
                    raise RuntimeError("AC analysis did not reach its requested final frequency")
            results[analysis["name"]] = vectors
            print("Completed", analysis["name"], flush=True)
            if seed:
                state = simulator.voltage_state()
                if len(state) < 50 or not any(name.startswith("xamp.") for name in state):
                    raise ValueError("Continuation did not retain the amplifier's internal voltages")
                # A subsequent OP/AC command otherwise starts the nonlinear
                # macromodel from a fresh cold guess. Seed it with its own
                # solved open-park equilibrium; NODESET is released by ngspice.
                # This does not clamp the final solution or alter components.
                nodesets = [f".nodeset v({name})={value:.17g}"
                            for name, value in sorted(state.items())
                            if name not in ("park_ctl", "test_ctl")]
                (output / "continuation_state.json").write_text(json.dumps(state, indent=2)+"\n")
                (output / "derived_nodeset.cir").write_text("\n".join(nodesets)+"\n")
                inputs["continuation_state"] = digest(output / "continuation_state.json")
                inputs["derived_nodeset"] = digest(output / "derived_nodeset.cir")
                simulator.command("destroy all")
                simulator.command("remcirc")
                simulator.circuit(netlist[:-1]+nodesets+netlist[-1:])
                # KLU cannot create the extra diagonal entries required by
                # NODESET on ideal-source nodes. Sparse 1.3 supports this
                # initialization without adding shunt elements to the circuit.
                simulator.command("option sparse")
                inputs["seeded_analysis_solver"] = "Sparse 1.3"
        simulator.close()
        derived = {}
        for name, sources in case.get("endpoint_results", {}).items():
            common = set.intersection(*(set(results[source]) for source in sources))
            combined = {}
            for vector_name in sorted(common):
                data = [results[source][vector_name] for source in sources]
                if any(item["complex"] or not item["values"] for item in data):
                    raise ValueError("Endpoint collection requires real DC vectors")
                combined[vector_name] = {"complex": False, "values": [item["values"][-1] for item in data]}
            results[name] = combined
            derived[name] = {"last_point_of": sources}
        for alias, source in case.get("result_aliases", {}).items():
            results[alias] = results[source]
            derived[alias] = {"alias_of": source}
        report = {"schema": "yam-f1-spice-case/1", "status": "simulation_completed",
                  "input_hashes": inputs, "results": results,
                  "source_updates": operations, "derived_results": derived,
                  "physical_evidence": False, "model_is_a_hardware_guarantee": False}
        (output / "results.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"output": str(output.relative_to(ROOT)), "analyses": list(results),
                            "input_hashes": inputs}


if __name__ == "__main__":
    main()
