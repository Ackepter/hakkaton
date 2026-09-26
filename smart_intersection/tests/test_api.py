"""
Tests 12–14: FastAPI endpoints for Smart Intersection.
"""
import pytest
from fastapi.testclient import TestClient

from smart_intersection.main import app
from smart_intersection.engine.simulation import SimulationEngine
from smart_intersection.api.routes import set_engine


@pytest.fixture(autouse=True)
def fresh_engine():
    """Give each test a clean engine."""
    engine = SimulationEngine(seed=42)
    set_engine(engine)
    yield engine
    import asyncio
    try:
        asyncio.get_event_loop().run_until_complete(engine.stop())
    except Exception:
        pass


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ──── Test 12: Core API endpoints ────

def test_api_12_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert data["status"] == "ok"


def test_api_12_get_state(client):
    r = client.get("/simulation/state")
    assert r.status_code == 200
    data = r.json()
    assert "sim_time" in data
    assert "lights" in data
    assert "vehicles" in data


def test_api_12_get_config(client):
    r = client.get("/simulation/config")
    assert r.status_code == 200
    data = r.json()
    assert "spawn_rate" in data
    assert "time_scale" in data


def test_api_12_list_scenarios(client):
    r = client.get("/scenarios")
    assert r.status_code == 200
    data = r.json()
    assert "normal" in data
    assert "empty" in data


def test_api_12_get_lights(client):
    r = client.get("/traffic-lights")
    assert r.status_code == 200
    data = r.json()
    assert "lights" in data
    assert len(data["lights"]) == 4


def test_api_12_get_metrics(client):
    r = client.get("/metrics")
    assert r.status_code == 200


def test_api_12_get_xml_state(client):
    r = client.get("/xml/state")
    assert r.status_code == 200
    assert "intersectionSimulation" in r.text
    assert r.headers["content-type"].startswith("application/xml")


# ──── Test 13: Simulation lifecycle ────

def test_api_13_start_stop_cycle(client):
    r = client.post("/simulation/start")
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    r = client.post("/simulation/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"


def test_api_13_pause_resume(client):
    client.post("/simulation/start")
    r = client.post("/simulation/pause")
    assert r.status_code == 200
    assert r.json()["status"] == "paused"

    r = client.post("/simulation/resume")
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    client.post("/simulation/stop")


def test_api_13_reset(client):
    client.post("/simulation/start")
    r = client.post("/simulation/reset")
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"
    assert r.json()["seed"] == 42


def test_api_13_update_config(client):
    r = client.post("/simulation/config", json={"spawn_rate": 30.0, "time_scale": 2.0})
    assert r.status_code == 200
    updated = r.json()["updated"]
    assert "spawn_rate" in updated
    assert "time_scale" in updated


def test_api_13_start_scenario(client):
    r = client.post("/scenario/start", json={"scenario_id": "empty"})
    assert r.status_code == 200
    data = r.json()
    assert data["scenario"] == "empty"
    assert data["status"] == "running"


def test_api_13_unknown_scenario(client):
    r = client.post("/scenario/start", json={"scenario_id": "does_not_exist"})
    assert r.status_code == 404


# ──── Test 14: Failure / edge cases ────

def test_api_14_set_light_valid(client):
    r = client.post("/traffic-lights/TL-N/state", json={"state": "RED"})
    assert r.status_code == 200
    assert r.json()["state"] == "RED"


def test_api_14_set_light_invalid_state(client):
    r = client.post("/traffic-lights/TL-N/state", json={"state": "PURPLE"})
    assert r.status_code == 422


def test_api_14_multiple_starts_idempotent(client):
    client.post("/simulation/start")
    r = client.post("/simulation/start")
    assert r.status_code == 200
    assert r.json()["status"] == "running"
    client.post("/simulation/stop")


def test_api_14_statistics_endpoint(client):
    r = client.get("/statistics")
    assert r.status_code == 200
    data = r.json()
    assert "summary" in data
    assert "history_len" in data
