"""
UDP LED-matrix traffic light (physical mock-up hardware): same wire protocol as `task_files/traffic_light.py` and
`smart_intersection/hardware/udp_matrix.py` - one 64x32 RGB frame per UDP datagram,
`struct.pack("<II", 0, len(frame)) + frame`, sent to (ip, port).

Kept as its own copy (not imported from `smart_intersection`) because the two services are meant to be deployable
on separate machines (Task 34.10) - the vision/backend side must not depend on the simulation package.
"""
import logging
import math
import socket
import struct
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 64, 32
RADIUS = 10
LAMP_CENTERS = {"red": 10, "yellow": 32, "green": 53}
COLORS = {"red": (255, 0, 0), "yellow": (255, 180, 0), "green": (0, 255, 0)}


def _make_frame(*lit: str) -> bytes:
    frame = bytearray(WIDTH * HEIGHT * 3)
    for name in lit:
        center_x, color = LAMP_CENTERS[name], COLORS[name]
        for y in range(HEIGHT // 2 - RADIUS - 1, HEIGHT // 2 + RADIUS + 2):
            for x in range(max(0, center_x - RADIUS - 1), min(WIDTH, center_x + RADIUS + 2)):
                coverage = min(1.0, max(0.0, RADIUS + 0.5 - math.hypot(x - center_x, y - HEIGHT // 2)))
                if coverage:
                    pos = (y * WIDTH + x) * 3
                    frame[pos:pos + 3] = bytes(round(v * coverage) for v in color)
    return bytes(frame)


_FRAME_GREEN = _make_frame("green")
_FRAME_YELLOW = _make_frame("yellow")
_FRAME_RED = _make_frame("red")
_FRAME_OFF = _make_frame()


class UdpMatrixLight:
    """One physical light at (ip, port). `send_*` are fire-and-forget, safe every tick."""

    def __init__(self, address: Tuple[str, int]):
        self.address = address
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._last_ok: Optional[bool] = None

    def _send(self, frame: bytes) -> bool:
        try:
            self._sock.sendto(struct.pack("<II", 0, len(frame)) + frame, self.address)
        except OSError as e:
            if self._last_ok is not False:
                logger.warning("Real light at %s unreachable: %s", self.address, e)
            self._last_ok = False
            return False
        if self._last_ok is False:
            logger.info("Real light at %s reachable again", self.address)
        self._last_ok = True
        return True

    def send_green(self) -> bool:
        return self._send(_FRAME_GREEN)

    def send_yellow(self) -> bool:
        return self._send(_FRAME_YELLOW)

    def send_red(self) -> bool:
        return self._send(_FRAME_RED)

    def send_off(self) -> bool:
        return self._send(_FRAME_OFF)

    def close(self) -> None:
        self._sock.close()
