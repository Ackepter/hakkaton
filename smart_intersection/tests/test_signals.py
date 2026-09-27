"""
Additional light sections (turn arrows) and pedestrian signals (Task 16: state, switch count and uptime tracked for
every signal; Task 9: MANUAL may force any of them).

Direction under test throughout, same as test_hardware.py: a section or a pedestrian light only ever reflects an
already-decided state — `_apply_lights` / `_update_ped_signals` are the only writers; nothing a vehicle or pedestrian
does can set a lamp directly.
"""
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from backend.xml_parser.parser import XmlParser
from smart_intersection.engine.simulation import SimulationEngine
from smart_intersection.layout import default_layout, presets, target_arm
from smart_intersection.main import app
from smart_intersection.xml_export.exporter import SimStateExporter
from .geo_helpers import run_checks

ZERO = dict.fromkeys(("overlap", "red_run", "stuck", "off_path", "ped_hit", "backwards"), 0)


def quiet(layout, seed=1):
    l = layout.model_copy(deep=True)
    l.traffic.spawn_rate = 0.0
    l.traffic.ped_spawn_rate = 0.0
    return SimulationEngine(seed=seed, layout=l)


# ------------------------------------------------------------------------------------------ which arms get sections

def test_a_plain_straight_only_arm_has_no_sections():
    e = SimulationEngine(seed=1, layout=default_layout())
    e.advance(5)
    assert all(l.sections == {} for l in e._lights.values())
    assert all(v["sections"] == {} for v in e.get_state()["lights"])


@pytest.mark.parametrize("name", ["Two-way street", "Tram avenue", "Bus street", "Busy junction", "Roundabout",
                                  "Roundabout 2-lane entries"])
def test_junction_types_without_turn_lanes_have_no_sections(name):
    e = SimulationEngine(seed=1, layout=presets()[name])
    e.advance(5)
    assert all(l.sections == {} for l in e._lights.values())


def test_a_turn_lane_gives_its_arm_a_matching_section():
    e = quiet(presets()["Turn crossroads"])
    e.advance(1)
    for l in e._lights.values():
        assert set(l.sections) == {"left", "right"}                        # inner lane left/uturn, outer straight/right
    e2 = quiet(presets()["Avenue with U-turn"])
    e2.advance(1)
    assert set(e2._lights["TL-E"].sections) == {"left", "uturn", "right"}    # the 4-lane avenue
    assert set(e2._lights["TL-N"].sections) == {"left", "right"}             # side street: one lane, every movement


def test_no_left_crossroads_has_only_a_right_section():
    e = quiet(presets()["No-left crossroads"])
    e.advance(1)
    assert set(e._lights["TL-N"].sections) == {"right"}


# ------------------------------------------------------------------------------------------ section state

def test_sections_mirror_a_red_or_yellow_main_lamp():
    e = quiet(presets()["Turn crossroads"])
    e.set_light_state("TL-N", "RED")
    e.advance(1)
    assert e._lights["TL-N"].sections == {"left": "RED", "right": "RED"}
    e.set_light_state("TL-N", "YELLOW")
    e.advance(1)
    assert e._lights["TL-N"].sections == {"left": "YELLOW", "right": "YELLOW"}


def test_a_green_arm_with_no_pedestrians_shows_green_arrows():
    e = quiet(presets()["Turn crossroads"])
    e.set_light_state("TL-N", "GREEN")
    e.advance(1)
    assert e._lights["TL-N"].sections == {"left": "GREEN", "right": "GREEN"}


def test_a_turn_arrow_goes_red_on_its_own_while_its_crosswalk_is_occupied():
    """The main lamp stays green (through traffic still moves); only the arrow for the blocked turn goes red."""
    e = quiet(presets()["Turn crossroads"])
    e.set_light_state("TL-N", "GREEN")
    target = target_arm("north", "right")                # the crosswalk a right turn from north drives over
    cid = f"PC-{target[0].upper()}"
    ped = e.spawn_pedestrian(cid)
    ped.state, ped.position_m = "crossing", 5.0
    e._tick(0.1)
    assert e._lights["TL-N"].sections["right"] == "RED"
    assert e._lights["TL-N"].sections["left"] == "GREEN"                    # the other turn is unaffected
    assert e._lights["TL-N"].state == "GREEN"                               # through traffic is not held up by this


def test_sections_never_less_safe_than_the_vehicle_physics():
    """The exact set a section checks (`_ped_occupied`) is the one `_update_vehicles` yields to — run the physical
    checks on every turn-lane junction type and confirm no collisions, no matter how busy the crosswalks get."""
    for name in ("Turn crossroads", "Avenue with U-turn", "No-left crossroads", "T-junction with turns"):
        l = presets()[name]
        l.traffic.spawn_rate, l.traffic.ped_spawn_rate = 40.0, 25.0
        e = SimulationEngine(seed=3, layout=l)
        assert run_checks(e, 200) == ZERO, name


def test_manual_override_is_reflected_in_the_sections_too():
    e = quiet(presets()["Turn crossroads"])
    assert e.set_light_state("TL-N", "GREEN")
    e.advance(1)
    assert all(s == "GREEN" for s in e._lights["TL-N"].sections.values())
    assert e.set_light_state("TL-N", "AUTO")


# ------------------------------------------------------------------------------------------ pedestrian lights

def test_every_crossing_has_a_first_class_pedestrian_light():
    e = SimulationEngine(seed=1, layout=default_layout())
    e.advance(1)
    assert set(e._crossings) == {"PC-N", "PC-S", "PC-E", "PC-W"}
    for c in e._crossings.values():
        assert c.state in ("RED", "GREEN") and c.phase_switches >= 0
    state = e.get_state()
    ids = {p["id"] for p in state["pedestrian_lights"]}
    assert ids == set(e._crossings)
    for p in state["pedestrian_lights"]:
        assert set(p) == {"id", "direction", "state", "phase_switches", "waiting_peds", "crossing_peds"}


def test_pedestrian_light_switch_count_only_increases_on_a_real_change():
    e = SimulationEngine(seed=1, layout=default_layout())
    switches = []
    last = e._crossings["PC-N"].state                                       # already correct as of construction
    for _ in range(3000):
        e._tick(0.1)
        c = e._crossings["PC-N"]
        if c.state != last:
            switches.append(c.phase_switches)
            last = c.state
    assert switches == sorted(switches) and switches == list(range(1, len(switches) + 1))
    assert e._crossings["PC-N"].phase_switches == len(switches)


def test_waiting_and_crossing_counts_match_the_actual_pedestrians():
    e = SimulationEngine(seed=1, layout=default_layout())
    e.set_ped_light_state("PC-N", "RED")
    a = e.spawn_pedestrian("PC-N")
    a.state = "waiting_for_green"
    b = e.spawn_pedestrian("PC-N")
    b.state = "crossing"
    e._tick(0.1)
    c = e._crossings["PC-N"]
    assert c.waiting_peds == 1 and c.crossing_peds == 1


# ------------------------------------------------------------------------------------------ manual control (Task 9)

def test_a_pedestrian_light_can_be_forced_and_released():
    e = SimulationEngine(seed=1, layout=default_layout())
    assert e.set_ped_light_state("PC-N", "GREEN")
    e.advance(1)
    assert e._crossings["PC-N"].state == "GREEN"
    assert e.set_ped_light_state("PC-N", "AUTO")
    assert not e.set_ped_light_state("PC-nope", "GREEN")


def test_clear_overrides_releases_both_vehicle_and_pedestrian_overrides():
    e = SimulationEngine(seed=1, layout=default_layout())
    e.set_light_state("TL-N", "RED")
    e.set_ped_light_state("PC-N", "GREEN")
    e.clear_overrides()
    assert e._overrides == {} and e._ped_overrides == {}


# ------------------------------------------------------------------------------------------ statistics (Task 16)

def test_ped_signal_switches_are_counted_separately_from_vehicle_phase_switches():
    e = SimulationEngine(seed=1, layout=default_layout())
    e.advance(120)
    m = e.get_state()["metrics"]
    assert m["ped_signal_switches"] > 0
    assert m["ped_signal_switches"] == sum(c.phase_switches for c in e._crossings.values())
    assert m["phase_switches"] == sum(l.phase_switches for l in e._lights.values())


def test_empty_snapshot_has_the_new_metric_too():
    from smart_intersection.engine.metrics import MetricsEngine
    assert MetricsEngine.empty_snapshot()["ped_signal_switches"] == 0


# ------------------------------------------------------------------------------------------ XML

def test_xml_carries_sections_and_pedestrian_lights():
    e = SimulationEngine(seed=1, layout=presets()["Turn crossroads"])
    e.advance(60)
    xml = SimStateExporter.to_xml(e.get_state())
    XmlParser.validate(xml)
    root = ET.fromstring(xml)
    n_light = root.find("trafficLights/light[@id='TL-N']")
    assert {s.get("movement") for s in n_light.findall("section")} == set(e._lights["TL-N"].sections)
    for s in n_light.findall("section"):
        assert s.get("state") == e._lights["TL-N"].sections[s.get("movement")]
    ped_els = root.findall("pedestrianLights/pedestrianLight")
    assert {p.get("id") for p in ped_els} == set(e._crossings)

    data = XmlParser.parse(xml)
    light = next(l for l in data.lights if l.id == "TL-N")
    assert light.sections == e._lights["TL-N"].sections
    ped = next(p for p in data.pedestrian_lights if p.id == "PC-N")
    assert ped.state == e._crossings["PC-N"].state and ped.phase_switches == e._crossings["PC-N"].phase_switches
    assert data.metrics.ped_signal_switches == e.get_state()["metrics"]["ped_signal_switches"]


def test_xml_of_a_plain_crossroads_has_no_section_elements():
    e = SimulationEngine(seed=1, layout=default_layout())
    e.advance(10)
    root = ET.fromstring(SimStateExporter.to_xml(e.get_state()))
    assert root.findall(".//section") == []


# ------------------------------------------------------------------------------------------ API

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_api_lists_and_forces_a_pedestrian_light(client):
    d = client.get("/pedestrian-lights").json()
    assert {p["id"] for p in d["pedestrian_lights"]} == {"PC-N", "PC-S", "PC-E", "PC-W"}
    r = client.post("/pedestrian-lights/PC-N/state", json={"state": "GREEN"})
    assert r.status_code == 200
    assert next(p for p in client.get("/pedestrian-lights").json()["pedestrian_lights"] if p["id"] == "PC-N")["state"] == "GREEN"
    assert client.post("/pedestrian-lights/PC-N/state", json={"state": "AUTO"}).status_code == 200
    assert client.post("/pedestrian-lights/PC-N/state", json={"state": "PURPLE"}).status_code == 422
    assert client.post("/pedestrian-lights/PC-nope/state", json={"state": "GREEN"}).status_code == 404


def test_api_traffic_lights_include_sections(client):
    r = client.put("/layout", json=presets()["Turn crossroads"].model_dump())
    assert r.status_code == 200
    d = client.get("/traffic-lights").json()
    n = next(l for l in d["lights"] if l["id"] == "TL-N")
    assert set(n["sections"]) == {"left", "right"}
