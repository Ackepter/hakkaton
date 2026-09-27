"""Cameras placed in the constructor (layout) become vision cameras of the main backend."""
import time

import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image

from backend.config.settings import settings
from backend.core import app_state
from backend.main import app
from backend.models.schemas import SystemMode
from backend.vision import sources
from smart_intersection.geometry import scene_geometry
from smart_intersection.layout import CameraObject, Layout, default_layout, presets
from .vision_helpers import sim_xml
from .test_vision_api import wait

YAML = {"cameras": [{"id": "CAM-01", "source": "simulation", "uri": "http://127.0.0.1:9", "detector": "virtual",
                     "fps": 20, "width": 320, "height": 320, "timeout_s": 0.6, "reconnect_s": 0.2}]}


class Holder:
    layout = None
    xml = None


@pytest.fixture(autouse=True)
def fresh_controller():
    app_state.controller.set_data_health(True)
    app_state.controller.set_mode(SystemMode.AUTO)
    yield
    app_state.controller.set_data_health(True)
    app_state.controller.set_mode(SystemMode.AUTO)


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text(yaml.safe_dump(YAML))
    monkeypatch.setattr(settings, "vision_config_path", str(cfg))
    monkeypatch.setattr(settings, "vision_enabled", True)
    monkeypatch.setattr(settings, "vision_push_to_simulation", False)
    Holder.layout, Holder.xml = default_layout().model_dump(), sim_xml(60)

    async def fake_layout(self):
        return Holder.layout

    async def fake_geometry(self):
        return scene_geometry(Layout.model_validate(Holder.layout))
    monkeypatch.setattr(type(app_state), "_fetch_layout", fake_layout)
    monkeypatch.setattr(type(app_state), "_fetch_geometry", fake_geometry)
    monkeypatch.setattr(sources.SimulationSource, "_http_fetch", lambda self: Holder.xml)
    monkeypatch.setattr(sources.SimulationSource, "_http_geometry",
                        lambda self: scene_geometry(Layout.model_validate(Holder.layout)))
    with TestClient(app) as c:
        wait(lambda: c.get("/api/vision/cameras").json()["cameras"][0]["frames"] >= 2)
        yield c


def zones(client):
    return {c["id"]: {z["id"] for z in c["zones"]} for c in client.get("/api/vision/cameras").json()["cameras"]}


def test_default_layout_keeps_the_yaml_camera_and_changes_nothing(client):
    p = app_state.vision.pipelines["CAM-01"]
    r = client.post("/api/vision/sync-layout")
    assert r.status_code == 200 and r.json() == {"changed": False, "cameras": ["CAM-01"]}
    assert app_state.vision.pipelines["CAM-01"] is p                        # not restarted
    assert len(zones(client)["CAM-01"]) == 8


def test_zones_follow_the_arms_and_crosswalks_that_exist(client):
    l = default_layout()
    l.arms["south"].enabled = False
    l.arms["east"].crossing = False
    Holder.layout = l.model_dump()
    assert client.post("/api/vision/sync-layout").json()["changed"] is True
    assert zones(client)["CAM-01"] == {"north-in", "east-in", "west-in", "PC-N", "PC-W"}
    assert wait(lambda: client.get("/api/vision/cameras").json()["healthy"])
    assert app_state.vision.snapshot() is not None


def test_placed_cameras_replace_the_simulation_camera_and_split_the_zones(client):
    l = default_layout()
    l.cameras = [CameraObject(id="CAM-A", x=-25, z=-25, radius_m=45, fov_deg=90),
                 CameraObject(id="CAM-B", x=25, z=25, radius_m=45, fov_deg=90)]
    Holder.layout = l.model_dump()
    r = client.post("/api/vision/sync-layout").json()
    assert r["changed"] and set(r["cameras"]) == {"CAM-A", "CAM-B"}
    z = zones(client)
    assert z["CAM-A"] and z["CAM-B"] and z["CAM-A"].isdisjoint(z["CAM-B"])       # no zone is counted twice
    assert z["CAM-A"] | z["CAM-B"] <= {f"{a}-in" for a in ("north", "south", "east", "west")} | {
        "PC-N", "PC-S", "PC-E", "PC-W"}
    cam = app_state.vision.pipelines["CAM-A"].cfg
    assert (cam.x, cam.z, cam.range_m, cam.fov_deg) == (-25, -25, 45, 90)
    assert wait(lambda: all(c["frames"] >= 2 for c in client.get("/api/vision/cameras").json()["cameras"]))


def test_disabled_layout_cameras_are_ignored_and_second_sync_is_a_noop(client):
    l = default_layout()
    l.cameras = [CameraObject(id="CAM-X", x=0, z=0, enabled=False)]
    Holder.layout = l.model_dump()
    assert client.post("/api/vision/sync-layout").json()["cameras"] == ["CAM-01"]
    l.cameras = [CameraObject(id="CAM-X", x=10, z=10, radius_m=50)]
    Holder.layout = l.model_dump()
    assert client.post("/api/vision/sync-layout").json()["changed"] is True
    assert client.post("/api/vision/sync-layout").json()["changed"] is False


def test_a_camera_that_sees_no_zone_still_runs(client):
    l = default_layout()
    l.cameras = [CameraObject(id="CAM-FAR", x=110, z=110, radius_m=20)]              # 20 m range, 150 m from the junction
    Holder.layout = l.model_dump()
    client.post("/api/vision/sync-layout")
    assert zones(client)["CAM-FAR"] == {"no-zones"}
    assert wait(lambda: client.get("/api/vision/cameras").json()["cameras"][0]["frames"] >= 3)
    a = client.get("/api/vision/analysis").json()
    assert a is not None and a["vehicles"] == 0


def test_camera_picture_follows_the_layout(client):
    l = default_layout()
    l.arms["east"].enabled = False
    Holder.layout = l.model_dump()
    time.sleep(3.3)                                                        # the source refreshes the geometry every 3 s
    img = Image.open(__import__("io").BytesIO(client.get("/api/vision/cameras/CAM-01/snapshot.jpg?overlay=false").content))
    cam = app_state.vision.pipelines["CAM-01"].source._view.cam
    px, py, _ = cam.project(35, 0, 2)                                        # a lane centre of the (removed) east road
    east_road = img.convert("RGB").getpixel((int(px * img.size[0] / cam.w), int(py * img.size[1] / cam.h)))
    assert east_road[1] > 100 and east_road[0] < 100                        # green grass where the east road was


def test_sync_reports_503_when_the_simulation_is_down(client, monkeypatch):
    async def down(self):
        return None
    monkeypatch.setattr(type(app_state), "_fetch_layout", down)
    assert client.post("/api/vision/sync-layout").status_code == 503
    assert client.get("/api/health").status_code == 200


def test_yaml_cameras_of_other_kinds_survive_a_sync(tmp_path, monkeypatch):
    img = tmp_path / "road.png"
    Image.new("RGB", (64, 48), (20, 80, 20)).save(img)
    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump({"cameras": YAML["cameras"] + [
        {"id": "CAM-IMG", "source": "image", "uri": str(img), "detector": "none", "fps": 10, "width": 64, "height": 48}]}))
    monkeypatch.setattr(settings, "vision_config_path", str(cfg))
    monkeypatch.setattr(settings, "vision_push_to_simulation", False)
    monkeypatch.setattr(sources.SimulationSource, "_http_fetch", lambda self: sim_xml(30))

    async def fake_layout(self):
        return presets()["T-junction"].model_dump()

    async def fake_geometry(self):
        return scene_geometry(presets()["T-junction"])
    monkeypatch.setattr(type(app_state), "_fetch_layout", fake_layout)
    monkeypatch.setattr(type(app_state), "_fetch_geometry", fake_geometry)
    with TestClient(app) as c:
        assert c.post("/api/vision/sync-layout").status_code == 200
        ids = {x["id"] for x in c.get("/api/vision/cameras").json()["cameras"]}
        assert ids == {"CAM-01", "CAM-IMG"}
        assert "south-in" not in zones(c)["CAM-01"]
