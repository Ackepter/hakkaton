"""Plain data types shared by the vision modules. No dependency on the traffic controller or GPIO."""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

VEHICLE_CLASSES = ("car", "truck", "bus", "tram", "motorcycle", "emergency")
PEDESTRIAN_CLASSES = ("person",)
ALL_CLASSES = VEHICLE_CLASSES + PEDESTRIAN_CLASSES + ("bicycle",)


@dataclass
class Detection:
    """One detected object. Box is centre + size, normalised to the image (0..1)."""
    cls: str
    confidence: float
    x: float
    y: float
    w: float
    h: float
    track_id: Optional[int] = None
    source_id: Optional[str] = None                 # identity known to the source (virtual detections only)
    zone: Optional[str] = None
    lane: Optional[str] = None                      # hint from virtual sources ("north-in")
    world: Optional[Tuple[float, float]] = None     # metres, virtual sources only
    foot: Optional[Tuple[float, float]] = None      # ground contact point, normalised image coordinates (perspective cameras)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["world"] = list(self.world) if self.world else None
        d["foot"] = list(self.foot) if self.foot else None
        return d


@dataclass
class Frame:
    image: Image.Image
    ts: float                                       # wall-clock seconds
    seq: int = 0
    detections: Optional[List[Detection]] = None    # pre-computed by virtual sources
    meta: Dict[str, Any] = field(default_factory=dict)


class CameraError(Exception):
    """Camera cannot be opened / read (missing device, missing OpenCV, bad path...)."""


class DetectorUnavailable(Exception):
    """Detector cannot run (missing YOLO package or model file)."""
