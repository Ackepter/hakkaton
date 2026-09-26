"""
Unit tests for Smart Intersection engine.
All deterministic (seed=42).
"""
import pytest
import asyncio
import random

from smart_intersection.engine.models import Vehicle, Pedestrian, VEHICLE_DEFAULTS
from smart_intersection.engine.world import build_world, ARM_LENGTH
from smart_intersection.engine.behaviors import update_vehicle, update_pedestrian
from smart_intersection.engine.traffic_generator import SpawnManager
from smart_intersection.engine.metrics import MetricsEngine
from smart_intersection.engine.simulation import SimulationEngine


# ──────────── world layout ────────────

def test_build_world_lanes():
    lanes, lights, crossings = build_world()
    assert "north-in" in lanes
    assert "north-out" in lanes
    assert len(lanes) == 8


def test_build_world_lights():
    lanes, lights, crossings = build_world()
    assert "TL-N" in lights
    assert "TL-S" in lights
    assert "TL-E" in lights
    assert "TL-W" in lights
    assert lights["TL-N"].state == "GREEN"
    assert lights["TL-E"].state == "RED"


def test_build_world_crossings():
    lanes, lights, crossings = build_world()
    assert len(crossings) == 4
    assert "PC-N" in crossings


# ──────────── vehicle FSM ────────────

def _make_vehicle(speed=10.0, state="driving", position=0.0):
    return Vehicle(
        id="car-0001",
        vehicle_type="car",
        lane_id="north-in",
        direction="north",
        position_m=position,
        speed_mps=speed,
        max_speed=13.9,
        length_m=4.5,
        accel=3.0,
        decel=5.0,
        state=state,
        spawn_time=0.0,
        wait_time=0.0,
    )


def test_vehicle_moves_on_green():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _make_vehicle(speed=10.0, state="driving", position=10.0)
    prev_pos = v.position_m
    update_vehicle(v, 0.1, lane, "GREEN", [])
    assert v.position_m > prev_pos


def test_vehicle_decelerates_on_red():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    # Place near stop line
    v = _make_vehicle(speed=10.0, state="driving", position=lane.stop_line_m - 20.0)
    update_vehicle(v, 0.1, lane, "RED", [])
    assert v.state == "decelerating"


def test_vehicle_waits_at_red():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _make_vehicle(speed=0.0, state="waiting", position=lane.stop_line_m - 0.3)
    v.speed_mps = 0.0
    result_none = update_vehicle(v, 0.1, lane, "RED", [])
    assert result_none is None
    assert v.wait_time > 0


def test_vehicle_passes_on_green_from_waiting():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _make_vehicle(speed=0.0, state="waiting", position=lane.stop_line_m - 0.1)
    update_vehicle(v, 0.1, lane, "GREEN", [])
    assert v.state == "passing"


def test_vehicle_finished_past_end():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    v = _make_vehicle(speed=13.9, state="driving", position=lane.length_m + 15.0)
    result = update_vehicle(v, 0.1, lane, "GREEN", [])
    assert result == "finished"


def test_vehicle_follows_leader():
    lanes, _, _ = build_world()
    lane = lanes["north-in"]
    leader = _make_vehicle(speed=5.0, state="driving", position=20.0)
    follower = _make_vehicle(speed=13.9, state="driving", position=10.0)
    update_vehicle(follower, 0.5, lane, "GREEN", [leader])
    assert follower.speed_mps < 13.9  # slowed down due to leader


# ──────────── pedestrian FSM ────────────

def _make_ped():
    return Pedestrian(
        id="ped-0001",
        crossing_id="PC-N",
        state="walking_to_crossing",
        spawn_time=0.0,
        wait_time=0.0,
        position_m=0.0,
    )


def test_pedestrian_transitions_to_waiting():
    p = _make_ped()
    update_pedestrian(p, 0.1, "RED")
    assert p.state == "waiting_for_green"


def test_pedestrian_waits_on_red():
    p = _make_ped()
    p.state = "waiting_for_green"
    update_pedestrian(p, 1.0, "RED")
    assert p.wait_time == pytest.approx(1.0, abs=0.01)


def test_pedestrian_crosses_on_green():
    p = _make_ped()
    p.state = "waiting_for_green"
    update_pedestrian(p, 0.1, "GREEN")
    assert p.state == "crossing"


def test_pedestrian_finishes_crossing():
    p = _make_ped()
    p.state = "crossing"
    p.position_m = p.crossing_width - 0.1
    result = update_pedestrian(p, 0.5, "GREEN")
    assert result == "finished"


# ──────────── spawn manager ────────────

def test_spawn_manager_deterministic():
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    sm1 = SpawnManager(spawn_rate=60.0, rng=rng1)
    sm2 = SpawnManager(spawn_rate=60.0, rng=rng2)
    v1 = sm1.try_spawn_vehicles(0.0, 1.0)
    v2 = sm2.try_spawn_vehicles(0.0, 1.0)
    assert len(v1) == len(v2)


def test_spawn_manager_zero_rate():
    sm = SpawnManager(spawn_rate=0.0)
    vehicles = sm.try_spawn_vehicles(0.0, 100.0)
    assert vehicles == []


def test_spawn_manager_emergency():
    sm = SpawnManager()
    v = sm.add_emergency_vehicle(0.0, "north")
    assert v.vehicle_type == "emergency"
    assert v.lane_id == "north-in"


def test_spawn_manager_direction_probs():
    rng = random.Random(42)
    sm = SpawnManager(
        spawn_rate=600.0,
        direction_probs={"north": 1.0, "south": 0.0, "east": 0.0, "west": 0.0},
        rng=rng,
    )
    vehicles = sm.try_spawn_vehicles(0.0, 1.0)
    assert all(v.direction == "north" for v in vehicles)


# ──────────── metrics engine ────────────

def test_metrics_initial_empty():
    me = MetricsEngine()
    assert me.get_summary() == {}


def test_metrics_update_basic():
    lanes, lights, crossings = build_world()
    me = MetricsEngine()
    snap = me.update(
        sim_time=10.0,
        vehicles=[],
        pedestrians=[],
        lights=list(lights.values()),
        lanes=lanes,
        newly_passed=5,
        newly_crossed=2,
    )
    assert snap["passed_total"] == 5
    assert snap["peds_crossed_total"] == 2


# ──────────── simulation engine (async) ────────────

@pytest.mark.asyncio
async def test_simulation_engine_start_stop():
    engine = SimulationEngine(seed=42)
    await engine.start()
    assert engine.status == "running"
    await asyncio.sleep(0.2)
    await engine.stop()
    assert engine.status == "stopped"


@pytest.mark.asyncio
async def test_simulation_engine_tick_advances_time():
    engine = SimulationEngine(seed=42, tick_rate=50.0)
    engine.configure(spawn_rate=0.0, time_scale=5.0)
    await engine.start()
    await asyncio.sleep(0.3)
    await engine.stop()
    assert engine.sim_time > 0.0


@pytest.mark.asyncio
async def test_simulation_engine_get_state_structure():
    engine = SimulationEngine(seed=42)
    state = engine.get_state()
    assert "sim_time" in state
    assert "vehicles" in state
    assert "lights" in state
    assert "pedestrians" in state
    assert "metrics" in state


@pytest.mark.asyncio
async def test_simulation_engine_spawns_vehicles():
    engine = SimulationEngine(seed=42, tick_rate=50.0)
    engine.configure(spawn_rate=600.0, time_scale=10.0)
    await engine.start()
    await asyncio.sleep(0.5)
    await engine.stop()
    state = engine.get_state()
    total = state["metrics"].get("passed_total", 0) + len(state["vehicles"])
    assert total > 0


@pytest.mark.asyncio
async def test_simulation_engine_reset():
    engine = SimulationEngine(seed=42)
    engine.configure(spawn_rate=600.0, time_scale=10.0)
    await engine.start()
    await asyncio.sleep(0.2)
    await engine.reset()
    assert engine.sim_time == 0.0
    assert len(engine._vehicles) == 0
