"""Config loading and camera sources (simulation, image, video file, USB, network)."""
import builtins
import os

import pytest
import yaml
from PIL import Image

from backend.vision.config import (CameraConfig, Zone, camera_from_dict, default_cameras, full_frame_zone,
                                   load_cameras)
from backend.vision.sources import (FileSource, ImageSource, NetworkSource, SimulationSource, UsbSource,
                                    create_source, discover_usb_cameras)
from backend.vision.types import CameraError
from .vision_helpers import sim_xml

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


# ---------------------------------------------------------------- config

def test_zone_contains_uses_polygon_not_bounding_box():
    tri = Zone("t", "lane", [(0, 0), (1, 0), (0, 1)])
    assert tri.contains(0.2, 0.2) and not tri.contains(0.8, 0.8)


def test_load_cameras_from_yaml(tmp_path):
    f = tmp_path / "cameras.yaml"
    f.write_text(yaml.safe_dump({"cameras": [
        {"id": "A", "source": "file", "uri": "x.mp4", "fps": 8, "confidence": 0.4, "classes": ["car"],
         "zones": [{"id": "z1", "kind": "lane", "direction": "north", "polygon": [[0, 0], [1, 0], [1, 1]]}]},
        {"id": "B", "source": "simulation", "uri": "http://127.0.0.1:9"},
    ]}))
    a, b = load_cameras(str(f))
    assert (a.source, a.detector, a.fps, a.confidence, a.classes) == ("file", "yolo", 8.0, 0.4, ["car"])
    assert a.zones[0].direction == "north" and a.zones[0].polygon[1] == (1.0, 0.0)
    assert (b.source, b.detector) == ("simulation", "virtual")


@pytest.mark.parametrize("bad", [
    {"cameras": [{"id": "A", "source": "telepathy"}]},
    {"cameras": [{"id": "A", "detector": "magic"}]},
    {"cameras": [{"id": "A", "fps": 0}]},
    {"cameras": [{"id": "A"}, {"id": "A"}]},
    {"cameras": "nope"},
])
def test_invalid_camera_config_fails_loudly(tmp_path, bad):
    f = tmp_path / "c.yaml"
    f.write_text(yaml.safe_dump(bad))
    with pytest.raises(ValueError):
        load_cameras(str(f))


def test_missing_yaml_falls_back_to_settings_defaults():
    class S:
        camera_mode, video_source, camera_fps, camera_width, camera_height = "file", "demo.mp4", 7, 320, 240
        yolo_confidence, yolo_model_path, yolo_device = 0.6, "m.pt", "cpu"
    (cam,) = load_cameras("does-not-exist.yaml", S)
    assert (cam.source, cam.uri, cam.fps, cam.detector, cam.confidence) == ("file", "demo.mp4", 7.0, "yolo", 0.6)
    (sim,) = default_cameras(type("S2", (), {"camera_mode": "simulation"}))
    assert sim.source == "simulation" and sim.detector == "virtual" and sim.uri.startswith("http")


def test_repository_cameras_yaml_is_valid_and_zones_are_well_formed():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "cameras.yaml")
    assert os.path.isfile(path)
    cams = load_cameras(path)
    assert [c.id for c in cams] == ["CAM-01"] and cams[0].source == "simulation" and cams[0].detector == "virtual"
    assert cams[0].timeout_s > 0 and cams[0].width == cams[0].height == 640


# ---------------------------------------------------------------- simulation source

def test_simulation_source_renders_frame_and_virtual_detections():
    xml = sim_xml(80)
    src = SimulationSource(CameraConfig(width=640, height=480), fetch_xml=lambda: xml)
    src.open()
    f = src.read()
    assert f.image.size == (640, 480) and f.seq == 1 and f.detections
    assert {d.cls for d in f.detections} <= {"car", "truck", "bus", "tram", "emergency", "person"}
    assert src.read().seq == 2
    assert {z.id for z in src.zones} >= {"north-in", "PC-N"}


def test_simulation_source_reports_signal_loss_as_none():
    src = SimulationSource(CameraConfig(), fetch_xml=lambda: None)
    src.open()
    assert src.read() is None


def test_simulation_source_survives_garbage_xml():
    src = SimulationSource(CameraConfig(), fetch_xml=lambda: "<intersectionSimulation><oops>")
    src.open()
    assert src.read() is None


def test_simulation_source_over_http_treats_connection_refused_as_signal_loss():
    src = SimulationSource(CameraConfig(uri="http://127.0.0.1:9"))       # nothing listens on port 9
    src.open()
    assert src.read() is None
    src.close()


# ---------------------------------------------------------------- still image

def test_image_source(tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGB", (40, 30), (1, 2, 3)).save(p)
    src = ImageSource(CameraConfig(source="image", uri=str(p)))
    src.open()
    f = src.read()
    assert f.image.size == (40, 30) and f.image.getpixel((0, 0)) == (1, 2, 3) and f.detections is None


def test_image_source_errors(tmp_path):
    with pytest.raises(CameraError):
        ImageSource(CameraConfig(source="image", uri=str(tmp_path / "missing.png"))).open()
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    with pytest.raises(CameraError):
        ImageSource(CameraConfig(source="image", uri=str(bad))).open()


# ---------------------------------------------------------------- OpenCV sources

@pytest.fixture
def video(tmp_path):
    path = str(tmp_path / "clip.avi")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 10, (96, 64))
    assert w.isOpened()
    for i in range(6):
        w.write(np.full((64, 96, 3), i * 40, dtype=np.uint8))
    w.release()
    return path


def test_file_source_reads_frames_resizes_and_loops(video):
    src = FileSource(CameraConfig(source="file", uri=video, width=48, height=32))
    src.open()
    frames = [src.read() for _ in range(14)]              # clip has 6 frames -> must wrap around
    src.close()
    assert all(f is not None for f in frames)
    assert frames[0].image.size == (48, 32)
    assert [f.seq for f in frames] == list(range(1, 15))
    assert not src.is_open


def test_file_source_missing_file_is_a_camera_error():
    with pytest.raises(CameraError, match="not found"):
        FileSource(CameraConfig(source="file", uri="nope.mp4")).open()


def test_file_source_rejects_a_file_that_is_not_a_video(tmp_path):
    p = tmp_path / "x.mp4"
    p.write_bytes(b"garbage")
    with pytest.raises(CameraError):
        FileSource(CameraConfig(source="file", uri=str(p))).open()


def test_usb_source_without_a_camera_is_a_camera_error_not_a_crash():
    with pytest.raises(CameraError):
        UsbSource(CameraConfig(source="usb", uri="97")).open()


def test_network_source_needs_a_url_and_reports_unreachable_streams():
    with pytest.raises(CameraError, match="URL"):
        NetworkSource(CameraConfig(source="network", uri="")).open()
    with pytest.raises(CameraError):
        NetworkSource(CameraConfig(source="network", uri="http://127.0.0.1:9/stream.mjpg")).open()


def test_opencv_missing_gives_a_clear_error(monkeypatch, video):
    real_import = builtins.__import__

    def no_cv2(name, *a, **k):
        if name == "cv2":
            raise ImportError("no cv2")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_cv2)
    with pytest.raises(CameraError, match="OpenCV is not installed"):
        FileSource(CameraConfig(source="file", uri=video)).open()
    assert discover_usb_cameras() == []


def test_discover_usb_cameras_returns_a_list():
    assert isinstance(discover_usb_cameras(max_index=1), list)


def test_factory_maps_every_source_kind():
    for kind, cls in [("simulation", SimulationSource), ("usb", UsbSource), ("file", FileSource),
                      ("network", NetworkSource), ("image", ImageSource)]:
        assert isinstance(create_source(CameraConfig(source=kind)), cls)


def test_full_frame_zone_covers_everything():
    z = full_frame_zone()
    assert z.contains(0.01, 0.01) and z.contains(0.99, 0.99)
