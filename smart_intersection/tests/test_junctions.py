"""
Lanes, turns, u-turns and roundabouts: the layout model, the routes vehicles drive, the signal stages, and the
physical rules (no overlaps, no red-light running, nobody stuck) on every ready-made junction type.
"""
import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from smart_intersection.engine.simulation import SimulationEngine
from smart_intersection.geometry import (build_paths, crossing_stages, lane_id, needs_zones, path_zones, pedestrian_xz,
                                         scene_geometry)
from smart_intersection.layout import (ARMS, JUNCTION_TYPES, Arm, Layout, SignalPhase, box_half, compatible, default_layout,
                                       hits_road, is_split, junction_types, lane_moves, min_arm_length, presets, stages,
                                       target_arm, turns_conflict, validate_layout)
from .geo_helpers import corners, rects_overlap, run_checks

ZERO = dict.fromkeys(("overlap", "red_run", "stuck", "off_path", "ped_hit", "backwards"), 0)
NEW_TYPES = sorted(JUNCTION_TYPES)


def layout_with(**arms):
    l = default_layout()
    for arm, cfg in arms.items():
        for k, v in cfg.items():
            setattr(l.arms[arm], k, v)
    l.scenery = [o for o in l.scenery if not hits_road(l, o.x, o.z, 1.0)]
    return l


def run_until_done(e: SimulationEngine, vid: str, seconds: float = 200.0):
    """Follow one vehicle to the end of its trip: [(x, z, heading)] per tick."""
    trail = []
    for _ in range(int(seconds / 0.1)):
        e._tick(0.1)
        v = e._vehicles.get(vid)
        if v is None:
            return trail
        trail.append((v.x, v.z, v.heading, v.speed_mps, v.state))
    raise AssertionError(f"{vid} did not finish")


def quiet_engine(layout, seed=1):
    l = layout.model_copy(deep=True)
    l.traffic.spawn_rate = 0.0
    l.traffic.ped_spawn_rate = 0.0
    return SimulationEngine(seed=seed, layout=l)


# ------------------------------------------------------------------------------------------ the layout model

@pytest.mark.parametrize("lanes,box", [(1, 16.0), (2, 16.0), (3, 20.0), (4, 24.0)])
def test_the_centre_grows_with_the_widest_road(lanes, box):
    l = layout_with(east={"lanes_in": lanes, "lanes_out": 1})
    assert box_half(l) == box
    assert min_arm_length(l) == box + 14
    e = SimulationEngine(layout=l)
    assert max(p.box_entry_s for p in e._paths.values()) == pytest.approx(80 - box)     # the routes enter the bigger centre
    assert e._lanes["north-in"].stop_line_m == pytest.approx(80 - (box + 5))


def test_outbound_lanes_widen_the_road_too():
    assert box_half(layout_with(west={"lanes_in": 1, "lanes_out": 4})) == 24.0


def test_roads_that_do_not_fit_the_bigger_centre_are_refused():
    l = layout_with(east={"lanes_in": 4, "length_m": 30})
    errs = validate_layout(l)
    assert any("east road is too short" in e and "38" in e for e in errs), errs
    l.arms["east"].length_m = 38
    assert not validate_layout(l)


def test_scenery_may_not_stand_on_the_widened_road():
    l = default_layout()
    l.scenery = []
    from smart_intersection.layout import SceneObject
    l.scenery.append(SceneObject(id="t", type="tree", x=10, z=-45))          # just beside a 1-lane north road
    assert not validate_layout(l)
    l.arms["north"].lanes_out = 4                                             # the road now reaches x = 16
    assert any("stands on the road" in e for e in validate_layout(l))


def test_turn_lists_are_validated():
    with pytest.raises(ValidationError):
        Arm(lanes_in=2, turns=[["left"]])                                    # one entry per inbound lane
    with pytest.raises(ValidationError):
        Arm(lanes_in=1, turns=[[]])                                          # a lane must allow something
    with pytest.raises(ValidationError):
        Arm(lanes_in=1, turns=[["left", "left"]])
    with pytest.raises(ValidationError):
        Arm(lanes_in=5)
    assert Arm(lanes_in=2, turns=[["left", "uturn"], ["straight", "right"]]).lane_turns()[0] == ["left", "uturn"]
    assert Arm(lanes_in=3).lane_turns() == [["straight"]] * 3                # default: straight on


def test_a_movement_towards_a_missing_road_is_refused():
    l = layout_with(north={"turns": [["left"]]}, east={"enabled": False})
    assert any("lane 1" in e and "does not exist" in e for e in validate_layout(l))
    l.arms["north"].turns = [["left", "straight"]]                            # straight is always possible (dead end)
    assert not validate_layout(l)


@pytest.mark.parametrize("move,expected", [
    ("straight", {"north": "south", "east": "west"}), ("right", {"north": "west", "south": "east", "east": "north", "west": "south"}),
    ("left", {"north": "east", "south": "west", "east": "south", "west": "north"}), ("uturn", {"north": "north"})])
def test_targets_follow_right_hand_traffic(move, expected):
    for arm, target in expected.items():
        assert target_arm(arm, move) == target


def test_layouts_with_turns_and_cameras_survive_a_json_roundtrip():
    l = presets()["Avenue with U-turn"]
    again = Layout.model_validate_json(l.model_dump_json())
    assert again == l and again.arms["east"].turns == [["left", "uturn"], ["straight", "right"]]
    assert again.cameras[0].height_m == 14 and again.cameras[0].yaw_deg is None
    old = default_layout().model_dump()
    for k in ("junction",):
        old.pop(k)
    for arm in old["arms"].values():
        for k in ("lanes_in", "lanes_out", "turns"):
            arm.pop(k)
    assert Layout.model_validate(old).arms["north"].lanes_in == 1              # layouts saved before lanes existed still load


# ------------------------------------------------------------------------------------------ junction types

def test_there_are_at_least_six_new_junction_types_with_their_logic_described():
    assert len(NEW_TYPES) >= 6
    catalogue = {t["name"]: t for t in junction_types()}
    for name in NEW_TYPES:
        assert name in presets() and name in catalogue and len(catalogue[name]["description"]) > 30
        assert not validate_layout(presets()[name]), name
    kinds = {t["junction"] for t in catalogue.values()}
    assert kinds == {"signal", "roundabout"}


def test_a_four_lane_avenue_with_a_u_turn_exists_and_drives_forward_or_into_the_left_lane():
    l = presets()["Avenue with U-turn"]
    assert l.arms["east"].lanes_in + l.arms["east"].lanes_out == 4 and l.arms["west"].lanes_in + l.arms["west"].lanes_out == 4
    assert lane_moves(l, "east", 0) == ["left", "uturn"] and lane_moves(l, "east", 1) == ["straight", "right"]
    paths = build_paths(l)
    through = [p for p in paths.values() if p.lane_id == "east-in-1" and p.movement == "straight"]
    assert {p.exit_lane for p in through} == {0, 1}                          # forward, or over into the left lane after the crossing
    ends = {p.exit_lane: p.at(p.length) for p in through}
    assert ends[0][1] == pytest.approx(-2.0, abs=0.01) and ends[1][1] == pytest.approx(-6.0, abs=0.01)   # west road: left lane z = -2, next z = -6


def test_stages_split_only_where_turns_cross_the_opposing_flow():
    assert stages(default_layout()) == [("north", "south"), ("east", "west")]
    assert stages(presets()["No-left crossroads"]) == [("north", "south"), ("east", "west")]      # rights do not cross oncoming cars
    assert stages(presets()["Turn crossroads"]) == [("north",), ("south",), ("east",), ("west",)]
    assert stages(presets()["T-junction with turns"]) == [("north",), ("east",), ("west",)]
    mixed = layout_with(east={"turns": [["left"]]})                          # one arm with a left turn splits its pair only
    assert stages(mixed) == [("north", "south"), ("east",), ("west",)]
    assert is_split(presets()["Turn crossroads"]) and not is_split(default_layout())
    assert compatible(default_layout(), "north", "south") and not compatible(presets()["Turn crossroads"], "north", "south")
    assert turns_conflict(presets()["Turn crossroads"], "north") and not turns_conflict(default_layout(), "north")


def test_fixed_programs_may_open_only_compatible_arms_together():
    l = presets()["Turn crossroads"]
    l.signal.mode = "fixed"
    l.signal.program = [SignalPhase(ns="GREEN", ew="RED", duration=10), SignalPhase(ns="RED", ew="GREEN", duration=10)]
    errs = validate_layout(l)
    assert any("same time" in e for e in errs)                               # north + south together would collide
    steps = []
    for a in ARMS:
        steps += [SignalPhase(ns="RED", ew="RED", duration=10, arms={x: "GREEN" if x == a else "RED" for x in ARMS}),
                  SignalPhase(ns="RED", ew="RED", duration=3, arms={x: "RED" for x in ARMS})]
    l.signal.program = steps
    assert not validate_layout(l)
    l.signal.program = steps[:-2]
    assert any("never gives green to west" in e for e in validate_layout(l))


def test_a_fixed_program_with_per_arm_lamps_is_executed_on_a_split_junction():
    l = presets()["Turn crossroads"]
    l.signal.mode = "fixed"
    l.signal.program = [SignalPhase(ns="RED", ew="RED", duration=10, arms={x: "GREEN" if x == a else "RED" for x in ARMS})
                        for a in ARMS]
    e = SimulationEngine(layout=l)
    seen = []
    for _ in range(450):
        e._tick(0.1)
        greens = tuple(sorted(li.direction for li in e._lights.values() if li.state == "GREEN"))
        if not seen or seen[-1] != greens:
            seen.append(greens)
    assert seen[:5] == [("north",), ("south",), ("east",), ("west",), ("north",)]


# ------------------------------------------------------------------------------------------ routes

def test_every_route_starts_on_its_lane_and_ends_on_the_lane_it_names():
    for name in ["Crossroads", *NEW_TYPES]:
        l = presets()[name]
        for p in build_paths(l).values():
            x0, z0, _ = p.at(0)
            assert (x0, z0) == pytest.approx(p.points[0]), (name, p.id)
            sx, sz = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}[p.arm]
            assert abs(sx * x0 + sz * z0) == pytest.approx(80.0, abs=0.01), (name, p.id)      # 80 m out on its own arm
            ex, ez, _ = p.at(p.length)
            tx, tz = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}[p.exit_arm]
            assert tx * ex + tz * ez == pytest.approx(l.arms[p.exit_arm].length_m if l.arms[p.exit_arm].enabled
                                                      else box_half(l) + 6.0, abs=0.01), (name, p.id)


def test_routes_are_smooth_and_the_bends_slow_vehicles_down():
    for name in NEW_TYPES:
        l = presets()[name]
        for p in build_paths(l).values():
            for k in range(1, int(p.length)):
                (xa, za, ha), (xb, zb, hb) = p.at(k - 1.0), p.at(float(k))
                assert math.hypot(xb - xa, zb - za) == pytest.approx(1.0, abs=0.35), (name, p.id, k)     # no jumps
                turn = abs((hb - ha + math.pi) % (2 * math.pi) - math.pi)
                assert turn < 0.85, (name, p.id, k)                                                     # no sharp corners
            if p.movement in ("left", "right", "uturn") or l.junction == "roundabout":
                assert p.speed_cap < 8.0, (name, p.id)
            else:
                assert p.speed_cap > 11.0, (name, p.id)


def test_u_turns_and_long_vehicles():
    e = quiet_engine(presets()["Avenue with U-turn"])
    assert e.spawn_vehicle("east", "car", lane=0, movement="uturn") is not None
    assert e.spawn_vehicle("east", "truck", lane=0, movement="uturn") is None       # too long for a 4 m wide u-turn
    assert e.spawn_vehicle("west", "tram", lane=0, movement="left") is None         # a tram cannot corner
    assert e.spawn_vehicle("west", "tram", lane=1, movement="straight") is not None
    assert e.spawn_vehicle("east", "car", lane=1, movement="uturn") is None         # lane 2 has no u-turn arrow
    assert e.spawn_vehicle("east", "car", lane=5) is None


@pytest.mark.parametrize("move", ["left", "right", "uturn", "straight"])
def test_a_vehicle_turns_and_leaves_on_the_right_road_the_right_way_round(move):
    l = presets()["Turn crossroads"] if move != "uturn" else presets()["Avenue with U-turn"]
    e = quiet_engine(l)
    lane = 0 if move in ("left", "uturn") else 1
    v = e.spawn_vehicle("east", "car", lane=lane, movement=move)
    e.set_light_state("TL-E", "GREEN")
    assert v is not None and v.movement == move
    trail = run_until_done(e, v.id)
    x, z, heading = trail[-1][:3]
    expected = target_arm("east", move)
    assert {"north": z < -40, "south": z > 40, "east": x > 40, "west": x < -40}[expected], (move, x, z)
    heading_out = {"north": -math.pi / 2, "south": math.pi / 2, "east": 0.0, "west": math.pi}[expected]
    assert abs((heading - heading_out + math.pi) % (2 * math.pi) - math.pi) < 0.1
    assert heading == pytest.approx(math.pi, abs=0.05) or trail[0][2] == pytest.approx(math.pi, abs=0.05)   # it started heading west
    assert min(t[3] for t in trail[10:60]) >= 0
    assert max(t[3] for t in trail) <= 13.9 + 1e-6


def test_turning_vehicles_slow_down_for_the_bend():
    e = quiet_engine(presets()["Turn crossroads"])
    v = e.spawn_vehicle("east", "car", lane=0, movement="left")
    e.set_light_state("TL-E", "GREEN")
    path = e._paths[v.path_id]
    speeds = []
    for _ in range(1500):
        e._tick(0.1)
        if v.id not in e._vehicles:
            break
        if path.box_entry_s < v.position_m < path.box_exit_s:
            speeds.append(v.speed_mps)
    assert speeds and max(speeds) <= path.speed_cap + 0.05 and path.speed_cap < 8


def test_vehicles_wait_for_red_in_every_lane_and_turn_only_on_green():
    e = quiet_engine(presets()["Turn crossroads"])
    ids = [e.spawn_vehicle("north", "car", lane=i, movement=m).id for i, m in ((0, "left"), (1, "right"))]
    e.set_light_state("TL-N", "RED")
    for _ in range(400):
        e._tick(0.1)
    for vid in ids:
        v = e._vehicles[vid]
        lane = e._lanes[v.lane_id]
        assert v.position_m + v.length_m / 2 <= lane.stop_line_m + 0.3 and v.speed_mps < 0.1 and v.state == "waiting"
    e.set_light_state("TL-N", "GREEN")
    for _ in range(800):
        e._tick(0.1)
    assert not e._vehicles                                                       # both drove off after the switch


def test_the_stage_after_a_protected_green_starts_only_when_the_box_is_empty():
    e = SimulationEngine(seed=5, layout=presets()["Turn crossroads"])
    for _ in range(3000):
        e._tick(0.1)
        greens = [li.direction for li in e._lights.values() if li.state == "GREEN"]
        assert len(greens) <= 1                                                  # never two protected arms together
        if len(greens) == 1:
            arm = greens[0]
            for v in e._vehicles.values():
                if v.direction != arm and v.position_m + v.length_m / 2 > e._lanes[v.lane_id].stop_line_m + 2:
                    inside_box = abs(v.x) < box_half(e.layout) - 3 and abs(v.z) < box_half(e.layout) - 3
                    assert not inside_box, (e.sim_time, v.id, v.direction, arm)   # a leftover of the previous stage


def test_arms_without_waiting_traffic_are_skipped_in_a_protected_cycle():
    e = quiet_engine(presets()["Turn crossroads"])
    e.spawn_vehicle("west", "car", lane=1, movement="straight")
    greens = []
    for _ in range(1500):
        e._tick(0.1)
        for li in e._lights.values():
            if li.state == "GREEN" and li.direction not in greens:
                greens.append(li.direction)
    assert greens[0] == "north" and "west" in greens[:3]                         # the west car did not wait for east and south


# ------------------------------------------------------------------------------------------ pedestrians and crosswalks

def test_crosswalks_scale_with_the_road_and_open_when_their_road_is_quiet():
    l = presets()["Grand junction"]
    e = SimulationEngine(layout=l)
    assert e._crossings["PC-N"].geo["width"] == 4 * (4 + 4) + 4
    assert box_half(l) == 24 and e._crossings["PC-N"].geo["center"] == 26.5
    st = crossing_stages(l)
    assert all(len(v) == 2 for v in st.values())          # closed while its own road or the road opposite it has green
    e.spawn_pedestrian("PC-N")
    p = next(iter(e._pedestrians.values()))
    assert p.crossing_width == 36
    e.advance(160)
    assert p.id not in e._pedestrians and e._newly_crossed >= 0                  # walked all 36 m and finished


def test_pedestrians_never_meet_moving_traffic_on_wide_junctions():
    for name in ("Avenue with U-turn", "Boulevard", "Grand junction", "Turn crossroads"):
        l = presets()[name]
        l.traffic.spawn_rate, l.traffic.ped_spawn_rate = 30.0, 25.0
        st = run_checks(SimulationEngine(seed=11, layout=l), 300)
        assert st["ped_hit"] == 0 and st["overlap"] == 0, (name, st)


def test_pedestrian_positions_are_world_coordinates_inside_the_crosswalk_band():
    l = presets()["Avenue with U-turn"]
    e = SimulationEngine(seed=3, layout=l)
    e.configure(ped_spawn_rate=40.0)
    e.advance(120)
    g = {c["id"]: c for c in scene_geometry(l)["crossings"]}
    assert e._pedestrians
    for p in e._pedestrians.values():
        cg = g[p.crossing_id]
        assert (p.x, p.z) == pytest.approx(pedestrian_xz(cg, p.position_m, p.direction, p.offset), abs=0.01)


# ------------------------------------------------------------------------------------------ the roundabout

def test_a_roundabout_has_no_lights_and_no_crosswalks_but_a_ring_everybody_uses():
    l = presets()["Roundabout"]
    e = SimulationEngine(seed=2, layout=l)
    assert not e._lights and not e._crossings and e._stages == [] and e.get_state()["junction"] == "roundabout"
    e.configure(spawn_rate=30.0)
    exits = set()
    for _ in range(1800):
        e._tick(0.1)
        for v in e._vehicles.values():
            exits.add((v.direction, v.exit_arm))
    assert len({b for _, b in exits}) == 4                                       # every arm is an exit ...
    assert any(a == b for a, b in exits)                                         # ... including the u-turn round the island
    assert e.get_state()["metrics"]["passed_total"] > 30


def test_vehicles_on_the_ring_keep_the_ring_and_entering_ones_give_way():
    l = presets()["Roundabout"]
    l.traffic.spawn_rate = 45
    e = SimulationEngine(seed=9, layout=l)
    ring_r = scene_geometry(l)["island"]["ring_center"]
    max_ring = 0
    for _ in range(3000):
        e._tick(0.1)
        on_ring = [v for v in e._vehicles.values() if abs(math.hypot(v.x, v.z) - ring_r) < 3.0]
        max_ring = max(max_ring, len(on_ring))
        boxes = [corners(v) for v in e._vehicles.values() if math.hypot(v.x, v.z) < ring_r + 12]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                assert not rects_overlap(a, b, 0.05)
    assert 2 <= max_ring <= 12                                                    # traffic circulates, but the ring never locks up


def test_the_ring_keeps_moving_at_very_high_demand():
    l = presets()["Roundabout 2-lane entries"]
    l.traffic.spawn_rate = 120
    e = SimulationEngine(seed=4, layout=l)
    e.advance(200)
    before = e.get_state()["metrics"]["passed_total"]
    e.advance(200)
    assert e.get_state()["metrics"]["passed_total"] - before > 40                 # no gridlock, still flowing
    assert run_checks(e, 100)["overlap"] == 0


# ------------------------------------------------------------------------------------------ physics on every type

@pytest.mark.parametrize("name", NEW_TYPES)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_no_collisions_no_red_runs_nobody_stuck(name, seed):
    l = presets()[name]
    l.traffic.spawn_rate = max(l.traffic.spawn_rate, 12.0 if l.junction == "roundabout" else 35.0)
    l.traffic.ped_spawn_rate = 15.0
    l.traffic.type_probs = {"car": 0.5, "truck": 0.2, "bus": 0.15, "tram": 0.05, "emergency": 0.05, "taxi": 0.05}
    e = SimulationEngine(seed=seed, layout=l)
    assert run_checks(e, 240) == ZERO


def test_unbalanced_and_jammed_traffic_stays_physical_on_a_turn_junction():
    l = presets()["Turn crossroads"]
    l.traffic.spawn_rate = 90
    l.arms["north"].weight, l.arms["south"].weight, l.arms["east"].weight, l.arms["west"].weight = 6, 0.5, 0.5, 0.5
    e = SimulationEngine(seed=6, layout=l)
    per_arm = dict.fromkeys(ARMS, 0)
    for _ in range(40):
        assert run_checks(e, 10) == ZERO
        for v in e._vehicles.values():
            per_arm[v.direction] += 1
    assert per_arm["north"] > 1.5 * max(per_arm[a] for a in ("south", "east", "west"))       # the jam is where the demand is


def test_emergency_vehicles_get_green_on_a_protected_junction():
    e = quiet_engine(presets()["Turn crossroads"])
    e.advance(2)
    e.set_light_state("TL-N", "AUTO")
    v = e.spawn_emergency("west")
    assert v is not None
    e.advance(60)
    assert v.id not in e._vehicles                                               # it drove through without a long wait


def test_failsafe_uses_a_fixed_timing_on_a_protected_junction():
    e = SimulationEngine(seed=1, layout=presets()["Turn crossroads"])
    e.configure(control_mode="failsafe")
    log, last, start = [], e._phase_index, e.sim_time
    for _ in range(4000):
        e._tick(0.1)
        if e._phase_index != last:
            log.append((last, round(e.sim_time - start, 1)))
            last, start = e._phase_index, e.sim_time
    greens = [d for i, d in log if i % 3 == 0]
    assert greens and all(19.9 <= d <= 20.3 for d in greens)                    # FAILSAFE_GREEN, whatever the demand


def test_the_simulation_is_deterministic_for_a_seed_on_a_turn_junction():
    def snapshot(seed):
        e = SimulationEngine(seed=seed, layout=presets()["Avenue with U-turn"])
        e.advance(120)
        return [(v.id, v.path_id, round(v.position_m, 2), round(v.speed_mps, 2)) for v in e._vehicles.values()]
    assert snapshot(42) == snapshot(42) and snapshot(42) != snapshot(43)


def test_restart_leaves_nothing_behind():
    e = SimulationEngine(seed=8, layout=presets()["Boulevard"])
    e.advance(120)
    assert e._vehicles
    e.set_layout(presets()["Boulevard"])
    assert not e._vehicles and not e._pedestrians and e.sim_time == 0 and e.get_state()["metrics"]["passed_total"] == 0
    e.advance(60)
    assert len({v.id for v in e._vehicles.values()}) == len(e._vehicles)


def test_long_run_on_a_wide_junction_does_not_leak_or_degrade():
    l = presets()["Avenue with U-turn"]
    e = SimulationEngine(seed=12, layout=l)
    counts, passed = [], []
    for hour in range(6):                                                         # 6 x 5 virtual minutes at 0.25 s steps
        e.advance(300, dt=0.25)
        counts.append(len(e._vehicles) + len(e._pedestrians))
        passed.append(e.get_state()["metrics"]["passed_total"])
    assert max(counts) < 160
    gains = [b - a for a, b in zip(passed, passed[1:])]
    assert min(gains) > 15 and len(e._metrics.get_history()) <= 300              # steady throughput, bounded history
    assert not [1 for v in e._vehicles.values() if v.state == "finished"]


def test_conflict_zones_are_symmetric_and_only_built_where_routes_can_meet():
    l = presets()["Turn crossroads"]
    paths = build_paths(l)
    assert needs_zones(paths, l) and not needs_zones(build_paths(default_layout()), default_layout())
    exclusive, follow = path_zones(paths, box_half(l) + 14)
    for a, zs in exclusive.items():
        for b, a0, a1, b0, b1 in zs:
            assert any(o == a and (x0, x1, y0, y1) == (b0, b1, a0, a1) for o, x0, x1, y0, y1 in exclusive[b]) or \
                any(o == a for o, *_ in exclusive[b])                             # the other route knows about the meeting too
    assert exclusive["north-in:left:east0"]                                        # a left turn crosses other routes
    ring = build_paths(presets()["Roundabout"])
    _, ring_follow = path_zones(ring, box_half(presets()["Roundabout"]) + 14)
    assert any(ring_follow.values())                                             # ring routes share long stretches


# ------------------------------------------------------------------------------------------ XML and API

def test_xml_carries_world_positions_and_movements():
    import xml.etree.ElementTree as ET
    from smart_intersection.xml_export.exporter import SimStateExporter
    e = SimulationEngine(seed=3, layout=presets()["Turn crossroads"])
    e.advance(120)
    root = ET.fromstring(SimStateExporter.to_xml(e.get_state()))
    vs = root.findall("vehicles/vehicle")
    assert vs and {v.get("movement") for v in vs} <= {"left", "straight", "right", "uturn"}
    for el, v in zip(vs, e._vehicles.values()):
        assert float(el.get("x")) == pytest.approx(v.x, abs=0.01) and float(el.get("z")) == pytest.approx(v.z, abs=0.01)
        assert float(el.get("heading")) == pytest.approx(v.heading, abs=0.001) and int(el.get("lane_index")) == v.lane_index


def test_xml_of_every_junction_validates_against_the_schema_and_parses():
    lxml = pytest.importorskip("lxml")
    from backend.xml_parser.parser import XmlParser
    from smart_intersection.xml_export.exporter import SimStateExporter
    for name in ("Roundabout", "Avenue with U-turn", "Grand junction"):
        e = SimulationEngine(seed=5, layout=presets()[name])
        e.advance(90)
        xml = SimStateExporter.to_xml(e.get_state())
        XmlParser.validate(xml)
        data = XmlParser.parse(xml)
        assert len(data.vehicles) == len(e._vehicles)
        assert [round(v.x, 2) for v in data.vehicles] == [round(v.x, 2) for v in e._vehicles.values()]
        assert [p.x for p in data.pedestrians] == [round(p.x, 2) for p in e._pedestrians.values()]


@pytest.fixture
def client():
    from smart_intersection.main import app
    with TestClient(app) as c:
        yield c


def test_api_serves_geometry_and_the_junction_catalogue(client):
    g = client.get("/geometry").json()
    assert g["box_half"] == 16 and len(g["lanes"]) == 4 and len(g["crossings"]) == 4 and len(g["lights"]) == 4
    types = client.get("/layout/junction-types").json()["types"]
    assert {t["name"] for t in types} >= set(NEW_TYPES) | {"Crossroads", "T-junction"}
    r = client.put("/layout", json=presets()["Grand junction"].model_dump())
    assert r.status_code == 200
    g = client.get("/geometry").json()
    assert g["box_half"] == 24 and len(g["lanes"]) == 16 and {a["lanes_in"] for a in g["arms"]} == {4}
    assert client.put("/layout", json=presets()["Roundabout"].model_dump()).status_code == 200
    g = client.get("/geometry").json()
    assert g["island"]["radius"] == 12 and g["lights"] == [] and g["crossings"] == []


def test_api_spawns_on_a_lane_with_a_movement(client):
    assert client.put("/layout", json=presets()["Avenue with U-turn"].model_dump()).status_code == 200
    ok = client.post("/simulation/spawn", json={"kind": "vehicle", "arm": "east", "type": "car", "lane": 0, "movement": "uturn"})
    assert ok.status_code == 200
    bad = client.post("/simulation/spawn", json={"kind": "vehicle", "arm": "east", "type": "car", "lane": 1, "movement": "uturn"})
    assert bad.status_code == 409
    assert client.post("/simulation/spawn", json={"kind": "vehicle", "arm": "east", "movement": "loop"}).status_code == 422
    v = next(v for v in client.get("/simulation/state").json()["vehicles"] if v["movement"] == "uturn")
    assert v["lane_id"] == "east-in" and "x" in v and "heading" in v


def test_api_validates_lane_layouts(client):
    d = presets()["Turn crossroads"].model_dump()
    d["arms"]["north"]["turns"] = [["left"]]
    assert client.put("/layout", json=d).status_code == 422
    d = presets()["Grand junction"].model_dump()
    d["arms"]["east"]["length_m"] = 30
    r = client.put("/layout", json=d)
    assert r.status_code == 422 and any("too short" in e for e in r.json()["detail"])
    d = presets()["Turn crossroads"].model_dump()
    d["arms"]["east"]["lanes_out"] = 1
    d["arms"]["east"]["turns"] = [["left"], ["straight", "right", "uturn"]]
    assert client.put("/layout", json=d).status_code == 200                       # lane 2 + one outbound lane leave room to turn round
    d["arms"]["east"]["lanes_in"], d["arms"]["east"]["turns"] = 1, [["uturn"]]
    r = client.put("/layout", json=d)
    assert r.status_code == 422 and any("U-turn needs room" in e for e in r.json()["detail"])
    d = presets()["Roundabout"].model_dump()
    d["arms"]["north"]["lanes_in"] = 3
    r = client.post("/layout/validate", json=d)
    assert r.json()["valid"] is False and any("at most 2 lanes" in e for e in r.json()["errors"])
