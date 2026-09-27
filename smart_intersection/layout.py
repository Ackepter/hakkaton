"""
Intersection layout: the machine-readable description the constructor edits and the simulation runs on.

    Layout
      ├── arms      north/south/east/west: enabled, length, lane type, speed limit, crossing, traffic weight
      ├── signal    adaptive parameters or a user-made fixed program (list of phases)
      ├── traffic   spawn rates and vehicle type mix
      ├── scenery   buildings, trees, lamps, bus stops ... (decoration, never blocks the road)
      └── cameras   virtual cameras (position + radius) consumed by the vision service

Every arm has 1..4 inbound and 1..4 outbound lanes (4 m each). The central part (the "box") grows with the widest
road: BOX = max(16, 4 * lanes + 8) metres from the centre. Each inbound lane lists the movements it allows
(left / straight / right / u-turn), so a layout is a crossroads, a T-junction, an avenue with u-turns ...
`junction = "roundabout"` replaces the box by a ring with an island: vehicles yield instead of obeying lights.

Signals run in stages. Opposite arms share a stage when nobody on them turns left or u-turns (classic NS / EW
phasing, one light per arm); otherwise each arm gets its own protected stage.
"""
import colorsys
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

ARMS = ("north", "south", "east", "west")
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
GROUP_OF = {"north": "ns", "south": "ns", "east": "ew", "west": "ew"}
LampState = Literal["RED", "YELLOW", "GREEN"]

LANE_W = 4.0
BOX_HALF = 16.0                    # smallest box (1..2 lanes per direction); see box_half()
ASPHALT_HALF = 4.0                 # half width of a one-lane-each-way arm
MAX_LANES = 4
MOVES = ("left", "straight", "right", "uturn")
MIN_ARM_EXTRA = 14.0               # an arm must be at least box + this long (stop line, queue space)
OUT = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}     # outward unit vectors (x, z)
NAME_RE = r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,39}$"
ID_RE = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,23}$"

# object type -> footprint radius in metres at scale 1 (used to keep decoration off the roads)
SCENE_TYPES: Dict[str, float] = {
    "building": 5.0, "house": 4.0, "tree": 0.8, "lamp": 0.6, "bus_stop": 2.5, "bench": 1.0, "fence": 2.0, "kiosk": 1.8,
}


class Arm(BaseModel):
    enabled: bool = True
    length_m: float = Field(80.0, ge=30.0, le=80.0)
    lane_type: Literal["mixed", "bus", "tram"] = "mixed"
    lanes_in: int = Field(1, ge=1, le=MAX_LANES)        # lanes towards the junction
    lanes_out: int = Field(1, ge=1, le=MAX_LANES)       # lanes away from it
    turns: Optional[List[List[Literal["left", "straight", "right", "uturn"]]]] = None   # per inbound lane, 0 = innermost
    speed_limit_mps: float = Field(13.9, ge=3.0, le=25.0)
    crossing: bool = True
    weight: float = Field(1.0, ge=0.0, le=10.0)          # share of the vehicle arrivals

    @model_validator(mode="after")
    def _turns(self):
        if self.turns is not None:
            if len(self.turns) != self.lanes_in:
                raise ValueError(f"turns must list every inbound lane ({self.lanes_in}), got {len(self.turns)}")
            for i, t in enumerate(self.turns):
                if not t or len(set(t)) != len(t):
                    raise ValueError(f"lane {i + 1}: choose at least one movement, each only once")
        return self

    def lane_turns(self) -> List[List[str]]:
        """Movements allowed on each inbound lane (default: every lane goes straight)."""
        return [list(t) for t in self.turns] if self.turns is not None else [["straight"] for _ in range(self.lanes_in)]


class SignalPhase(BaseModel):
    name: str = Field("", max_length=40)
    ns: LampState
    ew: LampState
    duration: float = Field(..., ge=1.0, le=180.0)
    arms: Optional[Dict[str, LampState]] = None    # per-arm lamps; overrides ns / ew (needed for protected turn stages)

    @field_validator("arms")
    @classmethod
    def _arm_keys(cls, v):
        if v is not None and set(v) - set(ARMS):
            raise ValueError(f"unknown arms: {sorted(set(v) - set(ARMS))}")
        return v

    def lamp(self, arm: str) -> str:
        if self.arms is not None and arm in self.arms:
            return self.arms[arm]
        return self.ns if GROUP_OF[arm] == "ns" else self.ew


def standard_program(green: float = 30.0, yellow: float = 3.0, all_red: float = 3.0) -> List[SignalPhase]:
    return [SignalPhase(name="NS green", ns="GREEN", ew="RED", duration=green),
            SignalPhase(name="NS yellow", ns="YELLOW", ew="RED", duration=yellow),
            SignalPhase(name="all red", ns="RED", ew="RED", duration=all_red),
            SignalPhase(name="EW green", ns="RED", ew="GREEN", duration=green),
            SignalPhase(name="EW yellow", ns="RED", ew="YELLOW", duration=yellow),
            SignalPhase(name="all red", ns="RED", ew="RED", duration=all_red)]


class Signal(BaseModel):
    mode: Literal["adaptive", "fixed"] = "adaptive"
    base_green: float = Field(30.0, ge=5.0, le=90.0)
    min_green: float = Field(8.0, ge=3.0, le=60.0)
    max_green: float = Field(60.0, ge=10.0, le=180.0)
    yellow: float = Field(3.0, ge=1.0, le=10.0)
    all_red: float = Field(3.0, ge=1.0, le=15.0)
    program: List[SignalPhase] = Field(default_factory=standard_program, max_length=24)

    @model_validator(mode="after")
    def _order(self):
        if not self.min_green <= self.base_green <= self.max_green:
            raise ValueError("green times must satisfy min_green <= base_green <= max_green")
        return self


class Traffic(BaseModel):
    spawn_rate: float = Field(12.0, ge=0.0, le=200.0)
    ped_spawn_rate: float = Field(5.0, ge=0.0, le=200.0)
    type_probs: Dict[str, float] = Field(default_factory=lambda: {
        "car": 0.75, "truck": 0.10, "bus": 0.10, "tram": 0.04, "emergency": 0.01})

    @field_validator("type_probs")
    @classmethod
    def _probs(cls, v):
        known = {"car", "truck", "bus", "tram", "emergency", "taxi", "motorcycle", "bicycle"}
        if set(v) - known:
            raise ValueError(f"unknown vehicle types: {sorted(set(v) - known)}")
        if any(p < 0 for p in v.values()) or sum(v.values()) <= 0:
            raise ValueError("type probabilities must be >= 0 and not all zero")
        return v


class SceneObject(BaseModel):
    id: str = Field(..., pattern=ID_RE)
    type: Literal["building", "house", "tree", "lamp", "bus_stop", "bench", "fence", "kiosk"]
    x: float = Field(..., ge=-150.0, le=150.0)
    z: float = Field(..., ge=-150.0, le=150.0)
    rotation_deg: float = Field(0.0, ge=-360.0, le=360.0)
    scale: float = Field(1.0, ge=0.5, le=3.0)
    height: Optional[float] = Field(None, ge=2.0, le=60.0)
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class CameraObject(BaseModel):
    """A virtual pinhole camera on a mast. It sees what a real one would: a perspective image limited by its field of view.

    yaw_deg is a compass bearing (0 = looking north, 90 = east); yaw_deg None = aim at the middle of the junction.
    pitch_deg is the downward tilt (90 = straight down); None = tilted so the junction centre is in the middle of the frame.
    radius_m is the range: farther objects are not detected."""
    id: str = Field(..., pattern=ID_RE)
    x: float = Field(..., ge=-120.0, le=120.0)
    z: float = Field(..., ge=-120.0, le=120.0)
    radius_m: float = Field(64.0, ge=20.0, le=120.0)
    enabled: bool = True
    height_m: float = Field(12.0, ge=3.0, le=40.0)
    fov_deg: float = Field(70.0, ge=20.0, le=120.0)
    yaw_deg: Optional[float] = Field(None, ge=-360.0, le=360.0)
    pitch_deg: Optional[float] = Field(None, ge=5.0, le=90.0)


class Layout(BaseModel):
    version: int = 1
    name: str = Field("Crossroads", pattern=NAME_RE)
    junction: Literal["signal", "roundabout"] = "signal"
    arms: Dict[str, Arm] = Field(default_factory=lambda: {a: Arm() for a in ARMS})
    signal: Signal = Field(default_factory=Signal)
    traffic: Traffic = Field(default_factory=Traffic)
    scenery: List[SceneObject] = Field(default_factory=list, max_length=300)
    cameras: List[CameraObject] = Field(default_factory=list, max_length=4)

    @field_validator("arms")
    @classmethod
    def _arms(cls, v):
        if set(v) != set(ARMS):
            raise ValueError(f"arms must be exactly {list(ARMS)}")
        return v

    def enabled_arms(self) -> List[str]:
        return [a for a in ARMS if self.arms[a].enabled]


# ----------------------------------------------------------------------------- geometry / validation

def right_vec(arm: str) -> tuple:
    """Unit vector to the driver's right for traffic entering the junction from `arm`."""
    hx, hz = -OUT[arm][0], -OUT[arm][1]
    return (-hz, hx)


def target_arm(arm: str, move: str) -> str:
    """The arm a vehicle ends up on after `move` (right-hand traffic)."""
    if move == "straight":
        return OPPOSITE[arm]
    if move == "uturn":
        return arm
    rx, rz = right_vec(arm)
    sign = 1 if move == "right" else -1
    want = (rx * sign, rz * sign)
    return next(a for a in ARMS if OUT[a] == want)


def max_lanes(layout: "Layout") -> int:
    return max((max(layout.arms[a].lanes_in, layout.arms[a].lanes_out) for a in layout.enabled_arms()), default=1)


def roundabout_dims(layout: "Layout") -> Dict[str, float]:
    """Island / ring radii of a roundabout (metres). The ring is one 5 m lane wide."""
    ri = 10.0 + 2.0 * min(max_lanes(layout), 2)
    return {"island": ri, "ring_center": ri + 2.5, "outer": ri + 5.0, "box": ri + 13.0}


def box_half(layout: "Layout") -> float:
    """Half side of the central square (metres): wide roads need a bigger junction."""
    if layout.junction == "roundabout":
        return roundabout_dims(layout)["box"]
    return max(BOX_HALF, LANE_W * max_lanes(layout) + 8.0)


def stop_dist(layout: "Layout") -> float:
    return box_half(layout) + 5.0


def lateral_span(layout: "Layout", arm: str) -> tuple:
    """Asphalt extent of an arm across its axis (world x for north / south, world z for east / west)."""
    a = layout.arms[arm]
    rx, rz = right_vec(arm)
    r_u = rx if arm in ("north", "south") else rz
    lin, lout = LANE_W * a.lanes_in, LANE_W * a.lanes_out
    return (-lin, lout) if r_u < 0 else (-lout, lin)


def crossing_span(layout: "Layout", arm: str) -> tuple:
    """(low, high) of the walkway across an arm, including a 2 m kerb on both sides."""
    lo, hi = lateral_span(layout, arm)
    return (lo - 2.0, hi + 2.0)


def has_crossing(layout: "Layout", arm: str) -> bool:
    a = layout.arms[arm]
    return a.enabled and a.crossing and layout.junction == "signal"


def lane_moves(layout: "Layout", arm: str, lane: int) -> List[str]:
    """Movements of inbound lane `lane` that lead somewhere (a straight ride into a missing arm is a dead end)."""
    out = []
    for m in layout.arms[arm].lane_turns()[lane]:
        if m == "straight" or layout.arms[target_arm(arm, m)].enabled:
            out.append(m)
    return out


def turns_conflict(layout: "Layout", arm: str) -> bool:
    """True when traffic of this arm crosses the opposite arm's traffic (left turns, u-turns)."""
    return any(m in ("left", "uturn") for i in range(layout.arms[arm].lanes_in) for m in lane_moves(layout, arm, i))


def compatible(layout: "Layout", a: str, b: str) -> bool:
    """May the two arms have green at the same time?"""
    if a == b:
        return True
    return OPPOSITE[a] == b and not turns_conflict(layout, a) and not turns_conflict(layout, b)


def stages(layout: "Layout") -> List[tuple]:
    """Signal stages: the classic NS / EW pairs, split into one stage per arm where a turn would cross the opposing flow."""
    out: List[tuple] = []
    for pair in (("north", "south"), ("east", "west")):
        arms = [a for a in pair if layout.arms[a].enabled]
        if len(arms) == 2 and compatible(layout, *arms):
            out.append(tuple(arms))
        else:
            out += [(a,) for a in arms]
    return out


def is_split(layout: "Layout") -> bool:
    """True when the classic north-south / east-west lamps cannot describe the signal plan (protected turn stages)."""
    return layout.junction == "signal" and any(len(s) == 1 and OPPOSITE[s[0]] in layout.enabled_arms() for s in stages(layout))


def min_arm_length(layout: "Layout") -> float:
    return box_half(layout) + MIN_ARM_EXTRA


def road_rects(layout: Layout) -> List[tuple]:
    """Axis-aligned (x0, z0, x1, z1) rectangles scenery must stay off: the box, arm asphalt and crosswalk bands."""
    h = box_half(layout)
    rects = [(-h, -h, h, h)]
    c0, c1 = h + 1.0, h + 4.0
    for arm in layout.enabled_arms():
        length = layout.arms[arm].length_m
        lo, hi = lateral_span(layout, arm)
        cross = has_crossing(layout, arm)
        clo, chi = crossing_span(layout, arm)
        mid, hw = (clo + chi) / 2, (chi - clo) / 2 + 3.0
        if arm == "north":
            rects.append((lo, -length, hi, -h))
            if cross:
                rects.append((mid - hw, -c1, mid + hw, -c0))
        elif arm == "south":
            rects.append((lo, h, hi, length))
            if cross:
                rects.append((mid - hw, c0, mid + hw, c1))
        elif arm == "east":
            rects.append((h, lo, length, hi))
            if cross:
                rects.append((c0, mid - hw, c1, mid + hw))
        else:
            rects.append((-length, lo, -h, hi))
            if cross:
                rects.append((-c1, mid - hw, -c0, mid + hw))
    return rects


def hits_road(layout: Layout, x: float, z: float, radius: float) -> bool:
    for x0, z0, x1, z1 in road_rects(layout):
        dx = max(x0 - x, 0.0, x - x1)
        dz = max(z0 - z, 0.0, z - z1)
        if dx * dx + dz * dz < radius * radius:
            return True
    return False


def validate_layout(layout: Layout) -> List[str]:
    """Semantic checks beyond the field constraints. Empty list = valid."""
    errors: List[str] = []
    if not layout.enabled_arms():
        errors.append("at least one arm must be enabled")

    roundabout = layout.junction == "roundabout"
    if roundabout and len(layout.enabled_arms()) < 2:
        errors.append("a roundabout needs at least two roads")
    if roundabout and any(max(layout.arms[a].lanes_in, layout.arms[a].lanes_out) > 2 for a in layout.enabled_arms()):
        errors.append("a roundabout supports at most 2 lanes per direction")
    need = min_arm_length(layout)
    for a in layout.enabled_arms():
        if layout.arms[a].length_m < need:
            errors.append(f"{a} road is too short for this junction (at least {need:.0f} m)")
        if not roundabout:
            for i in range(layout.arms[a].lanes_in):
                moves = lane_moves(layout, a, i)
                if not moves:
                    errors.append(f"{a} road, lane {i + 1}: its movements lead to a road that does not exist")
                if "uturn" in moves and i + layout.arms[a].lanes_out < 2:
                    errors.append(f"{a} road, lane {i + 1}: a U-turn needs room to turn: at least two outbound lanes")

    ids = [o.id for o in layout.scenery]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errors.append(f"duplicate scenery ids: {dup}")
    cams = [c.id for c in layout.cameras]
    if len(set(cams)) != len(cams):
        errors.append("duplicate camera ids")
    for o in layout.scenery:
        r = SCENE_TYPES[o.type] * o.scale
        if hits_road(layout, o.x, o.z, r):
            errors.append(f"{o.type} '{o.id}' stands on the road or a crosswalk")

    sig = layout.signal
    if sig.mode == "fixed" and not roundabout:
        arms = layout.enabled_arms()
        for i, p in enumerate(sig.program, 1):
            open_arms = [a for a in arms if p.lamp(a) != "RED"]
            for x, a in enumerate(open_arms):
                for b in open_arms[x + 1:]:
                    if not compatible(layout, a, b):
                        errors.append(f"phase {i}: {a} and {b} are open at the same time (collision)")
        if not sig.program:
            errors.append("the signal program is empty")
        for grp in stages(layout):
            for a in grp:
                if not any(p.lamp(a) == "GREEN" for p in sig.program):
                    who = ("north-south" if a in ("north", "south") else "east-west") if len(grp) == 2 else a
                    err = f"the program never gives green to {who}"
                    if err not in errors:
                        errors.append(err)
    return errors


# ----------------------------------------------------------------------------- presets

def _hsl_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l / 100.0, s / 100.0)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def default_scenery() -> List[SceneObject]:
    """The city around the crossing shown by default (every piece is editable)."""
    buildings = [(-60, -60), (60, -60), (-60, 60), (60, 60), (-90, -30), (90, -30), (-90, 30), (90, 30),
                 (-30, -90), (30, -90), (-30, 90), (30, 90)]
    trees = [(-22, -22), (22, -22), (-22, 22), (22, 22), (-22, -5), (-22, 5), (22, -5), (22, 5),
             (-5, -22), (5, -22), (-5, 22), (5, 22)]
    out = [SceneObject(id=f"b{i + 1}", type="building", x=x, z=z, scale=(8 + (i % 3) * 3) / 10.0,
                       height=8.0 + (i % 4) * 5.0, color=_hsl_hex(200 + i * 15, 30, 55))
           for i, (x, z) in enumerate(buildings)]
    out += [SceneObject(id=f"t{i + 1}", type="tree", x=x, z=z) for i, (x, z) in enumerate(trees)]
    return out


def default_layout() -> Layout:
    return Layout(name="Crossroads", scenery=default_scenery())


def presets() -> Dict[str, Layout]:
    crossroads = default_layout()

    two_way = default_layout()
    two_way.name = "Two-way street"
    for a in ("east", "west"):
        two_way.arms[a].enabled = False
    two_way.scenery = [o for o in two_way.scenery if not hits_road(two_way, o.x, o.z, 0.1)]

    t_junction = default_layout()
    t_junction.name = "T-junction"
    t_junction.arms["south"].enabled = False

    tram = default_layout()
    tram.name = "Tram avenue"
    for a in ("east", "west"):
        tram.arms[a].lane_type = "tram"
        tram.arms[a].speed_limit_mps = 9.0
    tram.traffic.type_probs = {"car": 0.8, "truck": 0.1, "bus": 0.1}

    bus = default_layout()
    bus.name = "Bus street"
    for a in ("north", "south"):
        bus.arms[a].lane_type = "bus"
    bus.scenery += [SceneObject(id="stop1", type="bus_stop", x=-7, z=-40, rotation_deg=90),
                    SceneObject(id="stop2", type="bus_stop", x=7, z=40, rotation_deg=-90)]

    busy = default_layout()
    busy.name = "Busy junction"
    busy.traffic.spawn_rate = 40
    busy.traffic.ped_spawn_rate = 15
    busy.arms["north"].weight = 2.0
    busy.cameras = [CameraObject(id="CAM-01", x=-12, z=-12, radius_m=70)]
    busy.scenery += [SceneObject(id=f"lamp{i}", type="lamp", x=x, z=z) for i, (x, z) in
                     enumerate([(-7, -30), (7, 30), (30, -7), (-30, 7)], 1)]
    out = [crossroads, two_way, t_junction, tram, bus, busy]
    out += [make(name) for name in JUNCTION_TYPES if name not in {p.name for p in out}]
    return {p.name: p for p in out}


# ----------------------------------------------------------------------------- junction types

def _arms_setup(layout: Layout, **per_arm) -> Layout:
    """per_arm: arm -> dict of Arm fields; an arm named with None is switched off."""
    for arm, cfg in per_arm.items():
        if cfg is None:
            layout.arms[arm].enabled = False
        else:
            for k, v in cfg.items():
                setattr(layout.arms[arm], k, v)
    return layout


def _city(name: str) -> Layout:
    l = default_layout()
    l.name = name
    return l


def _fit(l: Layout) -> Layout:
    """Keep only the decoration that does not stand on the (possibly wider) roads."""
    l.scenery = [o for o in l.scenery if not hits_road(l, o.x, o.z, SCENE_TYPES[o.type] * o.scale)]
    return l


def _turn_crossroads() -> Layout:
    l = _city("Turn crossroads")
    for a in ARMS:
        _arms_setup(l, **{a: dict(lanes_in=2, lanes_out=2, turns=[["left"], ["straight", "right"]])})
    return _fit(l)


def _no_left_crossroads() -> Layout:
    l = _city("No-left crossroads")
    for a in ARMS:
        _arms_setup(l, **{a: dict(lanes_in=2, lanes_out=2, turns=[["straight"], ["straight", "right"]])})
    return _fit(l)


def _t_turns() -> Layout:
    l = _city("T-junction with turns")
    _arms_setup(l, south=None,
                north=dict(turns=[["left", "right"]]),
                east=dict(turns=[["straight", "right"]]),
                west=dict(turns=[["straight", "left"]]))
    return _fit(l)


def _roundabout() -> Layout:
    l = _city("Roundabout")
    l.junction = "roundabout"
    l.traffic.spawn_rate = 14                  # a one-lane ring carries about 18 vehicles a minute
    return _fit(l)


def _roundabout2() -> Layout:
    l = _city("Roundabout 2-lane entries")
    l.junction = "roundabout"
    for a in ARMS:
        _arms_setup(l, **{a: dict(lanes_in=2, lanes_out=2)})
    l.traffic.spawn_rate = 16
    return _fit(l)


def _avenue_uturn() -> Layout:
    """4 lanes on the avenue (2 each way): inner lane = left turn or u-turn, outer lane = straight (may drift into the
    left lane after the junction) or right. Side streets: one lane each way, every movement."""
    l = _city("Avenue with U-turn")
    for a in ("east", "west"):
        _arms_setup(l, **{a: dict(lanes_in=2, lanes_out=2, turns=[["left", "uturn"], ["straight", "right"]])})
    for a in ("north", "south"):
        _arms_setup(l, **{a: dict(turns=[["left", "straight", "right"]], weight=0.6)})
    l.traffic.spawn_rate = 24
    l.cameras = [CameraObject(id="CAM-01", x=-28, z=-28, radius_m=90, height_m=14)]
    return _fit(l)


def _boulevard() -> Layout:
    """6 lanes (3 each way) on the boulevard with u-turns; the side streets have two lanes each way."""
    l = _city("Boulevard")
    for a in ("east", "west"):
        _arms_setup(l, **{a: dict(lanes_in=3, lanes_out=3, turns=[["left", "uturn"], ["straight"], ["straight", "right"]],
                                  speed_limit_mps=16.7)})
    for a in ("north", "south"):
        _arms_setup(l, **{a: dict(lanes_in=2, lanes_out=2, turns=[["left"], ["straight", "right"]], weight=0.7)})
    l.traffic.spawn_rate = 36
    l.signal.base_green = 25
    l.cameras = [CameraObject(id="CAM-01", x=-34, z=-34, radius_m=100, height_m=16)]
    return _fit(l)


def _grand_junction() -> Layout:
    l = _city("Grand junction")
    for a in ARMS:
        _arms_setup(l, **{a: dict(lanes_in=4, lanes_out=4,
                                  turns=[["left", "uturn"], ["straight"], ["straight"], ["straight", "right"]])})
    l.traffic.spawn_rate = 48
    l.signal.base_green = 25
    return _fit(l)


# name -> (builder, what the junction does)
JUNCTION_TYPES = {
    "Turn crossroads": (_turn_crossroads, "Crossroads, 2 lanes each way. Inner lane turns left, outer lane goes straight or right. "
                        "Every arm has its own protected green, so left turns never meet oncoming traffic."),
    "No-left crossroads": (_no_left_crossroads, "Crossroads without left turns: straight and right only. Opposite arms share "
                           "one green (north-south, then east-west); right turns yield to pedestrians."),
    "T-junction with turns": (_t_turns, "Side street from the north joins an east-west road; every movement allowed. "
                              "Three protected stages, one per arm."),
    "Roundabout": (_roundabout, "Circle with a central island, no lights. Vehicles yield to traffic already on the ring "
                   "and choose any exit."),
    "Roundabout 2-lane entries": (_roundabout2, "Roundabout with two lanes on every entry and exit; they queue side by side and merge onto "
                                 "the one circulating lane."),
    "Avenue with U-turn": (_avenue_uturn, "4-lane avenue (2 each way) with side streets. Inner lane: left turn or U-turn. "
                           "Outer lane: straight (may move into the left lane after the junction) or right."),
    "Boulevard": (_boulevard, "6-lane boulevard (3 each way) with U-turns, 2-lane side streets."),
    "Grand junction": (_grand_junction, "Four 8-lane roads (4 each way): the centre grows to 24 m, U-turn and left lane, "
                       "two through lanes, right lane. The largest layout."),
}


def make(name: str) -> Layout:
    return JUNCTION_TYPES[name][0]()


def junction_types() -> List[dict]:
    """Catalogue for the constructor: every ready-made junction with a short description of its logic."""
    info = {
        "Crossroads": "Classic crossroads, one lane each way, straight only. Two stages: north-south then east-west.",
        "T-junction": "Three roads, straight only; the road that ends becomes a dead end with a barrier.",
        "Two-way street": "A street without side roads: one stage, signals only serve pedestrians.",
        "Tram avenue": "East-west tram tracks: trams and cars share the crossing.",
        "Bus street": "North-south bus lane with bus stops.",
        "Busy junction": "Crossroads under heavy traffic with a camera.",
    }
    names = ["Crossroads", "T-junction", "Two-way street", "Tram avenue", "Bus street", "Busy junction"]
    out = [{"name": n, "description": info[n], "junction": "signal"} for n in names]
    for n, (build, text) in JUNCTION_TYPES.items():
        out.append({"name": n, "description": text, "junction": build().junction})
    return out


# ----------------------------------------------------------------------------- persistence

class LayoutStore:
    """Named layouts as JSON files. Names are validated, so no path can escape the directory."""

    def __init__(self, directory: str):
        self.dir = Path(directory)

    def _path(self, name: str) -> Path:
        if not re.match(NAME_RE, name or ""):
            raise ValueError("invalid layout name")
        return self.dir / f"{name}.json"

    def list(self) -> List[str]:
        return sorted(p.stem for p in self.dir.glob("*.json")) if self.dir.is_dir() else []

    def save(self, layout: Layout) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(layout.name)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(layout.model_dump(), indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def load(self, name: str) -> Layout:
        path = self._path(name)
        if not path.is_file():
            raise FileNotFoundError(name)
        return Layout.model_validate_json(path.read_text(encoding="utf-8"))

    def remember(self, name: str) -> None:
        """Remember which layout was applied last, so a restart comes back to it."""
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / ".last").write_text(name, encoding="utf-8")

    def last(self) -> Optional[Layout]:
        try:
            return self.load((self.dir / ".last").read_text(encoding="utf-8").strip())
        except (OSError, ValueError, FileNotFoundError):
            return None

    def delete(self, name: str) -> None:
        path = self._path(name)
        if not path.is_file():
            raise FileNotFoundError(name)
        path.unlink()
