"""
Vision pipeline: CameraSource -> Detector -> TrafficAnalyzer, one asyncio task per camera.

The pipeline only reports health and results through callbacks; it does not import the traffic controller or GPIO.
A failing camera or detector never raises out of the loop: it is logged, shown in the status and reported as
"unhealthy" so the application can switch the signals to FAILSAFE while the web UI keeps running (Task 24).
"""
import asyncio
import inspect
import io
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from .analysis import TrafficAnalyzer, TrafficSnapshot, merge_snapshots
from .config import CameraConfig, full_frame_zone
from .detectors import Detector, create_detector
from .sources import CameraSource, create_source
from .types import CameraError, Detection, DetectorUnavailable, Frame

logger = logging.getLogger(__name__)

CLASS_COLORS = {
    "car": (59, 130, 246), "truck": (249, 115, 22), "bus": (34, 197, 94), "tram": (168, 85, 247),
    "emergency": (239, 68, 68), "person": (250, 204, 21), "motorcycle": (6, 182, 212), "bicycle": (132, 204, 22),
}
DETECTOR_FAILURES_BEFORE_UNHEALTHY = 3


def _redact(uri: str) -> str:
    return re.sub(r"//[^/@]*@", "//***@", uri or "")


async def _maybe_await(value: Any) -> None:
    if inspect.isawaitable(value):
        await value


class CameraPipeline:
    def __init__(self, cfg: CameraConfig, source: CameraSource, detector: Detector, analyzer: TrafficAnalyzer, *,
                 clock: Callable[[], float] = time.monotonic,
                 on_update: Optional[Callable[[str, TrafficSnapshot], Any]] = None,
                 on_health: Optional[Callable[[str, bool, str], Any]] = None):
        self.cfg, self.source, self.detector, self.analyzer = cfg, source, detector, analyzer
        self._clock, self._on_update, self._on_health = clock, on_update, on_health
        self._task: Optional[asyncio.Task] = None
        self._enabled = cfg.enabled
        self._started_at = clock()
        self._next_open = 0.0
        self._last_frame_at: Optional[float] = None
        self._last_logged_error: Optional[str] = None
        self._last_detector_msg: Optional[str] = None
        self.camera_state = "disconnected" if not self._enabled else "connecting"
        self.camera_error: Optional[str] = None
        self.detector_state = "loading"
        self.detector_error: Optional[str] = None
        self._detector_failures = 0
        self.fps = 0.0
        self.frames = 0
        self.frame: Optional[Frame] = None
        self.detections: List[Detection] = []
        self.snapshot: Optional[TrafficSnapshot] = None
        self.healthy = True
        self.reason = "starting"
        self._jpeg_cache: Dict[tuple, bytes] = {}

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"camera-{self.cfg.id}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await asyncio.to_thread(self.source.close)

    async def disconnect(self) -> None:
        """Unplug the camera (manual switch, used to demonstrate FAILSAFE)."""
        self._enabled = False
        await asyncio.to_thread(self.source.close)
        self.camera_state, self.frame, self.detections = "disconnected", None, []
        logger.warning("Camera %s disconnected by user", self.cfg.id)
        await self._evaluate()

    async def connect(self) -> None:
        self._enabled, self._next_open = True, 0.0
        self._started_at, self._last_frame_at = self._clock(), None
        self.camera_state = "connecting"
        logger.info("Camera %s connect requested", self.cfg.id)

    # ------------------------------------------------------------------ main loop
    async def _run(self) -> None:
        period = 1.0 / self.cfg.fps
        while True:
            t0 = self._clock()
            try:
                await self._step()
            except asyncio.CancelledError:
                raise
            except Exception as e:                                       # a bug here must not kill the loop
                logger.exception("Camera %s: unexpected pipeline error", self.cfg.id)
                self.camera_state, self.camera_error = "error", f"internal error: {e}"
            await self._evaluate()
            await asyncio.sleep(max(0.005, period - (self._clock() - t0)))

    async def _step(self) -> None:
        now = self._clock()
        if not self._enabled:
            self.camera_state = "disconnected"
            return
        if not self.source.is_open:
            if now < self._next_open:
                return
            self.camera_state = "connecting" if self._last_frame_at is None else "no_signal"
            try:
                await asyncio.to_thread(self.source.open)
            except CameraError as e:
                self._camera_failed(str(e), now)
                return
            self.camera_error = None
        try:
            frame = await asyncio.to_thread(self.source.read)
        except Exception as e:
            await asyncio.to_thread(self.source.close)
            self._camera_failed(f"read failed: {e}", now)
            return
        if not self._enabled:                                 # disconnect() ran while we were reading
            return
        if frame is None:
            if self._last_frame_at is not None:
                self.camera_state = "no_signal"
                if now - self._last_frame_at > max(self.cfg.reconnect_s, self.cfg.timeout_s):
                    await asyncio.to_thread(self.source.close)           # force a clean re-open
            return
        self._accept_frame(frame, now)
        await self._detect(frame, now)
        if not self._enabled:                                 # ... or while detection was running
            self.detections, self.frame = [], None

    def _camera_failed(self, msg: str, now: float) -> None:
        self.camera_state, self.camera_error = "error", msg
        self._next_open = now + self.cfg.reconnect_s
        if msg != self._last_logged_error:
            logger.warning("Camera %s: %s", self.cfg.id, msg)
            self._last_logged_error = msg

    def _accept_frame(self, frame: Frame, now: float) -> None:
        if self._last_frame_at is not None and now > self._last_frame_at:
            inst = 1.0 / (now - self._last_frame_at)
            self.fps = inst if self.fps == 0 else 0.8 * self.fps + 0.2 * inst
        if self.camera_state != "connected":
            logger.info("Camera %s connected", self.cfg.id)
        self._last_frame_at, self.frames = now, self.frames + 1
        self.camera_state, self._last_logged_error = "connected", None
        self.frame = frame

    async def _detect(self, frame: Frame, now: float) -> None:
        try:
            dets = await asyncio.to_thread(self.detector.detect, frame)
        except DetectorUnavailable as e:
            self._detector_failed(str(e), fatal=True)
            self.detections = []
            return
        except Exception as e:
            self._detector_failed(f"detector error: {e}", fatal=False)
            self.detections = []
            return
        self._detector_failures, self.detector_error, self.detector_state = 0, None, "ok"
        self.detections = dets
        # A simulation frame carries its own clock: waits and flows are then in simulation seconds, at any speed.
        self.snapshot = self.analyzer.analyze(self.cfg.id, dets, float(frame.meta.get("sim_time", now)))
        if self._on_update:
            await _maybe_await(self._on_update(self.cfg.id, self.snapshot))

    def _detector_failed(self, msg: str, fatal: bool) -> None:
        self._detector_failures = DETECTOR_FAILURES_BEFORE_UNHEALTHY if fatal else self._detector_failures + 1
        self.detector_error = msg
        self.detector_state = "unavailable" if fatal else "error"
        if msg != self._last_detector_msg:
            logger.error("Camera %s detector: %s", self.cfg.id, msg)
            self._last_detector_msg = msg

    # ------------------------------------------------------------------ health
    def _health(self, now: float):
        if not self._enabled:
            return False, "camera disconnected"
        if self.camera_state == "error":
            return False, f"camera error: {self.camera_error}"
        if self._detector_failures >= DETECTOR_FAILURES_BEFORE_UNHEALTHY:
            return False, f"detector failure: {self.detector_error}"
        if self._last_frame_at is None:
            if now - self._started_at > self.cfg.timeout_s:
                return False, "no frames received"
            return True, "connecting"
        age = now - self._last_frame_at
        if age > self.cfg.timeout_s:
            return False, f"no signal for {age:.1f}s"
        return True, "ok"

    async def _evaluate(self) -> None:
        healthy, reason = self._health(self._clock())
        changed = healthy != self.healthy
        self.healthy, self.reason = healthy, reason
        if changed:
            (logger.info if healthy else logger.warning)("Camera %s health: %s (%s)", self.cfg.id,
                                                         "OK" if healthy else "UNHEALTHY", reason)
            if self._on_health:
                await _maybe_await(self._on_health(self.cfg.id, healthy, reason))

    # ------------------------------------------------------------------ outputs
    def status(self, detail: bool = True) -> Dict[str, Any]:
        now = self._clock()
        out = {
            "id": self.cfg.id, "name": self.cfg.name, "source": self.cfg.source, "uri": _redact(self.cfg.uri),
            "enabled": self._enabled, "state": self.camera_state, "error": self.camera_error,
            "healthy": self.healthy, "reason": self.reason, "fps": round(self.fps, 1), "frames": self.frames,
            "last_frame_age_s": round(now - self._last_frame_at, 2) if self._last_frame_at is not None else None,
            "width": self.cfg.width, "height": self.cfg.height,
            "detector": {**self.detector.describe(), "state": self.detector_state, "error": self.detector_error},
        }
        if detail:
            out["zones"] = [{"id": z.id, "kind": z.kind, "direction": z.direction, "polygon": z.polygon}
                            for z in self.analyzer.zones]
            out["detections"] = [d.to_dict() for d in self.detections]
        return out

    def _placeholder(self, text: str) -> Image.Image:
        img = Image.new("RGB", (self.cfg.width, self.cfg.height), (24, 26, 34))
        d = ImageDraw.Draw(img)
        d.rectangle([2, 2, img.width - 3, img.height - 3], outline=(120, 40, 40), width=2)
        big = ImageFont.load_default(size=max(14, img.width // 16))
        small = ImageFont.load_default(size=max(10, img.width // 40))
        d.text((img.width / 2, img.height / 2), text, fill=(240, 120, 120), font=big, anchor="mm")
        d.text((8, 8), self.cfg.id, fill=(160, 160, 170), font=small)
        return img

    def render(self, overlay: bool = True, zones: bool = False, quality: int = 75) -> bytes:
        """JPEG of the latest frame with detection boxes; a labelled placeholder while there is no signal."""
        live = self.frame is not None and self.camera_state == "connected"
        key = (self.frame.seq if live else self.camera_state, overlay, zones, quality, self.cfg.width)
        cached = self._jpeg_cache.get("last")
        if cached and cached[0] == key:
            return cached[1]
        if live:
            img = self.frame.image.convert("RGB")
            if overlay:
                self._draw(img, zones)
        else:
            label = {"disconnected": "CAMERA DISCONNECTED", "error": "CAMERA ERROR", "no_signal": "NO SIGNAL",
                     "connecting": "CONNECTING..."}.get(self.camera_state, "NO SIGNAL")
            img = self._placeholder(label)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        data = buf.getvalue()
        self._jpeg_cache["last"] = (key, data)
        return data

    def _draw(self, img: Image.Image, zones: bool) -> None:
        d = ImageDraw.Draw(img)
        f = ImageFont.load_default()
        W, H = img.size
        if zones:
            for z in self.analyzer.zones:
                pts = [(x * W, y * H) for x, y in z.polygon]
                d.polygon(pts, outline=(255, 255, 255))
                d.text((pts[0][0] + 2, pts[0][1] + 2), z.id, fill=(255, 255, 255), font=f)
        for det in self.detections:
            color = CLASS_COLORS.get(det.cls, (200, 200, 200))
            x0, y0 = (det.x - det.w / 2) * W, (det.y - det.h / 2) * H
            x1, y1 = (det.x + det.w / 2) * W, (det.y + det.h / 2) * H
            d.rectangle([x0, y0, x1, y1], outline=color, width=2)
            tag = f"{det.cls} {det.confidence:.2f}" + (f" #{det.track_id}" if det.track_id else "")
            tw = 6 * len(tag) + 4
            d.rectangle([x0, y0 - 11, x0 + tw, y0], fill=color)
            d.text((x0 + 2, y0 - 10), tag, fill=(0, 0, 0), font=f)


class VisionManager:
    """All cameras of the system. Aggregates health and traffic analysis; camera absence is not an error."""

    def __init__(self, pipelines: List[CameraPipeline], *,
                 on_health: Optional[Callable[[bool, str], Any]] = None,
                 on_snapshot: Optional[Callable[[TrafficSnapshot, bool], Any]] = None):
        self.pipelines: Dict[str, CameraPipeline] = {p.cfg.id: p for p in pipelines}
        self._on_health, self._on_snapshot = on_health, on_snapshot
        self._last_health: Optional[tuple] = None
        for p in pipelines:
            p._on_health = self._camera_health
            p._on_update = self._camera_update

    @property
    def active(self) -> bool:
        return bool(self.pipelines)

    @property
    def healthy(self) -> bool:
        return self.active and all(p.healthy for p in self.pipelines.values())

    @property
    def reason(self) -> str:
        bad = [f"{p.cfg.id}: {p.reason}" for p in self.pipelines.values() if not p.healthy]
        return "; ".join(bad) if bad else "ok"

    def snapshot(self) -> Optional[TrafficSnapshot]:
        snaps = [p.snapshot for p in self.pipelines.values() if p.snapshot is not None and p.healthy]
        return merge_snapshots(snaps) if snaps else None

    async def _camera_health(self, camera_id: str, healthy: bool, reason: str) -> None:
        state = (self.healthy, self.reason if not self.healthy else "ok")
        if state != self._last_health:
            self._last_health = state
            if self._on_health:
                await _maybe_await(self._on_health(*state))

    async def _camera_update(self, camera_id: str, snap: TrafficSnapshot) -> None:
        if self._on_snapshot:
            merged = self.snapshot()
            if merged is not None:
                await _maybe_await(self._on_snapshot(merged, self.healthy))

    async def start(self) -> None:
        for p in self.pipelines.values():
            await p.start()

    async def stop(self) -> None:
        for p in self.pipelines.values():
            await p.stop()

    def status(self, detail: bool = True) -> Dict[str, Any]:
        snap = self.snapshot()
        return {"active": self.active, "healthy": self.healthy, "reason": self.reason,
                "cameras": [p.status(detail) for p in self.pipelines.values()],
                "analysis": snap.to_dict() if snap else None}

    def get(self, camera_id: str) -> CameraPipeline:
        try:
            return self.pipelines[camera_id]
        except KeyError:
            raise KeyError(f"unknown camera {camera_id!r}")


def build_manager(configs: List[CameraConfig], *, ped_priority_threshold: int = 5,
                  on_health=None, on_snapshot=None, source_factory=create_source,
                  detector_factory=create_detector) -> VisionManager:
    pipelines = []
    for cfg in configs:
        if not cfg.enabled:
            continue                                             # configured but switched off in cameras.yaml
        source = source_factory(cfg)
        zones = cfg.zones or getattr(source, "zones", None) or [full_frame_zone()]
        pipelines.append(CameraPipeline(cfg, source, detector_factory(cfg), TrafficAnalyzer(zones, ped_priority_threshold, foot_zones=cfg.calibrated)))
    return VisionManager(pipelines, on_health=on_health, on_snapshot=on_snapshot)
