"""Small synchronous interface to the ngspice library bundled with KiCad.

The C interface follows ngspice's published sharedspice.h. Circuit simulation
is run in a separate owned worker, with time limits set by its caller.
"""

import ctypes as ct
import math
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "build/engineering/tools/b1-kicad/AppDir/shared/lib/libngspice.so.0.0.14"
CODE_MODELS = [LIBRARY.parent / "ngspice" / (name + ".cm")
               for name in ("analog", "table", "spice2poly", "xtradev")]


class ComplexValue(ct.Structure):
    _fields_ = [("real", ct.c_double), ("imag", ct.c_double)]


class VectorInfo(ct.Structure):
    _fields_ = [
        ("name", ct.c_char_p), ("type", ct.c_int), ("flags", ct.c_short),
        ("realdata", ct.POINTER(ct.c_double)),
        ("complexdata", ct.POINTER(ComplexValue)), ("length", ct.c_int)
    ]


class Spice:
    """One synchronous ngspice instance per worker process."""

    def __init__(self, log_path):
        # Use an owned startup directory. Circuit options and the required
        # bundled code-model libraries are loaded explicitly below.
        os.environ["SPICE_SCRIPTS"] = str(Path(log_path).resolve().parent / "init")
        Path(os.environ["SPICE_SCRIPTS"]).mkdir(parents=True, exist_ok=True)
        (Path(os.environ["SPICE_SCRIPTS"]) / "spinit").write_text(
            "* F1 simulation worker: options and bundled code models are explicit inputs.\n")
        self.log = Path(log_path).open("w")
        self.exits = []
        self.messages = []
        self.lib = ct.CDLL(str(LIBRARY))
        send = ct.CFUNCTYPE(ct.c_int, ct.c_char_p, ct.c_int, ct.c_void_p)
        exit_type = ct.CFUNCTYPE(ct.c_int, ct.c_int, ct.c_bool, ct.c_bool, ct.c_int, ct.c_void_p)

        @send
        def output(message, ident, user):
            if message:
                line = message.decode("utf-8", errors="replace")
                self.messages.append(line)
                self.log.write(line+"\n")
                self.log.flush()
            return 0

        @send
        def status(message, ident, user):
            return 0

        @exit_type
        def exited(code, immediate, quit_requested, ident, user):
            self.exits.append({"code": code, "immediate": immediate, "quit_requested": quit_requested})
            return 0

        self.callbacks = (output, status, exited)
        self.lib.ngSpice_Init.argtypes = [send, send, exit_type, ct.c_void_p, ct.c_void_p, ct.c_void_p, ct.c_void_p]
        self.lib.ngSpice_Init.restype = ct.c_int
        self.lib.ngSpice_Command.argtypes = [ct.c_char_p]
        self.lib.ngSpice_Command.restype = ct.c_int
        self.lib.ngSpice_Circ.argtypes = [ct.POINTER(ct.c_char_p)]
        self.lib.ngSpice_Circ.restype = ct.c_int
        self.lib.ngGet_Vec_Info.argtypes = [ct.c_char_p]
        self.lib.ngGet_Vec_Info.restype = ct.POINTER(VectorInfo)
        self.lib.ngSpice_CurPlot.argtypes = []
        self.lib.ngSpice_CurPlot.restype = ct.c_char_p
        self.lib.ngSpice_AllVecs.argtypes = [ct.c_char_p]
        self.lib.ngSpice_AllVecs.restype = ct.POINTER(ct.c_char_p)
        if self.lib.ngSpice_Init(output, status, exited, None, None, None, None):
            raise RuntimeError("ngspice initialization failed")
        self.command("version")
        self.command("set noaskquit")
        self.command("set nomoremode")
        for model in CODE_MODELS:
            if any(char.isspace() for char in str(model)):
                raise ValueError("Prepared code-model path needs a whitespace-free workspace")
            self.command(f"codemodel {model}")

    def command(self, text):
        previous = len(self.messages)
        result = self.lib.ngSpice_Command(text.encode("ascii"))
        errors = [line for line in self.messages[previous:]
                  if re.match(r"(?:stderr|stdout)\s+(?:error|fatal|doAnalyses:)", line, re.IGNORECASE)
                  or "simulation(s) aborted" in line.lower()]
        if result or self.exits or errors:
            raise RuntimeError(f"ngspice command failed: {text}; result {result}; exits {self.exits}; {errors[:3]}")

    def circuit(self, lines):
        # No interactive control blocks or shell/system commands are accepted
        # here. All analysis commands are fixed by the reviewed worker.
        forbidden = (".control", ".endc", ".shell", "shell ", "cd ", "source ")
        if any(line.lstrip().lower().startswith(forbidden) for line in lines):
            raise ValueError("Unexpected control command in circuit input")
        strings = [line.encode("ascii") for line in lines]
        buffer = (ct.c_char_p*(len(strings)+1))(*strings, None)
        previous = len(self.messages)
        result = self.lib.ngSpice_Circ(buffer)
        errors = [line for line in self.messages[previous:]
                  if re.match(r"(?:stderr|stdout)\s+(?:error|fatal)", line, re.IGNORECASE)]
        if result or self.exits or errors:
            raise RuntimeError(f"ngspice circuit load failed: {result}; exits {self.exits}; {errors[:3]}")

    def vector(self, name):
        pointer = self.lib.ngGet_Vec_Info(name.encode("ascii"))
        if not pointer:
            raise ValueError(f"Missing simulation vector: {name}")
        data = pointer.contents
        if not 0 < data.length <= 1000000:
            raise ValueError(f"Unexpected vector length: {name}/{data.length}")
        if data.realdata:
            return [data.realdata[i] for i in range(data.length)]
        if data.complexdata:
            return [complex(data.complexdata[i].real, data.complexdata[i].imag) for i in range(data.length)]
        raise ValueError(f"No data for {name}")

    def voltage_state(self, reference_node="output"):
        """Copy final node voltages from the active plot for a NODESET seed."""
        voltage_type = self.lib.ngGet_Vec_Info(reference_node.encode("ascii")).contents.type
        names = self.lib.ngSpice_AllVecs(self.lib.ngSpice_CurPlot())
        if not names:
            raise ValueError("No plot vectors for the continuation state")
        state = {}
        index = 0
        while names[index]:
            name = names[index].decode("ascii")
            info = self.lib.ngGet_Vec_Info(name.encode("ascii")).contents
            if (info.type == voltage_type and info.realdata and info.length
                    and name not in ("v-sweep", "i-sweep", "frequency", "time")):
                value = float(info.realdata[info.length-1])
                if not math.isfinite(value):
                    raise ValueError("Nonfinite node voltage in continuation state")
                if not re.fullmatch(r"[A-Za-z0-9_.:+\-]+", name):
                    raise ValueError(f"Unexpected voltage node name: {name}")
                state[name] = value
            index += 1
            if index > 10000:
                raise ValueError("Unexpectedly large continuation state")
        return state

    def close(self):
        self.command("destroy all")
        self.log.close()
