"""Shared helpers for the vision tests."""
import asyncio
import time
from typing import Callable, List, Optional

from PIL import Image

from backend.vision.config import CameraConfig, Zone
from backend.vision.detectors import Detector
from backend.vision.pipeline import CameraPipeline
from backend.vision.analysis import TrafficAnalyzer
from backend.vision.sources import CameraSource
from backend.vision.types import CameraError, Detection, DetectorUnavailable, Frame
from smart_intersection.engine.simulation import SimulationEngine
from smart_intersection.xml_export.exporter import SimStateExporter


def sim_xml(seconds: float = 60, scenario_cfg: Optional[dict] = None, seed: int = 42) -> str:
    """XML of a running simulation (what the SI service serves on /sensor/camera-feed)."""
    e = SimulationEngine(seed=seed)
    e.configure(spawn_rate=30.0, ped_spawn_rate=15.0, **(scenario_cfg or {}))
    e.advance(seconds)
    return SimStateExporter.to_xml(e.get_state())


def det(cls="car", x=0.5, y=0.5, w=0.05, h=0.05, conf=0.9) -> Detection:
    return Detection(cls=cls, confidence=conf, x=x, y=y, w=w, h=h)


class FakeSource(CameraSource):
    """Scriptable source: `frames` is consumed one per read(); None means "no frame"."""
    kind = "fake"

    def __init__(self, cfg: CameraConfig, frames: Optional[List] = None, fail_open: int = 0):
        super().__init__(cfg)
        self.script = list(frames) if frames is not None else None
        self.fail_open = fail_open
        self.open_calls = 0
        self.closed = 0
        self.mode = "ok"                      # ok | none | raise

    def open(self):
        self.open_calls += 1
        if self.open_calls <= self.fail_open:
            raise CameraError("device busy")
        self._open = True

    def read(self):
        if self.mode == "raise":
            raise RuntimeError("usb glitch")
        if self.mode == "none":
            return None
        if self.script is not None:
            item = self.script.pop(0) if self.script else None
            return item
        return self._frame(Image.new("RGB", (self.cfg.width, self.cfg.height), (30, 30, 30)),
                           detections=[det("car", 0.3, 0.3), det("person", 0.6, 0.6)])

    def close(self):
        self.closed += 1
        super().close()


class FakeDetector(Detector):
    name = "fake"

    def __init__(self):
        super().__init__(0.5, None)
        self.mode = "ok"                      # ok | unavailable | error

    def detect(self, frame):
        if self.mode == "unavailable":
            raise DetectorUnavailable("model file not found")
        if self.mode == "error":
            raise RuntimeError("inference blew up")
        return list(frame.detections or [])


def make_pipeline(cfg: Optional[CameraConfig] = None, source=None, detector=None, zones=None, **kw):
    cfg = cfg or CameraConfig(id="CAM-T", fps=100.0, width=64, height=48, timeout_s=0.3, reconnect_s=0.1,
                              detector="virtual")
    zones = zones or [Zone("z-all", "lane", [(0, 0), (1, 0), (1, 1), (0, 1)], "north"),
                      Zone("p-all", "pedestrian", [(0.5, 0.5), (1, 0.5), (1, 1), (0.5, 1)], "north")]
    source = source or FakeSource(cfg)
    detector = detector or FakeDetector()
    return CameraPipeline(cfg, source, detector, TrafficAnalyzer(zones), **kw)


async def wait_for(cond: Callable[[], bool], timeout: float = 3.0, step: float = 0.01) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(step)
    return cond()
