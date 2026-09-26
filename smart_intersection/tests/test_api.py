"""
REST + WebSocket API tests for the Smart Intersection microservice.
"""
import time
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from smart_intersection.main import app
from smart_intersection.scenarios.presets import SCENARIOS


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def engine(client):
    return app.state.engine


# ──── read-only endpoints ────

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok" and d["sim_status"] == "stopped" and d["vehicles"] == 0


def test_state_has_all_sections(client):
    d = client.get("/simulation/state").json()
    for k in ("sim_time", "lights", "vehicles", "pedestrians", "metrics", "control_mode", "phase", "seed"):
        assert k in d
    assert len(d["lights"]) == 4


def test_config_defaults(client):
    d = client.get("/simulation/config").json()
    assert d["time_scale"] == 1.0 and d["control_mode"] == "auto" and d["seed"] == 42


def test_scenarios_listing_contains_all_presets(client):
    d = client.get("/scenarios").json()
    assert set(d) == set(SCENARIOS)
    assert all("name" in v and "description" in v for v in d.values())


def test_metrics_and_statistics(client):
    assert client.get("/metrics").status_code == 200
    d = client.get("/statistics").json()
    assert "summary" in d and "history_len" in d


def test_xml_state_is_well_formed_xml_with_correct_content_type(client):
    r = client.get("/xml/state")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(r.text.split("?>", 1)[1])
    assert root.tag == "intersectionSimulation"


def test_unknown_route_is_404(client):
    assert client.get("/nope").status_code == 404


# ──── lifecycle ────

def test_start_stop_cycle(client):
    assert client.post("/simulation/start").json()["status"] == "running"
    assert client.post("/simulation/stop").json()["status"] == "stopped"


def test_start_is_idempotent(client, engine):
    client.post("/simulation/start")
    task = engine._task
    assert client.post("/simulation/start").json()["status"] == "running"
    assert engine._task is task
    client.post("/simulation/stop")


def test_pause_freezes_time_resume_continues(client, engine):
    client.post("/simulation/config", json={"time_scale": 10})
    client.post("/simulation/start")
    time.sleep(0.4)
    assert client.post("/simulation/pause").json()["status"] == "paused"
    frozen = client.get("/simulation/state").json()["sim_time"]
    time.sleep(0.3)
    assert client.get("/simulation/state").json()["sim_time"] == frozen
    assert client.post("/simulation/resume").json()["status"] == "running"
    time.sleep(0.4)
    assert client.get("/simulation/state").json()["sim_time"] > frozen
    client.post("/simulation/stop")


def test_pause_when_stopped_does_not_change_status(client):
    assert client.post("/simulation/pause").json()["status"] == "stopped"


def test_reset_restores_seed_and_clears_state(client, engine):
    client.post("/simulation/config", json={"spawn_rate": 120})
    engine.advance(30)
    assert client.get("/simulation/state").json()["vehicles"]
    d = client.post("/simulation/reset?seed=7").json()
    assert d == {"status": "stopped", "seed": 7}
    s = client.get("/simulation/state").json()
    assert s["sim_time"] == 0 and not s["vehicles"] and s["seed"] == 7


def test_reset_rejects_negative_seed(client):
    assert client.post("/simulation/reset?seed=-1").status_code == 422


def test_simulation_actually_progresses_when_started(client):
    client.post("/simulation/config", json={"time_scale": 20, "spawn_rate": 60})
    client.post("/simulation/start")
    time.sleep(1.0)
    s = client.get("/simulation/state").json()
    client.post("/simulation/stop")
    assert s["sim_time"] > 5 and s["metrics"]["vehicles_active"] + s["metrics"]["passed_total"] > 0


# ──── configuration validation ────

def test_config_update_applies(client, engine):
    r = client.post("/simulation/config", json={"spawn_rate": 30.0, "time_scale": 2.0, "control_mode": "failsafe"})
    assert r.status_code == 200 and set(r.json()["updated"]) == {"spawn_rate", "time_scale", "control_mode"}
    assert engine._spawn.spawn_rate == 30.0 and engine.time_scale == 2.0 and engine.control_mode == "failsafe"


@pytest.mark.parametrize("payload", [
    {"time_scale": 0}, {"time_scale": -1}, {"time_scale": 1000},
    {"spawn_rate": -5}, {"spawn_rate": 10_000}, {"ped_spawn_rate": -1},
    {"control_mode": "bogus"}, {"time_scale": "fast"},
])
def test_config_rejects_invalid_values(client, payload):
    assert client.post("/simulation/config", json=payload).status_code == 422


# ──── scenarios ────

@pytest.mark.parametrize("scenario_id", list(SCENARIOS))
def test_every_scenario_starts_and_applies_its_settings(client, engine, scenario_id):
    r = client.post("/scenario/start", json={"scenario_id": scenario_id})
    assert r.status_code == 200 and r.json() == {"scenario": scenario_id, "status": "running"}
    preset = SCENARIOS[scenario_id]
    assert engine.scenario == scenario_id
    assert engine._spawn.spawn_rate == preset["spawn_rate"]
    assert engine.control_mode == preset.get("control_mode", "auto")
    assert bool(engine._timeline) == ("timeline" in preset)
    client.post("/scenario/stop")


def test_starting_a_scenario_resets_previous_run(client, engine):
    client.post("/scenario/start", json={"scenario_id": "traffic_jam"})
    engine.advance(20)
    client.post("/scenario/start", json={"scenario_id": "empty"})
    s = client.get("/simulation/state").json()
    assert s["sim_time"] < 1 and s["vehicles"] == []
    client.post("/scenario/stop")


def test_unknown_scenario_is_404(client):
    assert client.post("/scenario/start", json={"scenario_id": "nope"}).status_code == 404


def test_scenario_start_requires_body(client):
    assert client.post("/scenario/start", json={}).status_code == 422


# ──── traffic light control ────

def test_lights_listing(client):
    lights = client.get("/traffic-lights").json()["lights"]
    assert {l["id"] for l in lights} == {"TL-N", "TL-S", "TL-E", "TL-W"}


def test_manual_override_is_applied_and_survives_the_signal_cycle(client, engine):
    assert client.post("/traffic-lights/TL-E/state", json={"state": "GREEN"}).status_code == 200
    engine.advance(70)
    states = {l["id"]: l["state"] for l in client.get("/traffic-lights").json()["lights"]}
    assert states["TL-E"] == "GREEN"


def test_override_can_be_released_with_auto(client, engine):
    client.post("/traffic-lights/TL-E/state", json={"state": "GREEN"})
    assert client.post("/traffic-lights/TL-E/state", json={"state": "AUTO"}).status_code == 200
    assert "TL-E" not in engine._overrides


def test_invalid_light_state_is_422(client):
    assert client.post("/traffic-lights/TL-N/state", json={"state": "PURPLE"}).status_code == 422


def test_unknown_light_is_404(client):
    assert client.post("/traffic-lights/TL-X/state", json={"state": "RED"}).status_code == 404


# ──── websocket ────

def test_websocket_streams_state_updates(client):
    client.post("/simulation/config", json={"time_scale": 10, "spawn_rate": 30})
    client.post("/simulation/start")
    with client.websocket_connect("/ws/state") as ws:
        msgs = [ws.receive_json() for _ in range(4)]
    client.post("/simulation/stop")
    times = [m["sim_time"] for m in msgs]
    assert times == sorted(times) and times[-1] > times[0]
    assert all({"vehicles", "pedestrians", "lights", "metrics"} <= set(m) for m in msgs)


def test_websocket_disconnect_is_cleaned_up(client):
    from smart_intersection.api import routes
    with client.websocket_connect("/ws/state") as ws:
        ws.receive_json()
        assert len(routes._ws_clients) == 1
    time.sleep(0.4)
    assert len(routes._ws_clients) == 0


def test_two_websocket_clients_receive_independently(client):
    with client.websocket_connect("/ws/state") as a, client.websocket_connect("/ws/state") as b:
        assert a.receive_json()["intersection_id"] == b.receive_json()["intersection_id"] == "SI-001"
