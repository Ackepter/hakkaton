"""Detectors: virtual, YOLO (with an injected fake model - no weights, no ultralytics needed), null."""
import builtins
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.vision.config import CameraConfig
from backend.vision.detectors import (COCO_TO_PROJECT, NullDetector, VirtualDetector, YoloDetector,
                                      create_detector)
from backend.vision.types import DetectorUnavailable, Frame
from .vision_helpers import det


def frame(dets=None):
    return Frame(image=Image.new("RGB", (64, 48)), ts=0.0, seq=1, detections=dets)


class _Arr(list):
    def tolist(self):
        return list(self)


def fake_result(items, names=None):
    """items: [(class_name, conf, (x, y, w, h))] shaped like an ultralytics Results object."""
    names = names or {0: "person", 1: "car", 2: "truck", 3: "train", 4: "ambulance", 5: "kite"}
    inv = {v: k for k, v in names.items()}
    boxes = SimpleNamespace(xywhn=_Arr([b for _, _, b in items]), cls=_Arr([inv[n] for n, _, _ in items]),
                            conf=_Arr([c for _, c, _ in items]))
    return SimpleNamespace(names=names, boxes=boxes)


class FakeModel:
    def __init__(self, result):
        self.result, self.calls = result, []

    def predict(self, arr, **kw):
        self.calls.append((arr.shape, kw))
        return [self.result]


# ---------------------------------------------------------------- virtual

def test_virtual_detector_passes_precomputed_detections_and_filters():
    d = VirtualDetector(confidence=0.6, classes={"car", "person"})
    out = d.detect(frame([det("car", conf=0.9), det("car", conf=0.4), det("bus"), det("person", conf=0.7)]))
    assert [(x.cls, x.confidence) for x in out] == [("car", 0.9), ("person", 0.7)]


def test_virtual_detector_needs_a_frame_with_virtual_detections():
    with pytest.raises(DetectorUnavailable):
        VirtualDetector().detect(frame(None))


def test_configure_changes_threshold_and_classes_at_runtime():
    d = VirtualDetector(0.5)
    d.configure(confidence=0.95, classes=["car"])
    assert d.confidence == 0.95 and d.classes == {"car"}
    with pytest.raises(ValueError):
        d.configure(confidence=1.5)
    with pytest.raises(ValueError):
        d.configure(confidence=-0.1)
    assert d.confidence == 0.95                          # a rejected value changes nothing


# ---------------------------------------------------------------- yolo

def test_yolo_maps_coco_names_to_project_classes_and_skips_unknown_ones():
    res = fake_result([("person", 0.9, (0.1, 0.2, 0.05, 0.1)), ("car", 0.8, (0.5, 0.5, 0.2, 0.1)),
                       ("train", 0.7, (0.3, 0.3, 0.4, 0.2)), ("kite", 0.9, (0.9, 0.9, 0.1, 0.1))])
    y = YoloDetector(model=FakeModel(res))
    out = y.detect(frame())
    assert [d.cls for d in out] == ["person", "car", "tram"]            # kite is not an intersection class
    assert out[1].x == 0.5 and out[1].w == 0.2 and out[1].confidence == 0.8


def test_yolo_custom_classes_through_class_map():
    res = fake_result([("ambulance", 0.9, (0.5, 0.5, 0.1, 0.1))])
    assert YoloDetector(model=FakeModel(res)).detect(frame()) == []
    y = YoloDetector(model=FakeModel(res), class_map={"ambulance": "emergency"})
    assert [d.cls for d in y.detect(frame())] == ["emergency"]


def test_yolo_respects_tracked_classes_and_threshold():
    res = fake_result([("person", 0.9, (0.1, 0.1, 0.1, 0.1)), ("car", 0.55, (0.5, 0.5, 0.1, 0.1)),
                       ("truck", 0.3, (0.7, 0.7, 0.1, 0.1))])
    y = YoloDetector(model=FakeModel(res), confidence=0.5, classes={"car", "truck"})
    assert [d.cls for d in y.detect(frame())] == ["car"]


def test_yolo_is_configured_for_cpu_small_input_and_passes_settings_to_the_model():
    m = FakeModel(fake_result([]))
    y = YoloDetector(model=m, confidence=0.42, device="cpu", imgsz=320)
    y.detect(frame())
    shape, kw = m.calls[0]
    assert shape == (48, 64, 3) and kw["conf"] == 0.42 and kw["device"] == "cpu" and kw["imgsz"] == 320
    assert y.describe()["device"] == "cpu"


def test_yolo_missing_weights_is_unavailable_not_a_crash(tmp_path):
    y = YoloDetector(model_path=str(tmp_path / "nope.pt"))
    with pytest.raises(DetectorUnavailable):
        y.detect(frame())
    assert not y.ready and "not found" in y.error or "ultralytics" in y.error


def test_yolo_without_ultralytics_gives_install_hint(monkeypatch):
    real = builtins.__import__

    def no_ul(name, *a, **k):
        if name == "ultralytics":
            raise ImportError("nope")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_ul)
    y = YoloDetector(model_path="whatever.pt")
    with pytest.raises(DetectorUnavailable, match="requirements-yolo"):
        y.detect(frame())


def test_yolo_inference_failure_is_reported_and_recovers():
    class Flaky:
        n = 0

        def predict(self, arr, **kw):
            Flaky.n += 1
            if Flaky.n == 1:
                raise RuntimeError("out of memory")
            return [fake_result([])]
    y = YoloDetector(model=Flaky())
    with pytest.raises(DetectorUnavailable, match="inference failed"):
        y.detect(frame())
    assert not y.ready
    y.detect(frame())
    assert y.ready                                       # next good frame clears the error


def test_coco_mapping_covers_the_required_classes():
    assert {"person", "car", "truck", "bus"} <= set(COCO_TO_PROJECT.values())
    assert COCO_TO_PROJECT["train"] == "tram"


# ---------------------------------------------------------------- factory / null

def test_null_detector_is_never_ready_and_refuses_to_detect():
    n = NullDetector()
    assert not n.ready
    with pytest.raises(DetectorUnavailable):
        n.detect(frame())


def test_factory_builds_the_configured_detector():
    assert isinstance(create_detector(CameraConfig(detector="virtual")), VirtualDetector)
    assert isinstance(create_detector(CameraConfig(detector="none")), NullDetector)
    y = create_detector(CameraConfig(detector="yolo", model_path="m.pt", confidence=0.3, imgsz=256))
    assert isinstance(y, YoloDetector) and y.model_path == "m.pt" and y.confidence == 0.3 and y.imgsz == 256
