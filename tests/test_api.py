import pytest
from fastapi.testclient import TestClient
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_get_intersection_empty():
    r = client.get("/api/intersection")
    assert r.status_code == 200


def test_save_intersection():
    config = {
        "id": "test",
        "name": "Test Intersection",
        "grid_cols": 20,
        "grid_rows": 20,
        "cell_size": 40,
        "lanes": [],
        "traffic_lights": [],
        "pedestrian_crossings": [],
        "cameras": [],
        "detection_zones": [],
        "tram_tracks": [],
        "direction_priorities": {"north": 1.0}
    }
    r = client.post("/api/intersection", json=config)
    assert r.status_code == 200
    assert r.json()["name"] == "Test Intersection"


def test_get_lights():
    r = client.get("/api/lights")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_status():
    r = client.get("/api/control/status")
    assert r.status_code == 200
    data = r.json()
    assert "mode" in data
    assert "uptime" in data


def test_set_mode_auto():
    r = client.post("/api/control/mode", json={"mode": "AUTO"})
    assert r.status_code == 200
    assert r.json()["mode"] == "AUTO"


def test_set_mode_manual():
    r = client.post("/api/control/mode", json={"mode": "MANUAL"})
    assert r.status_code == 200


def test_set_mode_failsafe():
    r = client.post("/api/control/mode", json={"mode": "FAILSAFE"})
    assert r.status_code == 200


def test_trigger_failsafe():
    r = client.post("/api/control/failsafe?reason=Test+reason")
    assert r.status_code == 200
    assert r.json()["mode"] == "FAILSAFE"


def test_recover_from_failsafe():
    client.post("/api/control/failsafe?reason=Test")
    r = client.post("/api/control/recover")
    assert r.status_code == 200


def test_manual_light_without_manual_mode():
    # Set to AUTO first
    client.post("/api/control/mode", json={"mode": "AUTO"})
    r = client.post("/api/lights/manual", json={"light_id": "TL-01", "state": "GREEN"})
    assert r.status_code == 400  # Should reject


def test_get_metrics():
    r = client.get("/api/metrics")
    assert r.status_code == 200


def test_get_metrics_history():
    r = client.get("/api/metrics/history?seconds=60")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_simulation_control():
    r = client.post("/api/control/simulation", json={"action": "reset"})
    assert r.status_code == 200


def test_update_priorities():
    r = client.post("/api/control/priorities", json={"direction_priorities": {"north": 1.5, "south": 1.0}})
    assert r.status_code == 200
