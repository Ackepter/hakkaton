"""Camera configuration: cameras.yaml (or defaults built from Settings) -> CameraConfig objects."""
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .types import ALL_CLASSES

logger = logging.getLogger(__name__)

SOURCES = ("simulation", "usb", "file", "network", "image")
DETECTORS = ("virtual", "yolo", "none")


@dataclass
class Zone:
    id: str
    kind: str                                   # "lane" | "pedestrian"
    polygon: List[Tuple[float, float]]          # normalised image coordinates
    direction: Optional[str] = None             # arm the zone belongs to: north/south/east/west
    capacity: int = 8                           # objects that fill the zone (density = count / capacity)

    def contains(self, x: float, y: float) -> bool:
        inside = False
        pts = self.polygon
        j = len(pts) - 1
        for i in range(len(pts)):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
                inside = not inside
            j = i
        return inside


@dataclass
class CameraConfig:
    id: str = "CAM-01"
    name: str = "Overhead camera"
    source: str = "simulation"
    uri: str = ""                               # device index / file path / stream URL / SI base URL
    fps: float = 5.0
    width: int = 640
    height: int = 640
    detector: str = "virtual"
    confidence: float = 0.5
    classes: List[str] = field(default_factory=lambda: list(ALL_CLASSES))
    model_path: str = "models/yolov8n.pt"
    device: str = "cpu"
    imgsz: int = 416                            # small input keeps YOLO usable on a Raspberry Pi 3B+
    class_map: Dict[str, str] = field(default_factory=dict)   # model class name -> project class
    timeout_s: float = 2.0                      # no frame for this long -> camera lost
    reconnect_s: float = 3.0
    zones: List[Zone] = field(default_factory=list)
    enabled: bool = True
    # mount of the camera (pinhole model, see camera_model): position on the ground plan, height, heading and tilt.
    # x None = a directional default camera mounted beside one approach;
    # yaw / pitch None = aim at the middle of the junction; height / fov / range None = sensible defaults.
    x: Optional[float] = None
    z: Optional[float] = None
    height_m: Optional[float] = None
    yaw_deg: Optional[float] = None
    pitch_deg: Optional[float] = None
    fov_deg: Optional[float] = None             # horizontal field of view
    range_m: Optional[float] = None             # objects farther than this are not detected

    @property
    def calibrated(self) -> bool:
        """The mount is known, so road zones can be projected into the image (always true for simulation cameras)."""
        return self.source == "simulation" or self.x is not None

    def pose(self, box_half: float = 16.0):
        from .camera_model import CameraPose
        return CameraPose(x=self.x if self.x is not None else -(box_half + 14.0),
                          z=self.z if self.z is not None else 0.0,
                          height_m=self.height_m or 12.0,
                          yaw_deg=self.yaw_deg, pitch_deg=self.pitch_deg,
                          fov_deg=self.fov_deg or 55.0, range_m=self.range_m or 75.0)


def _zone_from_dict(d: Dict[str, Any]) -> Zone:
    return Zone(id=str(d["id"]), kind=d.get("kind", "lane"),
                polygon=[(float(x), float(y)) for x, y in d["polygon"]],
                direction=d.get("direction"), capacity=int(d.get("capacity", 8)))


def camera_from_dict(d: Dict[str, Any]) -> CameraConfig:
    src = d.get("source", "simulation")
    if src not in SOURCES:
        raise ValueError(f"camera {d.get('id')!r}: unknown source {src!r} (expected one of {SOURCES})")
    det = d.get("detector", "virtual" if src == "simulation" else "yolo")
    if det not in DETECTORS:
        raise ValueError(f"camera {d.get('id')!r}: unknown detector {det!r} (expected one of {DETECTORS})")
    cfg = CameraConfig(id=str(d.get("id", "CAM-01")), source=src, detector=det)
    for key in ("name", "uri", "fps", "width", "height", "confidence", "model_path", "device", "imgsz",
                "timeout_s", "reconnect_s", "enabled"):
        if key in d:
            setattr(cfg, key, type(getattr(cfg, key))(d[key]))
    for key in ("x", "z", "yaw_deg", "pitch_deg", "height_m", "fov_deg", "range_m"):    # null / missing = automatic
        if d.get(key) is not None:
            setattr(cfg, key, float(d[key]))
    if cfg.fov_deg is not None and not 20.0 <= cfg.fov_deg <= 120.0:
        raise ValueError(f"camera {cfg.id!r}: fov_deg must be within 20..120")
    if "classes" in d:
        cfg.classes = list(d["classes"])
    if "class_map" in d:
        cfg.class_map = dict(d["class_map"])
    cfg.zones = [_zone_from_dict(z) for z in d.get("zones", [])]
    if cfg.fps <= 0:
        raise ValueError(f"camera {cfg.id!r}: fps must be > 0")
    return cfg


def full_frame_zone() -> Zone:
    return Zone(id="full-frame", kind="lane", polygon=[(0, 0), (1, 0), (1, 1), (0, 1)], capacity=20)


def default_cameras(settings) -> List[CameraConfig]:
    """Single camera derived from .env settings when no cameras.yaml exists."""
    mode = getattr(settings, "camera_mode", "simulation")
    cfg = CameraConfig(fps=float(getattr(settings, "camera_fps", 5)),
                       width=int(getattr(settings, "camera_width", 640)),
                       height=int(getattr(settings, "camera_height", 480)),
                       confidence=float(getattr(settings, "yolo_confidence", 0.5)),
                       model_path=getattr(settings, "yolo_model_path", "models/yolov8n.pt"),
                       device=getattr(settings, "yolo_device", "cpu"))
    cfg.source = mode
    cfg.uri = getattr(settings, "si_base_url", "http://127.0.0.1:8001") if mode == "simulation" \
        else str(getattr(settings, "video_source", "0"))
    cfg.detector = "virtual" if mode == "simulation" else "yolo"
    return [cfg]


def load_cameras(path: Optional[str], settings=None) -> List[CameraConfig]:
    """cameras.yaml -> configs. Missing file -> defaults. Broken file -> ValueError (fail loudly at start-up)."""
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        items = raw.get("cameras", [])
        if not isinstance(items, list):
            raise ValueError(f"{path}: 'cameras' must be a list")
        cams = [camera_from_dict(d) for d in items]
        ids = [c.id for c in cams]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{path}: duplicate camera ids {ids}")
        return cams
    logger.info("No camera config at %s - using defaults from settings", path)
    return default_cameras(settings) if settings is not None else [CameraConfig()]
