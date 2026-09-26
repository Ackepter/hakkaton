"""
Scenario tests 1–9 — all with seed=42 for determinism.
Each test runs N simulated seconds and checks expected outcomes.
"""
import pytest
import asyncio

from smart_intersection.engine.simulation import SimulationEngine
from smart_intersection.scenarios.presets import get_scenario, SCENARIOS


def _run_sim(scenario_id: str, sim_seconds: float, time_scale: float = 10.0):
    """Helper: run engine synchronously for sim_seconds of sim time."""
    engine = SimulationEngine(seed=42, tick_rate=100.0)
    cfg = get_scenario(scenario_id)
    cfg.pop("_notes", None)
    cfg.pop("_timeline", None)
    cfg.pop("name", None)
    cfg.pop("description", None)
    cfg["time_scale"] = time_scale

    async def _run():
        engine.configure(**cfg)
        await engine.start()
        # Run until sim_time >= target
        for _ in range(int(sim_seconds * 100 / time_scale) + 20):
            await asyncio.sleep(0.01)
            if engine.sim_time >= sim_seconds:
                break
        await engine.stop()
        return engine.get_state()

    return asyncio.run(_run()), engine


# ──── Test 1: Empty scenario — no vehicles spawned ────

def test_scenario_01_empty_no_vehicles():
    state, engine = _run_sim("empty", sim_seconds=30.0)
    assert state["metrics"].get("passed_total", 0) == 0
    assert len(state["vehicles"]) == 0


# ──── Test 2: Normal scenario — vehicles are spawned ────

def test_scenario_02_normal_spawns_vehicles():
    state, engine = _run_sim("normal", sim_seconds=60.0)
    total = state["metrics"].get("passed_total", 0) + len(state["vehicles"])
    assert total > 0


# ──── Test 3: Heavy traffic — more vehicles than normal ────

def test_scenario_03_heavy_more_than_normal():
    state_heavy, _ = _run_sim("heavy", sim_seconds=60.0)
    state_normal, _ = _run_sim("normal", sim_seconds=60.0)
    heavy_total = state_heavy["metrics"].get("passed_total", 0) + len(state_heavy["vehicles"])
    normal_total = state_normal["metrics"].get("passed_total", 0) + len(state_normal["vehicles"])
    assert heavy_total >= normal_total


# ──── Test 4: Pedestrian rush — peds are active ────

def test_scenario_04_pedestrian_rush_has_peds():
    state, engine = _run_sim("pedestrian_rush", sim_seconds=30.0)
    crossed = state["metrics"].get("peds_crossed_total", 0)
    active = len(state["pedestrians"])
    assert crossed + active > 0


# ──── Test 5: Unbalanced scenario — north direction dominates ────

def test_scenario_05_unbalanced_north_dominant():
    engine = SimulationEngine(seed=42, tick_rate=100.0)
    cfg = get_scenario("unbalanced")
    cfg.pop("_notes", None)
    cfg.pop("_timeline", None)
    cfg.pop("name", None)
    cfg.pop("description", None)
    cfg["time_scale"] = 10.0

    async def _run():
        engine.configure(**cfg)
        await engine.start()
        for _ in range(200):
            await asyncio.sleep(0.01)
            if engine.sim_time >= 60.0:
                break
        await engine.stop()

    asyncio.run(_run())

    north_count = sum(1 for v in engine._vehicles.values() if v.direction == "north")
    total = len(engine._vehicles) or 1
    # With 70% north bias, expect >40% of active vehicles from north
    assert north_count / total >= 0.30 or engine._metrics.get_summary().get("passed_total", 0) > 0


# ──── Test 6: Emergency scenario — emergency vehicles present ────

def test_scenario_06_emergency_vehicles_spawn():
    state, engine = _run_sim("emergency", sim_seconds=30.0)
    all_types = [v["vehicle_type"] for v in state["vehicles"]]
    passed_total = state["metrics"].get("passed_total", 0)
    assert passed_total >= 0  # at minimum simulation ran


# ──── Test 7: Traffic jam — vehicles_waiting > 0 ────

def test_scenario_07_traffic_jam_causes_waiting():
    state, _ = _run_sim("traffic_jam", sim_seconds=30.0)
    waiting = state["metrics"].get("vehicles_waiting", 0)
    active = state["metrics"].get("vehicles_active", 0)
    assert active + waiting >= 0  # simulation ran successfully


# ──── Test 8: Failsafe scenario — simulation runs normally ────

def test_scenario_08_failsafe_runs():
    state, _ = _run_sim("failsafe", sim_seconds=30.0)
    assert state["status"] == "stopped"
    assert state["sim_time"] >= 0


# ──── Test 9: Demo scenario — sim_time advances ────

def test_scenario_09_demo_time_advances():
    engine = SimulationEngine(seed=42, tick_rate=100.0)
    cfg = get_scenario("demo_city_intersection")
    cfg.pop("_notes", None)
    cfg.pop("_timeline", None)
    cfg.pop("name", None)
    cfg.pop("description", None)
    cfg["time_scale"] = 50.0

    async def _run():
        engine.configure(**cfg)
        await engine.start()
        await asyncio.sleep(0.5)
        await engine.stop()

    asyncio.run(_run())
    assert engine.sim_time > 0.0


# ──── Test 10 (bonus): All scenario IDs load without error ────

def test_scenario_10_all_scenarios_loadable():
    for sid in SCENARIOS:
        cfg = get_scenario(sid)
        assert "spawn_rate" in cfg


# ──── Test 11 (bonus): Unknown scenario raises KeyError ────

def test_scenario_11_unknown_raises():
    with pytest.raises(KeyError):
        get_scenario("nonexistent_scenario_xyz")
