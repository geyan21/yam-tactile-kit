"""
Numbers quoted in docs/ENPIRE_T.md, measured from the exported ENPIRE-T geometry and the original
ENPIRE meshes (so the docs can't drift). Writes out/enpire/check/measurements.json.
Usage (from cartridge/): python3 cad/enpire_measure.py
"""
import json
import os
import sys
import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enpire_finger as E       # noqa: E402
import enpire_source as ES      # noqa: E402

CHK = os.path.join(E.OUT, "check")


def span_y(meshes, x, z):
    """Total thickness along y through (x, z): outer extent of all hits."""
    ys = []
    for m in meshes:
        loc, _, _ = m.ray.intersects_location(np.array([[x, -40.0, z]]), np.array([[0, 1.0, 0]]), multiple_hits=True)
        loc = np.asarray(loc, float).reshape(-1, 3)
        ys += list(loc[:, 1])
    return (max(ys) - min(ys)) if ys else 0.0


def width_x(meshes, z):
    xs = []
    for m in meshes:
        s = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if s is not None:
            xs += list(s.vertices[:, 0])
    return (max(xs) - min(xs)) if xs else 0.0


def main():
    os.makedirs(CHK, exist_ok=True)
    pr = E.build_profile()
    N = E.nail_regions(pr)
    D = E.derived(pr, N)
    core = trimesh.load(os.path.join(E.OUT, "core.stl"))
    film = trimesh.load(os.path.join(E.OUT, "film.stl"))
    skin = trimesh.load(os.path.join(E.OUT, "skin.stl"))
    new = [core, film, skin]
    src_t = ES.load(E.P["DZ"])                         # stock ENPIRE placed like ENPIRE-T (same tip)
    old = [src_t["hard"], src_t["soft"]]
    tip_z = D["tip_g"][2]
    out = dict(tip_profile=[])
    for d in (0.5, 1.7, 3.0, 5.0, 10.0):
        z = tip_z + d
        out["tip_profile"].append(dict(from_tip_mm=d, thickness_mm=round(span_y(new, -3.5, z), 3),
                                       stock_thickness_mm=round(span_y(old, -3.5, z), 3),
                                       width_mm=round(width_x(new, z), 3), stock_width_mm=round(width_x(old, z), 3)))
    stock = ES.load(0.0)
    out["tip_below_carriage_mm"] = D["tip_below_carriage_mm"]
    out["stock_tip_below_carriage_mm"] = round(float(E.FP["Z_CARRIAGE"] - stock["hard"].bounds[0][2]), 2)
    out["stock_tip_below_carriage_if_rib_in_slot_mm"] = round(out["stock_tip_below_carriage_mm"] - 5.0, 2)
    out["finger_root_to_tip_mm"] = round(float(E.Zs - tip_z), 2)
    out["strip_developed_mm"] = D["strip_length"]
    out["laminate_length_mm"] = D["C_length"]
    out["core_volume_cm3"] = round(core.volume / 1000, 2)
    out["core_mass_g_solid_petg"] = round(core.volume / 1000 * 1.27, 1)
    out["core_mass_g_pa12_mjf"] = round(core.volume / 1000 * 1.01, 1)
    out["skin_volume_cm3"] = round(skin.volume / 1000, 2)
    out["skin_mass_g_silicone"] = round(skin.volume / 1000 * 1.08, 1)
    out["stock_enpire_mass_g_solid_estimate"] = round((stock["hard"].volume * 1.27 + stock["soft"].volume * 1.21) / 1000, 1)
    out["seat_set_back_mm"] = E.SEAT_SET
    h = E.P["HOOK"]          # room for a skin wall to move out while its hook rib passes the tongue lip, minus the rib
    out["skin_rib_pass_margin_mm"] = round(E.P["RAIL_CUT"] + E.P["SKIN_SIDE_CLR"] - (h["depth"] - h["clr"]), 3)
    out["nail_pocket_depth_mm"] = E.POCKET_D
    fpc = json.load(open(os.path.join(E.OUT, "fpc_pcb", "drc.json")))
    out["taxels"] = fpc["taxels"]
    out["lines"] = fpc["lines"]
    out["min_seat_bend_radius_under_taxels_mm"] = fpc["min_seat_bend_radius_under_taxels_mm"]
    chk = json.load(open(os.path.join(CHK, "checks.json")))
    out["q_touch_mm"] = chk["contact"]["q_touch_mm"]
    out["walls"] = chk["walls"]
    out["shape"] = {k: v for k, v in chk["shape"].items() if k.startswith(("depth_map_cradle", "depth_map_nail", "core_vs", "film_vs", "transition_notch"))}
    json.dump(out, open(os.path.join(CHK, "measurements.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
