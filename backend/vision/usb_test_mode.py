"""
USB camera test mode: while active, a live USB camera drives a real traffic light directly, running a fixed
pedestrian-crossing sequence (independent of TrafficController/AUTO/FAILSAFE - it never touches the simulation or
the normal signal phase machine):

    GREEN (idle, no pedestrians)
      -> pedestrian detected -> BLINK green x3 at 1 Hz -> YELLOW 3s -> RED
      -> RED holds while pedestrians are present, plus a further 3s clearance once they're gone -> YELLOW 3s -> GREEN
"""
import asyncio
import logging
import time
from typing import Callable, Optional

from ..hardware.udp_matrix_light import UdpMatrixLight

logger = logging.getLogger(__name__)

POLL_S = 0.3
BLINK_COUNT = 3
BLINK_ON_S = 0.5
BLINK_OFF_S = 0.5
YELLOW_S = 3.0
RED_CLEAR_S = 3.0   # keep red this long after pedestrians are gone before turning yellow


class UsbTestMode:
    def __init__(self, get_pipeline: Callable[[str], Optional[object]]):
        self._get_pipeline = get_pipeline
        self._light: Optional[UdpMatrixLight] = None
        self._task: Optional[asyncio.Task] = None
        self.camera_id: Optional[str] = None
        self.ip: Optional[str] = None
        self.port: Optional[int] = None
        self.phase = "GREEN"          # GREEN | BLINK | YELLOW | RED
        self.person_detected = False

    @property
    def active(self) -> bool:
        return self._task is not None

    async def start(self, camera_id: str, ip: str, port: int) -> None:
        await self.stop()
        self.camera_id, self.ip, self.port = camera_id, ip, port
        self.phase, self.person_detected = "GREEN", False
        self._light = UdpMatrixLight((ip, port))
        self._task = asyncio.create_task(self._run(), name="usb-test-mode")
        logger.info("USB test mode started: camera=%s -> light %s:%s", camera_id, ip, port)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._light:
            self._light.close()
            self._light = None
        if self.camera_id:
            logger.info("USB test mode stopped (was: camera=%s)", self.camera_id)
        self.camera_id, self.ip, self.port = None, None, None
        self.phase = "GREEN"

    def status(self) -> dict:
        return {"active": self.active, "camera_id": self.camera_id, "ip": self.ip, "port": self.port,
                "phase": self.phase, "person_detected": self.person_detected}

    def _has_person(self) -> bool:
        pipeline = self._get_pipeline(self.camera_id)
        detections = getattr(pipeline, "detections", []) if pipeline else []
        self.person_detected = any(d.cls == "person" for d in detections)
        return self.person_detected

    async def _run(self) -> None:
        while True:
            self.phase = "GREEN"
            await self._wait_for_person()
            await self._blink_and_yellow()
            await self._red_until_clear()

    async def _wait_for_person(self) -> None:
        while True:
            self._light.send_green()
            if self._has_person():
                return
            await asyncio.sleep(POLL_S)

    async def _blink_and_yellow(self) -> None:
        self.phase = "BLINK"
        for _ in range(BLINK_COUNT):
            self._light.send_green()
            await asyncio.sleep(BLINK_ON_S)
            self._light.send_off()
            await asyncio.sleep(BLINK_OFF_S)
        self.phase = "YELLOW"
        self._light.send_yellow()
        await asyncio.sleep(YELLOW_S)

    async def _red_until_clear(self) -> None:
        self.phase = "RED"
        clear_since: Optional[float] = None
        while True:
            self._light.send_red()
            now = time.monotonic()
            if self._has_person():
                clear_since = None
            elif clear_since is None:
                clear_since = now
            elif now - clear_since >= RED_CLEAR_S:
                break
            await asyncio.sleep(POLL_S)
        self.phase = "YELLOW"
        self._light.send_yellow()
        await asyncio.sleep(YELLOW_S)
