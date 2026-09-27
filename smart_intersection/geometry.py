"""
Road geometry of a layout: lanes, vehicle paths (straight / turn / u-turn / roundabout), conflict cells, scene description.

Coordinates (metres, top view): x west -> east, z north -> south, the junction centre is (0, 0).

A *path* is the polyline one movement follows: from 80 m out on an inbound lane, through the central part, to the far end of
the exit road. Vehicles carry a distance `s` along their path, so the engine stays one-dimensional while the paths bend.

    path.at(s) -> (x, z, heading)         heading = atan2(dz, dx)
    path.box_entry_s / box_exit_s         where the central part starts / ends
    path.speed_cap                        highest comfortable speed in the bend (m/s)

Conflict zones: for every pair of routes that come closer than ZONE_DIST anywhere inside the junction, `path_zones`
gives the stretch of each route that is shared (crossing, merging, diverging). The engine lets only one vehicle at a time
be inside such a zone (the one already there, else the one with priority), so turns, u-turns and roundabouts stay
collision free without any rasterising.
"""
import math
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

from .layout import (ARMS, LANE_W, OPPOSITE, OUT, Layout, box_half, crossing_span, has_crossing, lane_moves, lateral_span,
                     right_vec, roundabout_dims, stages, stop_dist, target_arm)

ARM_LENGTH = 80.0            # inbound paths start this far from the centre (the spawn point of the longest arm)
A_LAT = 3.0                  # comfortable lateral acceleration (m/s^2) -> speed limit in bends
MIN_CURVE_SPEED = 2.5
CROSS_MAX = 10.0             # a shared stretch longer than this is a merge (vehicles follow), shorter = a crossing
MERGE_LEN = 8.0              # only the entrance of a merge is exclusive
ZONE_DIST = 3.8              # routes closer than this (centre lines) share a conflict zone; lanes are 4 m apart
MAX_SWEEP = 3.6              # a vehicle that would sweep a wider band than this in the bends cannot drive the route
SWEEP_MARGIN = 0.3
AXLE = 0.35                  # axle positions relative to the vehicle length: the body is drawn along the chord between them
REGION_EXTRA = 14.0          # conflict zones are only kept within box + this many metres of the centre
DEAD_END_RUN = 6.0           # a straight ride into a missing arm ends this far past the box
MOVE_WEIGHT = {"straight": 1.0, "right": 0.6, "left": 0.6, "uturn": 0.25}



def lane_id(arm: str, index: int, inbound: bool = True) -> str:
    base = f"{arm}-{'in' if inbound else 'out'}"
    return base if index == 0 else f"{base}-{index}"


def _pt(arm: str, dist: float, lateral: float) -> Tuple[float, float]:
    """World point at `dist` from the centre along the arm axis, `lateral` metres to the inbound driver's right."""
    o, r = OUT[arm], right_vec(arm)
    return (o[0] * dist + r[0] * lateral, o[1] * dist + r[1] * lateral)


def _bezier(ctrl: List[Tuple[float, float]], step: float = 1.0) -> List[Tuple[float, float]]:
    """Sampled Bezier curve (2 = line, 3 = quadratic, 4 = cubic), first point included."""
    rough = sum(math.dist(ctrl[i], ctrl[i + 1]) for i in range(len(ctrl) - 1))
    n = max(2, int(math.ceil(rough / step)))
    out = []
    for k in range(n + 1):
        t = k / n
        pts = ctrl
        while len(pts) > 1:
            pts = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1]) for a, b in zip(pts, pts[1:])]
        out.append(pts[0])
    return out


@dataclass
class Path:
    id: str
    lane_id: str
    arm: str
    lane_index: int
    movement: str                    # left / straight / right / uturn (roundabouts: relation of the exit to the entry)
    exit_arm: str
    exit_lane: int
    exit_key: str                    # exit lane vehicles of different paths share (or "<arm>-dead-end")
    points: List[Tuple[float, float]]
    cum: List[float]
    box_entry_s: float
    box_exit_s: float
    speed_cap: float
    weight: float = 1.0
    dead_end: bool = False
    radius_min: float = math.inf                # tightest bend of the whole route (metres)
    kappa: List[float] = field(default_factory=list)      # curvature (1/m) around every metre of the route
    _fit: Dict[tuple, bool] = field(default_factory=dict)

    def swept_radius(self, length: float, width: float) -> List[float]:
        """Band around the route a body of this size sweeps at every metre: half width + margin + the bend sagitta."""
        half, out = int(length / 2) + 1, []
        for k in range(len(self.kappa)):
            kap = max(self.kappa[max(0, k - half):k + half + 1], default=0.0)
            out.append(SWEEP_MARGIN + width / 2 + length * length / 8.0 * kap)
        return out

    def fits(self, length: float, width: float) -> bool:
        """Can a vehicle of this size drive the route (a tram cannot u-turn, a truck cannot take a tight ring exit)?"""
        key = (round(length, 2), round(width, 2))
        if key not in self._fit:
            self._fit[key] = max(self.swept_radius(length, width), default=0.0) <= MAX_SWEEP
        return self._fit[key]

    def pose(self, s: float, length: float) -> Tuple[float, float, float]:
        """Centre and heading of a vehicle body of `length` whose centre is at s: it follows the chord between its axles."""
        d = AXLE * length
        if d < 0.05:
            return self.at(s)
        x1, z1, _ = self.at(s + d)
        x0, z0, _ = self.at(s - d)
        return (x0 + x1) / 2, (z0 + z1) / 2, math.atan2(z1 - z0, x1 - x0)

    @property
    def length(self) -> float:
        return self.cum[-1]

    @property
    def passing_len(self) -> float:
        """Metres after the stop line during which a vehicle counts as 'passing' the junction."""
        return (self.box_exit_s - self.box_entry_s) + 10.0

    def at(self, s: float) -> Tuple[float, float, float]:
        cum, pts = self.cum, self.points
        i = 0 if s <= 0 else min(bisect_right(cum, s) - 1, len(cum) - 2)
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        seg = cum[i + 1] - cum[i] or 1e-9
        t = (s - cum[i]) / seg
        return x0 + (x1 - x0) * t, z0 + (z1 - z0) * t, math.atan2(z1 - z0, x1 - x0)


def _make_path(pid, lane, arm, li, move, exit_arm, exit_lane, exit_key, pts, entry_pt, exit_pt, dead_end=False) -> Path:
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    # first and last vertex are the exact box entry / exit (they are in the list); find them by position
    def s_of(p):
        return min(range(len(pts)), key=lambda i: math.dist(pts[i], p))
    entry_s, exit_s = cum[s_of(entry_pt)], cum[s_of(exit_pt)]
    rmin = _min_radius(pts, cum, entry_s, exit_s)
    cap = math.inf if rmin == math.inf else max(MIN_CURVE_SPEED, math.sqrt(A_LAT * rmin))
    return Path(pid, lane, arm, li, move, exit_arm, exit_lane, exit_key, pts, cum, entry_s, exit_s, cap,
                MOVE_WEIGHT[move], dead_end, rmin, _kappa_table(pts, cum))


def _kappa_table(pts, cum) -> List[float]:
    """Curvature of the route around every whole metre (max over the vertices within half a metre)."""
    table = [0.0] * (int(math.ceil(cum[-1])) + 2)
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        d1, d2 = math.dist(a, b), math.dist(b, c)
        if d1 < 1e-6 or d2 < 1e-6:
            continue
        a1, a2 = math.atan2(b[1] - a[1], b[0] - a[0]), math.atan2(c[1] - b[1], c[0] - b[0])
        turn = abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)
        if turn > 1e-4:
            kap = turn / ((d1 + d2) / 2)
            for k in {int(round(cum[i] - 0.5)), int(round(cum[i])), int(round(cum[i] + 0.5))}:
                if 0 <= k < len(table):
                    table[k] = max(table[k], kap)
    return table


def _min_radius(pts, cum, entry_s, exit_s) -> float:
    """Radius of the tightest bend between the box entry and exit (inf on straight paths)."""
    rmin = math.inf
    for i in range(1, len(pts) - 1):
        if not entry_s - 1e-6 <= cum[i] <= exit_s + 1e-6:
            continue
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        d1, d2 = math.dist(a, b), math.dist(b, c)
        if d1 < 1e-6 or d2 < 1e-6:
            continue
        a1, a2 = math.atan2(b[1] - a[1], b[0] - a[0]), math.atan2(c[1] - b[1], c[0] - b[0])
        turn = abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)
        if turn > 1e-4:
            rmin = min(rmin, (d1 + d2) / 2 / turn)
    return rmin


# ----------------------------------------------------------------------------- path construction

def _turn_exit_lane(layout: Layout, arm: str, i: int, move: str) -> int:
    """Exit lane of a turning movement: lefts fill the inner lanes, rights the outer ones (order preserving)."""
    a = layout.arms[arm]
    t = layout.arms[target_arm(arm, move)]
    same = [k for k in range(a.lanes_in) if move in lane_moves(layout, arm, k)]
    k = same.index(i)
    if move == "right":
        return max(t.lanes_out - 1 - (len(same) - 1 - k), 0)
    if move == "uturn":                       # wide enough to turn in (centre lines >= 8 m apart): the outer lane where needed
        return min(max(1 - i, 0) + k, t.lanes_out - 1)
    return min(k, t.lanes_out - 1)


def _straight_exit_lanes(layout: Layout, arm: str, i: int) -> List[int]:
    """Exit lanes a through lane may take. Fewer through lanes than exit lanes = the driver may drift into a neighbour lane."""
    t = OPPOSITE[arm]
    if not layout.arms[t].enabled:
        return [i]
    through = [k for k in range(layout.arms[arm].lanes_in) if "straight" in lane_moves(layout, arm, k)]
    k, m, n = through.index(i), len(through), layout.arms[t].lanes_out
    return list(range(k, k + n - m + 1)) if n >= m else [min(k, n - 1)]


def _signal_path(layout: Layout, arm: str, i: int, move: str, j: int) -> Path:
    B = box_half(layout)
    t = target_arm(arm, move)
    dead = not layout.arms[t].enabled
    h = (-OUT[arm][0], -OUT[arm][1])
    lat_in = (i + 0.5) * LANE_W
    start, E = _pt(arm, ARM_LENGTH, lat_in), _pt(arm, B, lat_in)
    X = _pt(t, B, -(j + 0.5) * LANE_W)
    end_dist = B + DEAD_END_RUN if dead else layout.arms[t].length_m
    end = _pt(t, end_dist, -(j + 0.5) * LANE_W)
    if move == "straight":
        run = math.dist(E, X)
        shift = abs((X[0] - E[0]) * h[1] - (X[1] - E[1]) * h[0])         # sideways distance the driver drifts
        mid = [E, X] if shift < 1e-6 else _bezier([E, (E[0] + h[0] * run / 2, E[1] + h[1] * run / 2),
                                                   (X[0] - h[0] * run / 2, X[1] - h[1] * run / 2), X])
    elif move == "uturn":
        d = 0.67 * math.dist(E, X)                # handles of a cubic that approximates a half circle
        mid = _bezier([E, (E[0] + h[0] * d, E[1] + h[1] * d), (X[0] + h[0] * d, X[1] + h[1] * d), X])
    else:
        run = (X[0] - E[0]) * h[0] + (X[1] - E[1]) * h[1]
        C = (E[0] + h[0] * run, E[1] + h[1] * run)
        mid = _bezier([E, C, X])
    pts = [start] + mid + [end]
    exit_key = f"{t}-dead-end-{j}" if dead else lane_id(t, j, inbound=False)
    lid = lane_id(arm, i)
    pid = f"{lid}:{move}:{t}{j}"
    return _make_path(pid, lid, arm, i, move, t, j, exit_key, pts, E, X, dead_end=dead)


def _ring_path(layout: Layout, arm: str, i: int, t: str, j: int) -> Path:
    """Entry lane -> right turn onto the ring -> counter-clockwise arc -> exit lane."""
    B = box_half(layout)
    Rc = roundabout_dims(layout)["ring_center"]
    h = (-OUT[arm][0], -OUT[arm][1])
    lat_in = (i + 0.5) * LANE_W
    start, P0 = _pt(arm, ARM_LENGTH, lat_in), _pt(arm, B, lat_in)
    psi_a = math.atan2(OUT[arm][1], OUT[arm][0])
    psi_t = math.atan2(OUT[t][1], OUT[t][0])
    d = math.radians(38)
    psi_e, psi_x = psi_a - d, psi_t + d
    total = (psi_e - psi_x) % (2 * math.pi)
    ring = lambda ps: (Rc * math.cos(ps), Rc * math.sin(ps))
    tang = lambda ps: (math.sin(ps), -math.cos(ps))                     # counter-clockwise on the map
    Pe, Te = ring(psi_e), tang(psi_e)
    Px, Tx = ring(psi_x), tang(psi_x)
    P3 = _pt(t, B, -(j + 0.5) * LANE_W)
    o_t = OUT[t]
    k1 = 0.45 * math.dist(P0, Pe)
    entry = _bezier([P0, (P0[0] + h[0] * k1, P0[1] + h[1] * k1), (Pe[0] - Te[0] * k1, Pe[1] - Te[1] * k1), Pe])
    n = max(2, int(math.ceil(total * Rc)))
    arc = [ring(psi_e - total * k / n) for k in range(1, n)]
    k2 = 0.45 * math.dist(Px, P3)
    leave = _bezier([Px, (Px[0] + Tx[0] * k2, Px[1] + Tx[1] * k2), (P3[0] - o_t[0] * k2, P3[1] - o_t[1] * k2), P3])
    end = _pt(t, layout.arms[t].length_m, -(j + 0.5) * LANE_W)
    pts = [start] + entry + arc + leave + [end]
    rel = {"right": OUT[target_arm(arm, "right")], "straight": OUT[OPPOSITE[arm]], "left": OUT[target_arm(arm, "left")]}
    move = "uturn" if t == arm else next(m for m, v in rel.items() if v == o_t)
    lid = lane_id(arm, i)
    return _make_path(f"{lid}:{move}:{t}{j}", lid, arm, i, move, t, j, lane_id(t, j, inbound=False), pts, P0, P3)


def build_paths(layout: Layout) -> Dict[str, Path]:
    paths: Dict[str, Path] = {}
    for arm in layout.enabled_arms():
        a = layout.arms[arm]
        for i in range(a.lanes_in):
            if layout.junction == "roundabout":
                for t in layout.enabled_arms():
                    for j in range(layout.arms[t].lanes_out):
                        p = _ring_path(layout, arm, i, t, j)
                        paths[p.id] = p
                continue
            for move in lane_moves(layout, arm, i):
                exits = _straight_exit_lanes(layout, arm, i) if move == "straight" else [_turn_exit_lane(layout, arm, i, move)]
                for j in exits:
                    p = _signal_path(layout, arm, i, move, j)
                    paths[p.id] = p
    # a lane with several exits (drifting) splits its weight among them
    per = {}
    for p in paths.values():
        per.setdefault((p.lane_id, p.movement), []).append(p)
    for group in per.values():
        for p in group:
            p.weight /= len(group)
    return paths


# ----------------------------------------------------------------------------- conflict cells

def divergence(p: Path, q: Path) -> int:
    """First metre where two routes that start on one lane stop being on top of each other."""
    k = 0
    while k < min(len(p.kappa), len(q.kappa)) and math.dist(p.at(float(k))[:2], q.at(float(k))[:2]) < 0.5:
        k += 1
    return k


def path_zones(paths: Dict[str, Path], region: float, dist: float = ZONE_DIST) -> Tuple[Dict[str, list], Dict[str, list]]:
    """
    Where routes meet inside `region` metres of the centre. Returns (exclusive, follow), both keyed by path id.

    exclusive[p] = [(q, a0, a1, b0, b1)]  p between s = a0..a1 and q between b0..b1 share a crossing (or the entrance of a
                   merge, MERGE_LEN metres long): one vehicle at a time
    follow[p]    = [(q, a0, a1, b0, b1, off)]  routes that run on top of each other for more than CROSS_MAX metres (a
                   merge / ring): once both vehicles are on the shared stretch they keep a gap; q is at s - off on p's axis

    The shared approach of two routes that start on the same lane is neither: those vehicles simply queue.
    """
    grid: Dict[Tuple[int, int], list] = {}
    for p in paths.values():
        for k in range(int(p.length) + 1):
            x, z, _ = p.at(float(k))
            if abs(x) <= region and abs(z) <= region:
                grid.setdefault((int(x // dist), int(z // dist)), []).append((p, k, x, z))
    split: Dict[Tuple[str, str], int] = {}

    def diverge(p: Path, q: Path) -> int:
        key = (p.id, q.id) if p.id < q.id else (q.id, p.id)
        if key not in split:
            split[key] = divergence(p, q)
        return split[key]

    samples: Dict[Tuple[str, str], list] = {}
    for p in paths.values():
        for k in range(int(p.length) + 1):
            x, z, _ = p.at(float(k))
            if abs(x) > region or abs(z) > region:
                continue
            gi, gj = int(x // dist), int(z // dist)
            for i in (gi - 1, gi, gi + 1):
                for j in (gj - 1, gj, gj + 1):
                    for q, kq, qx, qz in grid.get((i, j), ()):
                        if q.id == p.id or math.hypot(x - qx, z - qz) >= dist:
                            continue
                        if q.lane_id == p.lane_id:
                            d = diverge(p, q)
                            if k < d or kq < d:
                                continue
                        samples.setdefault((p.id, q.id), []).append((k, kq))
    exclusive: Dict[str, list] = {pid: [] for pid in paths}
    follow: Dict[str, list] = {pid: [] for pid in paths}
    for (a, b), pairs in samples.items():
        for run in _components(pairs):
            ks, kqs = [r[0] for r in run], [r[1] for r in run]
            a0, a1, b0, b1 = min(ks), max(ks), min(kqs), max(kqs)
            if max(a1 - a0, b1 - b0) <= CROSS_MAX:
                exclusive[a].append((b, float(a0), float(a1), float(b0), float(b1)))
            else:
                exclusive[a].append((b, float(a0), float(min(a1, a0 + MERGE_LEN)), float(b0), float(min(b1, b0 + MERGE_LEN))))
                offs = sorted(kq - k for k, kq in run)
                follow[a].append((b, float(a0), float(a1), float(b0), float(b1), float(offs[len(offs) // 2])))
    return exclusive, follow


def _components(pairs: List[Tuple[int, int]], step: int = 3) -> List[List[Tuple[int, int]]]:
    """Group (s on p, s on q) sample pairs into separate meeting places (connected in both coordinates)."""
    buckets: Dict[Tuple[int, int], list] = {}
    for k, kq in pairs:
        buckets.setdefault((k // step, kq // step), []).append((k, kq))
    seen, out = set(), []
    for start in buckets:
        if start in seen:
            continue
        seen.add(start)
        todo, comp = [start], []
        while todo:
            bk = todo.pop()
            comp += buckets[bk]
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    nb = (bk[0] + di, bk[1] + dj)
                    if nb in buckets and nb not in seen:
                        seen.add(nb)
                        todo.append(nb)
        out.append(comp)
    return out


def needs_zones(paths: Dict[str, Path], layout: Layout) -> bool:
    """Straight parallel lanes never meet; anything else (turns, drifting, roundabout) needs the conflict zones."""
    return layout.junction == "roundabout" or any(p.movement != "straight" or p.exit_lane != p.lane_index
                                                  for p in paths.values())


def zone_region(layout: Layout) -> float:
    return box_half(layout) + REGION_EXTRA


# ----------------------------------------------------------------------------- crossings and lights

def crossing_geometry(layout: Layout, arm: str) -> Optional[dict]:
    """Walkway across `arm`: centre distance, depth, walking axis, extent and the pedestrian queue sides."""
    if not has_crossing(layout, arm):
        return None
    B = box_half(layout)
    lo, hi = crossing_span(layout, arm)
    return {"arm": arm, "center": B + 2.5, "depth": 3.0, "axis": "x" if arm in ("north", "south") else "z",
            "lo": lo, "hi": hi, "mid": (lo + hi) / 2, "width": hi - lo}


def pedestrian_xz(cg: dict, position_m: float, direction: int, offset: float) -> Tuple[float, float]:
    """World position of a pedestrian on a crossing (position_m 0..width across, negative = waiting on the kerb)."""
    along = cg["mid"] + direction * (position_m - cg["width"] / 2)
    side = OUT[cg["arm"]]
    dist = cg["center"] + offset
    if cg["axis"] == "x":
        return along, side[1] * dist
    return side[0] * dist, along


def light_pole(layout: Layout, arm: str) -> Tuple[float, float]:
    """Traffic light pole: just past the stop line, on the kerb at the driver's right."""
    B = box_half(layout)
    return _pt(arm, B + 6.0, LANE_W * layout.arms[arm].lanes_in + 3.0)


def blocked_crossings(layout: Layout, stage: Tuple[str, ...]) -> set:
    """
    Arms whose crosswalk must stay closed while `stage` has green: its own arm and, on a signal junction, the arm its
    through traffic drives onto (turning vehicles give way to pedestrians on the crosswalk they turn into, so that one
    stays open). A roundabout's crossings sit on their own arm, before the ring, so a stage only closes its own arm.
    """
    closed = set(stage)
    if layout.junction == "roundabout":
        return closed
    for arm in stage:
        for i in range(layout.arms[arm].lanes_in):
            if "straight" in lane_moves(layout, arm, i) and layout.arms[OPPOSITE[arm]].enabled:
                closed.add(OPPOSITE[arm])
    return closed


def crossing_stages(layout: Layout) -> Dict[str, List[int]]:
    """Crosswalk id -> indexes of the stages in which pedestrians may cross it."""
    out = {}
    st = stages(layout)
    for arm in layout.enabled_arms():
        if has_crossing(layout, arm):
            out[f"PC-{arm[0].upper()}"] = [k for k, s in enumerate(st) if arm not in blocked_crossings(layout, s)]
    return out


# ----------------------------------------------------------------------------- scene description (cameras, renderers)

def scene_geometry(layout: Layout) -> dict:
    """Everything a camera needs to draw the junction and to cut its road into zones. Plain JSON."""
    B = box_half(layout)
    sd = stop_dist(layout)
    out = {"junction": layout.junction, "box_half": B, "lane_width": LANE_W, "stop_dist": sd, "arms": [], "lanes": [],
           "crossings": [], "lights": [], "island": None}
    if layout.junction == "roundabout":
        d = roundabout_dims(layout)
        out["island"] = {"radius": d["island"], "ring_center": d["ring_center"], "outer": d["outer"]}
    approach = 40.0
    for arm in layout.enabled_arms():
        a = layout.arms[arm]
        lo, hi = lateral_span(layout, arm)
        rx, rz = right_vec(arm)
        out["arms"].append({"arm": arm, "length": a.length_m, "lanes_in": a.lanes_in, "lanes_out": a.lanes_out,
                            "lateral": [lo, hi], "lane_type": a.lane_type,
                            "right": rx if arm in ("north", "south") else rz})    # side of the inbound lanes across the axis
        for i in range(a.lanes_in):
            lat0, lat1 = i * LANE_W, (i + 1) * LANE_W
            near = B if layout.junction == "roundabout" else sd
            far = min(near + approach, a.length_m)
            poly = [_pt(arm, near, lat0), _pt(arm, near, lat1), _pt(arm, far, lat1), _pt(arm, far, lat0)]
            out["lanes"].append({"id": lane_id(arm, i), "arm": arm, "index": i, "inbound": True, "polygon": poly,
                                 "moves": ["roundabout"] if layout.junction == "roundabout" else lane_moves(layout, arm, i)})
        cg = crossing_geometry(layout, arm)
        if cg:
            c, dp = cg["center"], cg["depth"] / 2
            lo_c, hi_c = cg["lo"] - 3.0, cg["hi"] + 3.0          # walking area incl. waiting spots
            if cg["axis"] == "x":
                s = OUT[arm][1]
                poly = [(lo_c, s * (c - dp)), (hi_c, s * (c - dp)), (hi_c, s * (c + dp)), (lo_c, s * (c + dp))]
            else:
                s = OUT[arm][0]
                poly = [(s * (c - dp), lo_c), (s * (c - dp), hi_c), (s * (c + dp), hi_c), (s * (c + dp), lo_c)]
            out["crossings"].append({**cg, "id": f"PC-{arm[0].upper()}", "polygon": poly})
        out["lights"].append({"id": f"TL-{arm[0].upper()}", "arm": arm, "pole": light_pole(layout, arm)})
    return out
