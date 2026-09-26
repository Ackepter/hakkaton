"""
Camera sources. Everything above this layer (detector, analysis, controller) only sees `CameraSource`.

    CameraSource
        ├── SimulationSource   virtual camera over the Smart Intersection service (no hardware, no OpenCV)
        ├── UsbSource          USB / built-in webcam          (OpenCV)
        ├── FileSource         video file, looped              (OpenCV)   <- camera replacement in WSL
        ├── NetworkSource      RTSP / HTTP stream              (OpenCV)
        └── ImageSource        one still image                 (Pillow)   <- test source

`open()` and `read()` are blocking and are called from a worker thread by the pipeline.
`read()` returns None when there is no frame right now (signal loss); `open()` raises CameraError.
"""
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

import httpx
from PIL import Image

from .config import CameraConfig
from .sim_view import SimView
from .types import CameraError, Frame

logger = logging.getLogger(__name__)


class CameraSource(ABC):
    kind = "base"

    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self._seq = 0
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def read(self) -> Optional[Frame]: ...

    def close(self) -> None:
        self._open = False

    def _frame(self, image: Image.Image, **kw) -> Frame:
        self._seq += 1
        return Frame(image=image, ts=time.time(), seq=self._seq, **kw)


# --------------------------------------------------------------------------- simulation

class SimulationSource(CameraSource):
    """
    Virtual camera. Pulls the simulation's XML (the same contract the Dashboard uses) and renders it as a
    top-down picture together with virtual detections. `fetch_xml` can be injected (tests / other transports).
    """
    kind = "simulation"

    def __init__(self, cfg: CameraConfig, fetch_xml: Optional[Callable[[], Optional[str]]] = None):
        super().__init__(cfg)
        self._view = SimView(cfg.width, cfg.height)
        self._fetch = fetch_xml or self._http_fetch
        self._client: Optional[httpx.Client] = None
        self.zones = self._view.default_zones()

    def _http_fetch(self) -> Optional[str]:
        if self._client is None:
            base = self.cfg.uri or "http://127.0.0.1:8001"
            self._client = httpx.Client(base_url=base, timeout=1.0, trust_env=False)
        try:
            r = self._client.get("/sensor/camera-feed")
        except httpx.HTTPError as e:
            logger.debug("virtual camera feed unreachable: %s", e)
            return None
        return r.text if r.status_code == 200 else None

    def open(self) -> None:
        self._open = True                       # the simulation may start later; loss shows up as "no signal"

    def read(self) -> Optional[Frame]:
        xml = self._fetch()
        if not xml:
            return None
        from backend.xml_parser.parser import XmlParser, XmlParseError
        try:
            data = XmlParser.parse(xml, validate=False)
        except XmlParseError as e:
            logger.warning("virtual camera: bad XML: %s", e)
            return None
        return self._frame(self._view.render(data, self.cfg.id), detections=self._view.detections(data),
                           meta={"sim_time": data.simulation.sim_time, "status": data.simulation.status})

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
        super().close()


# --------------------------------------------------------------------------- OpenCV based

class _CvSource(CameraSource):
    """Shared OpenCV capture logic. OpenCV is imported lazily so the backend runs without it."""
    loop = False

    def __init__(self, cfg: CameraConfig):
        super().__init__(cfg)
        self._cap = None
        self._cv2 = None

    def _target(self):
        raise NotImplementedError

    def open(self) -> None:
        try:
            import cv2
        except ImportError as e:
            raise CameraError("OpenCV is not installed (pip install opencv-python-headless)") from e
        self._cv2 = cv2
        target = self._target()
        cap = cv2.VideoCapture(target)
        if not cap.isOpened():
            cap.release()
            raise CameraError(f"cannot open {self.kind} source {target!r}")
        if self.kind == "usb":
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
            cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)
        self._cap, self._open = cap, True
        logger.info("Camera %s connected (%s: %s)", self.cfg.id, self.kind, target)

    def read(self) -> Optional[Frame]:
        if not self._cap:
            return None
        ok, bgr = self._cap.read()
        if not ok and self.loop:
            self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
            ok, bgr = self._cap.read()
        if not ok:
            return None
        cv2 = self._cv2
        if self.cfg.width and self.cfg.height and (bgr.shape[1], bgr.shape[0]) != (self.cfg.width, self.cfg.height):
            bgr = cv2.resize(bgr, (self.cfg.width, self.cfg.height))
        return self._frame(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))

    def close(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None
            logger.info("Camera %s disconnected", self.cfg.id)
        super().close()


class UsbSource(_CvSource):
    kind = "usb"

    def _target(self):
        uri = str(self.cfg.uri).strip() or "0"
        return int(uri) if uri.lstrip("-").isdigit() else uri


class FileSource(_CvSource):
    kind = "file"
    loop = True

    def _target(self):
        if not os.path.isfile(self.cfg.uri):
            raise CameraError(f"video file not found: {self.cfg.uri!r}")
        return self.cfg.uri


class NetworkSource(_CvSource):
    kind = "network"

    def _target(self):
        if not self.cfg.uri:
            raise CameraError("network camera needs a stream URL (uri)")
        return self.cfg.uri


# --------------------------------------------------------------------------- still image

class ImageSource(CameraSource):
    kind = "image"

    def __init__(self, cfg: CameraConfig):
        super().__init__(cfg)
        self._image: Optional[Image.Image] = None

    def open(self) -> None:
        if not os.path.isfile(self.cfg.uri):
            raise CameraError(f"image file not found: {self.cfg.uri!r}")
        try:
            self._image = Image.open(self.cfg.uri).convert("RGB")
        except OSError as e:
            raise CameraError(f"cannot read image {self.cfg.uri!r}: {e}") from e
        self._open = True

    def read(self) -> Optional[Frame]:
        return self._frame(self._image.copy()) if self._image is not None else None


# --------------------------------------------------------------------------- factory

def create_source(cfg: CameraConfig, **kwargs) -> CameraSource:
    table = {"simulation": SimulationSource, "usb": UsbSource, "file": FileSource,
             "network": NetworkSource, "image": ImageSource}
    return table[cfg.source](cfg, **kwargs)


def discover_usb_cameras(max_index: int = 4) -> List[dict]:
    """Probe the first USB camera indexes. Returns [] when OpenCV is missing or nothing is plugged in."""
    try:
        import cv2
    except ImportError:
        return []
    found = []
    for i in range(max_index + 1):
        cap = cv2.VideoCapture(i)
        try:
            if cap.isOpened():
                found.append({"index": i, "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                              "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))})
        finally:
            cap.release()
    return found
