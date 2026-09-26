"""
Tests 10–11: XML export contract + parser round-trip.
"""
import pytest
import xml.etree.ElementTree as ET

from smart_intersection.engine.simulation import SimulationEngine
from smart_intersection.xml_export.exporter import SimStateExporter


def _get_sample_state():
    engine = SimulationEngine(seed=42)
    return engine.get_state()


# ──── Test 10: XML export is valid and parseable ────

def test_xml_10_valid_xml():
    state = _get_sample_state()
    xml_str = SimStateExporter.to_xml(state)
    assert xml_str.startswith("<?xml")
    root = ET.fromstring(xml_str.split("\n", 1)[1] if "\n" in xml_str else xml_str)
    assert root.tag == "intersectionSimulation"


def test_xml_10_has_required_sections():
    state = _get_sample_state()
    xml_str = SimStateExporter.to_xml(state)
    root = ET.fromstring(xml_str.split("\n", 1)[1])
    tags = {child.tag for child in root}
    assert "simulation" in tags
    assert "trafficLights" in tags
    assert "vehicles" in tags
    assert "pedestrians" in tags
    assert "metrics" in tags


def test_xml_10_version_attribute():
    state = _get_sample_state()
    xml_str = SimStateExporter.to_xml(state)
    root = ET.fromstring(xml_str.split("\n", 1)[1])
    assert root.get("version") == "1.0"


def test_xml_10_simulation_attributes():
    state = _get_sample_state()
    xml_str = SimStateExporter.to_xml(state)
    root = ET.fromstring(xml_str.split("\n", 1)[1])
    sim_el = root.find("simulation")
    assert sim_el is not None
    assert sim_el.get("id") == state["intersection_id"]
    assert sim_el.get("status") == state["status"]


def test_xml_10_lights_present():
    state = _get_sample_state()
    xml_str = SimStateExporter.to_xml(state)
    root = ET.fromstring(xml_str.split("\n", 1)[1])
    lights_el = root.find("trafficLights")
    light_els = lights_el.findall("light")
    assert len(light_els) == len(state["lights"])


def test_xml_10_vehicles_count_attribute():
    import asyncio

    engine = SimulationEngine(seed=42, tick_rate=100.0)
    engine.configure(spawn_rate=600.0, time_scale=10.0)

    async def _run():
        await engine.start()
        import asyncio as _a
        await _a.sleep(0.2)
        await engine.stop()

    asyncio.run(_run())
    state = engine.get_state()
    xml_str = SimStateExporter.to_xml(state)
    root = ET.fromstring(xml_str.split("\n", 1)[1])
    vehicles_el = root.find("vehicles")
    assert int(vehicles_el.get("count")) == len(state["vehicles"])


def test_xml_10_metrics_attributes():
    state = _get_sample_state()
    xml_str = SimStateExporter.to_xml(state)
    root = ET.fromstring(xml_str.split("\n", 1)[1])
    m_el = root.find("metrics")
    assert m_el is not None
    required_attrs = ["vehicles_active", "vehicles_waiting", "passed_total",
                      "avg_wait_s", "max_wait_s", "throughput_per_min",
                      "congestion_pct", "efficiency_pct"]
    for attr in required_attrs:
        assert m_el.get(attr) is not None, f"Missing metric attribute: {attr}"


# ──── Test 11: XML data matches simulation state ────

def test_xml_11_roundtrip_lights_state():
    engine = SimulationEngine(seed=42)
    state = engine.get_state()
    xml_str = SimStateExporter.to_xml(state)
    root = ET.fromstring(xml_str.split("\n", 1)[1])

    xml_lights = {el.get("id"): el.get("state") for el in root.find("trafficLights").findall("light")}
    py_lights = {l["id"]: l["state"] for l in state["lights"]}

    assert xml_lights == py_lights


def test_xml_11_roundtrip_sim_time():
    engine = SimulationEngine(seed=42)
    engine.sim_time = 123.456
    state = engine.get_state()
    xml_str = SimStateExporter.to_xml(state)
    root = ET.fromstring(xml_str.split("\n", 1)[1])
    sim_el = root.find("simulation")
    assert float(sim_el.get("sim_time")) == pytest.approx(123.456, abs=0.001)


def test_xml_11_roundtrip_vehicle_fields():
    import asyncio

    engine = SimulationEngine(seed=42, tick_rate=100.0)
    engine.configure(spawn_rate=600.0, time_scale=10.0)

    async def _run():
        await engine.start()
        import asyncio as _a
        await _a.sleep(0.3)
        await engine.stop()

    asyncio.run(_run())
    state = engine.get_state()
    if not state["vehicles"]:
        return  # No vehicles — nothing to check

    xml_str = SimStateExporter.to_xml(state)
    root = ET.fromstring(xml_str.split("\n", 1)[1])

    xml_vehicles = {el.get("id"): el for el in root.find("vehicles").findall("vehicle")}
    py_vehicles = {v["id"]: v for v in state["vehicles"]}

    for vid, py_v in py_vehicles.items():
        assert vid in xml_vehicles
        el = xml_vehicles[vid]
        assert el.get("type") == py_v["vehicle_type"]
        assert el.get("state") == py_v["state"]
        assert float(el.get("position_m")) == pytest.approx(py_v["position_m"], abs=0.01)
