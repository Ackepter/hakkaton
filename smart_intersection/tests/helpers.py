"""Shared helpers: run an engine headlessly and count physical-invariant violations."""
from typing import Dict

from smart_intersection.engine.simulation import SimulationEngine
from smart_intersection.engine.world import ARM_LENGTH, INTERSECTION_HALF
from smart_intersection.scenarios.presets import get_scenario

OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
VEHICLE_STATES = {"driving", "decelerating", "waiting", "passing", "finished"}
PED_STATES = {"walking_to_crossing", "waiting_for_green", "crossing", "finished"}


def make_engine(scenario: str, seed: int = 42, **overrides) -> SimulationEngine:
    e = SimulationEngine(seed=seed)
    cfg = get_scenario(scenario)
    cfg.pop("name", None)
    cfg.pop("description", None)
    cfg["time_scale"] = 1.0
    cfg.update(overrides)
    e.configure(**cfg)
    return e


def world_xz(v):
    """World (x, z) of a vehicle centre; inbound path runs straight through the box."""
    t = v.position_m - ARM_LENGTH
    return {"north": (-2.0, t), "south": (2.0, -t), "east": (-t, -2.0), "west": (t, 2.0)}[v.direction]


def in_box(v) -> bool:
    x, z = world_xz(v)
    half = v.length_m / 2
    if v.direction in ("north", "south"):
        return abs(x) < INTERSECTION_HALF and abs(z) - half < INTERSECTION_HALF
    return abs(z) < INTERSECTION_HALF and abs(x) - half < INTERSECTION_HALF


def check_invariants(e: SimulationEngine, seconds: float, dt: float = 0.1) -> Dict[str, int]:
    st = dict(overlap=0, box_conflict=0, red_run=0, ped_hit=0, ped_stack=0, bad_state=0,
              speed_violation=0, backwards=0, early_removal=0, both_green=0)
    prev_front, prev_pos = {}, {}
    for _ in range(int(seconds / dt)):
        before = {vid: (v.position_m, v.length_m, v.lane_id) for vid, v in e._vehicles.items()}
        e._tick(dt)
        for vid, (pos, length, lane_id) in before.items():
            if vid not in e._vehicles and pos + length / 2 + 12 < e._lanes[lane_id].length_m:
                st["early_removal"] += 1

        for lane in e._lanes.values():
            vs = sorted((v for v in e._vehicles.values() if v.lane_id == lane.id), key=lambda v: v.position_m)
            for a, b in zip(vs, vs[1:]):
                if (b.position_m - b.length_m / 2) - (a.position_m + a.length_m / 2) < -1e-6:
                    st["overlap"] += 1

        groups = {"ns": 0, "ew": 0}
        for v in e._vehicles.values():
            if v.state not in VEHICLE_STATES:
                st["bad_state"] += 1
            if v.speed_mps < -1e-9 or v.speed_mps > v.max_speed + 1e-6:
                st["speed_violation"] += 1
            if v.id in prev_pos and v.position_m < prev_pos[v.id] - 1e-9:
                st["backwards"] += 1
            prev_pos[v.id] = v.position_m
            if in_box(v):
                groups["ns" if v.direction in ("north", "south") else "ew"] += 1
            lane = e._lanes[v.lane_id]
            light = e._lights[lane.traffic_light_id]
            front = v.position_m + v.length_m / 2
            pf = prev_front.get(v.id)
            if pf is not None and pf <= lane.stop_line_m < front and light.state == "RED":
                st["red_run"] += 1
            prev_front[v.id] = front
        if groups["ns"] and groups["ew"]:
            st["box_conflict"] += 1

        ns_green = any(l.state == "GREEN" for l in e._lights.values() if l.direction in ("north", "south"))
        ew_green = any(l.state == "GREEN" for l in e._lights.values() if l.direction in ("east", "west"))
        if ns_green and ew_green:
            st["both_green"] += 1

        crossing = [p for p in e._pedestrians.values() if p.state == "crossing"]
        for p in e._pedestrians.values():
            if p.state not in PED_STATES:
                st["bad_state"] += 1
        for p in crossing:
            arm = e._crossings[p.crossing_id].direction
            for v in e._vehicles.values():
                if v.direction not in (arm, OPPOSITE[arm]):
                    continue
                x, z = world_xz(v)
                along = {"north": -z, "south": z, "east": x, "west": -x}[arm]
                lateral = {"north": x, "south": x, "east": z, "west": z}[arm]
                half = v.length_m / 2
                if abs(lateral) < 4 and along + half > 17 and along - half < 20:
                    st["ped_hit"] += 1
        active = [p for p in e._pedestrians.values() if p.state in ("waiting_for_green", "crossing")]
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                if a.crossing_id != b.crossing_id:
                    continue
                pa = a.direction * (a.position_m - 6.0)
                pb = b.direction * (b.position_m - 6.0)
                if abs(pa - pb) < 0.3 and abs(a.offset - b.offset) < 0.3:
                    st["ped_stack"] += 1
    return st
