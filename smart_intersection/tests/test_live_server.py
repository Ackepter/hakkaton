"""
End-to-end test against a REAL uvicorn process (what start.bat launches): HTTP, WebSocket, XML and shutdown.
TestClient cannot catch a missing websocket library or a broken import path; this can.
"""
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

httpx_get = lambda url, **kw: httpx.get(url, trust_env=False, **kw)
httpx_post = lambda url, **kw: httpx.post(url, trust_env=False, **kw)

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "smart_intersection.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if proc.poll() is not None:
                raise RuntimeError("uvicorn exited early:\n" + proc.stdout.read())
            try:
                if httpx_get(f"{base}/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not start")
        yield base, port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_websocket_library_is_installed():
    """The original bug: uvicorn without websockets answers /ws/state with 404."""
    import websockets  # noqa: F401


def test_health_over_real_http(server):
    base, _ = server
    assert httpx_get(f"{base}/health").json()["status"] == "ok"


def test_real_websocket_streams_live_simulation(server):
    from websockets.sync.client import connect
    base, port = server
    httpx_post(f"{base}/scenario/start", json={"scenario_id": "heavy"})
    httpx_post(f"{base}/simulation/config", json={"time_scale": 10})
    with connect(f"ws://127.0.0.1:{port}/ws/state", open_timeout=5) as ws:
        first = json.loads(ws.recv(timeout=5))
        time.sleep(1.0)
        later = json.loads(ws.recv(timeout=5))
    httpx_post(f"{base}/simulation/stop")
    assert later["sim_time"] > first["sim_time"]
    assert first["status"] == "running" and len(first["lights"]) == 4


def test_xml_over_real_http_validates(server):
    lxml_etree = pytest.importorskip("lxml.etree")
    from backend.xml_parser.parser import XSD_PATH
    base, _ = server
    httpx_post(f"{base}/scenario/start", json={"scenario_id": "normal"})
    httpx_post(f"{base}/simulation/config", json={"time_scale": 20})
    time.sleep(1.0)
    xml = httpx_get(f"{base}/xml/state").text
    httpx_post(f"{base}/simulation/stop")
    schema = lxml_etree.XMLSchema(lxml_etree.parse(XSD_PATH))
    assert schema.validate(lxml_etree.fromstring(xml.encode())), [str(e) for e in schema.error_log]


def test_server_survives_many_rapid_requests(server):
    base, _ = server
    with httpx.Client(base_url=base, trust_env=False) as c:
        for i in range(150):
            assert c.get("/simulation/state").status_code == 200
            if i % 30 == 0:
                assert c.post("/simulation/config", json={"time_scale": 1 + i % 5}).status_code == 200
    assert httpx_get(f"{base}/health").status_code == 200
