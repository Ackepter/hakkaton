"""
Virtual camera model for the Smart Intersection simulation.

Projects the state published by the simulation service (XML -> IntersectionData) into a top-down camera image
and into "virtual detections" (Task 56): exactly what a YOLO model would report if it saw the scene.
World coordinates: x = west->east, z = north->south, metres, intersection centre = (0, 0).

The geometry constants intentionally mirror smart_intersection/engine/world.py; tests/test_vision_geometry.py
fails if they drift apart (the two services must stay independent, so nothing is imported from the simulation).
"""
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont

from .config import Zone
from .types import Detection

ARM_LENGTH = 80.0
HALF = 16.0
LANE_WIDTH = 4.0
STOP_DIST = 21.0
CROSS_CENTER = 18.5
CROSS_DEPTH = 3.0
CROSS_WIDTH = 12.0
APPROACH_DEPTH = 40.0
VIEW_RADIUS_M = 64.0
LANE_X = 2.0

ARMS = ("north", "south", "east", "west")

# (length, width) in metres, mirrors the simulation's vehicle table
VEHICLE_SIZE = {
    "car": (4.5, 2.0), "taxi": (4.5, 2.0), "truck": (12.0, 2.5), "bus": (12.0, 2.5), "tram": (20.0, 2.6),
    "emergency": (5.5, 2.2), "motorcycle": (2.2, 0.8), "bicycle": (1.8, 0.6),
}
DETECTION_CLASS = {"taxi": "car"}
VEHICLE_COLOR = {
    "car": (59, 130, 246), "taxi": (234, 179, 8), "truck": (249, 115, 22), "bus": (34, 197, 94),
    "tram": (168, 85, 247), "emergency": (239, 68, 68), "motorcycle": (6, 182, 212), "bicycle": (132, 204, 22),
}
LIGHT_COLOR = {"RED": (255, 60, 60), "YELLOW": (255, 220, 0), "GREEN": (40, 255, 90)}
LIGHT_POLE = {"north": (-7, -22), "south": (7, 22), "east": (22, -7), "west": (-22, 7)}


def vehicle_world(direction: str, position_m: float) -> Tuple[float, float]:
    t = position_m - ARM_LENGTH
    return {"north": (-LANE_X, t), "south": (LANE_X, -t), "east": (-t, -LANE_X), "west": (t, LANE_X)}[direction]


def pedestrian_world(crossing_id: str, position_m: float, direction: int = 1, offset: float = 0.0) -> Tuple[float, float]:
    along = direction * (position_m - CROSS_WIDTH / 2)
    return {
        "PC-N": (along, -CROSS_CENTER + offset), "PC-S": (along, CROSS_CENTER + offset),
        "PC-E": (CROSS_CENTER + offset, along), "PC-W": (-CROSS_CENTER + offset, along),
    }.get(crossing_id, (0.0, 0.0))


class SimView:
    def __init__(self, width: int = 640, height: int = 640, radius_m: float = VIEW_RADIUS_M):
        self.w, self.h = width, height
        self.scale = min(width, height) / (2 * radius_m)          # pixels per metre

    # -- projection
    def to_px(self, x: float, z: float) -> Tuple[float, float]:
        return self.w / 2 + x * self.scale, self.h / 2 + z * self.scale

    def to_norm(self, x: float, z: float) -> Tuple[float, float]:
        px, py = self.to_px(x, z)
        return px / self.w, py / self.h

    def rect_px(self, x0, z0, x1, z1):
        (a, b), (c, d) = self.to_px(x0, z0), self.to_px(x1, z1)
        return [min(a, c), min(b, d), max(a, c), max(b, d)]

    # -- zones: approach lanes before the stop line + crosswalk bands including the waiting area
    def default_zones(self) -> List[Zone]:
        near, far = STOP_DIST, STOP_DIST + APPROACH_DEPTH
        boxes = {
            "north": (-LANE_WIDTH, -far, 0, -near), "south": (0, near, LANE_WIDTH, far),
            "east": (near, -LANE_WIDTH, far, 0), "west": (-far, 0, -near, LANE_WIDTH),
        }
        zones = [Zone(f"{arm}-in", "lane", self._poly(*box), arm, capacity=8) for arm, box in boxes.items()]
        c, d, w = CROSS_CENTER, CROSS_DEPTH / 2, CROSS_WIDTH / 2 + 3
        bands = {"PC-N": ("north", -w, -c - d, w, -c + d), "PC-S": ("south", -w, c - d, w, c + d),
                 "PC-E": ("east", c - d, -w, c + d, w), "PC-W": ("west", -c - d, -w, -c + d, w)}
        for zid, (arm, x0, z0, x1, z1) in bands.items():
            zones.append(Zone(zid, "pedestrian", self._poly(x0, z0, x1, z1), arm, capacity=10))
        return zones

    def _poly(self, x0, z0, x1, z1):
        return [self.to_norm(x0, z0), self.to_norm(x1, z0), self.to_norm(x1, z1), self.to_norm(x0, z1)]

    # -- virtual detections
    def detections(self, data) -> List[Detection]:
        out: List[Detection] = []
        half_w, half_h = self.w / 2 / self.scale, self.h / 2 / self.scale
        for v in data.vehicles:
            length, width = VEHICLE_SIZE.get(v.vehicle_type, VEHICLE_SIZE["car"])
            x, z = vehicle_world(v.direction, v.position_m)
            if abs(x) > half_w or abs(z) > half_h:
                continue                                              # outside the camera's field of view
            bw, bh = (width, length) if v.direction in ("north", "south") else (length, width)
            cx, cy = self.to_norm(x, z)
            out.append(Detection(cls=DETECTION_CLASS.get(v.vehicle_type, v.vehicle_type), confidence=0.97,
                                 x=cx, y=cy, w=max(bw * self.scale, 8) / self.w, h=max(bh * self.scale, 8) / self.h,
                                 source_id=v.id, lane=v.lane_id, world=(round(x, 2), round(z, 2))))
        for p in data.pedestrians:
            if p.state == "finished":
                continue
            x, z = pedestrian_world(p.crossing_id, p.position_m, p.direction, p.offset)
            cx, cy = self.to_norm(x, z)
            size = max(1.0 * self.scale, 8)
            out.append(Detection(cls="person", confidence=0.95, x=cx, y=cy, w=size / self.w, h=size / self.h,
                                 source_id=p.id, lane=p.crossing_id, world=(round(x, 2), round(z, 2))))
        return out

    # -- picture
    def render(self, data, label: str = "CAM-01") -> Image.Image:
        img = Image.new("RGB", (self.w, self.h), (63, 125, 63))
        d = ImageDraw.Draw(img)
        R = max(self.w, self.h) / self.scale
        road, side, line = (70, 70, 74), (150, 155, 160), (235, 235, 235)
        for x0, z0, x1, z1 in ((-8, -R, 8, R), (-R, -8, R, 8)):        # asphalt arms
            d.rectangle(self.rect_px(x0, z0, x1, z1), fill=road)
        for sx in (-1, 1):                                              # sidewalks
            d.rectangle(self.rect_px(sx * 4, -R, sx * 8, R), fill=side)
            d.rectangle(self.rect_px(-R, sx * 4, R, sx * 8), fill=side)
        d.rectangle(self.rect_px(-HALF, -HALF, HALF, HALF), fill=road)  # box on top of the sidewalks
        for span in range(int(HALF + 4), int(R), 6):                    # centre dashes
            for s in (-1, 1):
                d.rectangle(self.rect_px(-0.1, s * span, 0.1, s * (span + 3)), fill=line)
                d.rectangle(self.rect_px(s * span, -0.1, s * (span + 3), 0.1), fill=line)
        c, dp = CROSS_CENTER, CROSS_DEPTH / 2
        for i in range(10):                                             # zebra stripes
            o = -CROSS_WIDTH / 2 + 0.6 + i * (CROSS_WIDTH / 10)
            for s in (-1, 1):
                d.rectangle(self.rect_px(o - 0.3, s * c - dp, o + 0.3, s * c + dp), fill=(220, 220, 225))
                d.rectangle(self.rect_px(s * c - dp, o - 0.3, s * c + dp, o + 0.3), fill=(220, 220, 225))
        sl = STOP_DIST                                                  # stop lines on the inbound lanes
        d.rectangle(self.rect_px(-LANE_WIDTH, -sl - 0.2, 0, -sl + 0.2), fill=line)
        d.rectangle(self.rect_px(0, sl - 0.2, LANE_WIDTH, sl + 0.2), fill=line)
        d.rectangle(self.rect_px(sl - 0.2, -LANE_WIDTH, sl + 0.2, 0), fill=line)
        d.rectangle(self.rect_px(-sl - 0.2, 0, -sl + 0.2, LANE_WIDTH), fill=line)

        for tl in data.lights:
            px, py = self.to_px(*LIGHT_POLE[tl.direction])
            r = max(3, self.scale * 0.9)
            d.ellipse([px - r, py - r, px + r, py + r], fill=LIGHT_COLOR.get(tl.state, (120, 120, 120)),
                      outline=(20, 20, 20))

        for v in data.vehicles:
            length, width = VEHICLE_SIZE.get(v.vehicle_type, VEHICLE_SIZE["car"])
            x, z = vehicle_world(v.direction, v.position_m)
            bw, bh = (width, length) if v.direction in ("north", "south") else (length, width)
            d.rectangle(self.rect_px(x - bw / 2, z - bh / 2, x + bw / 2, z + bh / 2),
                        fill=VEHICLE_COLOR.get(v.vehicle_type, (150, 150, 150)), outline=(15, 15, 15))
        for p in data.pedestrians:
            if p.state == "finished":
                continue
            px, py = self.to_px(*pedestrian_world(p.crossing_id, p.position_m, p.direction, p.offset))
            r = max(2.5, self.scale * 0.35)
            d.ellipse([px - r, py - r, px + r, py + r], fill=(250, 204, 21), outline=(20, 20, 20))

        d.rectangle([0, 0, 200, 14], fill=(0, 0, 0))
        d.text((4, 2), f"{label}  SIM  t={data.simulation.sim_time:7.1f}s", fill=(255, 255, 255),
               font=ImageFont.load_default())
        return img
