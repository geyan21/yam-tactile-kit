#!/usr/bin/python3
"""Route nominal F1 foil envelopes from source gaps to the R2 connectors."""

import argparse
from datetime import datetime, timezone
import heapq
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "build/engineering/tools/f1-matplotlib"))
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
sys.path.insert(0, str(ROOT / "src"))
from tactile_kit.records import execution
from develop_f1_fanout import transform
from f1_surfaces import load_surfaces, layer_offsets
from screen_f1_feedback import digest

CONFIG = ROOT / "engineering/designs/f1_tail_route_development.json"


def native_region(region):
    return affinity.affine_transform(region, [-1, 0, 0, -1, 0, 44])


def simplify_path(points, free):
    """Greedy visible chords; preserve the sampled search as a separate record."""
    result = [points[0]]
    index = 0
    while index < len(points)-1:
        end = len(points)-1
        while end > index+1 and not free.covers(LineString([points[index], points[end]])):
            end -= 1
        result.append(points[end])
        index = end
    return result


def astar(start, finish, free, bounds, spacing, seconds=15):
    lo_y, lo_z, hi_y, hi_z = bounds
    ys = np.arange(lo_y, hi_y+spacing/2, spacing)
    zs = np.arange(lo_z, hi_z+spacing/2, spacing)
    xx, yy = np.meshgrid(ys, zs)
    allowed = shapely.covers(free, shapely.points(xx.ravel(), yy.ravel())).reshape(xx.shape)
    def node(point):
        return (int(round((point[0]-lo_y)/spacing)), int(round((point[1]-lo_z)/spacing)))
    def coord(index):
        return (float(ys[index[0]]), float(zs[index[1]]))
    def valid(index):
        return 0 <= index[0] < len(ys) and 0 <= index[1] < len(zs) and allowed[index[1], index[0]]
    def nearest_visible(point):
        center = node(point)
        candidates = [(i, j) for i in range(center[0]-5, center[0]+6)
                      for j in range(center[1]-5, center[1]+6) if valid((i, j))]
        for candidate in sorted(candidates, key=lambda n: math.dist(point, coord(n))):
            if free.covers(LineString([point, coord(candidate)])):
                return candidate
        raise ValueError("Tail endpoint has no visible grid entrance")
    source, target = nearest_visible(start), nearest_visible(finish)
    queue = [(0., source)]
    costs, parent = {source: 0.}, {}
    deltas = [(i, j) for i in (-1, 0, 1) for j in (-1, 0, 1) if i or j]
    begun = time.monotonic()
    visited = 0
    while queue:
        _, current = heapq.heappop(queue)
        visited += 1
        if current == target:
            result = [coord(current)]
            while current != source:
                current = parent[current]
                result.append(coord(current))
            result = [list(start), *result[::-1], list(finish)]
            # Raster diagonals must not cut a sub-grid obstacle corner.
            if not free.covers(LineString(result)):
                raise ValueError("Grid path cuts an obstacle between sample points")
            return result, visited
        if visited % 1000 == 0 and time.monotonic()-begun > seconds:
            raise TimeoutError("15 second bound on this tail corridor search")
        for di, dj in deltas:
            neighbor = (current[0]+di, current[1]+dj)
            if not valid(neighbor):
                continue
            if di and dj and (not valid((current[0]+di, current[1])) or not valid((current[0], current[1]+dj))):
                continue
            candidate_cost = costs[current]+math.hypot(di, dj)
            if candidate_cost >= costs.get(neighbor, math.inf)-1e-9:
                continue
            costs[neighbor] = candidate_cost
            parent[neighbor] = current
            heuristic = math.dist(neighbor, target)
            heapq.heappush(queue, (candidate_cost+heuristic, neighbor))
    raise ValueError(f"No planar tail lane; visited {visited} grid nodes")


def route_role(role, spec, cfg, carrier, exits, stack, surfaces):
    side = "F" if role == "rows" else "B"
    suffix = "R" if role == "rows" else "C"
    pcb_face = carrier["board_native_x_center_mm"] + (1 if side == "F" else -1)*spec["thickness_mm"]/2
    plane = pcb_face + (1 if side == "F" else -1)*cfg["conductor_plane_above_board_assumed_mm"]
    by_ref = {part["reference"]: part for part in spec["parts"]}
    obstacles = []
    for part in spec["parts"]:
        if part["side"] != side:
            continue
        # Preserve conservative projected bodies even when a low resistor may
        # lie entirely below the nominal tail plane.
        obstacles.append(("part:"+part["reference"], native_region(transform(box(*part["body_envelope_mm"]), part))))
    for index in carrier["active_board_mount_indices"]:
        hole = spec["holes"][index]
        y, z = -hole["center_mm"][0], 44-hole["center_mm"][1]
        radius = (carrier["board_screw_head_envelope_mm"][0] if side == "F"
                  else carrier["board_post_outer_diameter_mm"])/2
        obstacles.append(("mount", Point(y, z).buffer(radius)))
    if side == "B":
        for yz in carrier["frame_mounts_native_yz_mm"]:
            obstacles.append(("frame_head", Point(yz).buffer(carrier["frame_screw_head_envelope_mm"][0]/2)))
        # The row foils travel across this inner plane before their outer
        # quarter bends. Different connector faces do not by themselves
        # separate the complete three-dimensional tails.
        if not 7.2 <= plane < cfg["lateral_bend_start_x_mm"]["rows"]:
            raise ValueError("Rebuild opposite-neck envelopes for this changed plane/bend relation")
        row_width = np.interp(plane, [7.2, 8.35],
                            [stack["tails"]["row_neck_width_mm"], stack["tails"]["long_tail_width_mm"]])
        m = stack["materials_mm"]
        for surface in surfaces:
            site = surface.site
            s = surface.body.bounds[1 if exits["edge_by_site"][site] == "distal" else 3]
            p, tangent, normal = surface.frame(s)
            origin = p+layer_offsets(site, stack)["row_conductor_center"]*normal
            center = origin+(exits["exit_native_y_mm_by_site"][site]-origin[1])/tangent[1]*tangent
            inner = -m["copper"]/2-m["coverlay"]
            outer = m["copper"]/2+m["polyimide"]+(m["copper"]+m["coverlay"] if site < 2 else 0)
            corners = [center+u*tangent+d*normal for u, d in
                       ((-row_width/2, inner), (row_width/2, inner),
                        (row_width/2, outer), (-row_width/2, outer))]
            obstacles.append(("row_neck_CH"+str(site), Polygon(np.asarray(corners)[:, 1:])))
    width = stack["tails"]["long_tail_width_mm"]
    clearance = cfg["tail_to_other_body_clearance_mm"]
    domain = box(*cfg["native_yz_route_bounds_mm"])
    blocked = unary_union([region for _, region in obstacles])
    previous, results, endings = [], [], []
    for site in cfg["routing_order"]:
        surface = surfaces[site]
        offset = layer_offsets(site, stack)["row_conductor_center" if role == "rows" else "column_conductor_center"]
        edge = exits["edge_by_site"][site]
        s = surface.body.bounds[1 if edge == "distal" else 3]
        p, tangent, normal = surface.frame(s)
        origin = p+offset*normal
        advance = (exits["exit_native_y_mm_by_site"][site]-origin[1])/tangent[1]
        center = origin+advance*tangent
        radius = plane-cfg["lateral_bend_start_x_mm"][role]
        if radius < stack["tails"]["nominal_minimum_form_radius_mm"]-1e-7:
            raise ValueError("Nominal quarter bend is below the declared forming radius")
        center[0] = cfg["lateral_bend_start_x_mm"][role]
        direction = -normal
        angle = np.linspace(0, math.pi/2, 81)
        bend = (center+radius*np.sin(angle)[:, None]*np.array([1., 0., 0.])
                +radius*(1-np.cos(angle))[:, None]*direction)
        start = bend[-1, 1:]
        start_lead = start+cfg["required_entry_lead_mm"]*direction[1:]
        ref = exits["site_to_connector_id"][site]+suffix
        connector = by_ref[ref]
        datum_yz = np.asarray([-connector["center_mm"][0], 44-connector["center_mm"][1]])
        sense = 1 if connector["rotation_deg"] == 0 else -1
        goal = datum_yz-np.array([0., sense*cfg["connector_approach_distance_mm"]])
        goal_lead = goal-np.array([0., sense*cfg["required_entry_lead_mm"]])
        # The complete stiffened region and its taper are retained separately.
        tip = datum_yz-np.array([0., sense*cfg["connector_tip_local_y_assumed_mm"]])
        tab_start = tip-np.array([0., sense*stack["tails"]["stiffener_length_mm"]])
        tab = box(datum_yz[0]-3.5, min(tip[1], tab_start[1]),
                  datum_yz[0]+3.5, max(tip[1], tab_start[1]))
        taper = Polygon([(goal[0]-width/2, goal[1]), (goal[0]+width/2, goal[1]),
                         (tab_start[0]+3.5, tab_start[1]), (tab_start[0]-3.5, tab_start[1])])
        result = {"site": site, "role": role, "connector": ref, "nominal_plane_native_x_mm": plane,
                  "nominal_form_radius_mm": radius, "bend_native_mm": bend.tolist(),
                  "start_yz_mm": start.tolist(), "goal_yz_mm": goal.tolist(),
                  "start_lead_yz_mm": start_lead.tolist(), "goal_lead_yz_mm": goal_lead.tolist(),
                  "tip_yz_mm_assumed": tip.tolist(), "tab_yz_mm": list(tab.exterior.coords),
                  "taper_yz_mm": list(taper.exterior.coords), "physical_evidence": False}
        mandatory = unary_union((LineString([start, start_lead]).buffer(width/2),
                                 LineString([goal_lead, goal]).buffer(width/2), taper, tab))
        endings.append((result, start, start_lead, goal, goal_lead, tab, taper, mandatory))
    for result, start, start_lead, goal, goal_lead, tab, taper, mandatory in endings:
        site, ref = result["site"], result["connector"]
        forbidden = blocked.buffer(width/2+clearance)
        reserves = [entry[-1] for entry in endings if entry[0]["site"] != site]
        forbidden = forbidden.union(unary_union(reserves).buffer(
            width/2+cfg["tail_to_tail_clearance_mm"]+cfg["future_entry_reservation_extra_mm"]))
        if previous:
            forbidden = forbidden.union(unary_union(previous).buffer(
                width/2+cfg["tail_to_tail_clearance_mm"]))
        free = domain.difference(forbidden)
        entry_segments = {
            "start": LineString([start, start_lead]),
            "connector": LineString([goal_lead, goal]),
        }
        constraints = [(name, shape.buffer(width/2+clearance)) for name, shape in obstacles]
        constraints += [("reserved_CH"+str(entry[0]["site"]),
                         entry[-1].buffer(width/2+cfg["tail_to_tail_clearance_mm"]))
                        for entry in endings if entry[0]["site"] != site]
        constraints += [("earlier_lane_"+str(index),
                         shape.buffer(width/2+cfg["tail_to_tail_clearance_mm"]))
                        for index, shape in enumerate(previous)]
        result["entry_conflicts"] = {
            name: [label for label, shape in constraints if line.intersects(shape)]
            for name, line in entry_segments.items()
        }
        result["entry_clearances_to_earlier_mm"] = {
            name: [shape.distance(line)-width/2 for shape in previous]
            for name, line in entry_segments.items()
        }
        try:
            if not free.covers(LineString([start, start_lead])) or not free.covers(LineString([goal_lead, goal])):
                raise ValueError("A required entry tangent intersects an expanded body or earlier tail")
            sampled, visited = astar(start_lead, goal_lead, free, cfg["native_yz_route_bounds_mm"], cfg["route_grid_mm"])
            path = [start.tolist(), *simplify_path(sampled, free), goal.tolist()]
            strip = LineString(path).buffer(width/2, cap_style="flat", join_style="round")
            others = unary_union([region for name, region in obstacles if name != "part:"+ref])
            assembly = unary_union((strip, taper, tab))
            if assembly.intersection(others).area > 1e-8:
                raise ValueError("Taper or tab intersects another projected component/mount")
            if previous and assembly.distance(unary_union(previous)) < cfg["tail_to_tail_clearance_mm"]-1e-7:
                raise ValueError("Taper or tab intersects a previous tail clearance")
            previous.append(assembly)
            result.update({"passed_nominal_lane": True, "path_yz_mm": path, "grid_nodes_visited": visited,
                           "planar_centerline_length_mm": LineString(path).length,
                           "nominal_bend_arc_length_mm": result["nominal_form_radius_mm"]*math.pi/2,
                           "tail_envelope_yz_mm": list(assembly.exterior.coords)})
        except (ValueError, TimeoutError) as error:
            result.update({"passed_nominal_lane": False, "error": str(error)})
        results.append(result)
    return results, obstacles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placement_run", type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    source, config_path = args.placement_run.resolve(), args.config.resolve()
    if not source.is_relative_to(ROOT) or not config_path.is_relative_to(ROOT):
        parser.error("Use repository-owned inputs")
    cfg = json.loads(config_path.read_text())
    carrier_path, exits_path = (ROOT / cfg[key] for key in ("carrier_configuration", "exit_configuration"))
    carrier, exits = (json.loads(path.read_text()) for path in (carrier_path, exits_path))
    stack, r1, nail, surfaces = load_surfaces()
    spec_path = source / "specification.json"
    spec = json.loads(spec_path.read_text())
    folder = ROOT / "build/engineering/prototypes/f1/tail_route_runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with execution(ROOT / "build/records", "Search nominal formed F1 tail lanes around R2 components and fasteners; retain every failed restricted-planar candidate") as record:
        folder.mkdir(parents=True, exist_ok=False)
        paths = [config_path, carrier_path, exits_path, spec_path, Path(__file__),
                 ROOT / "engineering/designs/f1_formed_stack.json", ROOT / "engineering/scripts/f1_surfaces.py"]
        for path in paths:
            target = folder / "inputs" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        results, figures = [], []
        for role in ("rows", "columns"):
            rows, obstacles = route_role(role, spec, cfg, carrier, exits, stack, surfaces)
            results.extend(rows)
            figures.append((role, rows, obstacles))
            (folder / "partial_routes.json").write_text(json.dumps(results, indent=2)+"\n")
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as PlotPolygon
        fig, axes = plt.subplots(1, 2, figsize=(16, 7), layout="constrained")
        colors = ["#c35f53", "#8358aa", "#317ea6", "#ba852f", "#459776", "#b65d8b"]
        for ax, (role, rows, obstacles) in zip(axes, figures):
            for name, region in obstacles:
                ax.add_patch(PlotPolygon(list(region.exterior.coords), facecolor="#ced4d6", edgecolor="#87949d", alpha=.6))
            for row in rows:
                color = colors[row["site"]]
                start, goal = row["start_yz_mm"], row["goal_yz_mm"]
                ax.plot(*start, "o", color=color)
                ax.text(start[0]-.6, start[1]-1, "CH"+str(row["site"]), color=color, fontsize=8)
                ax.plot(*goal, "s", color=color, markersize=4)
                if row["passed_nominal_lane"]:
                    ax.add_patch(PlotPolygon(row["tail_envelope_yz_mm"], facecolor=color, edgecolor=color, alpha=.55))
                else:
                    ax.plot([start[0], goal[0]], [start[1], goal[1]], "--", color=color, alpha=.4)
            ax.set(xlim=(-109, -8), ylim=(-13, 53), aspect="equal",
                   xlabel="Native Y (mm)", ylabel="Native Z (mm)",
                   title=role+" · nominal lanes only")
        fig.suptitle("F1 tail routing study · failed lanes are dashed, never silently omitted\n"
                     "Mating datum, bend slack, source/body joins and moving fit remain unqualified")
        for suffix in ("png", "svg", "pdf"):
            fig.savefig(folder / ("tail_routes."+suffix), dpi=160)
        plt.close(fig)
        report = {"schema": "yam-f1-tail-route-study/1", "physical_specimens_tested": 0,
                  "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in paths},
                  "routes": results, "nominal_lanes_passed": sum(row["passed_nominal_lane"] for row in results),
                  "total_lanes": len(results), "complete_f1_assembly": False,
                  "limitations": [
                      "Nominal conductor-plane midpoint and tip-stop midpoint remain explicit assumptions.",
                      "Planar path simplification is not finished electrode artwork or a fully rounded cut outline.",
                      "Body-to-neck joins, three-dimensional frame/tail collisions, mating uncertainty and flex motion remain.",
                      "No force/contact or physical fatigue result is implied."
                  ]}
        (folder / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        record["result"] = {"directory": str(folder.relative_to(ROOT)), "passed": report["nominal_lanes_passed"],
                            "total": len(results),
                            "failed": [{k: row[k] for k in ("site", "role", "error", "entry_conflicts")}
                                       for row in results if not row["passed_nominal_lane"]]}
        print(json.dumps(record["result"], indent=2))


if __name__ == "__main__":
    main()
