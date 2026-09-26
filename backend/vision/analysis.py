"""
Traffic analysis: detections -> traffic situation. It never learns whether detections came from a real camera,
a video file, YOLO or the 3D simulation (Task 55) - the input is only a list of `Detection`.

    Detection[] -> CentroidTracker (stable ids, stationary / moving, heading)
                -> zone assignment (lane zones for vehicles, crosswalk zones for pedestrians)
                -> TrafficSnapshot (counts, queues, waiting, density, flow, pedestrian priority, emergency)
"""
import math
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

from .config import Zone
from .types import Detection, PEDESTRIAN_CLASSES, VEHICLE_CLASSES

FLOW_WINDOW_S = 60.0


# ----------------------------------------------------------------------------- tracking

@dataclass
class _Track:
    id: int
    cls: str
    group: str
    cx: float
    cy: float
    first_seen: float
    last_seen: float
    history: Deque[Tuple[float, float, float]] = field(default_factory=lambda: deque(maxlen=90))
    still_since: Optional[float] = None


def _group(cls: str) -> str:
    return "person" if cls in PEDESTRIAN_CLASSES else "vehicle"


class CentroidTracker:
    """Greedy nearest-centroid tracker: cheap enough for a Raspberry Pi, good enough for slow intersection traffic."""

    def __init__(self, max_dist: float = 0.08, max_age_s: float = 1.5, stationary_eps: float = 0.006,
                 still_window_s: float = 1.0):
        self.max_dist, self.max_age_s = max_dist, max_age_s
        self.stationary_eps, self.still_window_s = stationary_eps, still_window_s
        self._tracks: Dict[int, _Track] = {}
        self._by_source: Dict[str, int] = {}          # source-provided identity -> track id
        self._next_id = 1

    def reset(self) -> None:
        self._tracks.clear()
        self._by_source.clear()

    def update(self, dets: List[Detection], now: float) -> None:
        used_t, used_d = set(), set()
        for i, d in enumerate(dets):                  # identities given by the source need no guessing
            tid = self._by_source.get(d.source_id) if d.source_id else None
            if tid in self._tracks and tid not in used_t:
                used_t.add(tid)
                used_d.add(i)
                self._touch(self._tracks[tid], d, now)
        pairs = []
        for t in self._tracks.values():
            if t.id in used_t:
                continue
            for i, d in enumerate(dets):
                if i not in used_d and not d.source_id and _group(d.cls) == t.group:
                    dist = math.hypot(d.x - t.cx, d.y - t.cy)
                    if dist <= self.max_dist:
                        pairs.append((dist, t.id, i))
        pairs.sort()
        for _, tid, i in pairs:
            if tid in used_t or i in used_d:
                continue
            used_t.add(tid)
            used_d.add(i)
            self._touch(self._tracks[tid], dets[i], now)
        for i, d in enumerate(dets):
            if i not in used_d:
                t = _Track(self._next_id, d.cls, _group(d.cls), d.x, d.y, now, now)
                self._next_id += 1
                self._tracks[t.id] = t
                if d.source_id:
                    self._by_source[d.source_id] = t.id
                self._touch(t, d, now)
        for tid in [tid for tid, t in self._tracks.items() if now - t.last_seen > self.max_age_s]:
            del self._tracks[tid]
        self._by_source = {sid: tid for sid, tid in self._by_source.items() if tid in self._tracks}

    def _touch(self, t: _Track, d: Detection, now: float) -> None:
        t.cx, t.cy, t.last_seen, t.cls = d.x, d.y, now, d.cls
        t.history.append((now, d.x, d.y))
        d.track_id = t.id
        window = [(ts, x, y) for ts, x, y in t.history if ts >= now - self.still_window_s]
        spans = window and (now - window[0][0]) >= self.still_window_s * 0.8
        if spans and max(math.hypot(x - d.x, y - d.y) for _, x, y in window) < self.stationary_eps:
            t.still_since = t.still_since if t.still_since is not None else window[0][0]
        else:
            t.still_since = None

    def track(self, track_id: Optional[int]) -> Optional[_Track]:
        return self._tracks.get(track_id) if track_id is not None else None

    def heading(self, t: _Track, now: float) -> Optional[str]:
        """north/south/east/west in image space (up = north), None while standing still."""
        old = [(ts, x, y) for ts, x, y in t.history if ts <= now - 0.5]
        if not old or t.still_since is not None:
            return None
        _, x0, y0 = old[-1]
        dx, dy = t.cx - x0, t.cy - y0
        if math.hypot(dx, dy) < self.stationary_eps * 2:
            return None
        return ("east" if dx > 0 else "west") if abs(dx) >= abs(dy) else ("south" if dy > 0 else "north")


# ----------------------------------------------------------------------------- snapshot

@dataclass
class ZoneStats:
    id: str
    kind: str
    direction: Optional[str]
    count: int = 0
    by_class: Dict[str, int] = field(default_factory=dict)
    waiting: int = 0                 # stationary objects
    density: float = 0.0             # 0..1, count / capacity
    flow_per_min: float = 0.0        # objects that entered the zone during the last minute
    avg_wait_s: float = 0.0
    max_wait_s: float = 0.0


@dataclass
class TrafficSnapshot:
    ts: float = 0.0
    cameras: List[str] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    vehicles: int = 0
    trucks: int = 0
    pedestrians: int = 0
    waiting_vehicles: int = 0
    pedestrians_waiting: int = 0
    zones: Dict[str, ZoneStats] = field(default_factory=dict)
    direction_counts: Dict[str, int] = field(default_factory=dict)      # arm -> vehicles in its approach zone
    flow_per_min: float = 0.0
    vehicles_per_hour: float = 0.0
    density: float = 0.0
    avg_wait_s: float = 0.0
    max_wait_s: float = 0.0
    ped_avg_wait_s: float = 0.0
    ped_priority: bool = False
    ped_priority_zones: Dict[str, bool] = field(default_factory=dict)   # crosswalk zone -> crowd >= threshold
    emergency: Dict[str, bool] = field(default_factory=dict)            # arm -> emergency vehicle approaching

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------------- analyzer

class TrafficAnalyzer:
    def __init__(self, zones: Iterable[Zone], ped_priority_threshold: int = 5, tracker: Optional[CentroidTracker] = None):
        self.zones = list(zones)
        self.ped_priority_threshold = ped_priority_threshold
        self.tracker = tracker or CentroidTracker()
        self._entries: Dict[str, Dict[int, float]] = {z.id: {} for z in self.zones}
        self._started: Optional[float] = None
        self._last_now: Optional[float] = None

    def reset(self) -> None:
        self.tracker.reset()
        self._entries = {z.id: {} for z in self.zones}
        self._started = None

    def _zone_for(self, d: Detection) -> Optional[Zone]:
        kind = "pedestrian" if _group(d.cls) == "person" else "lane"
        return next((z for z in self.zones if z.kind == kind and z.contains(d.x, d.y)), None)

    def analyze(self, camera_id: str, dets: List[Detection], now: float) -> TrafficSnapshot:
        if self._last_now is not None and now < self._last_now - 1.0:
            self.reset()                              # the clock went backwards (simulation reset): start over
        self._last_now = now
        if self._started is None:
            self._started = now
        self.tracker.update(dets, now)
        stats = {z.id: ZoneStats(z.id, z.kind, z.direction) for z in self.zones}
        waits: Dict[str, List[float]] = {z.id: [] for z in self.zones}
        snap = TrafficSnapshot(ts=now, cameras=[camera_id], zones=stats)

        for d in dets:
            snap.counts[d.cls] = snap.counts.get(d.cls, 0) + 1
            zone = self._zone_for(d)
            d.zone = zone.id if zone else None
            if not zone:
                continue
            s = stats[zone.id]
            s.count += 1
            s.by_class[d.cls] = s.by_class.get(d.cls, 0) + 1
            entries = self._entries[zone.id]
            if d.track_id is not None:
                entries.setdefault(d.track_id, now)
            t = self.tracker.track(d.track_id)
            if t is not None and t.still_since is not None:
                s.waiting += 1
                waits[zone.id].append(now - t.still_since)
            if d.cls == "emergency" and zone.direction:
                snap.emergency[zone.direction] = True

        window = min(FLOW_WINDOW_S, max(now - self._started, 10.0))
        for z in self.zones:
            s = stats[z.id]
            entries = self._entries[z.id]
            for tid in [tid for tid, ts in entries.items() if now - ts > FLOW_WINDOW_S]:
                del entries[tid]
            s.flow_per_min = round(len(entries) * 60.0 / window, 2)
            s.density = round(min(1.0, s.count / max(z.capacity, 1)), 2)
            if waits[z.id]:
                s.avg_wait_s = round(sum(waits[z.id]) / len(waits[z.id]), 2)
                s.max_wait_s = round(max(waits[z.id]), 2)

        lane = [(z, stats[z.id]) for z in self.zones if z.kind == "lane"]
        ped = [(z, stats[z.id]) for z in self.zones if z.kind == "pedestrian"]
        snap.vehicles = sum(n for c, n in snap.counts.items() if c in VEHICLE_CLASSES)
        snap.trucks = snap.counts.get("truck", 0)
        snap.pedestrians = sum(n for c, n in snap.counts.items() if c in PEDESTRIAN_CLASSES)
        snap.waiting_vehicles = sum(s.waiting for _, s in lane)
        snap.pedestrians_waiting = sum(s.waiting for _, s in ped)
        for z, s in lane:
            if z.direction:
                snap.direction_counts[z.direction] = snap.direction_counts.get(z.direction, 0) + s.count
        snap.flow_per_min = round(sum(s.flow_per_min for _, s in lane), 2)
        snap.vehicles_per_hour = round(snap.flow_per_min * 60, 1)
        snap.density = round(sum(s.density for _, s in lane) / len(lane), 2) if lane else 0.0
        lane_waits = [w for z, _ in lane for w in waits[z.id]]
        ped_waits = [w for z, _ in ped for w in waits[z.id]]
        snap.avg_wait_s = round(sum(lane_waits) / len(lane_waits), 2) if lane_waits else 0.0
        snap.max_wait_s = round(max(lane_waits), 2) if lane_waits else 0.0
        snap.ped_avg_wait_s = round(sum(ped_waits) / len(ped_waits), 2) if ped_waits else 0.0
        snap.ped_priority_zones = {z.id: s.waiting >= self.ped_priority_threshold for z, s in ped}
        snap.ped_priority = any(snap.ped_priority_zones.values())
        return snap


# ----------------------------------------------------------------------------- adapters

def merge_snapshots(snaps: List[TrafficSnapshot]) -> TrafficSnapshot:
    """Combine per-camera snapshots (zones are unique per camera)."""
    if len(snaps) == 1:
        return snaps[0]
    out = TrafficSnapshot(ts=max((s.ts for s in snaps), default=0.0))
    lane_density = []
    for s in snaps:
        out.cameras += s.cameras
        for c, n in s.counts.items():
            out.counts[c] = out.counts.get(c, 0) + n
        out.zones.update(s.zones)
        for a, n in s.direction_counts.items():
            out.direction_counts[a] = out.direction_counts.get(a, 0) + n
        for a, v in s.emergency.items():
            out.emergency[a] = out.emergency.get(a, False) or v
        out.vehicles += s.vehicles
        out.trucks += s.trucks
        out.pedestrians += s.pedestrians
        out.waiting_vehicles += s.waiting_vehicles
        out.pedestrians_waiting += s.pedestrians_waiting
        out.flow_per_min += s.flow_per_min
        out.max_wait_s = max(out.max_wait_s, s.max_wait_s)
        out.ped_priority = out.ped_priority or s.ped_priority
        out.ped_priority_zones.update(s.ped_priority_zones)
        lane_density.append(s.density)
    out.vehicles_per_hour = round(out.flow_per_min * 60, 1)
    out.density = round(sum(lane_density) / len(lane_density), 2)
    waits = [s.avg_wait_s for s in snaps if s.avg_wait_s]
    out.avg_wait_s = round(sum(waits) / len(waits), 2) if waits else 0.0
    pw = [s.ped_avg_wait_s for s in snaps if s.ped_avg_wait_s]
    out.ped_avg_wait_s = round(sum(pw) / len(pw), 2) if pw else 0.0
    return out


def to_traffic_data(s: TrafficSnapshot) -> Dict[str, Any]:
    """Snapshot -> the dict shape the TrafficController / MetricsCollector consume (same as the old simulator)."""
    queues = {}
    for zid, z in s.zones.items():
        b = z.by_class
        queues[zid] = {
            "cars": b.get("car", 0) + b.get("motorcycle", 0), "trucks": b.get("truck", 0), "buses": b.get("bus", 0),
            "pedestrians": b.get("person", 0), "total": z.count, "avg_wait": z.avg_wait_s,
            "max_wait": z.max_wait_s, "throughput": z.flow_per_min,
        }
    return {
        "queues": queues,
        "summary": {
            "total_cars": s.counts.get("car", 0) + s.counts.get("motorcycle", 0), "total_trucks": s.trucks,
            "total_buses": s.counts.get("bus", 0), "total_pedestrians": s.pedestrians,
            "pedestrians_waiting": s.pedestrians_waiting, "avg_car_wait": s.avg_wait_s,
            "avg_pedestrian_wait": s.ped_avg_wait_s, "cars_per_hour": s.vehicles_per_hour,
            "throughput": round(s.flow_per_min),
        },
        "spawned": {}, "passed": {},
    }


def perception_payload(s: Optional[TrafficSnapshot], camera_ok: bool) -> Dict[str, Any]:
    """What the simulation's signal logic receives: per-arm demand seen by the camera (no ground truth)."""
    if s is None or not camera_ok:
        return {"camera_ok": False, "vehicles": {}, "pedestrians_waiting": {}, "ped_priority": {}, "emergency": {}}
    return {
        "camera_ok": True,
        "vehicles": dict(s.direction_counts),
        "pedestrians_waiting": {zid: z.waiting for zid, z in s.zones.items() if z.kind == "pedestrian"},
        "ped_priority": dict(s.ped_priority_zones),
        "emergency": dict(s.emergency),
    }
