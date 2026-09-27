"""
XML contract tests: exporter output must validate against the XSD and survive a round trip through the
backend XmlParser (the consumer in the main project).
"""
import xml.etree.ElementTree as ET

import pytest

lxml_etree = pytest.importorskip("lxml.etree")

from backend.xml_parser.parser import XmlParser, XmlParseError, XSD_PATH
from smart_intersection.xml_export.exporter import SimStateExporter
from .helpers import make_engine


def busy_state(seconds=90, scenario="heavy"):
    e = make_engine(scenario)
    e.advance(seconds)
    return e, e.get_state()


def body(xml_str: str) -> str:
    return xml_str.split("?>", 1)[1].strip()


@pytest.fixture(scope="module")
def schema():
    return lxml_etree.XMLSchema(lxml_etree.parse(XSD_PATH))


def validate(schema, xml_str):
    doc = lxml_etree.fromstring(xml_str.encode("utf-8"))
    ok = schema.validate(doc)
    return ok, [str(e) for e in schema.error_log]


# ──── schema validity ────

def test_empty_state_validates_against_xsd(schema):
    e = make_engine("empty")
    ok, errors = validate(schema, SimStateExporter.to_xml(e.get_state()))
    assert ok, errors


@pytest.mark.parametrize("scenario", ["normal", "heavy", "pedestrian_rush", "emergency", "traffic_jam", "failsafe"])
def test_busy_states_validate_against_xsd(schema, scenario):
    _, state = busy_state(scenario=scenario)
    assert state["vehicles"], "scenario should have produced traffic"
    ok, errors = validate(schema, SimStateExporter.to_xml(state))
    assert ok, errors


def test_manually_overridden_lights_still_validate(schema):
    e = make_engine("normal")
    e.set_light_state("TL-N", "YELLOW")
    e.set_light_state("TL-E", "GREEN")
    e.advance(5)
    ok, errors = validate(schema, SimStateExporter.to_xml(e.get_state()))
    assert ok, errors


@pytest.mark.parametrize("mutate", [
    lambda r: r.find("trafficLights/light").set("state", "PURPLE"),
    lambda r: r.find("simulation").set("status", "exploding"),
    lambda r: r.remove(r.find("metrics")),
    lambda r: r.find("simulation").attrib.pop("seed"),
    lambda r: r.find("vehicles").set("count", "many"),
])
def test_xsd_rejects_broken_documents(schema, mutate):
    _, state = busy_state()
    root = ET.fromstring(body(SimStateExporter.to_xml(state)))
    mutate(root)
    ok, _ = validate(schema, ET.tostring(root, encoding="unicode"))
    assert not ok


# ──── structure ────

def test_root_sections_and_version():
    _, state = busy_state()
    root = ET.fromstring(body(SimStateExporter.to_xml(state)))
    assert root.tag == "intersectionSimulation" and root.get("version") == "1.0"
    assert [c.tag for c in root] == ["simulation", "trafficLights", "pedestrianLights", "vehicles", "pedestrians", "metrics"]


def test_counts_match_children():
    _, state = busy_state()
    root = ET.fromstring(body(SimStateExporter.to_xml(state)))
    assert int(root.find("vehicles").get("count")) == len(root.findall("vehicles/vehicle")) == len(state["vehicles"])
    assert int(root.find("pedestrians").get("count")) == len(root.findall("pedestrians/pedestrian")) == len(state["pedestrians"])


def test_xml_special_characters_are_escaped(schema):
    state = make_engine("empty").get_state()
    state["scenario"] = 'a&b<"c">'
    xml_str = SimStateExporter.to_xml(state)
    assert ET.fromstring(body(xml_str)).find("simulation").get("scenario") == 'a&b<"c">'
    ok, errors = validate(schema, xml_str)
    assert ok, errors


# ──── round trip through the main project's parser ────

def test_parser_round_trip_matches_simulation_state():
    e, state = busy_state()
    data = XmlParser.parse(SimStateExporter.to_xml(state))          # includes XSD validation via lxml
    assert data.simulation.intersection_id == state["intersection_id"]
    assert data.simulation.sim_time == pytest.approx(state["sim_time"], abs=0.001)
    assert data.simulation.seed == state["seed"]
    assert {l.id: l.state for l in data.lights} == {l["id"]: l["state"] for l in state["lights"]}
    assert len(data.vehicles) == len(state["vehicles"])
    by_id = {v["id"]: v for v in state["vehicles"]}
    for dto in data.vehicles:
        src = by_id[dto.id]
        assert dto.vehicle_type == src["vehicle_type"] and dto.state == src["state"]
        assert dto.position_m == pytest.approx(src["position_m"], abs=0.01)
        assert dto.speed_mps == pytest.approx(src["speed_mps"], abs=0.01)
    assert len(data.pedestrians) == len(state["pedestrians"])
    m = state["metrics"]
    assert data.metrics.passed_total == m["passed_total"]
    assert data.metrics.vehicles_waiting == m["vehicles_waiting"]
    assert data.metrics.avg_wait_s == pytest.approx(m["avg_wait_s"], abs=0.01)


def test_parser_rejects_schema_violations_and_garbage():
    _, state = busy_state()
    bad = SimStateExporter.to_xml(state).replace('state="GREEN"', 'state="PURPLE"', 1)
    with pytest.raises(XmlParseError):
        XmlParser.parse(bad)
    with pytest.raises(XmlParseError):
        XmlParser.parse("<intersectionSimulation><oops>")
    with pytest.raises(XmlParseError):
        XmlParser.parse("")
