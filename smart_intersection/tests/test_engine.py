"""
Unit tests for the Smart Intersection engine: world, vehicle/pedestrian FSM, spawning, metrics, lifecycle.
All deterministic (fixed seeds).
"""
import asyncio
import random

import pytest

from smart_intersection.engine.models import Vehicle, Pedestrian, VEHICLE_DEFAULTS
from smart_intersection.engine.world import (
    build_world, ARM_LENGTH, PATH_LENGTH, INTERSECTION_HALF, CROSSWALK_CENTER, CROSSWALK_DEPTH,
    get_vehicle_3d_position,
)
from smart_intersection.engine.behaviors import update_vehicle, update_pedestrian, MIN_GAP_M
from smart_intersection.engine.traffic_generator import SpawnManager
from smart_intersection.engine.metrics import MetricsEngine
from smart_intersection.engine.simulation import SimulationEngine


# ──────────── world layout ────────────

def test_world_has_eight_lanes_four_lights_four_crossings():
    lanes, lights, crossings = build_world()
    assert len(lanes) == 8 and len(lights) == 4 and len(crossings) == 4
    assert {"north-in", "north-out", "south-in", "west-out"} <= set(lanes)


def test_initial_light_state_ns_green_ew_red():
    _, lights, _ = build_world()
    assert lights["TL-N"].state == lights["TL-S"].state == "GREEN"
    assert lights["TL-E"].state == lights["TL-W"].state == "RED"


def test_stop_line_is_before_the_crosswalk_not_in_the_middle_of_the_box():
    lanes, _, _ = build_world()
    for lane in lanes.values():
        if lane.is_inbound:
            dist_from_centre = ARM_LENGTH - lane.stop_line_m
            assert dist_from_centre > CROSSWALK_CENTER + CROSSWALK_DEPTH / 2
            assert dist_from_centre > INTERSECTION_HALF


def test_inbound_path_runs_through_the_box_to_the_far_end():
    lanes, _, _ = build_world()
    for lane in lanes.values():
        if lane.is_inbound:
            assert lane.length_m == PATH_LENGTH == 2 * ARM_LENGTH


def test_3d_position_helper_is_continuous_through_the_box():
    assert get_vehicle_3d_position("north-in", 0)[2] == pytest.approx(-ARM_LENGTH)
    assert get_vehicle_3d_position("north-in", ARM_LENGTH)[2] == pytest.approx(0)
    assert get_vehicle_3d_position("north-in", PATH_LENGTH)[2] == pytest.approx(ARM_LENGTH)
    assert get_vehicle_3d_position("west-in", ARM_LENGTH)[0] == pytest.approx(0)
    assert get_vehicle_3d_position("east-in", PATH_LENGTH)[0] == pytest.approx(-ARM_LENGTH)


# ──────────── vehicle FSM ────────────

def _car(speed=10.0, state="driving", position=0.0, lane="north-in", vtype="car"):
    d = VEHICLE_DEFAULTS[vtype]
    return Vehicle(id=f"{vtype}-0001", vehicle_type=vtype, lane_id=lane, direction=lane.split("-")[0],
                   position_m=position, speed_mps=speed, max_speed=d["max_speed"], length_m=d["length_m"],
                   accel=d["accel"], decel=d["decel"], state=state, spawn_time=0.0, wait_time=0.0)


def _run_single(v, lane, light, seconds, dt=0.1):
    for _ in range(int(seconds / dt)):
        update_vehicle(v, dt, lane, light, [])


def test_vehicle_moves_on_green():
    lanes, _, _ = build_world()
    v = _car(position=10.0)
    update_vehicle(v, 0.1, lanes["north-in"], "GREEN", [])
    assert v.position_m > 10.0


def test_vehicle_starts_decelerating_when_approaching_red():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _car(position=lane.stop_line_m - 20.0)
    update_vehicle(v, 0.1, lane, "RED", [])
    assert v.state == "decelerating"


def test_vehicle_ignores_red_when_far_away():
    lanes, _, _ = build_world()
    v = _car(position=0.0)
    update_vehicle(v, 0.1, lanes["north-in"], "RED", [])
    assert v.state == "driving"


@pytest.mark.parametrize("vtype", ["car", "truck", "bus", "tram", "emergency"])
def test_every_vehicle_type_stops_before_the_line_on_red(vtype):
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _car(speed=VEHICLE_DEFAULTS[vtype]["max_speed"], position=0.0, vtype=vtype)
    _run_single(v, lane, "RED", 60)
    front = v.position_m + v.length_m / 2
    assert v.state == "waiting"
    assert v.speed_mps == 0.0
    assert front <= lane.stop_line_m + 0.05          # never crosses the line
    assert lane.stop_line_m - front < 1.0            # and stops close to it


def test_waiting_vehicle_accumulates_wait_time_on_red():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _car(speed=0.0, state="waiting", position=lane.stop_line_m - 2.3)
    update_vehicle(v, 0.5, lane, "RED", [])
    assert v.state == "waiting" and v.wait_time == pytest.approx(0.5)


def test_waiting_vehicle_departs_on_green():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _car(speed=0.0, state="waiting", position=lane.stop_line_m - 2.3)
    update_vehicle(v, 0.1, lane, "GREEN", [])
    assert v.state == "passing"
    _run_single(v, lane, "GREEN", 5)
    assert v.speed_mps > 5.0 and v.position_m + v.length_m / 2 > lane.stop_line_m


def test_vehicle_that_cannot_stop_drives_through_yellow():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _car(speed=13.9, position=lane.stop_line_m - 2.25 - 5.0)   # 5 m from the line at 50 km/h
    update_vehicle(v, 0.1, lane, "YELLOW", [])
    assert v.state != "decelerating"
    _run_single(v, lane, "RED", 3)                                  # even when it turns red meanwhile
    assert v.position_m + v.length_m / 2 > lane.stop_line_m


def test_vehicle_that_can_stop_stops_on_yellow():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _car(speed=10.0, position=lane.stop_line_m - 2.25 - 30.0)
    _run_single(v, lane, "YELLOW", 20)
    assert v.state == "waiting"


def test_vehicle_reaching_green_again_while_braking_recovers():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _car(speed=13.9, position=lane.stop_line_m - 40.0)
    _run_single(v, lane, "RED", 1.0)
    assert v.state == "decelerating"
    _run_single(v, lane, "GREEN", 5.0)
    assert v.state in ("driving", "passing") and v.speed_mps > 5.0


def test_vehicle_finishes_only_at_the_end_of_the_path():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _car(speed=13.9, position=lane.length_m - 1.0)
    assert update_vehicle(v, 0.1, lane, "GREEN", []) is None      # rear is still on the map
    v.position_m = lane.length_m + v.length_m
    assert update_vehicle(v, 0.1, lane, "GREEN", []) == "finished"


def test_vehicle_slows_for_leader():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    leader = _car(speed=0.0, position=20.0)
    follower = _car(speed=13.9, position=5.0)
    update_vehicle(follower, 0.5, lane, "GREEN", [leader])
    assert follower.speed_mps < 13.9


def test_follower_stops_behind_a_stopped_leader_with_minimum_gap():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    leader = _car(speed=0.0, position=40.0)
    follower = _car(speed=13.9, position=0.0)
    for _ in range(600):
        update_vehicle(follower, 0.1, lane, "GREEN", [leader])
    gap = (leader.position_m - leader.length_m / 2) - (follower.position_m + follower.length_m / 2)
    assert gap >= MIN_GAP_M - 0.3
    assert follower.speed_mps < 0.5


# ──────────── pedestrian FSM ────────────

def _ped(position=0.0, state="walking_to_crossing"):
    return Pedestrian(id="ped-0001", crossing_id="PC-N", state=state, spawn_time=0.0, wait_time=0.0,
                      position_m=position)


def test_pedestrian_walks_to_the_curb_then_waits():
    p = _ped(position=-2.5)
    for _ in range(30):
        update_pedestrian(p, 0.1, "RED")
    assert p.state == "waiting_for_green" and p.position_m == 0.0


def test_pedestrian_waits_on_red_and_counts_wait_time():
    p = _ped(state="waiting_for_green")
    update_pedestrian(p, 1.0, "RED")
    assert p.state == "waiting_for_green" and p.wait_time == pytest.approx(1.0)


def test_pedestrian_crosses_on_green_and_finishes():
    p = _ped(state="waiting_for_green")
    update_pedestrian(p, 0.1, "GREEN")
    assert p.state == "crossing"
    res = None
    for _ in range(200):
        res = update_pedestrian(p, 0.1, "RED")     # a started crossing is never interrupted
        if res:
            break
    assert res == "finished" and p.state == "finished"


# ──────────── spawn manager ────────────

def test_spawn_manager_deterministic():
    a = SpawnManager(spawn_rate=60.0, rng=random.Random(42))
    b = SpawnManager(spawn_rate=60.0, rng=random.Random(42))
    va = [v.id + v.lane_id for _ in range(200) for v in a.try_spawn_vehicles(0.0, 0.5)]
    vb = [v.id + v.lane_id for _ in range(200) for v in b.try_spawn_vehicles(0.0, 0.5)]
    assert va == vb and len(va) > 0


def test_spawn_manager_rate_matches_configuration():
    sm = SpawnManager(spawn_rate=30.0, rng=random.Random(1))
    total = sum(len(sm.try_spawn_vehicles(0.0, 0.1)) for _ in range(6000))   # 600 s
    assert 240 <= total <= 360                                               # expected 300


def test_spawn_manager_zero_rate_spawns_nothing():
    sm = SpawnManager(spawn_rate=0.0, ped_spawn_rate=0.0)
    assert sm.try_spawn_vehicles(0.0, 100.0) == []
    assert sm.try_spawn_pedestrians(0.0, 100.0, ["PC-N"]) == []


def test_spawn_manager_direction_and_type_probs_respected():
    sm = SpawnManager(spawn_rate=600.0, rng=random.Random(3),
                      direction_probs={"north": 1.0, "south": 0.0, "east": 0.0, "west": 0.0},
                      type_probs={"bus": 1.0})
    vs = [v for _ in range(50) for v in sm.try_spawn_vehicles(0.0, 0.1)]
    assert vs and all(v.direction == "north" and v.vehicle_type == "bus" for v in vs)


def test_spawn_manager_emergency():
    v = SpawnManager().add_emergency_vehicle(0.0, "east")
    assert v.vehicle_type == "emergency" and v.lane_id == "east-in"


def test_pedestrians_alternate_sides():
    sm = SpawnManager(ped_spawn_rate=6000.0, rng=random.Random(5))
    peds = [p for _ in range(20) for p in sm.try_spawn_pedestrians(0.0, 0.1, ["PC-N"])][:12]
    assert [p.direction for p in peds] == [1, -1] * 6


def test_engine_gives_opposite_directions_disjoint_lanes_and_queues_same_lane_pedestrians():
    e = SimulationEngine(seed=1)
    sm = SpawnManager(ped_spawn_rate=6000.0, rng=random.Random(5))
    peds = [p for _ in range(30) for p in sm.try_spawn_pedestrians(0.0, 0.1, ["PC-N"])][:14]
    for p in peds:
        e._assign_ped_slot(p)
        e._pedestrians[p.id] = p
    plus = {p.offset for p in peds if p.direction == 1}
    minus = {p.offset for p in peds if p.direction == -1}
    assert plus.isdisjoint(minus)
    spots = [(p.direction, p.offset, p.stand_position) for p in peds]
    assert len(set(spots)) == len(spots)                       # nobody shares a standing spot


# ──────────── engine placement ────────────

def test_engine_refuses_spawn_on_top_of_an_existing_vehicle():
    e = SimulationEngine(seed=1)
    a = SpawnManager().add_emergency_vehicle(0.0, "north")
    b = SpawnManager().add_emergency_vehicle(0.0, "north")
    b.id = "other"
    assert e._try_place(a) is True
    assert e._try_place(b) is False


def test_engine_spawn_speed_is_reduced_when_leader_is_close():
    e = SimulationEngine(seed=1)
    lead = _car(speed=0.0, position=14.0)
    e._vehicles[lead.id] = lead
    new = _car(speed=11.0, position=0.0)
    new.id = "new"
    assert e._try_place(new)
    assert new.speed_mps < 11.0


# ──────────── metrics ────────────

def test_metrics_initially_empty():
    assert MetricsEngine().get_summary() == {}


def test_metrics_counts_totals():
    lanes, lights, _ = build_world()
    me = MetricsEngine()
    snap = me.update(10.0, [], [], list(lights.values()), lanes, newly_passed=5, newly_crossed=2)
    assert snap["passed_total"] == 5 and snap["peds_crossed_total"] == 2


def test_throughput_uses_a_sixty_second_window():
    lanes, lights, _ = build_world()
    me = MetricsEngine()
    t = 0.0
    for _ in range(2000):                     # one vehicle per second for 200 s
        t += 0.1
        me.update(t, [], [], list(lights.values()), lanes, newly_passed=1 if int(t * 10) % 10 == 0 else 0,
                  newly_crossed=0)
    assert me.get_summary()["throughput_per_min"] == pytest.approx(60.0, abs=3.0)


def test_metrics_history_is_sampled_once_per_second():
    lanes, lights, _ = build_world()
    me = MetricsEngine()
    for i in range(1, 101):
        me.update(i * 0.1, [], [], list(lights.values()), lanes, 0, 0)
    assert 9 <= len(me.get_history()) <= 11


# ──────────── engine lifecycle ────────────

def test_state_structure():
    s = SimulationEngine(seed=42).get_state()
    for key in ("sim_time", "vehicles", "lights", "pedestrians", "metrics", "control_mode", "phase", "status"):
        assert key in s
    assert s["metrics"]["passed_total"] == 0        # complete metric set even before the first tick


def test_same_seed_gives_identical_runs_and_different_seed_differs():
    def run(seed):
        e = SimulationEngine(seed=seed)
        e.configure(spawn_rate=30.0, ped_spawn_rate=10.0)
        e.advance(120)
        s = e.get_state()
        s.pop("real_time")
        return s
    assert run(42) == run(42)
    assert run(42) != run(43)


def test_advance_moves_time_and_cycles_phases():
    e = SimulationEngine(seed=42)
    e.configure(spawn_rate=80.0, ped_spawn_rate=0.0)
    seen = set()
    for _ in range(1300):
        e.advance(0.1)
        seen.add(e._phase_index)
    assert e.sim_time == pytest.approx(130.0, abs=0.2)
    assert seen == {0, 1, 2, 3, 4, 5}


def test_configure_clamps_time_scale_and_rejects_bad_mode():
    e = SimulationEngine()
    e.configure(time_scale=1000)
    assert e.time_scale == 20.0
    e.configure(time_scale=0)
    assert e.time_scale == 0.1
    with pytest.raises(ValueError):
        e.configure(control_mode="bogus")


def test_manual_light_override_persists_until_released():
    e = SimulationEngine(seed=42)
    e.configure(spawn_rate=0.0, ped_spawn_rate=0.0)
    assert e.set_light_state("TL-E", "GREEN") is True
    e.advance(70)                                            # more than a full signal cycle
    assert e._lights["TL-E"].state == "GREEN"
    assert e.set_light_state("TL-E", "AUTO") is True
    e.advance(0.2)
    assert e._lights["TL-E"].state in ("RED", "GREEN", "YELLOW") and "TL-E" not in e._overrides


def test_unknown_light_override_returns_false():
    assert SimulationEngine().set_light_state("TL-X", "RED") is False


def test_timeline_changes_spawn_rate_at_the_right_time():
    e = SimulationEngine(seed=42)
    e.configure(spawn_rate=0.0, ped_spawn_rate=0.0,
                timeline=[{"at_sim_s": 10, "spawn_rate": 60.0}, {"at_sim_s": 50, "spawn_rate": 0.0}])
    e.advance(9)
    assert e._spawn.spawn_rate == 0.0
    e.advance(2)
    assert e._spawn.spawn_rate == 60.0
    e.advance(45)
    assert e._spawn.spawn_rate == 0.0


@pytest.mark.asyncio
async def test_start_stop():
    e = SimulationEngine(seed=42)
    await e.start()
    assert e.status == "running"
    await asyncio.sleep(0.2)
    await e.stop()
    assert e.status == "stopped" and e._task is None


@pytest.mark.asyncio
async def test_time_advances_in_real_time_loop():
    e = SimulationEngine(seed=42, tick_rate=50.0)
    e.configure(spawn_rate=0.0, time_scale=5.0)
    await e.start()
    await asyncio.sleep(0.5)
    await e.stop()
    assert 1.0 < e.sim_time < 6.0                             # ~0.5 s real * 5x


@pytest.mark.asyncio
async def test_pause_freezes_time_and_start_after_pause_does_not_spawn_a_second_loop():
    e = SimulationEngine(seed=42, tick_rate=50.0)
    await e.start()
    task = e._task
    await asyncio.sleep(0.2)
    await e.pause()
    frozen = e.sim_time
    await asyncio.sleep(0.2)
    assert e.sim_time == frozen and e.status == "paused"
    await e.start()                                           # "Start" pressed while paused = resume
    assert e._task is task and e.status == "running"
    await e.stop()


@pytest.mark.asyncio
async def test_time_scale_does_not_change_the_result_of_stepping():
    """High speed is sub-stepped, so a fast run must stay physically valid."""
    e = SimulationEngine(seed=42, tick_rate=50.0)
    e.configure(spawn_rate=40.0, time_scale=20.0)
    await e.start()
    await asyncio.sleep(1.0)
    await e.stop()
    for lane in e._lanes.values():
        vs = sorted((v for v in e._vehicles.values() if v.lane_id == lane.id), key=lambda v: v.position_m)
        for a, b in zip(vs, vs[1:]):
            assert (b.position_m - b.length_m / 2) - (a.position_m + a.length_m / 2) > -1e-6


@pytest.mark.asyncio
async def test_reset_clears_everything():
    e = SimulationEngine(seed=42)
    e.configure(spawn_rate=120.0, ped_spawn_rate=60.0)
    e.set_light_state("TL-N", "RED")
    e.advance(30)
    assert e._vehicles
    await e.reset()
    assert e.sim_time == 0.0 and not e._vehicles and not e._pedestrians and not e._overrides
    assert e.get_state()["metrics"]["passed_total"] == 0
