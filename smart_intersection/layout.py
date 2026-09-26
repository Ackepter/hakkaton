"""
Intersection layout: the machine-readable description the constructor edits and the simulation runs on.

    Layout
      ├── arms      north/south/east/west: enabled, length, lane type, speed limit, crossing, traffic weight
      ├── signal    adaptive parameters or a user-made fixed program (list of phases)
      ├── traffic   spawn rates and vehicle type mix
      ├── scenery   buildings, trees, lamps, bus stops ... (decoration, never blocks the road)
      └── cameras   virtual cameras (position + radius) consumed by the vision service

The geometry is fixed (a 32 m box, 8 m wide arms); what changes is which arms exist, how long they are and what
happens on them. Routes stay straight (an arm leads to the opposite arm), so every layout is conflict-free under
the signal groups NS / EW.
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

BOX_HALF = 16.0
ASPHALT_HALF = 4.0                 # half width of an arm's asphalt (two 4 m lanes)
CROSSWALK_BAND = (17.0, 20.0)      # distance from centre, crosswalk depth
CROSSWALK_HALF_WIDTH = 9.0         # walking area incl. waiting spots
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
    speed_limit_mps: float = Field(13.9, ge=3.0, le=25.0)
    crossing: bool = True
    weight: float = Field(1.0, ge=0.0, le=10.0)          # share of the vehicle arrivals


class SignalPhase(BaseModel):
    name: str = Field("", max_length=40)
    ns: LampState
    ew: LampState
    duration: float = Field(..., ge=1.0, le=180.0)


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
    id: str = Field(..., pattern=ID_RE)
    x: float = Field(..., ge=-120.0, le=120.0)
    z: float = Field(..., ge=-120.0, le=120.0)
    radius_m: float = Field(64.0, ge=20.0, le=70.0)
    enabled: bool = True


class Layout(BaseModel):
    version: int = 1
    name: str = Field("Crossroads", pattern=NAME_RE)
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

def road_rects(layout: Layout) -> List[tuple]:
    """Axis-aligned (x0, z0, x1, z1) rectangles scenery must stay off: the box, arm asphalt and crosswalk bands."""
    h = BOX_HALF
    rects = [(-h, -h, h, h)]
    for arm in layout.enabled_arms():
        a = layout.arms[arm]
        length = a.length_m
        c0, c1 = CROSSWALK_BAND
        w = CROSSWALK_HALF_WIDTH
        if arm == "north":
            rects.append((-ASPHALT_HALF, -length, ASPHALT_HALF, -h))
            if a.crossing:
                rects.append((-w, -c1, w, -c0))
        elif arm == "south":
            rects.append((-ASPHALT_HALF, h, ASPHALT_HALF, length))
            if a.crossing:
                rects.append((-w, c0, w, c1))
        elif arm == "east":
            rects.append((h, -ASPHALT_HALF, length, ASPHALT_HALF))
            if a.crossing:
                rects.append((c0, -w, c1, w))
        else:
            rects.append((-length, -ASPHALT_HALF, -h, ASPHALT_HALF))
            if a.crossing:
                rects.append((-c1, -w, -c0, w))
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
    if sig.mode == "fixed":
        groups = {GROUP_OF[a] for a in layout.enabled_arms()}
        for i, p in enumerate(sig.program, 1):
            if len(groups) == 2 and p.ns != "RED" and p.ew != "RED":
                errors.append(f"phase {i}: north-south and east-west are open at the same time (collision)")
        if not sig.program:
            errors.append("the signal program is empty")
        for g in sorted(groups):
            if not any((p.ns if g == "ns" else p.ew) == "GREEN" for p in sig.program):
                errors.append(f"the program never gives green to {'north-south' if g == 'ns' else 'east-west'}")
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
    return {p.name: p for p in (crossroads, two_way, t_junction, tram, bus, busy)}


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
