"""
UDP LED-matrix traffic light (physical mock-up hardware): same wire protocol as `task_files/traffic_light.py` —
one 64x32 RGB frame per UDP datagram, `struct.pack("<II", 0, len(frame)) + frame`, sent to a per-light (ip, port).

Stdlib only (socket/struct/math), so it costs nothing on a Raspberry Pi 3B+ and needs no extra dependency. A send
is fire-and-forget: a light with no real matrix behind its IP (or no network at all) never blocks or crashes the
simulation tick — the first failure is logged once, further ones stay quiet until a send succeeds again.
"""
import logging
import math
import socket
import struct
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 64, 32
RADIUS = 10
LAMP_CENTERS = {"red": 10, "yellow": 32, "green": 53}
COLORS = {"red": (255, 0, 0), "yellow": (255, 180, 0), "green": (0, 255, 0)}
# our RED/YELLOW/GREEN states map onto which lamps are lit; unknown states show nothing (matrix off, not wrong)
LAMPS_FOR_STATE = {"RED": ("red",), "YELLOW": ("yellow",), "GREEN": ("green",)}


def make_frame(*lit: str) -> bytes:
    """RGB24 frame (WIDTH*HEIGHT*3 bytes) with the named lamps ('red' / 'yellow' / 'green') on, the rest dark."""
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


# one frame per state, built once — sending never re-renders pixels on the hot path
_FRAMES = {state: make_frame(*lamps) for state, lamps in LAMPS_FOR_STATE.items()}
_BLANK = make_frame()


@dataclass
class UdpMatrixLight:
    """A single physical light: one destination address, one socket. `send` is safe to call every tick."""
    light_id: str
    address: Tuple[str, int]
    _sock: Optional[socket.socket] = None
    _last_ok: Optional[bool] = None

    def __post_init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, state: str) -> bool:
        frame = _FRAMES.get(state, _BLANK)
        try:
            self._sock.sendto(struct.pack("<II", 0, len(frame)) + frame, self.address)
        except OSError as e:
            if self._last_ok is not False:
                logger.warning("Traffic light %s: real signal at %s unreachable: %s", self.light_id, self.address, e)
            self._last_ok = False
            return False
        if self._last_ok is False:
            logger.info("Traffic light %s: real signal at %s reachable again", self.light_id, self.address)
        self._last_ok = True
        return True

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None
