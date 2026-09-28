"""
Vision API + application wiring, hermetic: the simulation service is replaced by a switchable XML source, so a lost
"cable" can be simulated by returning None.
"""
import io
import time

import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image

from backend.config.settings import settings
from backend.core import app_state
from backend.models.schemas import SystemMode
from backend.main import app
from backend.vision import sources
from backend.vision.bridge import SimulationBridge
from .vision_helpers import sim_xml

CAM_YAML = {"cameras": [{"id": "CAM-01", "source": "simulation", "uri": "http://127.0.0.1:9", "detector": "virtual",
                         "fps": 20, "width": 320, "height": 320, "timeout_s": 0.6, "reconnect_s": 0.2}]}


@pytest.fixture(autouse=True)
def fresh_controller():
    """The controller is an application-wide singleton: every test starts from a clean AUTO / healthy state."""
    def reset():
        app_state.controller.set_data_health(True)
        app_state.controller.set_mode(SystemMode.AUTO)
    reset()
    yield
    reset()


class Feed:
    """What the fake virtual camera returns; None = signal lost."""
    xml = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(yaml.safe_dump(CAM_YAML))
    monkeypatch.setattr(settings, "vision_config_path", str(cfg))
    monkeypatch.setattr(settings, "vision_enabled", True)
    Feed.xml = sim_xml(80)
    monkeypatch.setattr(sources.SimulationSource, "_http_fetch", lambda self: Feed.xml)
    pushed = []

    async def fake_send(self, payload):                 # the real ordering / throttling logic stays active
        pushed.append(payload)
        return True

    async def noop(self):
        return None
    monkeypatch.setattr(SimulationBridge, "_send", fake_send)
    monkeypatch.setattr(SimulationBridge, "release", noop)
    with TestClient(app) as c:
        c.pushed = pushed
        wait(lambda: c.get("/api/vision/cameras").json()["cameras"][0]["frames"] >= 3)
        yield c
    app_state.controller.set_data_health(True)


def wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def mode(c):
    return c.get("/api/control/status").json()["mode"]


def test_camera_listing_and_status(client):
    d = client.get("/api/vision/cameras").json()
    cam = d["cameras"][0]
    assert d["active"] and d["healthy"] and cam["id"] == "CAM-01" and cam["state"] == "connected"
    assert cam["detector"]["name"] == "virtual" and cam["detector"]["state"] == "ok"
    assert cam["fps"] > 3 and cam["width"] == 320 and any(z["id"] == "east-in" for z in cam["zones"])
    assert d["analysis"]["vehicles"] > 0
    assert client.get("/api/vision/cameras/CAM-01").json()["id"] == "CAM-01"


def test_snapshot_is_a_jpeg_with_boxes_only_when_overlay_is_on(client):
    plain = client.get("/api/vision/cameras/CAM-01/snapshot.jpg?overlay=false")
    boxed = client.get("/api/vision/cameras/CAM-01/snapshot.jpg?overlay=true&zones=true")
    assert plain.status_code == 200 and plain.headers["content-type"] == "image/jpeg"
    a, b = Image.open(io.BytesIO(plain.content)), Image.open(io.BytesIO(boxed.content))
    assert a.size == b.size == (320, 320) and a.tobytes() != b.tobytes()


def test_detections_are_zoned_and_carry_track_ids(client):
    d = client.get("/api/vision/cameras/CAM-01/detections").json()
    assert d["state"] == "connected" and d["detections"]
    assert any(x["zone"] for x in d["detections"]) and all(0 <= x["x"] <= 1 for x in d["detections"])
    assert any(x["track_id"] for x in d["detections"])
    assert {x["cls"] for x in d["detections"]} <= {"car", "truck", "bus", "tram", "emergency", "person"}


def test_threshold_and_classes_can_be_changed_at_runtime(client):
    n = len(client.get("/api/vision/cameras/CAM-01/detections").json()["detections"])
    assert n > 0
    r = client.patch("/api/vision/cameras/CAM-01/config", json={"confidence": 0.99})
    assert r.status_code == 200 and r.json()["confidence"] == 0.99
    assert wait(lambda: len(client.get("/api/vision/cameras/CAM-01/detections").json()["detections"]) == 0)
    client.patch("/api/vision/cameras/CAM-01/config", json={"confidence": 0.5, "classes": ["person"]})
    assert wait(lambda: {x["cls"] for x in client.get("/api/vision/cameras/CAM-01/detections").json()["detections"]}
                <= {"person"})


@pytest.mark.parametrize("body", [{"confidence": 1.5}, {"confidence": -1}, {"classes": ["unicorn"]}])
def test_invalid_detector_config_is_rejected(client, body):
    assert client.patch("/api/vision/cameras/CAM-01/config", json=body).status_code == 422


def test_unknown_camera_is_404_everywhere(client):
    for method, url in [("get", "/api/vision/cameras/X"), ("get", "/api/vision/cameras/X/snapshot.jpg"),
                        ("get", "/api/vision/cameras/X/detections"), ("post", "/api/vision/cameras/X/connect"),
                        ("post", "/api/vision/cameras/X/disconnect"), ("get", "/api/vision/cameras/X/stream")]:
        assert getattr(client, method)(url).status_code == 404, url


def test_disconnecting_the_camera_switches_to_failsafe_and_reconnecting_recovers(client):
    assert mode(client) == "AUTO"
    r = client.post("/api/vision/cameras/CAM-01/disconnect").json()
    assert r["state"] == "disconnected" and r["healthy"] is False
    assert mode(client) == "FAILSAFE"
    assert client.get("/api/control/status").json()["failsafe_reason"].startswith("Camera:")
    snap = client.get("/api/vision/cameras/CAM-01/snapshot.jpg")
    assert snap.status_code == 200 and Image.open(io.BytesIO(snap.content)).size == (320, 320)   # placeholder image
    assert client.get("/api/vision/analysis").json() is None
    client.post("/api/vision/cameras/CAM-01/connect")
    assert wait(lambda: mode(client) == "AUTO")
    assert client.get("/api/vision/cameras").json()["healthy"]


def test_lost_video_signal_triggers_failsafe_after_the_timeout_and_recovers(client):
    Feed.xml = None                                          # cable pulled
    assert wait(lambda: mode(client) == "FAILSAFE", timeout=4)
    cam = client.get("/api/vision/cameras").json()["cameras"][0]
    assert cam["healthy"] is False and "no signal" in cam["reason"]
    assert client.get("/api/health").status_code == 200      # the backend and the Dashboard keep working
    Feed.xml = sim_xml(90)
    assert wait(lambda: mode(client) == "AUTO", timeout=4)


def test_cannot_switch_to_auto_while_the_camera_is_down(client):
    client.post("/api/vision/cameras/CAM-01/disconnect")
    r = client.post("/api/control/mode", json={"mode": "AUTO"})
    assert r.status_code == 200 and mode(client) == "FAILSAFE"


def test_manual_mode_is_not_overridden_by_a_camera_failure(client):
    client.post("/api/control/mode", json={"mode": "MANUAL"})
    client.post("/api/vision/cameras/CAM-01/disconnect")
    assert mode(client) == "MANUAL"
    client.post("/api/control/mode", json={"mode": "AUTO"})
    assert mode(client) == "FAILSAFE"                        # leaving MANUAL blind ends in FAILSAFE
    client.post("/api/vision/cameras/CAM-01/connect")
    assert wait(lambda: mode(client) == "AUTO")


def test_user_selected_failsafe_is_not_cancelled_by_camera_recovery(client):
    client.post("/api/control/mode", json={"mode": "FAILSAFE"})
    client.post("/api/vision/cameras/CAM-01/disconnect")
    client.post("/api/vision/cameras/CAM-01/connect")
    assert wait(lambda: client.get("/api/vision/cameras").json()["healthy"])
    assert mode(client) == "FAILSAFE"


def test_perception_is_pushed_to_the_simulation_and_marks_camera_loss(client):
    assert wait(lambda: any(p["camera_ok"] and p["vehicles"] for p in client.pushed))
    ok = next(p for p in client.pushed if p["camera_ok"] and p["vehicles"])
    assert set(ok) == {"camera_ok", "vehicles", "pedestrians_waiting", "ped_priority", "emergency"}
    assert set(ok["vehicles"]) <= {"north", "south", "east", "west"}
    client.pushed.clear()
    client.post("/api/vision/cameras/CAM-01/disconnect")
    assert client.pushed and client.pushed[-1]["camera_ok"] is False        # the last word is "camera lost"
    time.sleep(0.4)
    assert client.pushed[-1]["camera_ok"] is False and not any(p["camera_ok"] for p in client.pushed[-3:])


def test_websocket_carries_vision_state_without_heavy_fields(client):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        while msg.get("type") != "state_update":
            msg = ws.receive_json()
    v = msg["vision"]
    assert v["active"] and v["healthy"] and v["cameras"][0]["state"] == "connected"
    assert "detections" not in v["cameras"][0] and "zones" not in v["cameras"][0]
    assert v["analysis"]["vehicles"] >= 0


def test_metrics_report_camera_state_and_fps(client):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        while msg.get("type") != "state_update":
            msg = ws.receive_json()
    sysm = msg["metrics"]["system"]
    assert sysm["camera_status"] == "connected" and sysm["camera_fps"] > 0 and sysm["yolo_status"] == "ok"


def test_dashboard_metrics_come_from_the_camera_analysis(client):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        while msg.get("type") != "state_update":
            msg = ws.receive_json()
    t = msg["metrics"]["traffic"]
    assert t["total_cars"] + t["total_trucks"] + t["total_buses"] > 0


# ---------------------------------------------------------------- failure isolation at start-up

def test_backend_starts_without_any_camera_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vision_config_path", str(tmp_path / "missing.yaml"))
    monkeypatch.setattr(settings, "camera_mode", "simulation")
    monkeypatch.setattr(sources.SimulationSource, "_http_fetch", lambda self: None)
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/vision/cameras").json()["active"] is True     # default simulation camera from settings
    app_state.controller.set_data_health(True)


def test_backend_starts_when_vision_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "vision_enabled", False)
    with TestClient(app) as c:
        d = c.get("/api/vision/cameras").json()
        assert d["active"] is False and d["cameras"] == []
        assert c.get("/api/vision/analysis").json() is None
        assert c.get("/api/vision/cameras/CAM-01").status_code == 404
        assert c.get("/api/control/status").json()["mode"] == "AUTO"       # no camera = no forced FAILSAFE


@pytest.mark.parametrize("content", ["cameras: [oops", "cameras: {a: 1}", "cameras:\n  - id: A\n    source: telepathy\n"])
def test_broken_camera_config_does_not_stop_the_backend(tmp_path, monkeypatch, content):
    f = tmp_path / "bad.yaml"
    f.write_text(content)
    monkeypatch.setattr(settings, "vision_config_path", str(f))
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/vision/cameras").json()["active"] is False


def test_yolo_camera_without_the_package_keeps_the_image_and_goes_failsafe(tmp_path, monkeypatch):
    img = tmp_path / "road.png"
    Image.new("RGB", (64, 48), (20, 80, 20)).save(img)
    f = tmp_path / "c.yaml"
    f.write_text(yaml.safe_dump({"cameras": [{"id": "CAM-Y", "source": "image", "uri": str(img), "detector": "yolo",
                                              "model_path": str(tmp_path / "missing.pt"), "fps": 20,
                                              "width": 64, "height": 48, "timeout_s": 0.5}]}))
    monkeypatch.setattr(settings, "vision_config_path", str(f))
    with TestClient(app) as c:
        assert wait(lambda: mode(c) == "FAILSAFE", timeout=4)
        cam = c.get("/api/vision/cameras/CAM-Y").json()
        assert cam["state"] == "connected" and cam["detector"]["state"] == "unavailable"
        assert cam["detector"]["error"]
        r = c.get("/api/vision/cameras/CAM-Y/snapshot.jpg")
        assert r.status_code == 200 and Image.open(io.BytesIO(r.content)).size == (64, 48)   # image still displayed
        assert c.get("/api/health").status_code == 200
    app_state.controller.set_data_health(True)
