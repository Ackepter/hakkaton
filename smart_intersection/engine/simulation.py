"""
SimulationEngine — physical simulation of a 4-way signalised intersection.

* deterministic for a given seed (all randomness goes through one random.Random)
* physics runs in fixed sub-steps (<= MAX_SUBSTEP) so high time_scale never breaks car following
* signal phases: 0 NS green | 1 NS yellow | 2 all-red | 3 EW green | 4 EW yellow | 5 all-red
* control_mode "auto": adaptive green (demand, pedestrian and emergency aware); "failsafe": fixed timing
"""
import asyncio
import math
import random
import time
import logging
from typing import Dict, List, Optional

from .models import Vehicle, Pedestrian, SimTrafficLight
from .world import build_world, ARM_LENGTH, STOP_LINE_DIST
from ..layout import Layout, default_layout, validate_layout
from .behaviors import update_vehicle, update_pedestrian, MIN_GAP_M
from .traffic_generator import SpawnManager
from .metrics import MetricsEngine

logger = logging.getLogger(__name__)

BASE_GREEN = 30.0
MIN_GREEN = 8.0
MAX_GREEN = 60.0
FAILSAFE_GREEN = 20.0
YELLOW_S = 3.0
ALL_RED_S = 3.0          # minimum all-red clearance
MAX_ALL_RED_S = 12.0     # hard cap while waiting for the box to clear
EMERGENCY_MIN_GREEN = 5.0
EMERGENCY_LOOKAHEAD_M = 60.0
DEMAND_LOOKAHEAD_M = 40.0
PED_MARGIN_S = 1.0
PED_PRIORITY_THRESHOLD = 5        # waiting pedestrians on one crosswalk that earn their phase priority (ground truth)
PED_LANES = {1: (-1.2, -0.75, -0.3), -1: (0.3, 0.75, 1.2)}   # opposite directions never share a lateral lane
PED_QUEUE_SPACING_M = 0.5
MAX_SUBSTEP = 0.1
MAX_QUEUE = 20
PERCEPTION_TIMEOUT_S = 3.0   # sim-seconds (scaled by time_scale) without camera data -> FAILSAFE
MIN_TIME_SCALE = 0.1
MAX_TIME_SCALE = 20.0

# (ns_state, ew_state, nominal_duration)
PHASES = [
    ("GREEN",  "RED",    BASE_GREEN),
    ("YELLOW", "RED",    YELLOW_S),
    ("RED",    "RED",    ALL_RED_S),
    ("RED",    "GREEN",  BASE_GREEN),
    ("RED",    "YELLOW", YELLOW_S),
    ("RED",    "RED",    ALL_RED_S),
]
GREEN_PHASE = {"ns": 0, "ew": 3}
GROUP_DIRS = {"ns": ("north", "south"), "ew": ("east", "west")}
OTHER = {"ns": "ew", "ew": "ns"}
CONTROL_MODES = ("auto", "failsafe")


def _group_of(direction: str) -> str:
    return "ns" if direction in ("north", "south") else "ew"


class SimulationEngine:
    def __init__(self, seed: int = 42, tick_rate: float = 10.0, layout: Optional[Layout] = None):
        self.layout = layout or default_layout()
        self.seed = seed
        self.tick_rate = tick_rate
        self.time_scale = 1.0
        self.control_mode = "auto"
        self.sim_time = 0.0
        self.status = "stopped"      # stopped / running / paused
        self.scenario = "normal"
        self.intersection_id = "SI-001"

        self._task: Optional[asyncio.Task] = None
        self._init_world()

    def _init_world(self):
        self._rng = random.Random(self.seed)
        self._vehicles: Dict[str, Vehicle] = {}
        self._pedestrians: Dict[str, Pedestrian] = {}
        self._lanes, self._lights, self._crossings = build_world(self.layout)
        self._phases = self._build_program()
        self._phase_index = 0
        self._phase_elapsed = 0.0
        self._overrides: Dict[str, str] = {}
        self.camera_failure = False           # virtual camera unplugged (scenario / API switch)
        self._perception: Optional[dict] = None  # latest camera-derived demand pushed by the main project
        self._perception_at = 0.0
        self._timeline: List[dict] = []
        self._timeline_idx = 0
        self._spawn = self._make_spawner()
        self._metrics = MetricsEngine()
        self._newly_passed = 0
        self._newly_crossed = 0
        self._finished_waits: List[float] = []
        self.sim_time = 0.0

    # ------------------------------------------------------------------ layout

    @property
    def sig(self):
        return self.layout.signal

    def _build_program(self) -> List[tuple]:
        """(ns_state, ew_state, duration). Adaptive keeps the classic 6-phase cycle; fixed runs the user's program."""
        sg = self.layout.signal
        if sg.mode == "fixed" and sg.program:
            return [(p.ns, p.ew, p.duration) for p in sg.program]
        return [("GREEN", "RED", sg.base_green), ("YELLOW", "RED", sg.yellow), ("RED", "RED", sg.all_red),
                ("RED", "GREEN", sg.base_green), ("RED", "YELLOW", sg.yellow), ("RED", "RED", sg.all_red)]

    @property
    def fixed_program(self) -> bool:
        return self.layout.signal.mode == "fixed" and bool(self.layout.signal.program)

    def _make_spawner(self) -> SpawnManager:
        t = self.layout.traffic
        sm = SpawnManager(spawn_rate=t.spawn_rate, ped_spawn_rate=t.ped_spawn_rate, type_probs=dict(t.type_probs),
                          rng=self._rng)
        arms = ("north", "south", "east", "west")
        sm.arm_weights = {a: (self.layout.arms[a].weight if self.layout.arms[a].enabled else 0.0) for a in arms}
        sm.arm_types = {a: {"bus": "bus", "tram": "tram"}.get(self.layout.arms[a].lane_type) for a in arms}
        return sm

    def set_layout(self, layout: Layout) -> None:
        """Replace the layout and restart the world (synchronous; use apply_layout while running)."""
        errors = validate_layout(layout)
        if errors:
            raise ValueError("; ".join(errors))
        self.layout = layout
        self.control_mode = "auto"
        self.time_scale = 1.0
        self._init_world()

    async def apply_layout(self, layout: Layout) -> None:
        await self.stop()
        self.set_layout(layout)

    # ------------------------------------------------------------------ public

    async def start(self):
        """Start, or resume when paused. Never creates a second loop."""
        if self._task is not None and not self._task.done():
            self.status = "running"
            return
        self.status = "running"
        self._task = asyncio.create_task(self._loop())
        logger.info("SimulationEngine started (seed=%d)", self.seed)

    async def stop(self):
        self.status = "stopped"
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def pause(self):
        if self.status == "running":
            self.status = "paused"

    async def resume(self):
        if self.status == "paused":
            self.status = "running"

    async def reset(self, seed: int = None):
        await self.stop()
        if seed is not None:
            self.seed = seed
        self.control_mode = "auto"
        self.time_scale = 1.0
        self._init_world()

    def configure(self, **kwargs):
        """Apply scenario / runtime settings. Unknown keys are ignored."""
        if "time_scale" in kwargs and kwargs["time_scale"] is not None:
            self.time_scale = max(MIN_TIME_SCALE, min(MAX_TIME_SCALE, float(kwargs["time_scale"])))
        if kwargs.get("scenario") is not None:
            self.scenario = kwargs["scenario"]
        if kwargs.get("camera_failure") is not None:
            self.camera_failure = bool(kwargs["camera_failure"])
        if kwargs.get("control_mode") is not None:
            if kwargs["control_mode"] not in CONTROL_MODES:
                raise ValueError(f"control_mode must be one of {CONTROL_MODES}")
            self.control_mode = kwargs["control_mode"]
        spawn_kwargs = {k: v for k, v in kwargs.items()
                        if k in ("spawn_rate", "ped_spawn_rate", "type_probs", "direction_probs") and v is not None}
        if spawn_kwargs:
            self._spawn.update_config(**spawn_kwargs)
        timeline = kwargs.get("timeline", kwargs.get("_timeline"))
        if timeline is not None:
            self._timeline = sorted(timeline, key=lambda e: e["at_sim_s"])
            self._timeline_idx = 0

    def set_light_state(self, light_id: str, state: str) -> bool:
        """Manual override. state 'AUTO' releases it. Returns False for an unknown light."""
        if light_id not in self._lights:
            return False
        if state == "AUTO":
            self._overrides.pop(light_id, None)
        else:
            self._overrides[light_id] = state
            self._lights[light_id].state = state
        return True

    def set_perception(self, payload: dict):
        """Camera-derived view of the intersection, produced by the vision pipeline of the main project."""
        self._perception = {
            "camera_ok": bool(payload.get("camera_ok", True)),
            "vehicles": dict(payload.get("vehicles", {})),
            "pedestrians_waiting": dict(payload.get("pedestrians_waiting", {})),
            "ped_priority": dict(payload.get("ped_priority", {})),
            "emergency": dict(payload.get("emergency", {})),
        }
        self._perception_at = self.sim_time

    def clear_perception(self):
        """Back to ground-truth demand (no camera pipeline attached)."""
        self._perception = None

    def perception_status(self) -> dict:
        stale = (self._perception is not None and
                 self.sim_time - self._perception_at > PERCEPTION_TIMEOUT_S * max(1.0, self.time_scale))
        return {
            "active": self._perception is not None,
            "camera_ok": bool(self._perception and self._perception["camera_ok"]),
            "stale": stale,
        }

    def _perception_usable(self) -> bool:
        p = self.perception_status()
        return p["active"] and p["camera_ok"] and not p["stale"] and not self.camera_failure

    def failsafe_reason(self) -> Optional[str]:
        """Why the signal plan is fixed-time right now, or None when adaptive control is available."""
        if self.control_mode == "failsafe":
            return "manual failsafe"
        if self.camera_failure:
            return "camera failure"
        p = self.perception_status()
        if p["active"] and not p["camera_ok"]:
            return "camera unavailable"
        if p["active"] and p["stale"]:
            return "camera data lost"
        return None

    def clear_overrides(self):
        self._overrides.clear()

    def spawn_vehicle(self, arm: str, vehicle_type: str = "car") -> Optional[Vehicle]:
        """Interactive: add one vehicle on `arm` now (refused when the arm is missing or its entry is blocked)."""
        if f"{arm}-in" not in self._lanes:
            return None
        v = self._spawn.make_vehicle(arm, vehicle_type, self.sim_time)
        return v if v is not None and self._try_place(v) else None

    def spawn_pedestrian(self, crossing_id: str) -> Optional[Pedestrian]:
        if crossing_id not in self._crossings:
            return None
        p = self._spawn.make_pedestrian(crossing_id, self.sim_time)
        self._assign_ped_slot(p)
        self._pedestrians[p.id] = p
        return p

    def spawn_emergency(self, direction: str = "north") -> Optional[Vehicle]:
        v = self._spawn.add_emergency_vehicle(self.sim_time, direction)
        if self._try_place(v):
            return v
        return None

    def advance(self, sim_seconds: float, dt: float = MAX_SUBSTEP):
        """Headless deterministic stepping (used by tests and scripts)."""
        steps = max(1, int(round(sim_seconds / dt)))
        for _ in range(steps):
            self._tick(dt)

    def get_state(self) -> dict:
        return {
            "sim_time": round(self.sim_time, 3),
            "real_time": round(time.time(), 3),
            "time_scale": self.time_scale,
            "status": self.status,
            "scenario": self.scenario,
            "intersection_id": self.intersection_id,
            "control_mode": self.control_mode,
            "layout_name": self.layout.name,
            "signal_mode": self.layout.signal.mode,
            "failsafe_reason": self.failsafe_reason(),
            "perception": self.perception_status(),
            "camera_failure": self.camera_failure,
            "phase": {"index": self._phase_index, "elapsed": round(self._phase_elapsed, 2)},
            "vehicles": [_vehicle_to_dict(v) for v in self._vehicles.values()],
            "pedestrians": [_ped_to_dict(p) for p in self._pedestrians.values()],
            "lights": [_light_to_dict(l) for l in self._lights.values()],
            "metrics": self._metrics.get_summary() or MetricsEngine.empty_snapshot(),
            "seed": self.seed,
        }

    # ---------------------------------------------------------------- internals

    async def _loop(self):
        last = time.monotonic()
        interval = 1.0 / self.tick_rate
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            real_dt = min(now - last, 0.5)
            last = now
            if self.status != "running":
                continue
            total = real_dt * self.time_scale
            n = max(1, math.ceil(total / MAX_SUBSTEP))
            for _ in range(n):
                self._tick(total / n)

    def _tick(self, dt: float):
        self.sim_time += dt
        self._newly_passed = 0
        self._newly_crossed = 0
        self._finished_waits = []

        self._apply_timeline()
        self._advance_phase(dt)
        self._apply_lights()
        self._spawn_traffic(dt)
        self._update_vehicles(dt)
        self._update_pedestrians(dt)

        self._metrics.update(
            sim_time=self.sim_time,
            vehicles=list(self._vehicles.values()),
            pedestrians=list(self._pedestrians.values()),
            lights=list(self._lights.values()),
            lanes=self._lanes,
            newly_passed=self._newly_passed,
            newly_crossed=self._newly_crossed,
            finished_waits=self._finished_waits,
        )

    # --- scenario timeline

    def _apply_timeline(self):
        while self._timeline_idx < len(self._timeline) and self._timeline[self._timeline_idx]["at_sim_s"] <= self.sim_time:
            entry = self._timeline[self._timeline_idx]
            self._timeline_idx += 1
            self.configure(**{k: v for k, v in entry.items() if k not in ("at_sim_s", "timeline", "_timeline")})

    # --- signal control

    def _advance_phase(self, dt: float):
        self._phase_elapsed += dt
        if self._should_end_phase():
            self._phase_index = (self._phase_index + 1) % len(self._phases)
            self._phase_elapsed = 0.0
            for light in self._lights.values():
                light.phase_switches += 1
                light.phase_index = self._phase_index
                light.phase_start_time = self.sim_time

    def _should_end_phase(self) -> bool:
        idx, elapsed, sg = self._phase_index, self._phase_elapsed, self.sig
        if self.fixed_program:                          # the user's program is executed exactly
            return elapsed >= self._phases[idx][2]
        if idx in (1, 4):
            return elapsed >= sg.yellow
        if idx in (2, 5):
            leaving = "ns" if idx == 2 else "ew"
            return elapsed >= MAX_ALL_RED_S or (elapsed >= sg.all_red and not self._group_in_conflict_zone(leaving))
        if self.failsafe_reason():
            return elapsed >= FAILSAFE_GREEN
        group = "ns" if idx == 0 else "ew"
        if elapsed >= sg.max_green:
            return True
        if self._peds_crossing_for(group):
            return False
        emerg_here, emerg_other = self._emergency_demand(group), self._emergency_demand(OTHER[group])
        if emerg_here:
            return False
        if emerg_other and elapsed >= EMERGENCY_MIN_GREEN:
            return True
        cur, other = self._demand(group), self._demand(OTHER[group])
        if elapsed >= sg.min_green and self._ped_priority(OTHER[group]):
            return True                                   # many pedestrians: give their phase priority
        if elapsed >= sg.min_green and cur == 0 and other > 0:
            return True
        if elapsed >= sg.base_green and other > 0:
            return True
        return False

    def _group_in_conflict_zone(self, group: str) -> bool:
        """True while a vehicle of `group` still occupies the box or the far crosswalk."""
        far_edge = ARM_LENGTH + STOP_LINE_DIST
        for v in self._vehicles.values():
            if _group_of(v.direction) != group:
                continue
            crossed = self._dist_to_stop(v) < 0
            if crossed and v.position_m - v.length_m / 2 < far_edge:
                return True
        return False

    def _dist_to_stop(self, v: Vehicle) -> float:
        lane = self._lanes[v.lane_id]
        return lane.stop_line_m - (v.position_m + v.length_m / 2)

    def _demand(self, group: str) -> int:
        """Vehicles queued/approaching on the group's arms plus pedestrians that need its green."""
        if self._perception_usable():
            p = self._perception
            return (sum(p["vehicles"].get(d, 0) for d in GROUP_DIRS[group]) +
                    sum(n for cid, n in p["pedestrians_waiting"].items()
                        if cid in self._crossings and self._crossing_needs(cid) == group))
        n = 0
        for v in self._vehicles.values():
            if _group_of(v.direction) != group:
                continue
            d = self._dist_to_stop(v)
            if v.state == "waiting" or -0.5 < d < DEMAND_LOOKAHEAD_M:
                n += 1
        for p in self._pedestrians.values():
            if p.state == "waiting_for_green" and self._crossing_needs(p.crossing_id) == group:
                n += 1
        return n

    def _ped_priority(self, group: str) -> bool:
        """A crowd waits on a crosswalk that only this group's green can serve."""
        if self._perception_usable():
            return any(flag for cid, flag in self._perception["ped_priority"].items()
                       if cid in self._crossings and self._crossing_needs(cid) == group)
        waiting: Dict[str, int] = {}
        for p in self._pedestrians.values():
            if p.state == "waiting_for_green":
                waiting[p.crossing_id] = waiting.get(p.crossing_id, 0) + 1
        return any(n >= PED_PRIORITY_THRESHOLD for cid, n in waiting.items() if self._crossing_needs(cid) == group)

    def _emergency_demand(self, group: str) -> bool:
        if self._perception_usable():
            return any(self._perception["emergency"].get(d) for d in GROUP_DIRS[group])
        for v in self._vehicles.values():
            if v.vehicle_type == "emergency" and _group_of(v.direction) == group:
                if -0.5 < self._dist_to_stop(v) < EMERGENCY_LOOKAHEAD_M:
                    return True
        return False

    def _crossing_needs(self, crossing_id: str) -> str:
        """A crosswalk on an arm can be used while the OTHER group has green."""
        return OTHER[_group_of(self._crossings[crossing_id].direction)]

    def _peds_crossing_for(self, group: str) -> bool:
        return any(p.state == "crossing" and self._crossing_needs(p.crossing_id) == group
                   for p in self._pedestrians.values())

    def _apply_lights(self):
        ns_state, ew_state, _ = self._phases[self._phase_index]
        for lid, light in self._lights.items():
            if lid in self._overrides:
                light.state = self._overrides[lid]
            else:
                light.state = ns_state if _group_of(light.direction) == "ns" else ew_state
            light.phase_index = self._phase_index
            light.phase_duration = self._phases[self._phase_index][2]

    # --- traffic

    def _spawn_traffic(self, dt: float):
        for v in self._spawn.try_spawn_vehicles(self.sim_time, dt):
            self._try_place(v)
        for p in self._spawn.try_spawn_pedestrians(self.sim_time, dt, list(self._crossings.keys())):
            self._assign_ped_slot(p)
            self._pedestrians[p.id] = p

    def _assign_ped_slot(self, p: Pedestrian):
        """Pick the emptiest lateral lane on the pedestrian's side and queue behind whoever is already there."""
        queued = [q for q in self._pedestrians.values()
                  if q.crossing_id == p.crossing_id and q.direction == p.direction
                  and q.state in ("walking_to_crossing", "waiting_for_green")]
        offset = min(PED_LANES[p.direction], key=lambda o: sum(1 for q in queued if q.offset == o))
        p.offset = offset
        p.stand_position = -PED_QUEUE_SPACING_M * sum(1 for q in queued if q.offset == offset)
        p.position_m = p.stand_position - 2.5

    def _try_place(self, v: Vehicle) -> bool:
        """Insert a new vehicle only if the entry point is free; adapt its speed to the leader."""
        lane = self._lanes.get(v.lane_id)
        if lane is None:
            return False
        v.position_m = lane.spawn_pos
        v.max_speed = min(v.max_speed, lane.speed_limit)
        # a short arm leaves little room before the stop line: never enter faster than the car could stop from
        room = max(lane.stop_line_m - (v.position_m + v.length_m / 2), 0.5)
        v.speed_mps = min(v.speed_mps, v.max_speed, math.sqrt(2 * 0.7 * v.decel * room))
        lane_vs = [x for x in self._vehicles.values() if x.lane_id == v.lane_id]
        if sum(1 for x in lane_vs if x.state == "waiting") >= MAX_QUEUE:
            return False
        gap = None
        for x in lane_vs:
            g = (x.position_m - x.length_m / 2) - (v.position_m + v.length_m / 2)
            if gap is None or g < gap:
                gap = g
        if gap is not None:
            if gap < MIN_GAP_M + 2.0:
                return False
            v.speed_mps = min(v.speed_mps, 0.9 * math.sqrt(2 * 0.7 * v.decel * (gap - MIN_GAP_M)))
        self._vehicles[v.id] = v
        return True

    def _crossing_occupied(self, direction: str) -> bool:
        cid = f"PC-{direction[0].upper()}"
        return any(p.crossing_id == cid and p.state == "crossing" for p in self._pedestrians.values())

    def _update_vehicles(self, dt: float):
        finished = []
        by_lane: Dict[str, List[Vehicle]] = {}
        for v in self._vehicles.values():
            by_lane.setdefault(v.lane_id, []).append(v)
        for lane_id, vs in by_lane.items():
            lane = self._lanes.get(lane_id)
            if lane is None:
                finished.extend(v.id for v in vs)
                continue
            light = self._lights.get(lane.traffic_light_id)
            light_state = light.state if light else "GREEN"
            if light_state == "GREEN" and self._crossing_occupied(lane.direction):
                light_state = "RED"
            # leaders first, so each follower sees the leader's already-updated position
            vs.sort(key=lambda x: -x.position_m)
            done = []
            for v in vs:
                if update_vehicle(v, dt, lane, light_state, done) == "finished":
                    finished.append(v.id)
                    self._newly_passed += 1
                    self._finished_waits.append(v.wait_time)
                else:
                    done.append(v)
        for vid in finished:
            self._vehicles.pop(vid, None)

    def _ped_signal(self, crossing_id: str) -> str:
        if self._overrides:
            return "RED"
        crossing_time = 12.0 / 1.4 + PED_MARGIN_S
        if self.fixed_program:
            return "GREEN" if self._fixed_window_ok(crossing_id, crossing_time) else "RED"
        need = self._crossing_needs(crossing_id)
        if self._phase_index != GREEN_PHASE[need]:
            return "RED"
        limit = FAILSAFE_GREEN if self.failsafe_reason() else self.sig.max_green
        return "GREEN" if self._phase_elapsed + crossing_time <= limit else "RED"

    def _fixed_window_ok(self, crossing_id: str, needed: float) -> bool:
        """User program: walk only while this arm's traffic is red for long enough and has cleared the crosswalk."""
        group = _group_of(self._crossings[crossing_id].direction)
        pick = (lambda ph: ph[0]) if group == "ns" else (lambda ph: ph[1])
        n, idx = len(self._phases), self._phase_index
        if pick(self._phases[idx]) != "RED" or self._group_in_conflict_zone(group):
            return False
        window = self._phases[idx][2] - self._phase_elapsed
        for k in range(1, n):
            ph = self._phases[(idx + k) % n]
            if pick(ph) != "RED":
                break
            window += ph[2]
        else:
            return True                                    # this group is never given green
        return window >= needed

    def _update_pedestrians(self, dt: float):
        finished = []
        signals = {cid: self._ped_signal(cid) for cid in self._crossings}
        for pid, ped in self._pedestrians.items():
            if update_pedestrian(ped, dt, signals.get(ped.crossing_id, "RED")) == "finished":
                finished.append(pid)
                self._newly_crossed += 1
        for pid in finished:
            self._pedestrians.pop(pid, None)


# ---------- serialization helpers ----------

def _vehicle_to_dict(v: Vehicle) -> dict:
    return {
        "id": v.id,
        "vehicle_type": v.vehicle_type,
        "lane_id": v.lane_id,
        "direction": v.direction,
        "position_m": round(v.position_m, 2),
        "speed_mps": round(v.speed_mps, 2),
        "state": v.state,
        "wait_time": round(v.wait_time, 2),
        "passed_intersection": v.passed_intersection,
    }


def _ped_to_dict(p: Pedestrian) -> dict:
    return {
        "id": p.id,
        "crossing_id": p.crossing_id,
        "state": p.state,
        "position_m": round(p.position_m, 2),
        "wait_time": round(p.wait_time, 2),
        "direction": p.direction,
        "offset": p.offset,
    }


def _light_to_dict(l: SimTrafficLight) -> dict:
    return {
        "id": l.id,
        "direction": l.direction,
        "state": l.state,
        "phase_index": l.phase_index,
        "phase_switches": l.phase_switches,
        "lane_ids": l.lane_ids,
    }
