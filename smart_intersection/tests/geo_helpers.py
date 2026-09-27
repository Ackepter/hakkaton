"""Physical invariants for any layout: no two vehicles overlap, nobody runs a red light, nobody is stuck for ever."""
import math
from typing import Dict, List, Tuple

from smart_intersection.engine.simulation import SimulationEngine
from smart_intersection.layout import Layout


def corners(v) -> List[Tuple[float, float]]:
    c, s = math.cos(v.heading), math.sin(v.heading)
    hl, hw = v.length_m / 2, v.width_m / 2
    return [(v.x + dx * c - dz * s, v.z + dx * s + dz * c) for dx, dz in ((hl, hw), (hl, -hw), (-hl, -hw), (-hl, hw))]


def rects_overlap(a: List[Tuple[float, float]], b: List[Tuple[float, float]], shrink: float = 0.0) -> bool:
    """Separating axis test of two rectangles given by their corners (`shrink` metres of tolerance)."""
    for poly in (a, b):
        for i in range(2):
            ex, ez = poly[i + 1][0] - poly[i][0], poly[i + 1][1] - poly[i][1]
            n = math.hypot(ex, ez) or 1.0
            nx, nz = -ez / n, ex / n
            pa = [nx * x + nz * z for x, z in a]
            pb = [nx * x + nz * z for x, z in b]
            if max(pa) - shrink <= min(pb) or max(pb) - shrink <= min(pa):
                return False
    return True


def point_in_vehicle(v, x: float, z: float, margin: float = 0.0) -> bool:
    c, s = math.cos(v.heading), math.sin(v.heading)
    dx, dz = x - v.x, z - v.z
    along, side = dx * c + dz * s, -dx * s + dz * c
    return abs(along) <= v.length_m / 2 + margin and abs(side) <= v.width_m / 2 + margin


def run_checks(e: SimulationEngine, seconds: float, dt: float = 0.1, stuck_s: float = 75.0) -> Dict[str, int]:
    """Step the engine and count violations. All counters must stay 0."""
    st = dict(overlap=0, red_run=0, stuck=0, off_path=0, ped_hit=0, backwards=0)
    prev_front, prev_pos, still = {}, {}, {}
    for _ in range(int(seconds / dt)):
        e._tick(dt)
        vs = list(e._vehicles.values())
        walking = {p.crossing_id for p in e._pedestrians.values()
                   if p.state == "crossing" or (p.state == "waiting_for_green" and e._ped_signals.get(p.crossing_id) == "GREEN")}
        boxes = {v.id: corners(v) for v in vs}
        for i, a in enumerate(vs):
            for b in vs[i + 1:]:
                if abs(a.x - b.x) < 25 and abs(a.z - b.z) < 25 and rects_overlap(boxes[a.id], boxes[b.id], 0.05):
                    st["overlap"] += 1
        for v in vs:
            lane = e._lanes[v.lane_id]
            path = e._paths[v.path_id]
            front = v.position_m + v.length_m / 2
            pf = prev_front.get(v.id)
            light = e._lights.get(lane.traffic_light_id)
            if light and pf is not None and pf <= lane.stop_line_m < front and light.state == "RED":
                st["red_run"] += 1
            prev_front[v.id] = front
            if v.id in prev_pos and v.position_m < prev_pos[v.id] - 1e-9:
                st["backwards"] += 1
            prev_pos[v.id] = v.position_m
            green = light is None or light.state == "GREEN"
            for_people = {f"PC-{path.exit_arm[0].upper()}", f"PC-{v.direction[0].upper()}"} & walking
            if v.speed_mps < 0.05 and green and not for_people:    # standing at a green (or absent) light, not for pedestrians
                still[v.id] = still.get(v.id, 0.0) + dt
                if still[v.id] > stuck_s:
                    st["stuck"] += 1
            else:
                still.pop(v.id, None)
        for p in e._pedestrians.values():
            if p.state != "crossing":
                continue
            for v in vs:
                if v.speed_mps > 0.3 and point_in_vehicle(v, p.x, p.z, 0.3):
                    st["ped_hit"] += 1
    return st
