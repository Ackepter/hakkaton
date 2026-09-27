"""
Pinhole camera model: where a camera hangs, where it looks and what it sees.

The same model describes a virtual camera in the simulation and a real one on the physical mock-up: put the mast
position, height, heading, tilt and field of view of the real camera into the configuration and the road zones
(lane approaches, crosswalks) are projected into its image exactly as they are for the virtual camera.

World axes (metres): x west -> east, z north -> south, y up. Bearing: 0 = north (-z), 90 = east (+x).
Image: pixels, origin top-left. Horizontal field of view `fov_deg` (the vertical one follows from the aspect ratio).
"""
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

NEAR = 0.3                        # objects closer than this to the lens plane are not drawn


@dataclass
class CameraPose:
    """Mount of a camera. yaw / pitch None = aim at `target` (the middle of the junction) automatically."""
    x: float = 0.0
    z: float = 0.0
    height_m: float = 14.0
    yaw_deg: Optional[float] = None           # compass bearing of the optical axis
    pitch_deg: Optional[float] = None         # downward tilt, 90 = straight down
    fov_deg: float = 70.0
    range_m: float = 90.0                     # farther objects are not detected
    target: Tuple[float, float] = (0.0, 0.0)

    def resolved(self) -> Tuple[float, float]:
        """(yaw, pitch) in degrees with the automatic aim applied."""
        dx, dz = self.target[0] - self.x, self.target[1] - self.z
        dist = math.hypot(dx, dz)
        yaw = self.yaw_deg if self.yaw_deg is not None else (math.degrees(math.atan2(dx, -dz)) if dist > 1e-6 else 0.0)
        pitch = self.pitch_deg if self.pitch_deg is not None else math.degrees(math.atan2(self.height_m, max(dist, 1e-6)))
        return yaw % 360.0, max(1.0, min(90.0, pitch))


class PinholeCamera:
    def __init__(self, pose: CameraPose, width: int, height: int):
        self.pose, self.w, self.h = pose, width, height
        yaw, pitch = pose.resolved()
        self.yaw, self.pitch = yaw, pitch
        ya, pa = math.radians(yaw), math.radians(pitch)
        # forward, right, up in (x, y, z)
        self.f = (math.sin(ya) * math.cos(pa), -math.sin(pa), -math.cos(ya) * math.cos(pa))
        self.r = (math.cos(ya), 0.0, math.sin(ya))
        self.u = (self.r[1] * self.f[2] - self.r[2] * self.f[1],
                  self.r[2] * self.f[0] - self.r[0] * self.f[2],
                  self.r[0] * self.f[1] - self.r[1] * self.f[0])
        self.focal = (width / 2) / math.tan(math.radians(pose.fov_deg) / 2)
        self.pos = (pose.x, pose.height_m, pose.z)

    # ---- projection
    def to_cam(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        vx, vy, vz = x - self.pos[0], y - self.pos[1], z - self.pos[2]
        return (vx * self.r[0] + vy * self.r[1] + vz * self.r[2],
                vx * self.u[0] + vy * self.u[1] + vz * self.u[2],
                vx * self.f[0] + vy * self.f[1] + vz * self.f[2])

    def cam_to_px(self, xc: float, yc: float, zc: float) -> Tuple[float, float]:
        return self.w / 2 + self.focal * xc / zc, self.h / 2 - self.focal * yc / zc

    def project(self, x: float, y: float, z: float) -> Optional[Tuple[float, float, float]]:
        """(px, py, depth) or None when the point is behind the lens."""
        xc, yc, zc = self.to_cam(x, y, z)
        if zc < NEAR:
            return None
        px, py = self.cam_to_px(xc, yc, zc)
        return px, py, zc

    def project_polygon(self, pts3: List[Tuple[float, float, float]]) -> List[Tuple[float, float]]:
        """Pixel polygon of a 3D polygon, cut at the near plane (empty when nothing of it is in front of the camera)."""
        cam = [self.to_cam(*p) for p in pts3]
        out = []
        for i, a in enumerate(cam):
            b = cam[(i + 1) % len(cam)]
            if a[2] >= NEAR:
                out.append(a)
            if (a[2] >= NEAR) != (b[2] >= NEAR):
                t = (NEAR - a[2]) / (b[2] - a[2])
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, NEAR))
        return [self.cam_to_px(*p) for p in out]

    def ground_polygon(self, pts: List[Tuple[float, float]], y: float = 0.0) -> List[Tuple[float, float]]:
        return self.project_polygon([(x, y, z) for x, z in pts])

    def depth(self, x: float, y: float, z: float) -> float:
        return self.to_cam(x, y, z)[2]

    # ---- helpers
    def norm(self, px: float, py: float) -> Tuple[float, float]:
        return px / self.w, py / self.h

    def visible_fraction(self, poly: List[Tuple[float, float]]) -> float:
        """Share of a pixel polygon that lies inside the picture."""
        if len(poly) < 3:
            return 0.0
        full = abs(_area(poly))
        if full < 1e-9:
            return 0.0
        clipped = poly
        for edge in ("l", "r", "t", "b"):
            clipped = _clip(clipped, edge, self.w, self.h)
            if not clipped:
                return 0.0
        return min(1.0, abs(_area(clipped)) / full)

    def footprint(self, max_range: Optional[float] = None) -> List[Tuple[float, float]]:
        """Where the picture corners meet the ground (world x, z), limited to `max_range`: the area the camera sees."""
        out = []
        for u, v in ((0, 0), (self.w, 0), (self.w, self.h), (0, self.h)):
            ray = _norm3((self.r[0] * (u - self.w / 2) / self.focal - self.u[0] * (v - self.h / 2) / self.focal + self.f[0],
                          self.r[1] * (u - self.w / 2) / self.focal - self.u[1] * (v - self.h / 2) / self.focal + self.f[1],
                          self.r[2] * (u - self.w / 2) / self.focal - self.u[2] * (v - self.h / 2) / self.focal + self.f[2]))
            dist = max_range or 1e9
            if ray[1] < -1e-6:
                t = self.pos[1] / -ray[1]
                dist = min(dist, math.hypot(ray[0] * t, ray[2] * t))
            hd = math.hypot(ray[0], ray[2]) or 1e-9
            out.append((self.pos[0] + ray[0] / hd * dist, self.pos[2] + ray[2] / hd * dist))
        return out


def _norm3(v):
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _area(poly) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1])) / 2


def _clip(poly, edge, w, h):
    inside = {"l": lambda p: p[0] >= 0, "r": lambda p: p[0] <= w, "t": lambda p: p[1] >= 0, "b": lambda p: p[1] <= h}[edge]

    def cut(a, b):
        if edge in ("l", "r"):
            x = 0 if edge == "l" else w
            t = (x - a[0]) / ((b[0] - a[0]) or 1e-12)
        else:
            y = 0 if edge == "t" else h
            t = (y - a[1]) / ((b[1] - a[1]) or 1e-12)
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    out = []
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        if inside(a):
            out.append(a)
            if not inside(b):
                out.append(cut(a, b))
        elif inside(b):
            out.append(cut(a, b))
    return out
