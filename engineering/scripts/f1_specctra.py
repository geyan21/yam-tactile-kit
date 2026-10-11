#!/usr/bin/python3
"""Native KiCad export/import for a separate local F1 autorouting study."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from f1_native_pcb import digest, mm
import pcbnew as pcb


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "import"))
    parser.add_argument("board_directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--session", type=Path)
    parser.add_argument("--normalize-empty-component", action="store_true")
    args = parser.parse_args()
    source, output = args.board_directory.resolve(), args.output.resolve()
    if not source.is_relative_to(ROOT) or not output.is_relative_to(ROOT / "build"):
        parser.error("Use repository-owned source and generated output")
    if output.exists():
        parser.error("Use a fresh output folder")
    name = "f1_fanout_r2"
    pcb_path = source / (name+".kicad_pcb")
    manifest_path = source / (name+".json")
    manifest = json.loads(manifest_path.read_text())
    if digest(pcb_path) != manifest["pcb_sha256"]:
        raise ValueError("Source native board changed")
    with execution(ROOT / "build/records", "Exchange a verified F1 R2 native board with a local Specctra routing worker; preserve native pad/net identities and independent checking requirements") as record:
        output.mkdir(parents=True, exist_ok=False)
        for path in (pcb_path, manifest_path, Path(__file__)):
            shutil.copyfile(path, output / ("source_"+path.name))
        board = pcb.LoadBoard(str(pcb_path))
        if args.action == "export":
            default = board.GetDesignSettings().m_NetSettings.GetDefaultNetclass()
            default.SetClearance(pcb.FromMM(.15))
            default.SetTrackWidth(pcb.FromMM(.15))
            default.SetViaDiameter(pcb.FromMM(.45))
            default.SetViaDrill(pcb.FromMM(.2))
            target = output / "f1_fanout_r2.dsn"
            if not pcb.ExportSpecctraDSN(board, str(target)):
                raise RuntimeError("Native DSN export failed")
            report = {"schema": "yam-f1-specctra-export/1", "source_pcb_sha256": digest(pcb_path),
                      "dsn_sha256": digest(target), "kicad": pcb.GetBuildVersion(),
                      "source_manifest_sha256": digest(manifest_path),
                      "note": "Default 0.15 mm signal width/clearance, 0.45 mm via/0.20 mm drill. Per-row widths and fabrication acceptance require the recorded routing rules and independent checks."}
        else:
            if not args.session or not args.session.resolve().is_relative_to(ROOT / "build"):
                parser.error("Import requires a repository-owned generated session")
            session = args.session.resolve()
            raw_session_sha = digest(session)
            normalized_empty_component = False
            if args.normalize_empty_component:
                # Freerouting 2.5 emits an unquoted empty package identifier
                # for this export's two board-only mounting footprints.
                # Restore only that missing string token; preserve every
                # placement, pad, wire, via and obstacle coordinate.
                text = session.read_text()
                text, count = re.subn(r"\(component\s+(?=\(place H[12]\s)",
                                      '(component ""\n      ', text)
                if count != 1:
                    raise ValueError("Expected exactly one empty mounting-package token")
                native_mounts = {f.GetReference() for f in board.GetFootprints()
                                 if f.GetReference() in ("H1", "H2")}
                if native_mounts != {"H1", "H2"}:
                    raise ValueError("Mounting references differ from the reviewed empty package")
                shutil.copyfile(session, output / "original_session.ses")
                session = output / "normalized_session.ses"
                session.write_text(text)
                normalized_empty_component = True
            if not pcb.ImportSpecctraSES(board, str(session)):
                raise RuntimeError("Native SES import failed")
            tracks, vias = [], []
            for item in board.GetTracks():
                if isinstance(item, pcb.PCB_VIA):
                    diameters = [item.GetWidth(board.GetLayerID(layer))
                                 for layer in ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")]
                    if len(set(diameters)) != 1:
                        raise ValueError("Imported via has a nonuniform pad stack")
                    vias.append({"net": item.GetNetname(), "center": mm(item.GetPosition()),
                                 "diameter": pcb.ToMM(diameters[0]), "drill": pcb.ToMM(item.GetDrillValue())})
                elif isinstance(item, pcb.PCB_ARC):
                    raise ValueError("Do not silently approximate an imported arc")
                else:
                    tracks.append({"net": item.GetNetname(), "start": mm(item.GetStart()), "end": mm(item.GetEnd()),
                                   "width": pcb.ToMM(item.GetWidth()), "layer": board.GetLayerName(item.GetLayer())})
            native_pads = {(f.GetReference(), p.GetNumber()): p
                           for f in board.GetFootprints() for p in f.Pads()}
            pad_comparisons = []
            for pad in manifest["pads"]:
                actual = native_pads[(pad["reference"], pad["pad"])]
                delta = math.dist(mm(actual.GetPosition()), pad["center"])
                pad_comparisons.append({"reference": pad["reference"], "pad": pad["pad"],
                                        "position_delta_mm": delta, "net_preserved": actual.GetNetname() == pad["net"]})
            (output / "pad_correspondence.json").write_text(json.dumps(pad_comparisons, indent=2)+"\n")
            # The observed session declares 10 units per micrometre. Record
            # its bounded 0.1 µm placement quantization, then rebuild the final
            # PCB from the unchanged original specification.
            if not re.search(r"\(resolution\s+um\s+10\)", session.read_text()):
                raise ValueError("Review placement quantization for this session resolution")
            if any(not p["net_preserved"] or p["position_delta_mm"] > .0001 for p in pad_comparisons):
                raise ValueError("SES import exceeded its declared placement grid or changed a net; see pad_correspondence.json")
            route = {"tracks": tracks, "vias": vias, "zones": [],
                     "status": "Imported local autoroute; independent DRC and current-path checks pending",
                     "physical_boards_tested": 0, "session_sha256": digest(session),
                     "source_pcb_sha256": digest(pcb_path)}
            (output / "routing.json").write_text(json.dumps(route, indent=2)+"\n")
            pcb.SaveBoard(str(output / "imported_f1_fanout_r2.kicad_pcb"), board)
            report = {"schema": "yam-f1-specctra-import/1", "source_pcb_sha256": digest(pcb_path),
                      "session_sha256": digest(session), "tracks": len(tracks), "vias": len(vias),
                      "original_session_sha256": raw_session_sha,
                      "normalized_empty_mounting_package_token": normalized_empty_component,
                      "native_pad_nets_preserved": True,
                      "maximum_import_pad_position_delta_mm": max(p["position_delta_mm"] for p in pad_comparisons),
                      "placement_quantization_bound_mm": .0001,
                      "final_board_uses_original_placement": True, "independent_drc_pending": True}
        (output / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(output.relative_to(ROOT)), **report}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
