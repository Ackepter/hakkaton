"""Layouts: model + validation, storage, world building, and physics on every preset / custom signal program."""
import asyncio

import pytest
from pydantic import ValidationError

from smart_intersection.engine.simulation import SimulationEngine
from smart_intersection.engine.world import build_world
from smart_intersection.layout import (
    Arm, CameraObject, Layout, LayoutStore, SceneObject, Signal, SignalPhase, default_layout, default_scenery,
    hits_road, presets, standard_program, validate_layout,
)
from .geo_helpers import run_checks
from .helpers import check_invariants

ZERO = dict(overlap=0, box_conflict=0, red_run=0, ped_hit=0, ped_stack=0, bad_state=0,
            speed_violation=0, backwards=0, early_removal=0, both_green=0)


def layout(**kw) -> Layout:
    l = default_layout()
    for k, v in kw.items():
        setattr(l, k, v)
    return l


def engine(l: Layout, **traffic) -> SimulationEngine:
    for k, v in traffic.items():
        setattr(l.traffic, k, v)
    return SimulationEngine(seed=42, layout=l)


# ---------------------------------------------------------------- model + validation

def test_default_layout_and_all_presets_are_valid():
    assert validate_layout(default_layout()) == []
    for name, l in presets().items():
        assert l.name == name and validate_layout(l) == [], name
    assert len(default_scenery()) == 24


@pytest.mark.parametrize("bad", [
    lambda: Arm(length_m=10), lambda: Arm(length_m=200), lambda: Arm(speed_limit_mps=0), lambda: Arm(weight=-1),
    lambda: Arm(lane_type="rocket"), lambda: SignalPhase(ns="GREEN", ew="RED", duration=0),
    lambda: SignalPhase(ns="PURPLE", ew="RED", duration=5), lambda: Signal(min_green=40, base_green=30),
    lambda: Signal(yellow=0), lambda: SceneObject(id="a", type="volcano", x=0, z=0),
    lambda: SceneObject(id="a b", type="tree", x=0, z=0), lambda: SceneObject(id="a", type="tree", x=999, z=0),
    lambda: SceneObject(id="a", type="tree", x=0, z=0, scale=10), lambda: SceneObject(id="a", type="tree", x=0, z=0, color="red"),
    lambda: CameraObject(id="c", x=0, z=0, radius_m=5), lambda: Layout(name="../evil"), lambda: Layout(name=""),
    lambda: Layout(arms={"north": Arm()}), lambda: Layout(cameras=[CameraObject(id=f"c{i}", x=0, z=0) for i in range(5)]),
    lambda: Layout(traffic={"type_probs": {"dragon": 1}}), lambda: Layout(traffic={"type_probs": {"car": 0}}),
])
def test_field_constraints_reject_bad_values(bad):
    with pytest.raises(ValidationError):
        bad()


def test_semantic_validation_finds_real_problems():
    l = default_layout()
    for a in l.arms.values():
        a.enabled = False
    assert "at least one arm" in validate_layout(l)[0]

    l = default_layout()
    l.scenery.append(SceneObject(id="oops", type="building", x=0, z=-40))           # in the middle of the north road
    l.scenery.append(SceneObject(id="oops2", type="tree", x=0, z=-18.5))            # on the north crosswalk
    errs = validate_layout(l)
    assert any("'oops'" in e for e in errs) and any("'oops2'" in e for e in errs)

    l = default_layout()
    l.scenery.append(SceneObject(id="t1", type="tree", x=50, z=50))                 # duplicate id (t1 exists)
    assert any("duplicate scenery ids" in e for e in validate_layout(l))

    l = default_layout()
    l.cameras = [CameraObject(id="c", x=0, z=0), CameraObject(id="c", x=5, z=5)]
    assert any("duplicate camera" in e for e in validate_layout(l))


def test_a_disabled_arm_frees_its_road_for_decoration():
    l = default_layout()
    l.scenery.append(SceneObject(id="park", type="building", x=40, z=0))
    assert validate_layout(l)                                                        # east road is there
    l.arms["east"].enabled = False
    assert validate_layout(l) == []
    l = default_layout()
    l.arms["north"].length_m = 40
    l.scenery.append(SceneObject(id="far", type="building", x=0, z=-60))             # beyond the shortened road
    assert validate_layout(l) == []


def test_fixed_program_must_be_collision_free_and_serve_every_group():
    l = default_layout()
    l.signal = Signal(mode="fixed", program=[SignalPhase(ns="GREEN", ew="GREEN", duration=10)])
    errs = validate_layout(l)
    assert any("same time" in e for e in errs)
    l.signal = Signal(mode="fixed", program=[SignalPhase(ns="GREEN", ew="RED", duration=10),
                                             SignalPhase(ns="RED", ew="RED", duration=3)])
    assert any("never gives green to east-west" in e for e in validate_layout(l))
    l.arms["east"].enabled = l.arms["west"].enabled = False                          # no EW arms: NS-only program is fine
    assert validate_layout(l) == []
    l.signal = Signal(mode="fixed", program=[])
    assert any("empty" in e for e in validate_layout(l))


def test_hits_road_is_geometry_not_a_bounding_box():
    l = default_layout()
    assert hits_road(l, 0, -40, 1) and hits_road(l, 10, 10, 1)          # road / box
    assert not hits_road(l, 6, -40, 1.5)                                # sidewalk beside the road
    assert not hits_road(l, 30, 30, 5)


# ---------------------------------------------------------------- storage

def test_store_roundtrip_list_delete(tmp_path):
    st = LayoutStore(str(tmp_path / "layouts"))
    assert st.list() == []
    l = presets()["Tram avenue"]
    st.save(l)
    assert st.list() == ["Tram avenue"]
    assert st.load("Tram avenue") == l
    st.save(l)                                                          # overwrite is fine
    st.delete("Tram avenue")
    assert st.list() == []
    with pytest.raises(FileNotFoundError):
        st.load("Tram avenue")
    with pytest.raises(FileNotFoundError):
        st.delete("Tram avenue")


@pytest.mark.parametrize("name", ["../secret", "a/b", "a\\b", "", ".hidden", "x" * 41, "con:"])
def test_store_rejects_dangerous_names(tmp_path, name):
    st = LayoutStore(str(tmp_path))
    with pytest.raises(ValueError):
        st.load(name)
    with pytest.raises(ValueError):
        st.delete(name)


def test_store_survives_a_corrupt_file(tmp_path):
    (tmp_path / "broken.json").write_text("{not json")
    st = LayoutStore(str(tmp_path))
    with pytest.raises(ValueError):
        st.load("broken")


# ---------------------------------------------------------------- world

def test_world_contains_only_enabled_arms_and_crossings():
    l = default_layout()
    l.arms["south"].enabled = False
    l.arms["east"].crossing = False
    lanes, lights, crossings = build_world(l)
    assert set(lights) == {"TL-N", "TL-E", "TL-W"} and set(crossings) == {"PC-N", "PC-W"}
    assert {k for k in lanes if k.endswith("-in")} == {"north-in", "east-in", "west-in"}


def test_arm_length_moves_the_spawn_point_and_opposite_arm_sets_the_route_end():
    l = default_layout()
    l.arms["north"].length_m = 50
    l.arms["south"].length_m = 40
    lanes, _, _ = build_world(l)
    assert lanes["north-in"].spawn_pos == 30 and lanes["south-in"].spawn_pos == 40
    assert lanes["north-in"].length_m == 80 + 40                        # leaves through the (shorter) south arm
    assert lanes["south-in"].length_m == 80 + 50


def test_missing_opposite_arm_makes_a_dead_end_right_after_the_box():
    l = default_layout()
    l.arms["south"].enabled = False
    lanes, _, _ = build_world(l)
    assert lanes["north-in"].length_m == pytest.approx(80 + 16 + 6)


# ---------------------------------------------------------------- traffic generation per layout

def run(e, seconds):
    e.advance(seconds)
    return e


def test_no_traffic_ever_appears_on_a_disabled_arm():
    e = engine(presets()["T-junction"], spawn_rate=60.0)
    seen = set()
    for _ in range(1500):
        e._tick(0.1)
        seen |= {v.direction for v in e._vehicles.values()}
    assert seen == {"north", "east", "west"}
    assert set(e.get_state()["lights"][i]["id"] for i in range(3)) == {"TL-N", "TL-E", "TL-W"}


def test_arm_weight_controls_the_share_of_arrivals():
    l = default_layout()
    l.arms["north"].weight = 3.0
    e = engine(l, spawn_rate=30.0)
    counts = {}
    ids = set()
    for _ in range(3000):
        e._tick(0.1)
        for v in e._vehicles.values():
            if v.id not in ids:
                ids.add(v.id)
                counts[v.direction] = counts.get(v.direction, 0) + 1
    others = [n for d, n in counts.items() if d != "north"]
    assert counts["north"] > 1.8 * max(others)                                  # expected ratio is 3


def test_bus_lane_and_tram_track_only_carry_their_own_vehicle_type():
    l = presets()["Tram avenue"]
    e = engine(l, spawn_rate=60.0)
    seen = {}
    for _ in range(3000):
        e._tick(0.1)
        for v in e._vehicles.values():
            seen.setdefault(v.direction, set()).add(v.vehicle_type)
    assert seen["east"] == {"tram"} and seen["west"] == {"tram"}
    assert "car" in seen["north"]
    l = presets()["Bus street"]
    e = engine(l, spawn_rate=60.0)
    seen = {}
    for _ in range(2000):
        e._tick(0.1)
        for v in e._vehicles.values():
            seen.setdefault(v.direction, set()).add(v.vehicle_type)
    assert seen["north"] == {"bus"} and seen["south"] == {"bus"}


def test_speed_limit_and_start_position_of_an_arm_are_respected():
    l = default_layout()
    l.arms["east"].speed_limit_mps = 5.0
    l.arms["east"].length_m = 50.0
    e = engine(l, spawn_rate=60.0)
    first_pos, top = [], 0.0
    for _ in range(2000):
        e._tick(0.1)
        for v in e._vehicles.values():
            if v.direction == "east":
                top = max(top, v.speed_mps)
                if v.state == "driving" and v.speed_mps > 0 and v.position_m < 31:
                    first_pos.append(v.position_m)
    assert 0 < top <= 5.0 + 1e-9
    assert first_pos and min(first_pos) >= 30.0 - 1e-6


def test_layout_traffic_settings_are_the_starting_configuration():
    l = default_layout()
    l.traffic.spawn_rate, l.traffic.ped_spawn_rate = 33.0, 21.0
    l.traffic.type_probs = {"truck": 1.0}
    e = SimulationEngine(layout=l)
    assert e._spawn.spawn_rate == 33.0 and e._spawn.ped_spawn_rate == 21.0
    e.advance(60)
    assert {v.vehicle_type for v in e._vehicles.values()} <= {"truck"}


# ---------------------------------------------------------------- physics on every preset

@pytest.mark.parametrize("name", sorted(presets()))
@pytest.mark.parametrize("seed", [42, 7])
def test_every_preset_is_physically_valid(name, seed):
    l = presets()[name]
    l.traffic.spawn_rate = max(l.traffic.spawn_rate, 30.0)
    l.traffic.ped_spawn_rate = max(l.traffic.ped_spawn_rate, 15.0)
    e = SimulationEngine(seed=seed, layout=l)
    if e._use_zones:                    # turns / u-turns / roundabouts: vehicles leave the straight lane grid
        assert run_checks(e, 240) == dict.fromkeys(("overlap", "red_run", "stuck", "off_path", "ped_hit", "backwards"), 0)
    else:
        assert check_invariants(e, seconds=240) == ZERO


def test_layout_with_shortened_and_dead_end_arms_stays_valid():
    l = default_layout()
    l.arms["north"].length_m = 35
    l.arms["south"].enabled = False
    l.arms["east"].length_m = 45
    l.arms["west"].crossing = False
    l.traffic.spawn_rate = 45
    e = SimulationEngine(seed=3, layout=l)
    assert check_invariants(e, seconds=300) == ZERO
    assert e.get_state()["metrics"]["passed_total"] > 20


# ---------------------------------------------------------------- user signal programs

def program_layout(phases, **kw) -> Layout:
    l = default_layout()
    l.signal = Signal(mode="fixed", program=phases)
    l.traffic.spawn_rate, l.traffic.ped_spawn_rate = 30.0, 12.0
    for k, v in kw.items():
        setattr(l, k, v)
    return l


def phase_log(e, seconds, dt=0.1):
    log, last, start = [], e._phase_index, e.sim_time
    for _ in range(int(seconds / dt)):
        e._tick(dt)
        if e._phase_index != last:
            log.append((last, round(e.sim_time - start, 1)))
            last, start = e._phase_index, e.sim_time
    return log


def test_fixed_program_runs_exactly_as_written():
    prog = [SignalPhase(ns="GREEN", ew="RED", duration=12), SignalPhase(ns="YELLOW", ew="RED", duration=2),
            SignalPhase(ns="RED", ew="RED", duration=4), SignalPhase(ns="RED", ew="GREEN", duration=7),
            SignalPhase(ns="RED", ew="YELLOW", duration=2), SignalPhase(ns="RED", ew="RED", duration=4)]
    e = SimulationEngine(layout=program_layout(prog))
    log = phase_log(e, 90)
    assert [i for i, _ in log[:6]] == [0, 1, 2, 3, 4, 5]
    for (i, d), p in zip(log[:6], prog):
        assert d == pytest.approx(p.duration, abs=0.15)
    assert e.get_state()["signal_mode"] == "fixed"


def test_program_states_reach_the_lights():
    prog = [SignalPhase(ns="GREEN", ew="RED", duration=5), SignalPhase(ns="YELLOW", ew="RED", duration=2),
            SignalPhase(ns="RED", ew="GREEN", duration=5), SignalPhase(ns="RED", ew="YELLOW", duration=2)]
    e = SimulationEngine(layout=program_layout(prog))
    seen = set()
    for _ in range(300):
        e._tick(0.1)
        seen.add((e._lights["TL-N"].state, e._lights["TL-E"].state))
    assert seen == {("GREEN", "RED"), ("YELLOW", "RED"), ("RED", "GREEN"), ("RED", "YELLOW")}


def test_custom_program_with_long_greens_and_clearance_is_physically_valid():
    prog = [SignalPhase(ns="GREEN", ew="RED", duration=45), SignalPhase(ns="YELLOW", ew="RED", duration=4),
            SignalPhase(ns="RED", ew="RED", duration=6), SignalPhase(ns="RED", ew="GREEN", duration=20),
            SignalPhase(ns="RED", ew="YELLOW", duration=4), SignalPhase(ns="RED", ew="RED", duration=6)]
    e = SimulationEngine(seed=11, layout=program_layout(prog))
    assert check_invariants(e, seconds=300) == ZERO
    assert e.get_state()["metrics"]["peds_crossed_total"] > 10


def test_pedestrians_only_walk_when_the_program_leaves_enough_red_time():
    """EW gets a 3 s red window only: nobody may start crossing the east/west crosswalks in it."""
    prog = [SignalPhase(ns="RED", ew="GREEN", duration=40), SignalPhase(ns="RED", ew="YELLOW", duration=3),
            SignalPhase(ns="GREEN", ew="RED", duration=3), SignalPhase(ns="YELLOW", ew="RED", duration=2),
            SignalPhase(ns="RED", ew="RED", duration=3)]
    e = SimulationEngine(seed=5, layout=program_layout(prog))
    started = {"PC-N": 0, "PC-E": 0}
    for _ in range(4000):
        before = {pid: p.state for pid, p in e._pedestrians.items()}
        e._tick(0.1)
        for pid, p in e._pedestrians.items():
            if before.get(pid) == "waiting_for_green" and p.state == "crossing" and p.crossing_id in started:
                started[p.crossing_id] += 1
    assert started["PC-N"] > 0        # north/south crosswalks get long red windows during EW green
    assert started["PC-E"] == 0       # EW is red for only 3+2+3 = 8 s < 9.6 s crossing time


def test_ns_only_layout_with_a_program_needs_no_ew_phase():
    l = presets()["Two-way street"]
    l.signal = Signal(mode="fixed", program=[SignalPhase(ns="GREEN", ew="RED", duration=20),
                                             SignalPhase(ns="YELLOW", ew="RED", duration=3),
                                             SignalPhase(ns="RED", ew="RED", duration=25)])
    l.traffic.spawn_rate, l.traffic.ped_spawn_rate = 30, 15
    assert validate_layout(l) == []
    e = SimulationEngine(seed=2, layout=l)
    assert check_invariants(e, seconds=240) == ZERO
    assert e.get_state()["metrics"]["peds_crossed_total"] > 5           # the long all-red is a pedestrian window


def test_adaptive_parameters_from_the_layout_are_used():
    l = default_layout()
    l.signal = Signal(base_green=12, min_green=6, max_green=20, yellow=2, all_red=2)
    l.traffic.spawn_rate, l.traffic.ped_spawn_rate = 50, 0
    e = SimulationEngine(layout=l)
    log = phase_log(e, 200)
    yellows = [d for i, d in log if i in (1, 4)]
    greens = [d for i, d in log if i in (0, 3)]
    assert yellows and all(y == pytest.approx(2.0, abs=0.15) for y in yellows)
    assert greens and max(greens) <= 20.2 and min(greens) >= 5.8


# ---------------------------------------------------------------- lifecycle + interactive spawning

def test_set_layout_validates_and_restarts_the_world():
    e = SimulationEngine(seed=1)
    e.advance(30)
    bad = default_layout()
    bad.signal = Signal(mode="fixed", program=[SignalPhase(ns="GREEN", ew="GREEN", duration=5)])
    with pytest.raises(ValueError, match="same time"):
        e.set_layout(bad)
    assert e.sim_time > 0                                               # a rejected layout changes nothing
    e.set_layout(presets()["T-junction"])
    assert e.sim_time == 0 and not e._vehicles and "south-in" not in e._lanes and e.get_state()["layout_name"] == "T-junction"


async def test_apply_layout_stops_a_running_simulation_and_reset_keeps_the_layout():
    e = SimulationEngine(seed=1)
    await e.start()
    await e.apply_layout(presets()["Two-way street"])
    assert e.status == "stopped" and set(e._crossings) == {"PC-N", "PC-S"}
    await e.reset()
    assert e.layout.name == "Two-way street" and "east-in" not in e._lanes


def test_interactive_spawning():
    e = SimulationEngine(seed=1, layout=presets()["T-junction"])
    e.configure(spawn_rate=0.0, ped_spawn_rate=0.0)
    v = e.spawn_vehicle("north", "truck")
    assert v and v.vehicle_type == "truck" and v.id in e._vehicles
    assert e.spawn_vehicle("south") is None                             # arm does not exist
    assert e.spawn_vehicle("north", "dragon") is None                   # unknown type
    assert e.spawn_vehicle("north") is None                             # entry still occupied by the truck
    p = e.spawn_pedestrian("PC-E")
    assert p and p.id in e._pedestrians and p.state == "walking_to_crossing"
    assert e.spawn_pedestrian("PC-S") is None
    e.advance(60)
    assert e.get_state()["metrics"]["passed_total"] + len(e._vehicles) >= 1


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_shortest_arms_never_let_a_car_run_the_light(seed):
    """Regression: a car entering 6 m before the stop line at full speed cannot stop and ran the red."""
    l = default_layout()
    for a in l.arms.values():
        a.length_m = 30.0
    l.traffic.spawn_rate, l.traffic.ped_spawn_rate = 60, 20
    e = SimulationEngine(seed=seed, layout=l)
    assert check_invariants(e, seconds=240) == ZERO
    assert e.get_state()["metrics"]["passed_total"] > 30
