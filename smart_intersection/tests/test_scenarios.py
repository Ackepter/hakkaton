"""
Scenario tests — headless and deterministic (seed=42): each scenario must produce its characteristic behaviour.
"""
import pytest

from smart_intersection.scenarios.presets import SCENARIOS, get_scenario
from .helpers import make_engine


def run(e, seconds, on_tick=None, dt=0.1):
    for _ in range(int(seconds / dt)):
        e._tick(dt)
        if on_tick:
            on_tick(e)
    return e.get_state()["metrics"]


def test_01_empty_intersection_has_no_traffic_at_all():
    e = make_engine("empty")
    seen = []
    m = run(e, 120, lambda e: seen.append(len(e._vehicles) + len(e._pedestrians)))
    assert max(seen) == 0
    assert m["passed_total"] == 0 and m["peds_crossed_total"] == 0
    assert m["efficiency_pct"] == 100.0


def test_02_normal_traffic_flows_with_reasonable_delay():
    m = run(make_engine("normal"), 300)
    assert 40 <= m["passed_total"] <= 80          # 12 veh/min * 5 min = 60 expected
    assert m["avg_trip_wait_s"] < 25
    assert m["peds_crossed_total"] > 10


def test_03_heavy_traffic_moves_more_vehicles_and_builds_queues():
    normal = run(make_engine("normal"), 300)
    e = make_engine("heavy")
    peak = [0]
    heavy = run(e, 300, lambda e: peak.__setitem__(0, max(peak[0], e.get_state()["metrics"]["vehicles_waiting"])))
    assert heavy["passed_total"] > 2 * normal["passed_total"]
    assert peak[0] >= 4


def test_04_pedestrian_rush_moves_many_pedestrians_without_blocking_cars():
    m = run(make_engine("pedestrian_rush"), 300)
    assert m["peds_crossed_total"] >= 100
    assert m["passed_total"] >= 5                  # the low-rate car stream still gets through


def test_05_unbalanced_north_dominates_arrivals_and_stays_stable():
    e = make_engine("unbalanced")
    arrivals = {"north": set(), "south": set(), "east": set(), "west": set()}

    def watch(e):
        for v in e._vehicles.values():
            arrivals[v.direction].add(v.id)
    m = run(e, 300, watch)
    total = sum(len(s) for s in arrivals.values())
    assert len(arrivals["north"]) / total > 0.55
    assert m["avg_trip_wait_s"] < 60                # adaptive control copes with the imbalance
    assert e._metrics.get_summary()["max_wait_s"] < 90


def test_06_emergency_scenario_serves_emergency_vehicles_fast():
    e = make_engine("emergency")
    worst = {}

    def watch(e):
        for v in e._vehicles.values():
            if v.vehicle_type == "emergency":
                worst[v.id] = max(worst.get(v.id, 0.0), v.wait_time)
    run(e, 300, watch)
    assert len(worst) >= 3
    assert max(worst.values()) <= 14.0


def test_07_traffic_jam_builds_long_queues_then_recovers():
    e = make_engine("traffic_jam")
    peak = [0]
    run(e, 240, lambda e: peak.__setitem__(0, max(peak[0], e.get_state()["metrics"]["congestion_pct"])))
    assert peak[0] >= 60
    e.configure(spawn_rate=0.0, ped_spawn_rate=0.0)
    run(e, 300)
    assert len(e._vehicles) == 0
    assert e.get_state()["metrics"]["vehicles_waiting"] == 0


def test_08_camera_failure_switches_to_fixed_timing_and_back():
    e = make_engine("failsafe")
    reasons = {}
    for t in (30, 70, 130):
        while e.sim_time < t:
            e._tick(0.1)
        reasons[t] = e.failsafe_reason()
    assert reasons == {30: None, 70: "camera failure", 130: None}
    m = e.get_state()["metrics"]
    assert m["passed_total"] > 10                  # traffic keeps moving through the failure


def test_09_demo_timeline_ramps_up_jams_and_recovers():
    e = make_engine("demo_city_intersection")
    checkpoints = {}
    for t in (10, 30, 70, 100, 130, 170):
        while e.sim_time < t:
            e._tick(0.1)
        checkpoints[t] = e._spawn.spawn_rate
    assert checkpoints == {10: 5.0, 30: 12.0, 70: 25.0, 100: 10.0, 130: 60.0, 170: 12.0}
    assert e._spawn.ped_spawn_rate == 5.0


def test_10_all_presets_are_complete_and_isolated_copies():
    for sid in SCENARIOS:
        cfg = get_scenario(sid)
        for key in ("name", "description", "spawn_rate", "ped_spawn_rate", "direction_probs", "type_probs"):
            assert key in cfg, (sid, key)
        assert sum(cfg["direction_probs"].values()) == pytest.approx(1.0)
        assert sum(cfg["type_probs"].values()) == pytest.approx(1.0)
    a = get_scenario("normal")
    a["direction_probs"]["north"] = 99
    assert get_scenario("normal")["direction_probs"]["north"] == 0.25      # deep copy


def test_pedestrian_rush_is_pedestrian_heavy_and_uses_only_cars():
    cfg = get_scenario("pedestrian_rush")
    assert cfg["ped_spawn_rate"] == 60.0
    assert cfg["spawn_rate"] == 3.0
    assert cfg["type_probs"] == {"car": 1.0, "truck": 0.0, "bus": 0.0, "tram": 0.0, "emergency": 0.0}


def test_pedestrian_queue_fills_the_first_free_slot_without_stacking():
    from smart_intersection.engine.models import Pedestrian

    e = make_engine("empty")
    for offset, positions in ((-1.2, (-0.5, -1.0)), (-0.75, (0.0, -0.5)), (-0.3, (0.0, -0.5))):
        for i, stand in enumerate(positions):
            p = Pedestrian(f"queued-{offset}-{i}", "PC-N", "waiting_for_green", 0.0, 0.0,
                           direction=1, offset=offset, stand_position=stand)
            e._pedestrians[p.id] = p
    incoming = Pedestrian("incoming", "PC-N", "walking_to_crossing", 0.0, 0.0, direction=1)

    e._assign_ped_slot(incoming)

    assert (incoming.offset, incoming.stand_position) == (-1.2, 0.0)


def test_11_unknown_scenario_raises_key_error():
    with pytest.raises(KeyError):
        get_scenario("nonexistent_scenario_xyz")


def test_12_time_scale_in_scenario_does_not_leak_into_headless_runs():
    e = make_engine("demo_city_intersection")
    assert e.time_scale == 1.0
