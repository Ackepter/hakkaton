"""Signal control tests: phase order and timing, adaptive green, failsafe, pedestrians, emergency priority."""
import pytest

from smart_intersection.engine.simulation import (
    SimulationEngine, PHASES, YELLOW_S, ALL_RED_S, MAX_ALL_RED_S, BASE_GREEN, MIN_GREEN, FAILSAFE_GREEN, MAX_GREEN,
)
from .helpers import make_engine, check_invariants


def phase_log(e, seconds, dt=0.1):
    """Return [(phase_index, duration)] for every completed phase."""
    log, last, start = [], e._phase_index, e.sim_time
    for _ in range(int(seconds / dt)):
        e._tick(dt)
        if e._phase_index != last:
            log.append((last, round(e.sim_time - start, 1)))
            last, start = e._phase_index, e.sim_time
    return log


def idle(**kw):
    e = SimulationEngine(seed=42)
    e.configure(spawn_rate=0.0, ped_spawn_rate=0.0, **kw)
    return e


def test_phase_order_and_fixed_durations_for_yellow_and_all_red():
    e = make_engine("normal")
    log = phase_log(e, 400)
    assert [p for p, _ in log[:6]] == [0, 1, 2, 3, 4, 5]
    for idx, dur in log:
        if idx in (1, 4):
            assert dur == pytest.approx(YELLOW_S, abs=0.15)
        if idx in (2, 5):
            assert ALL_RED_S - 0.15 <= dur <= MAX_ALL_RED_S + 0.15


def test_lights_follow_the_phase_table():
    e = idle()
    for _ in range(1000):
        e._tick(0.1)
        ns, ew, _ = PHASES[e._phase_index]
        assert e._lights["TL-N"].state == e._lights["TL-S"].state == ns
        assert e._lights["TL-E"].state == e._lights["TL-W"].state == ew


def test_never_both_groups_non_red():
    e = make_engine("heavy")
    for _ in range(3000):
        e._tick(0.1)
        ns_open = e._lights["TL-N"].state != "RED"
        ew_open = e._lights["TL-E"].state != "RED"
        assert not (ns_open and ew_open)


def test_failsafe_uses_fixed_twenty_second_greens():
    e = make_engine("failsafe")
    assert e.control_mode == "failsafe"
    greens = [d for idx, d in phase_log(e, 300) if idx in (0, 3)]
    assert len(greens) >= 4
    assert all(d == pytest.approx(FAILSAFE_GREEN, abs=0.2) for d in greens)


def test_auto_mode_extends_green_when_cross_street_is_empty():
    e = make_engine("normal", spawn_rate=20.0, ped_spawn_rate=0.0,
                    direction_probs={"north": 0.5, "south": 0.5, "east": 0.0, "west": 0.0})
    log = phase_log(e, 200)
    # nobody waits on east/west, so NS green is never cut short: no phase change until MAX_GREEN
    assert log[0] == (0, pytest.approx(MAX_GREEN, abs=0.2))


def test_auto_mode_switches_early_when_current_group_is_idle():
    e = make_engine("normal", spawn_rate=15.0, ped_spawn_rate=0.0,
                    direction_probs={"north": 0.0, "south": 0.0, "east": 0.5, "west": 0.5})
    log = phase_log(e, 60)
    idx, dur = log[0]
    assert idx == 0 and MIN_GREEN - 0.2 <= dur < BASE_GREEN


def test_auto_mode_gap_out_never_goes_below_min_green():
    e = make_engine("heavy", ped_spawn_rate=0.0)
    greens = [d for idx, d in phase_log(e, 400) if idx in (0, 3)]
    assert len(greens) >= 6
    assert all(MIN_GREEN - 0.2 <= d <= MAX_GREEN + 0.2 for d in greens)


def test_green_reaches_base_length_when_both_streets_keep_a_queue():
    e = make_engine("traffic_jam", ped_spawn_rate=0.0)
    greens = [d for idx, d in phase_log(e, 400) if idx in (0, 3)]
    assert max(greens) == pytest.approx(BASE_GREEN, abs=0.3)
    assert min(greens) >= MIN_GREEN - 0.2


def test_pedestrians_only_start_crossing_while_their_arm_is_red():
    e = make_engine("pedestrian_rush", seed=7)
    started = 0
    for _ in range(4000):
        before = {pid: p.state for pid, p in e._pedestrians.items()}
        e._tick(0.1)
        for pid, p in e._pedestrians.items():
            if before.get(pid) == "waiting_for_green" and p.state == "crossing":
                started += 1
                arm = e._crossings[p.crossing_id].direction
                assert e._lights[f"TL-{arm[0].upper()}"].state == "RED"
    assert started > 20


def test_no_pedestrian_starves():
    e = make_engine("pedestrian_rush", seed=42)
    worst = 0.0
    for _ in range(6000):
        e._tick(0.1)
        for p in e._pedestrians.values():
            worst = max(worst, p.wait_time)
    assert worst < 2 * (BASE_GREEN + YELLOW_S + ALL_RED_S) * 2


def test_pedestrians_on_the_crosswalk_always_have_red_for_the_cars_crossing_it():
    e = make_engine("pedestrian_rush", seed=42)
    crossed_while = 0
    for _ in range(5000):
        e._tick(0.1)
        for p in e._pedestrians.values():
            if p.state == "crossing":
                crossed_while += 1
                arm = e._crossings[p.crossing_id].direction
                opposite = {"north": "south", "south": "north", "east": "west", "west": "east"}[arm]
                for d in (arm, opposite):
                    assert e._lights[f"TL-{d[0].upper()}"].state == "RED"
    assert crossed_while > 100


def _emergency_wait(e, direction, in_seconds=60):
    v = e.spawn_emergency(direction)
    assert v is not None
    worst = 0.0
    for _ in range(int(in_seconds * 10)):
        e._tick(0.1)
        if v.id in e._vehicles:
            worst = max(worst, v.wait_time)
        else:
            break
    return worst, v.id not in e._vehicles


def test_emergency_vehicle_on_red_arm_gets_green_quickly():
    e = idle()
    e.advance(2)                       # NS is green, the emergency vehicle comes from the east
    worst, passed = _emergency_wait(e, "east")
    assert passed
    assert worst <= EMERGENCY_MAX_WAIT


def test_emergency_vehicle_on_green_arm_is_not_stopped():
    e = idle()
    e.advance(2)
    worst, passed = _emergency_wait(e, "north")
    assert passed and worst == 0.0


EMERGENCY_MAX_WAIT = 14.0     # min green 5 s + yellow 3 s + all-red 3 s + braking margin


def test_emergency_priority_does_not_break_safety_invariants():
    e = make_engine("emergency", seed=42)
    v = check_invariants(e, seconds=300)
    assert all(count == 0 for count in v.values()), v


def test_emergency_scenario_really_spawns_emergency_vehicles():
    e = make_engine("emergency", seed=42)
    seen = set()
    for _ in range(3000):
        e._tick(0.1)
        seen |= {v.id for v in e._vehicles.values() if v.vehicle_type == "emergency"}
    assert len(seen) >= 3


def test_all_red_lasts_until_a_slow_long_vehicle_has_cleared_the_box():
    e = idle()
    tram = e._spawn.add_emergency_vehicle(0.0, "north")
    from smart_intersection.engine.models import VEHICLE_DEFAULTS
    d = VEHICLE_DEFAULTS["tram"]
    tram.vehicle_type, tram.length_m, tram.max_speed, tram.accel, tram.decel = "tram", d["length_m"], d["max_speed"], d["accel"], d["decel"]
    tram.id, tram.speed_mps = "tram-x", d["max_speed"]
    e._try_place(tram)
    ew_green_with_tram_in_zone = 0
    for _ in range(1500):
        e._tick(0.1)
        if e._phase_index == 3 and e._group_in_conflict_zone("ns"):
            ew_green_with_tram_in_zone += 1
    assert ew_green_with_tram_in_zone == 0
