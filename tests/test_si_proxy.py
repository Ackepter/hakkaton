"""
Tests for the main backend's /api/si/* proxy: fetch XML from the SI service, validate, parse, return JSON.
The SI service is replaced with httpx.MockTransport, so no second process is needed.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.api import routes_si
from smart_intersection.engine.simulation import SimulationEngine
from smart_intersection.xml_export.exporter import SimStateExporter


def _xml_from_engine():
    e = SimulationEngine(seed=42)
    e.configure(spawn_rate=60.0, ped_spawn_rate=20.0)
    e.advance(60)
    return SimStateExporter.to_xml(e.get_state()), e.get_state()


def _mock(monkeypatch, handler):
    client = httpx.AsyncClient(base_url="http://si.test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(routes_si, "_http_client", client)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_state_is_fetched_parsed_and_returned_as_json(client, monkeypatch):
    xml, state = _xml_from_engine()
    _mock(monkeypatch, lambda req: httpx.Response(200, text=xml, headers={"content-type": "application/xml"}))
    r = client.get("/api/si/state")
    assert r.status_code == 200
    d = r.json()
    assert d["simulation"]["intersection_id"] == "SI-001"
    assert len(d["vehicles"]) == len(state["vehicles"]) > 0
    assert {l["id"] for l in d["lights"]} == {"TL-N", "TL-S", "TL-E", "TL-W"}
    assert d["metrics"]["passed_total"] == state["metrics"]["passed_total"]


def test_unreachable_service_gives_503(client, monkeypatch):
    def boom(req):
        raise httpx.ConnectError("refused")
    _mock(monkeypatch, boom)
    assert client.get("/api/si/state").status_code == 503
    assert client.get("/api/si/health").status_code == 503
    assert client.post("/api/si/simulation/start").status_code == 503


def test_timeout_gives_503_not_500(client, monkeypatch):
    def slow(req):
        raise httpx.ReadTimeout("slow")
    _mock(monkeypatch, slow)
    assert client.get("/api/si/state").status_code == 503


def test_upstream_error_gives_502(client, monkeypatch):
    _mock(monkeypatch, lambda req: httpx.Response(500, text="oops"))
    assert client.get("/api/si/state").status_code == 502


def test_invalid_xml_from_service_gives_502(client, monkeypatch):
    xml, _ = _xml_from_engine()
    _mock(monkeypatch, lambda req: httpx.Response(200, text=xml.replace('state="GREEN"', 'state="PURPLE"', 1)))
    assert client.get("/api/si/state").status_code == 502
    _mock(monkeypatch, lambda req: httpx.Response(200, text="<not-xml"))
    assert client.get("/api/si/state").status_code == 502


def test_commands_are_forwarded_to_the_service(client, monkeypatch):
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, req.content))
        return httpx.Response(200, json={"status": "ok"})
    _mock(monkeypatch, handler)
    assert client.post("/api/si/simulation/start").status_code == 200
    assert client.post("/api/si/simulation/stop").status_code == 200
    assert client.post("/api/si/scenario/start?scenario_id=heavy").status_code == 200
    assert [s[:2] for s in seen] == [("POST", "/simulation/start"), ("POST", "/simulation/stop"), ("POST", "/scenario/start")]
    assert b"heavy" in seen[2][2]
