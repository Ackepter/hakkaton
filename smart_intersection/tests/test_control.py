"""Signal control tests: phase order and timing, adaptive green, failsafe, pedestrians, emergency priority."""
import pytest

from smart_intersection.engine.simulation import (
    SimulationEngine, PHASES, YELLOW_S, ALL_RED_S, MAX_ALL_RED_S, BASE_GREEN, MIN_GREEN, FAILSAFE_GREEN, MAX_GREEN,
)
from smart_intersection.layout import default_layout
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
    e = make_engine("normal", control_mode="failsafe")
    assert e.control_mode == "failsafe"
    greens = [d for idx, d in phase_log(e, 300) if idx in (0, 3)]
    assert len(greens) >= 4
    assert all(d == pytest.approx(FAILSAFE_GREEN, abs=0.2) for d in greens)


def test_auto_mode_extends_green_when_cross_street_is_empty():
    e = make_engine("normal", spawn_rate=20.0, ped_spawn_rate=0.0,
                    direction_probs={"north": 0.5, "south": 0.5, "east": 0.0, "west": 0.0})
    for _ in range(2000):
        e.set_perception({"camera_ok": True, "vehicles": {"north": 5, "south": 4, "east": 0, "west": 0}})
        e._tick(0.1)
    assert e._phase_index == 0
    assert all(light.phase_switches == 0 for light in e._lights.values())


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


# ──── camera perception channel ────

def test_signals_follow_camera_data_instead_of_ground_truth():
    """Cars are queued on north/south, but the camera reports demand only on east -> NS green is cut at MIN_GREEN."""
    e = make_engine("normal", spawn_rate=30.0, ped_spawn_rate=0.0,
                    direction_probs={"north": 0.5, "south": 0.5, "east": 0.0, "west": 0.0})
    e.set_perception({"camera_ok": True, "vehicles": {"east": 4}})
    log = []
    last = e._phase_index
    start = e.sim_time
    for _ in range(300):
        e.set_perception({"camera_ok": True, "vehicles": {"east": 4}})     # camera keeps reporting
        e._tick(0.1)
        if e._phase_index != last:
            log.append((last, round(e.sim_time - start, 1)))
            break
    assert log and log[0][0] == 0 and log[0][1] == pytest.approx(MIN_GREEN, abs=0.3)


def test_stale_camera_data_triggers_failsafe_and_recovers_when_data_returns():
    e = idle()
    e.set_perception({"camera_ok": True})
    assert e.failsafe_reason() is None
    e.advance(5)                                          # no new data for > 3 s
    assert e.failsafe_reason() == "camera data lost"
    e.set_perception({"camera_ok": True})
    assert e.failsafe_reason() is None


def test_camera_reported_unavailable_gives_fixed_greens():
    e = idle()
    e.set_perception({"camera_ok": False})
    greens = []
    last, start = e._phase_index, e.sim_time
    for _ in range(3000):
        e.set_perception({"camera_ok": False})
        e._tick(0.1)
        if e._phase_index != last:
            if last in (0, 3):
                greens.append(round(e.sim_time - start, 1))
            last, start = e._phase_index, e.sim_time
    assert e.failsafe_reason() == "camera unavailable"
    assert len(greens) >= 3 and all(g == pytest.approx(FAILSAFE_GREEN, abs=0.2) for g in greens)


def test_perception_staleness_is_scaled_by_time_scale():
    e = idle(time_scale=10)
    e.set_perception({"camera_ok": True})
    e.advance(20)                                         # 20 sim-s = 2 real s at 10x, inside 3 s * 10
    assert e.failsafe_reason() is None
    e.advance(15)
    assert e.failsafe_reason() == "camera data lost"


def test_clear_perception_returns_to_ground_truth():
    e = idle()
    e.set_perception({"camera_ok": False})
    e.clear_perception()
    assert e.failsafe_reason() is None and e.get_state()["perception"]["active"] is False


def test_camera_failure_flag_and_reset():
    e = idle()
    e.configure(camera_failure=True)
    assert e.failsafe_reason() == "camera failure"
    e.set_perception({"camera_ok": True})
    assert not e._perception_usable()                     # a pushed frame does not help while unplugged
    import asyncio
    asyncio.run(e.reset())
    assert e.failsafe_reason() is None and e._perception is None


# ──── pedestrian priority (Task 13) ────

def _crowd(e, crossing="PC-N", n=6, direction=1):
    from smart_intersection.engine.models import Pedestrian
    for i in range(n):
        p = Pedestrian(f"crowd-{crossing}-{i}", crossing, "waiting_for_green", 0.0, 0.0, direction=direction,
                       offset=-1.2 + 0.3 * i)
        e._pedestrians[p.id] = p


def _first_green_length(e, max_s=70):
    last, start, seen = e._phase_index, e.sim_time, None
    for _ in range(int(max_s * 10)):
        e._tick(0.1)
        if e._phase_index != last:
            return round(e.sim_time - start, 1)
    return None


def test_crowd_of_pedestrians_cuts_the_conflicting_green_short():
    """Local simulation keeps its timer plan; a crowd on the opposing stage earns priority."""
    kw = dict(spawn_rate=30.0, ped_spawn_rate=0.0, direction_probs={"north": 0.5, "south": 0.5, "east": 0.0, "west": 0.0})
    calm = make_engine("normal", **kw)
    assert _first_green_length(calm) == pytest.approx(MAX_GREEN, abs=0.3)
    crowded = make_engine("normal", **kw)
    _crowd(crowded)
    assert _first_green_length(crowded) == pytest.approx(MIN_GREEN, abs=0.3)


def test_a_small_group_of_pedestrians_does_not_trigger_priority():
    e = make_engine("normal", spawn_rate=0.0, ped_spawn_rate=0.0)
    _crowd(e, n=2)
    e.set_perception({"camera_ok": True, "vehicles": {"north": 3}, "pedestrians_waiting": {"PC-N": 2}})
    assert _first_green_length(e) > MIN_GREEN + 5


def test_pedestrian_priority_also_works_from_the_camera_flag():
    e = make_engine("normal", spawn_rate=30.0, ped_spawn_rate=0.0,
                    direction_probs={"north": 0.5, "south": 0.5, "east": 0.0, "west": 0.0})
    last, start = e._phase_index, e.sim_time
    for _ in range(700):
        e.set_perception({"camera_ok": True, "vehicles": {"north": 3}, "pedestrians_waiting": {"PC-N": 6},
                          "ped_priority": {"PC-N": True}})
        e._tick(0.1)
        if e._phase_index != last:
            break
    assert e.sim_time - start == pytest.approx(MIN_GREEN, abs=0.3)


def test_camera_priority_is_exposed_for_the_live_screen_and_falls_back_without_camera():
    e = idle()
    e.set_perception({"camera_ok": True, "vehicles": {"east": 1}, "pedestrians_waiting": {"PC-N": 8},
                      "ped_priority": {"PC-N": True}})
    assert e.get_state()["camera_priority"] == {
        "camera_ok": True, "recipient": "pedestrians", "vehicles": 1, "pedestrians": 8,
    }

    e.set_perception({"camera_ok": True, "vehicles": {"east": 8}, "pedestrians_waiting": {"PC-N": 5},
                      "ped_priority": {"PC-N": True}})
    assert e.get_state()["camera_priority"]["recipient"] == "drivers"
    assert e._ped_priority(next(s for s in range(len(e._stages)) if e._serves(s, "PC-N"))) is False

    e.set_perception({"camera_ok": False})
    assert e.get_state()["camera_priority"] == {
        "camera_ok": False, "recipient": None, "vehicles": 0, "pedestrians": 0,
    }


def test_camera_mode_holds_green_when_perpendicular_approach_is_empty():
    e = idle()
    for _ in range(1200):
        e.set_perception({"camera_ok": True, "vehicles": {"north": 1}})
        e._tick(0.1)

    assert e._phase_index == 0
    assert all(light.phase_switches == 0 for light in e._lights.values())


def test_pedestrian_crosses_a_single_arm_layout_instead_of_waiting_forever():
    layout = default_layout()
    for arm in ("south", "east", "west"):
        layout.arms[arm].enabled = False
    layout.arms["north"].lanes_out = 2
    layout.arms["north"].turns = [["uturn"]]
    e = SimulationEngine(seed=42, layout=layout)
    e.configure(spawn_rate=0.0, ped_spawn_rate=0.0)
    ped = e.spawn_pedestrian("PC-N")

    e.advance(60)

    assert ped.crossing_id == "PC-N"
    assert e.get_state()["metrics"]["peds_crossed_total"] == 1
