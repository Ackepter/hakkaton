"""
Object detectors. A detector turns a Frame into Detection objects and knows nothing about traffic lights,
GPIO or the controller (Task 34.10). Model, confidence threshold and tracked classes are replaceable at runtime.

    Detector
        ├── VirtualDetector   reads the detections a virtual source attached to the frame (Simulation Mode)
        ├── YoloDetector      local YOLO (ultralytics), CPU only, optional dependency
        └── NullDetector      no detection configured
"""
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional

from .config import CameraConfig
from .types import ALL_CLASSES, Detection, DetectorUnavailable, Frame

logger = logging.getLogger(__name__)

# COCO class name -> project class. Custom models extend this through `class_map` (e.g. ambulance -> emergency).
COCO_TO_PROJECT = {
    "person": "person", "bicycle": "bicycle", "car": "car", "motorcycle": "motorcycle",
    "bus": "bus", "truck": "truck", "train": "tram",
}


class Detector(ABC):
    name = "base"

    def __init__(self, confidence: float = 0.5, classes: Optional[Iterable[str]] = None):
        self.confidence = confidence
        self.classes = set(classes) if classes is not None else set(ALL_CLASSES)
        self.error: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self.error is None

    def configure(self, confidence: Optional[float] = None, classes: Optional[Iterable[str]] = None) -> None:
        if confidence is not None:
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("confidence must be within 0..1")
            self.confidence = confidence
        if classes is not None:
            self.classes = set(classes)

    def _keep(self, d: Detection) -> bool:
        return d.confidence >= self.confidence and d.cls in self.classes

    @abstractmethod
    def detect(self, frame: Frame) -> List[Detection]: ...

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "ready": self.ready, "error": self.error,
                "confidence": self.confidence, "classes": sorted(self.classes)}


class VirtualDetector(Detector):
    name = "virtual"

    def detect(self, frame: Frame) -> List[Detection]:
        if frame.detections is None:
            raise DetectorUnavailable("frame carries no virtual detections (use a simulation source)")
        return [d for d in frame.detections if self._keep(d)]


class NullDetector(Detector):
    name = "none"

    @property
    def ready(self) -> bool:
        return False

    def detect(self, frame: Frame) -> List[Detection]:
        raise DetectorUnavailable("no detector configured")


class YoloDetector(Detector):
    """
    Local YOLO through `ultralytics`. Nothing here requires CUDA; `device` defaults to cpu and `imgsz` is small so
    a Raspberry Pi 3B+ can cope. The model is loaded lazily; a missing package or weights file makes the detector
    unavailable (the camera image keeps working, the system falls back to FAILSAFE) instead of crashing the backend.
    `model` can be injected (tests, or a different backend that follows the same call convention).
    """
    name = "yolo"

    def __init__(self, model_path: str = "models/yolov8n.pt", confidence: float = 0.5,
                 classes: Optional[Iterable[str]] = None, device: str = "cpu", imgsz: int = 416,
                 class_map: Optional[Dict[str, str]] = None, model: Any = None):
        super().__init__(confidence, classes)
        self.model_path, self.device, self.imgsz = model_path, device, imgsz
        self.class_map = {**COCO_TO_PROJECT, **(class_map or {})}
        self._model = model

    def load(self) -> None:
        if self._model is not None:
            return
        try:
            from ultralytics import YOLO
        except ImportError as e:
            self.error = "ultralytics is not installed (pip install -r requirements-yolo.txt)"
            raise DetectorUnavailable(self.error) from e
        if not os.path.isfile(self.model_path):
            self.error = f"YOLO model file not found: {self.model_path}"
            raise DetectorUnavailable(self.error)
        try:
            self._model = YOLO(self.model_path)
        except Exception as e:                                       # corrupt weights, incompatible version...
            self.error = f"cannot load YOLO model: {e}"
            raise DetectorUnavailable(self.error) from e
        self.error = None
        logger.info("YOLO model loaded: %s (device=%s, imgsz=%d)", self.model_path, self.device, self.imgsz)

    def detect(self, frame: Frame) -> List[Detection]:
        self.load()
        try:
            import numpy as np
            result = self._model.predict(np.asarray(frame.image), conf=self.confidence, imgsz=self.imgsz,
                                         device=self.device, verbose=False)[0]
        except DetectorUnavailable:
            raise
        except Exception as e:
            self.error = f"YOLO inference failed: {e}"
            raise DetectorUnavailable(self.error) from e
        self.error = None
        return [d for d in self.parse(result) if self._keep(d)]

    def parse(self, result: Any) -> List[Detection]:
        """ultralytics Result -> Detection list (normalised centre boxes, project class names)."""
        names = result.names
        out = []
        boxes = result.boxes
        for (x, y, w, h), c, conf in zip(boxes.xywhn.tolist(), boxes.cls.tolist(), boxes.conf.tolist()):
            cls = self.class_map.get(names[int(c)])
            if cls:
                out.append(Detection(cls=cls, confidence=float(conf), x=x, y=y, w=w, h=h))
        return out

    def describe(self) -> Dict[str, Any]:
        return {**super().describe(), "model": self.model_path, "device": self.device, "imgsz": self.imgsz}


def create_detector(cfg: CameraConfig, **kwargs) -> Detector:
    if cfg.detector == "virtual":
        return VirtualDetector(cfg.confidence, cfg.classes)
    if cfg.detector == "yolo":
        return YoloDetector(cfg.model_path, cfg.confidence, cfg.classes, cfg.device, cfg.imgsz, cfg.class_map,
                            **kwargs)
    return NullDetector(cfg.confidence, cfg.classes)
