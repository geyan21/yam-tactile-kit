#!/usr/bin/python3
"""Check translated resistor/switch primitives under shifted common modes."""

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_spice import Spice, LIBRARY, CODE_MODELS


def main():
    folder = ROOT / "build/engineering/prototypes/f1/primitive_probes" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Isolate the vendor model's translated resistor and switch primitives with equivalent voltage-reference fixtures") as record:
        folder.mkdir(parents=True, exist_ok=False)
        circuit = [
            "F1 reference-invariance controls for PSPICE primitives",
            "VTOPP top_p 0 3.3",
            "VTOPS top_s 0 1.65",
            "VBOTTOM bottom_s 0 -1.65",
            "VBIASP bias_p 0 1.65",
            "VCTRL control 0 0",
            "ECP cp bias_p control 0 1",
            "SP top_p out_p cp bias_p TS",
            "RP out_p 0 1000",
            "SS top_s out_s control 0 TS",
            "RS out_s bottom_s 1000",
            "SM top_s out_m cp bias_p TS",
            "RM out_m bottom_s 1000",
            ".model TS VSWITCH RON=10m ROFF=1e12 VON=10m VOFF=0",
            "RNP top_p divider_p RN 1000",
            "RLP divider_p 0 1000",
            "RNS top_s divider_s RN 1000",
            "RLS divider_s bottom_s 1000",
            ".model RN RES(T_ABS=-273.15)",
            ".save out_p out_s out_m divider_p divider_s control",
            ".end"
        ]
        (folder / "primitives.cir").write_text("\n".join(circuit)+"\n")
        simulator = Spice(folder / "ngspice.log")
        simulator.command("set ngbehavior=psa")
        simulator.circuit(circuit)
        simulator.command("option klu")
        simulator.command("dc vctrl 0 .01 .001")
        controls = simulator.vector("control")
        positive = simulator.vector("out_p")
        symmetric = [value+1.65 for value in simulator.vector("out_s")]
        mixed = [value+1.65 for value in simulator.vector("out_m")]
        rp = simulator.vector("divider_p"); rs = simulator.vector("divider_s")
        simulator.close()
        delta_s = max(abs(a-b) for a, b in zip(positive, symmetric))
        delta_m = max(abs(a-b) for a, b in zip(positive, mixed))
        resistor_error = max(max(abs(v-1.65) for v in rp), max(abs(v) for v in rs))
        with (folder / "values.csv").open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["control_difference_v", "positive_fixture_output_v",
                             "symmetric_fixture_translated_v", "mixed_fixture_translated_v"])
            writer.writerows(zip(controls, positive, symmetric, mixed))
        result = {
            "schema": "yam-f1-spice-primitive-reference-probe/1",
            "resistor_divider_maximum_error_v": resistor_error,
            "switch_control_and_signal_shift_difference_v": delta_s,
            "switch_signal_shift_difference_v": delta_m,
            "passed": resistor_error < 1e-8 and max(delta_s, delta_m) < 1e-7,
            "physical_evidence": False,
            "library_sha256": hashlib.sha256(LIBRARY.read_bytes()).hexdigest(),
            "code_model_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in CODE_MODELS}
        }
        (folder / "probe.json").write_text(json.dumps(result, indent=2)+"\n")
        record["probe"] = result
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), **result}, indent=2))
        if not result["passed"]:
            raise ValueError("The translated primitives differ between equivalent reference fixtures")


if __name__ == "__main__":
    main()
