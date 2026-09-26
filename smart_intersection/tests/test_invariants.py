"""
Physical-invariant tests: run every scenario with several seeds and assert that the simulation
never produces impossible situations (overlapping cars, red-light running, cars in the box together
with cross traffic, pedestrians under wheels, stacked pedestrians, vanishing vehicles).
"""
import pytest

from smart_intersection.scenarios.presets import SCENARIOS
from .helpers import make_engine, check_invariants

SCENARIO_IDS = [s for s in SCENARIOS if s != "empty"]
SEEDS = [42, 7, 2024]
ZERO = dict(overlap=0, box_conflict=0, red_run=0, ped_hit=0, ped_stack=0, bad_state=0,
            speed_violation=0, backwards=0, early_removal=0, both_green=0)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("scenario", SCENARIO_IDS)
def test_no_physical_violations(scenario, seed):
    e = make_engine(scenario, seed=seed)
    violations = check_invariants(e, seconds=240)
    assert violations == ZERO, f"{scenario}/seed={seed}: {violations}"


@pytest.mark.parametrize("seed", SEEDS)
def test_no_violations_with_a_coarser_time_step(seed):
    e = make_engine("heavy", seed=seed)
    assert check_invariants(e, seconds=240, dt=0.05) == ZERO


def test_checker_detects_a_real_conflict():
    """Sanity of the checker itself: forcing both directions green must be reported."""
    e = make_engine("heavy", seed=42)
    for lid in ("TL-N", "TL-S", "TL-E", "TL-W"):
        e.set_light_state(lid, "GREEN")
    v = check_invariants(e, seconds=120)
    assert v["both_green"] > 0
    assert v["box_conflict"] > 0


def test_checker_detects_overlapping_vehicles():
    e = make_engine("heavy", seed=42)
    e.advance(40)
    car = next(iter(e._vehicles.values()), None)
    assert car is not None
    clone = type(car)(**{**car.__dict__, "id": "ghost"})
    e._vehicles["ghost"] = clone
    v = check_invariants(e, seconds=1)
    assert v["overlap"] > 0


def test_vehicles_actually_move_through_the_whole_intersection():
    e = make_engine("normal", seed=42)
    seen_positions = {}
    for _ in range(3000):
        e._tick(0.1)
        for v in e._vehicles.values():
            seen_positions[v.id] = max(seen_positions.get(v.id, 0), v.position_m)
    assert e.get_state()["metrics"]["passed_total"] > 30
    assert max(seen_positions.values()) > 150         # vehicles reach the far end of the path


def test_queue_never_exceeds_lane_capacity_and_system_drains_after_jam():
    e = make_engine("traffic_jam", seed=42)
    max_waiting = 0
    for _ in range(3000):
        e._tick(0.1)
        for lane_id in ("north-in", "south-in", "east-in", "west-in"):
            n = sum(1 for v in e._vehicles.values() if v.lane_id == lane_id and v.state == "waiting")
            max_waiting = max(max_waiting, n)
    assert 6 <= max_waiting <= 20
    e.configure(spawn_rate=0.0, ped_spawn_rate=0.0)
    e.advance(300)
    assert len(e._vehicles) == 0                       # everybody eventually gets through
