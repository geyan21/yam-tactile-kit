#!/usr/bin/python3
"""Verify the prepared ngspice C interface with a known RC circuit."""

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_spice import Spice, LIBRARY


def main():
    folder = ROOT / "build/engineering/prototypes/f1/spice_probes" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Check the already prepared ngspice library on a known RC transfer function before using a vendor amplifier model") as record:
        folder.mkdir(parents=True, exist_ok=False)
        circuit = ["F1 ngspice interface control", "V1 in 0 dc 1 ac 1",
                   "R1 in out 1000", "C1 out 0 1n", ".end"]
        (folder / "rc.cir").write_text("\n".join(circuit)+"\n")
        simulator = Spice(folder / "ngspice.log")
        simulator.circuit(circuit)
        simulator.command("ac dec 20 1 10000000")
        frequency = simulator.vector("frequency")
        actual = simulator.vector("out")
        maximum = 0.
        for frequency_hz, value in zip(frequency, actual):
            f = frequency_hz.real if isinstance(frequency_hz, complex) else frequency_hz
            expected = 1/(1+2j*math.pi*f*1000*1e-9)
            maximum = max(maximum, abs(value-expected)/abs(expected))
        if maximum > 1e-8:
            raise ValueError(f"RC check failed: {maximum}")
        simulator.close()
        report = {"schema": "yam-f1-spice-interface-probe/1", "passed": True,
                  "maximum_relative_error": maximum, "physical_evidence": False,
                  "library": str(LIBRARY.relative_to(ROOT)),
                  "library_sha256": hashlib.sha256(LIBRARY.read_bytes()).hexdigest(),
                  "interface_sha256": hashlib.sha256((ROOT / "engineering/scripts/f1_spice.py").read_bytes()).hexdigest()}
        (folder / "probe.json").write_text(json.dumps(report, indent=2)+"\n")
        record["probe"] = report
        print(json.dumps({"directory": str(folder.relative_to(ROOT)), **report}, indent=2))


if __name__ == "__main__":
    main()
