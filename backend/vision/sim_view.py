"""
Virtual camera of the Smart Intersection simulation.

A real pinhole camera (see camera_model) looks at the state the simulation service publishes (XML) and at the road
geometry it serves (`/geometry`). It produces what a physical camera would:

    picture      perspective image of the road, markings, lights, vehicles and pedestrians, limited by the field of view
    detections   bounding boxes of the objects that are inside the frame and inside the range, ground contact point included
    zones        lane approaches and crosswalks projected into the image (only the ones the camera really sees)

World coordinates: x = west->east, z = north->south, metres, junction centre = (0, 0).
The simulation is never imported; everything arrives as data (XML + geometry JSON), like it will for a physical mock-up.
"""
import math
from typing import Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .camera_model import CameraPose, PinholeCamera
from .config import Zone
from .types import Detection

# (length, width, height) in metres, mirrors the simulation's vehicle table
VEHICLE_SIZE = {
    "car": (4.5, 2.0, 1.5), "taxi": (4.5, 2.0, 1.5), "truck": (12.0, 2.5, 3.0), "bus": (12.0, 2.5, 3.2),
    "tram": (20.0, 2.6, 3.4), "emergency": (5.5, 2.2, 2.0), "motorcycle": (2.2, 0.8, 1.3), "bicycle": (1.8, 0.6, 1.2),
}
PERSON = (0.6, 0.6, 1.7)
DETECTION_CLASS = {"taxi": "car"}
VEHICLE_COLOR = {
    "car": (59, 130, 246), "taxi": (234, 179, 8), "truck": (249, 115, 22), "bus": (34, 197, 94),
    "tram": (168, 85, 247), "emergency": (239, 68, 68), "motorcycle": (6, 182, 212), "bicycle": (132, 204, 22),
}
LIGHT_COLOR = {"RED": (255, 60, 60), "YELLOW": (255, 220, 0), "GREEN": (40, 255, 90)}
SKY, GRASS, ROAD, SIDE, LINE = (150, 190, 235), (63, 125, 63), (70, 70, 74), (150, 155, 160), (235, 235, 235)
MIN_VISIBLE = 0.35              # a zone / object needs this share inside the picture
MIN_PIXELS = 3                  # smaller boxes are not detected
APPROACH_CAPACITY = 8
CROSSING_CAPACITY = 10
FLIP = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}


def arm_point(arm: str, dist: float, lateral: float) -> Tuple[float, float]:
    """World point at `dist` from the centre along an arm axis; `lateral` is the world coordinate across it."""
    ox, oz = FLIP[arm]
    return (lateral, oz * dist) if arm in ("north", "south") else (ox * dist, lateral)


def default_geometry() -> dict:
    """Geometry of the default crossroads (one lane each way, 32 m centre): used until the simulation has answered."""
    B, sd = 16.0, 21.0
    arms, lanes, crossings, lights = [], [], [], []
    for arm, rs in (("north", -1), ("south", 1), ("east", -1), ("west", 1)):
        arms.append({"arm": arm, "length": 80.0, "lanes_in": 1, "lanes_out": 1, "lateral": [-4.0, 4.0], "lane_type": "mixed",
                     "right": rs})
        lat0, lat1 = 0.0, 4.0 * rs
        quad = [arm_point(arm, sd, lat0), arm_point(arm, sd, lat1), arm_point(arm, sd + 40, lat1), arm_point(arm, sd + 40, lat0)]
        lanes.append({"id": f"{arm}-in", "arm": arm, "index": 0, "inbound": True, "polygon": quad, "moves": ["straight"]})
        c, dp = B + 2.5, 1.5
        lo, hi = -9.0, 9.0
        if arm in ("north", "south"):
            s = FLIP[arm][1]
            poly = [(lo, s * (c - dp)), (hi, s * (c - dp)), (hi, s * (c + dp)), (lo, s * (c + dp))]
        else:
            s = FLIP[arm][0]
            poly = [(s * (c - dp), lo), (s * (c - dp), hi), (s * (c + dp), hi), (s * (c + dp), lo)]
        crossings.append({"arm": arm, "center": c, "depth": 3.0, "axis": "x" if arm in ("north", "south") else "z",
                          "lo": -6.0, "hi": 6.0, "mid": 0.0, "width": 12.0, "id": f"PC-{arm[0].upper()}", "polygon": poly})
        lights.append({"id": f"TL-{arm[0].upper()}", "arm": arm, "pole": arm_point(arm, B + 6.0, 7.0 * rs)})
    return {"junction": "signal", "box_half": B, "lane_width": 4.0, "stop_dist": sd, "arms": arms, "lanes": lanes,
            "crossings": crossings, "lights": lights, "island": None}


def legacy_vehicle_world(direction: str, position_m: float) -> Tuple[float, float]:
    """Position on the straight default lane grid (only for XML of older simulation services that carry no x / z)."""
    t = position_m - 80.0
    return {"north": (-2.0, t), "south": (2.0, -t), "east": (-t, -2.0), "west": (t, 2.0)}[direction]


class SimView:
    def __init__(self, width: int = 640, height: int = 480, pose: Optional[CameraPose] = None,
                 geometry: Optional[dict] = None):
        self.w, self.h = width, height
        self.geometry = geometry or default_geometry()
        self.set_pose(pose)

    def set_pose(self, pose: Optional[CameraPose]) -> None:
        self.pose = pose or CameraPose(x=0.0, z=0.0, height_m=2.8 * self.geometry["box_half"], fov_deg=100.0, range_m=150.0)
        self.cam = PinholeCamera(self.pose, self.w, self.h)

    def set_geometry(self, geometry: dict) -> None:
        self.geometry = geometry

    # -- projection helpers
    def to_norm(self, x: float, z: float, y: float = 0.0) -> Optional[Tuple[float, float]]:
        p = self.cam.project(x, y, z)
        return (p[0] / self.w, p[1] / self.h) if p else None

    def sees(self, x: float, z: float) -> bool:
        p = self.cam.project(x, 0.0, z)
        return bool(p) and 0 <= p[0] <= self.w and 0 <= p[1] <= self.h and self._ground_dist(x, z) <= self.pose.range_m

    def _ground_dist(self, x: float, z: float) -> float:
        return math.hypot(x - self.pose.x, z - self.pose.z)

    # -- zones: lane approaches and crosswalks that are really inside the picture
    def zones(self, arms: Optional[Iterable[str]] = None, crossings: Optional[Iterable[str]] = None,
              skip: Iterable[str] = ()) -> List[Zone]:
        skip = set(skip)
        g = self.geometry
        out: List[Zone] = []
        for lane in g["lanes"]:
            if (arms is not None and lane["arm"] not in arms) or lane["id"] in skip:
                continue
            zone = self._zone(lane["id"], "lane", lane["polygon"], lane["arm"], APPROACH_CAPACITY)
            if zone:
                out.append(zone)
        for c in g["crossings"]:
            if (crossings is not None and c["id"] not in crossings) or c["id"] in skip:
                continue
            zone = self._zone(c["id"], "pedestrian", c["polygon"], c["arm"], CROSSING_CAPACITY)
            if zone:
                out.append(zone)
        return out

    def _zone(self, zid: str, kind: str, world_poly, arm: str, capacity: int) -> Optional[Zone]:
        px = self.cam.ground_polygon([tuple(p) for p in world_poly])
        cx = sum(p[0] for p in world_poly) / len(world_poly)
        cz = sum(p[1] for p in world_poly) / len(world_poly)
        if len(px) < 3 or self._ground_dist(cx, cz) > self.pose.range_m:
            return None
        if self.cam.visible_fraction(px) < MIN_VISIBLE or abs(_poly_area(px)) < 12.0:
            return None
        return Zone(zid, kind, [self.cam.norm(*p) for p in px], arm, capacity=capacity)

    def default_zones(self, arms=None, crossings=None, skip=()) -> List[Zone]:
        return self.zones(arms, crossings, skip)

    # -- detections: what a detector would report for this picture
    def _box(self, x: float, z: float, heading: float, length: float, width: float, height: float):
        c, s = math.cos(heading), math.sin(heading)
        pts = []
        for dx, dz in ((length / 2, width / 2), (length / 2, -width / 2), (-length / 2, -width / 2), (-length / 2, width / 2)):
            pts.append((x + dx * c - dz * s, z + dx * s + dz * c))
        return pts

    def _project_box(self, base: List[Tuple[float, float]], height: float):
        """Pixel corners of a box standing on `base` (bottom four then top four), or None when a corner is behind the lens."""
        out = []
        for y in (0.0, height):
            for x, z in base:
                p = self.cam.project(x, y, z)
                if p is None:
                    return None
                out.append(p)
        return out

    def detections(self, data) -> List[Detection]:
        found = []
        for v in data.vehicles:
            length, width, height = VEHICLE_SIZE.get(v.vehicle_type, VEHICLE_SIZE["car"])
            x, z, heading = self._vehicle_pose(v)
            found.append((v.id, DETECTION_CLASS.get(v.vehicle_type, v.vehicle_type), x, z, heading, length, width, height,
                          v.lane_id, 0.97))
        for p in data.pedestrians:
            if p.state == "finished":
                continue
            x, z = self._pedestrian_xz(p)
            found.append((p.id, "person", x, z, 0.0, PERSON[0], PERSON[1], PERSON[2], p.crossing_id, 0.95))
        boxes = []
        for sid, cls, x, z, heading, length, width, height, lane, conf in found:
            if self._ground_dist(x, z) > self.pose.range_m:
                continue                                              # too far for this camera
            corners = self._project_box(self._box(x, z, heading, length, width, height), height)
            if corners is None:
                continue
            x0, x1 = min(c[0] for c in corners), max(c[0] for c in corners)
            y0, y1 = min(c[1] for c in corners), max(c[1] for c in corners)
            area = max((x1 - x0) * (y1 - y0), 1e-9)
            cx0, cx1, cy0, cy1 = max(x0, 0), min(x1, self.w), max(y0, 0), min(y1, self.h)
            if cx1 <= cx0 or cy1 <= cy0:
                continue                                              # outside the frame
            visible = (cx1 - cx0) * (cy1 - cy0) / area
            if visible < MIN_VISIBLE or (cx1 - cx0) < MIN_PIXELS or (cy1 - cy0) < MIN_PIXELS:
                continue
            depth = self.cam.depth(x, height / 2, z)
            boxes.append((depth, sid, cls, x, z, lane, conf * (0.6 + 0.4 * visible), (cx0, cy0, cx1, cy1)))
        boxes.sort()
        out: List[Detection] = []
        nearer: List[Tuple[float, float, float, float]] = []
        for depth, sid, cls, x, z, lane, conf, (a, b, c, d) in boxes:
            covered = sum(max(0.0, min(c, nc) - max(a, na)) * max(0.0, min(d, nd) - max(b, nb)) for na, nb, nc, nd in nearer)
            if covered / max((c - a) * (d - b), 1e-9) > 0.85:
                continue                                              # hidden behind nearer objects
            nearer.append((a, b, c, d))
            foot = self.to_norm(x, z)
            out.append(Detection(cls=cls, confidence=round(conf, 3), x=(a + c) / 2 / self.w, y=(b + d) / 2 / self.h,
                                 w=(c - a) / self.w, h=(d - b) / self.h, source_id=sid, lane=lane,
                                 world=(round(x, 2), round(z, 2)), foot=foot))
        return out

    def _vehicle_pose(self, v) -> Tuple[float, float, float]:
        if getattr(v, "x", None) is not None:
            return v.x, v.z, v.heading
        x, z = legacy_vehicle_world(v.direction, v.position_m)
        return x, z, (math.pi / 2 if v.direction == "south" else -math.pi / 2 if v.direction == "north" else
                      math.pi if v.direction == "east" else 0.0)

    def _pedestrian_xz(self, p) -> Tuple[float, float]:
        if getattr(p, "x", None) is not None:
            return p.x, p.z
        cg = next((c for c in self.geometry["crossings"] if c["id"] == p.crossing_id), None)
        if cg is None:
            return 0.0, 0.0
        along = cg["mid"] + p.direction * (p.position_m - cg["width"] / 2)
        s = FLIP[cg["arm"]]
        dist = cg["center"] + p.offset
        return (along, s[1] * dist) if cg["axis"] == "x" else (s[0] * dist, along)

    # -- picture
    def render(self, data, label: str = "CAM-01", arms=None) -> Image.Image:
        """Perspective picture of the road and everything on it. (`arms` is kept for old callers and ignored.)"""
        img = Image.new("RGB", (self.w, self.h), SKY)
        d = ImageDraw.Draw(img)
        self._draw_road(d)
        for tl in data.lights:
            self._draw_light(d, tl)
        objects = []
        for v in data.vehicles:
            length, width, height = VEHICLE_SIZE.get(v.vehicle_type, VEHICLE_SIZE["car"])
            x, z, heading = self._vehicle_pose(v)
            objects.append((self.cam.depth(x, 0, z), "v", x, z, heading, length, width, height,
                            VEHICLE_COLOR.get(v.vehicle_type, (150, 150, 150))))
        for p in data.pedestrians:
            if p.state == "finished":
                continue
            x, z = self._pedestrian_xz(p)
            objects.append((self.cam.depth(x, 0, z), "p", x, z, 0.0, PERSON[0], PERSON[1], PERSON[2], (250, 204, 21)))
        for depth, kind, x, z, heading, length, width, height, color in sorted(objects, reverse=True):
            if depth < 0.5:
                continue
            self._draw_box(d, self._box(x, z, heading, length, width, height), height, color)
        pose = f"h={self.pose.height_m:.0f}m yaw={self.cam.yaw:.0f} tilt={self.cam.pitch:.0f} fov={self.pose.fov_deg:.0f}"
        d.rectangle([0, 0, min(self.w, 330), 14], fill=(0, 0, 0))
        d.text((4, 2), f"{label}  SIM  t={data.simulation.sim_time:7.1f}s  {pose}", fill=(255, 255, 255),
               font=ImageFont.load_default())
        return img

    def _poly(self, d: ImageDraw.ImageDraw, pts, fill, y: float = 0.0, outline=None) -> None:
        px = self.cam.ground_polygon(pts, y)
        if len(px) >= 3:
            d.polygon(px, fill=fill, outline=outline)

    def _draw_road(self, d: ImageDraw.ImageDraw) -> None:
        g = self.geometry
        B = g["box_half"]
        far = 600.0
        self._poly(d, [(-far, -far), (far, -far), (far, far), (-far, far)], GRASS)
        circle = lambda r: [(r * math.cos(t * math.pi / 24), r * math.sin(t * math.pi / 24)) for t in range(48)]
        if g.get("island"):
            self._poly(d, circle(B + 3), SIDE)                                                                    # round plaza
        else:
            self._poly(d, [(-B - 4, -B - 4), (B + 4, -B - 4), (B + 4, B + 4), (-B - 4, B + 4)], SIDE)         # corner pavement
        for a in g["arms"]:
            arm, L = a["arm"], a["length"]
            lo, hi = a["lateral"]
            self._poly(d, [arm_point(arm, B, lo - 4), arm_point(arm, L, lo - 4), arm_point(arm, L, hi + 4),
                           arm_point(arm, B, hi + 4)], SIDE)                                                    # kerbs
        self._poly(d, circle(B) if g.get("island") else [(-B, -B), (B, -B), (B, B), (-B, B)], ROAD)
        edge = B - 1.5 if g.get("island") else B                                                              # arms overlap the plaza
        for a in g["arms"]:
            arm, L = a["arm"], a["length"]
            lo, hi = a["lateral"]
            rs = a.get("right", -1)
            self._poly(d, [arm_point(arm, edge, lo), arm_point(arm, L, lo), arm_point(arm, L, hi), arm_point(arm, edge, hi)], ROAD)
            if a.get("lane_type") == "bus":
                lat = [0.0, rs * 4.0 * a["lanes_in"]]
                self._poly(d, [arm_point(arm, B, lat[0]), arm_point(arm, L, lat[0]), arm_point(arm, L, lat[1]),
                               arm_point(arm, B, lat[1])], (150, 90, 30))
            # centre line and lane dividers (dashed)
            for lateral, colour in [(0.0, (240, 200, 40))] + \
                    [(rs * 4.0 * i, LINE) for i in range(1, a["lanes_in"])] + \
                    [(-rs * 4.0 * j, LINE) for j in range(1, a["lanes_out"])]:
                step = 6.0 if colour == LINE else 60.0
                dist = B + 4.0
                while dist < L - 3.0:
                    seg = min(3.0 if colour == LINE else 60.0, L - 3.0 - dist)
                    self._poly(d, [arm_point(arm, dist, lateral - 0.1), arm_point(arm, dist + seg, lateral - 0.1),
                                   arm_point(arm, dist + seg, lateral + 0.1), arm_point(arm, dist, lateral + 0.1)], colour)
                    dist += step
            sd = g["stop_dist"]
            self._poly(d, [arm_point(arm, sd - 0.25, 0.0), arm_point(arm, sd + 0.25, 0.0),
                           arm_point(arm, sd + 0.25, rs * 4.0 * a["lanes_in"]), arm_point(arm, sd - 0.25, rs * 4.0 * a["lanes_in"])], LINE)
        for c in g["crossings"]:
            lo, hi = c["lo"], c["hi"]
            dp = c["depth"] / 2
            x = lo + 0.6
            while x < hi - 0.3:
                pts = [(x, c["center"] - dp), (x + 0.6, c["center"] - dp), (x + 0.6, c["center"] + dp), (x, c["center"] + dp)]
                s = FLIP[c["arm"]]
                pts = [(u, s[1] * w) if c["axis"] == "x" else (s[0] * w, u) for u, w in pts]
                self._poly(d, pts, (222, 222, 228))
                x += 1.2
        if g.get("island"):
            r = g["island"]["radius"]
            ring = [(r * math.cos(t * math.pi / 16), r * math.sin(t * math.pi / 16)) for t in range(32)]
            self._poly(d, [(1.06 * x, 1.06 * z) for x, z in ring], (200, 200, 205), 0.05)
            self._poly(d, ring, (86, 140, 80), 0.12)

    def _draw_light(self, d: ImageDraw.ImageDraw, tl) -> None:
        pole = next((l["pole"] for l in self.geometry["lights"] if l["id"] == tl.id), None)
        if pole is None:
            return
        a, b = self.cam.project(pole[0], 0.0, pole[1]), self.cam.project(pole[0], 5.8, pole[1])
        if a and b:
            d.line([a[:2], b[:2]], fill=(90, 90, 90), width=max(1, int(self.cam.focal * 0.2 / max(a[2], 1))))
            r = max(2.0, self.cam.focal * 0.45 / b[2])
            d.ellipse([b[0] - r, b[1] - r, b[0] + r, b[1] + r], fill=LIGHT_COLOR.get(tl.state, (120, 120, 120)), outline=(20, 20, 20))

    def _draw_box(self, d: ImageDraw.ImageDraw, base, height: float, color) -> None:
        bottom = [self.cam.project(x, 0.0, z) for x, z in base]
        top = [self.cam.project(x, height, z) for x, z in base]
        if any(p is None for p in bottom + top):
            return
        b2, t2 = [p[:2] for p in bottom], [p[:2] for p in top]
        faces = []
        for i in range(4):
            j = (i + 1) % 4
            depth = sum(bottom[k][2] + top[k][2] for k in (i, j)) / 4
            faces.append((depth, [b2[i], b2[j], t2[j], t2[i]], 0.62 + 0.12 * (i % 2)))
        faces.sort(key=lambda f: -f[0])
        for _, poly, shade in faces:
            d.polygon(poly, fill=tuple(int(c * shade) for c in color), outline=(15, 15, 15))
        d.polygon(t2, fill=color, outline=(15, 15, 15))


def _poly_area(poly) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1])) / 2
