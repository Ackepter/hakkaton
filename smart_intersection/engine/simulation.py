"""
SimulationEngine — physical simulation of a signalised intersection or a roundabout.

* deterministic for a given seed (all randomness goes through one random.Random)
* physics runs in fixed sub-steps (<= MAX_SUBSTEP) so high time_scale never breaks car following
* signals run in stages (layout.stages): three phases each: green | yellow | all-red. The classic crossroads has two
  stages, north-south and east-west: 0 NS green | 1 NS yellow | 2 all-red | 3 EW green | 4 EW yellow | 5 all-red.
  Turn lanes with left turns / u-turns get one protected stage per arm.
* vehicles follow geometry paths (straight, turn, u-turn, roundabout); where paths merge or cross, conflict cells are
  reserved in priority order (vehicles past their stop line first, then the older one)
* control_mode "auto": adaptive green (demand, pedestrian and emergency aware); "failsafe": fixed timing
"""
import asyncio
import math
import random
import time
import logging
from typing import Dict, List, Optional

from .models import Vehicle, Pedestrian, PedestrianCrossing, SimTrafficLight
from .world import build_world, ARM_LENGTH, STOP_LINE_DIST
from ..hardware.udp_matrix import UdpMatrixLight
from ..geometry import (blocked_crossings, build_paths, crossing_stages, divergence, needs_zones, path_zones,
                        pedestrian_xz, zone_region)
from ..layout import Layout, default_layout, lane_moves, roundabout_dims, stages as layout_stages, target_arm, validate_layout
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
PED_LANES = {1: (-1.2, -0.75, -0.3), -1: (0.3, 0.75, 1.2)}   # opposite directions never share a lateral lane
PED_QUEUE_SPACING_M = 0.5
MAX_SUBSTEP = 0.1
MAX_QUEUE = 20
PERCEPTION_TIMEOUT_S = 3.0   # sim-seconds (scaled by time_scale) without camera data -> FAILSAFE
RING_LOAD_LIMIT = 0.5        # share of the roundabout ring that may be taken before entries wait (no gridlock)
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


INTERSECTION_HALF_DEFAULT = 16.0


class SimulationEngine:
    def __init__(self, seed: int = 42, tick_rate: float = 10.0, layout: Optional[Layout] = None,
                 light_hardware: Optional[Dict[str, UdpMatrixLight]] = None):
        self.layout = layout or default_layout()
        self.seed = seed
        self.tick_rate = tick_rate
        self.time_scale = 1.0
        self.control_mode = "auto"
        self.sim_time = 0.0
        self.status = "stopped"      # stopped / running / paused
        self.scenario = "normal"
        self.intersection_id = "SI-001"
        # optional physical mirror (Task: parallel output to a real signal by IP), keyed by light id (e.g. "TL-N"):
        # `_default_light_hw` comes from config/traffic_lights.yaml (fixed wiring, survives layout changes); a layout
        # can override any of it per arm (Arm.light_ip/light_port, set in the constructor) — rebuilt on every
        # `_init_world` into `self._light_hw`, the one `_apply_lights` actually sends to. A light with neither stays
        # virtual-only.
        self._default_light_hw = light_hardware or {}
        self._layout_light_hw: Dict[str, UdpMatrixLight] = {}
        self._light_hw: Dict[str, UdpMatrixLight] = {}

        self._task: Optional[asyncio.Task] = None
        self._init_world()

    def _init_world(self):
        self._rng = random.Random(self.seed)
        self._vehicles: Dict[str, Vehicle] = {}
        self._pedestrians: Dict[str, Pedestrian] = {}
        self._lanes, self._lights, self._crossings = build_world(self.layout)
        self._rebuild_light_hardware()
        self._paths = build_paths(self.layout)
        self._roundabout = self.layout.junction == "roundabout"
        self._use_zones = needs_zones(self._paths, self.layout)
        self._zones, self._follow = path_zones(self._paths, zone_region(self.layout)) if self._use_zones else ({}, {})
        self._split: Dict[tuple, int] = {}
        self._stages = layout_stages(self.layout)
        self._crossing_stages = crossing_stages(self.layout)
        self._orphan_crossings = {cid for cid in self._crossings if not self._crossing_stages.get(cid)}
        self._blockers = {cid: [a for a in self.layout.enabled_arms() if cg.direction in blocked_crossings(self.layout, (a,))]
                          for cid, cg in self._crossings.items()}
        # additional sections this arm's light needs (Task: not every light is a plain 3-lamp head any more) — one per
        # turning movement any of its lanes actually use; a plain-straight arm (most preset types) gets none at all.
        self._arm_sections: Dict[str, List[str]] = {}
        for direction in self.layout.enabled_arms():
            moves = set()
            for i in range(self.layout.arms[direction].lanes_in):
                moves |= set(lane_moves(self.layout, direction, i))
            moves.discard("straight")
            if moves:
                self._arm_sections[direction] = sorted(moves)
        self._phases = self._build_program()
        self._phase_index = 0
        self._phase_elapsed = 0.0
        self._overrides: Dict[str, str] = {}
        self._ped_overrides: Dict[str, str] = {}
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
        self._ped_signals: Dict[str, str] = {}
        self._ped_occupied: set = set()
        self.sim_time = 0.0
        self._update_ped_signals()          # so a fresh / just-applied layout already shows correct lights and
        self._apply_lights()                # sections before the first tick, not only once the loop has run once

    # ------------------------------------------------------------------ layout

    @property
    def sig(self):
        return self.layout.signal

    def _build_program(self) -> List[tuple]:
        """
        [(lamp per arm, duration)]. Adaptive: three phases (green, yellow, all-red) per stage, in stage order.
        Fixed: the user program, phase by phase. A roundabout is metered the same way: its lights gate entry onto the
        ring, which still does its own give-way (path_zones / ring-load); an empty layout gets one endless dummy phase.
        """
        sg = self.layout.signal
        arms = self.layout.enabled_arms()
        if not arms:
            return [({}, 60.0)]
        if self.fixed_program:
            return [({a: p.lamp(a) for a in arms}, p.duration) for p in sg.program]
        out = []
        for stage in self._stages:
            out.append(({a: "GREEN" if a in stage else "RED" for a in arms}, sg.base_green))
            out.append(({a: "YELLOW" if a in stage else "RED" for a in arms}, sg.yellow))
            out.append(({a: "RED" for a in arms}, sg.all_red))
        return out

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
        for path in self._paths.values():
            sm.arm_paths.setdefault(path.arm, {}).setdefault(path.lane_index, []).append(path)
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

    def close_hardware(self) -> None:
        """Close every UDP socket this engine opened for a layout-defined light IP (not the ones injected at construction — the caller owns those)."""
        for hw in self._layout_light_hw.values():
            hw.close()
        self._layout_light_hw = {}

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

    def set_ped_light_state(self, crossing_id: str, state: str) -> bool:
        """Manual override of one pedestrian signal. state 'AUTO' releases it. Returns False for an unknown crossing."""
        if crossing_id not in self._crossings:
            return False
        if state == "AUTO":
            self._ped_overrides.pop(crossing_id, None)
        else:
            self._ped_overrides[crossing_id] = state
            self._crossings[crossing_id].state = state
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

    def camera_priority(self) -> dict:
        """Summarize which road users the healthy camera demand currently favors."""
        if not self._perception_usable():
            return {"camera_ok": False, "recipient": None, "vehicles": 0, "pedestrians": 0}
        p = self._perception
        vehicles = sum(n for arm, n in p["vehicles"].items() if arm in self.layout.enabled_arms())
        pedestrians = sum(n for cid, n in p["pedestrians_waiting"].items() if cid in self._crossings)
        if pedestrians > vehicles:
            recipient = "pedestrians"
        elif vehicles > pedestrians:
            recipient = "drivers"
        elif vehicles:
            recipient = "balanced"
        else:
            recipient = None
        return {"camera_ok": True, "recipient": recipient, "vehicles": vehicles, "pedestrians": pedestrians}

    def clear_overrides(self):
        self._overrides.clear()
        self._ped_overrides.clear()

    def spawn_vehicle(self, arm: str, vehicle_type: str = "car", lane: Optional[int] = None,
                      movement: Optional[str] = None) -> Optional[Vehicle]:
        """Interactive: add one vehicle on `arm` now (refused when the arm / lane / movement is missing or the entry is blocked)."""
        if f"{arm}-in" not in self._lanes:
            return None
        v = self._spawn.make_vehicle(arm, vehicle_type, self.sim_time, lane, movement)
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
            "camera_priority": self.camera_priority(),
            "camera_failure": self.camera_failure,
            "phase": {"index": self._phase_index, "elapsed": round(self._phase_elapsed, 2)},
            "junction": self.layout.junction,
            "stages": [list(st) for st in self._stages],
            "vehicles": [_vehicle_to_dict(v) for v in self._vehicles.values()],
            "pedestrians": [_ped_to_dict(p) for p in self._pedestrians.values()],
            "lights": [_light_to_dict(l) for l in self._lights.values()],
            "pedestrian_lights": [_ped_light_to_dict(c) for c in self._crossings.values()],
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
        self._update_ped_signals()          # before _apply_lights: sections read it to decide a turn arrow
        self._apply_lights()
        self._spawn_traffic(dt)
        self._update_vehicles(dt)
        self._update_pedestrians(dt)

        self._metrics.update(
            sim_time=self.sim_time,
            vehicles=list(self._vehicles.values()),
            pedestrians=list(self._pedestrians.values()),
            lights=list(self._lights.values()),
            ped_lights=list(self._crossings.values()),
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
            self._phase_index = self._next_phase(self._phase_index)
            self._phase_elapsed = 0.0
            for light in self._lights.values():
                light.phase_switches += 1
                light.phase_index = self._phase_index
                light.phase_start_time = self.sim_time

    def _next_phase(self, idx: int) -> int:
        nxt = (idx + 1) % len(self._phases)
        if not self.fixed_program and len(self._stages) > 2 and nxt % 3 == 0 and not self.failsafe_reason():
            demand = [self._demand(k) for k in range(len(self._stages))]
            if any(demand):                                  # protected stages: skip an arm nobody is waiting on
                k = nxt // 3
                while not demand[k]:
                    k = (k + 1) % len(self._stages)
                nxt = 3 * k
        return nxt

    def _should_end_phase(self) -> bool:
        idx, elapsed, sg = self._phase_index, self._phase_elapsed, self.sig
        if self.fixed_program:                          # the user program is executed exactly
            return elapsed >= self._phases[idx][1]
        stage, kind = divmod(idx, 3)
        if kind == 1:
            return elapsed >= sg.yellow
        if kind == 2:
            # all-red: wait for the stage that just had green to leave the box (phase 2 -> stage 0, phase 5 -> stage 1 ...)
            if (self._orphan_pedestrian_demand() or
                    any(p.state == "crossing" and p.crossing_id in self._orphan_crossings
                        for p in self._pedestrians.values())):
                return False
            return elapsed >= MAX_ALL_RED_S or (elapsed >= sg.all_red and not self._arms_in_conflict_zone(self._stages[stage]))
        if self.failsafe_reason():
            return elapsed >= FAILSAFE_GREEN
        # Camera-driven holding is only available with a healthy, fresh frame.
        # Otherwise keep the original timer plan (including camera-loss fallback).
        if not self._perception_usable() and elapsed >= sg.max_green:
            return True
        if self._roundabout and elapsed >= sg.max_green:
            return True
        if self._peds_crossing_for(stage):
            return False
        others = [k for k in range(len(self._stages)) if k != stage]
        if self._emergency_demand(stage):
            return False
        if elapsed >= EMERGENCY_MIN_GREEN and any(self._emergency_demand(k) for k in others):
            return True
        cur, other = self._demand(stage), sum(self._demand(k) for k in others)
        orphan_peds = self._orphan_pedestrian_demand()
        other += orphan_peds
        if elapsed >= sg.min_green and (any(self._ped_priority(k) for k in others) or
                                        orphan_peds > self._total_vehicle_demand()):
            return True                                   # the larger pedestrian queue gets priority
        if elapsed >= sg.max_green and other > 0:
            return True
        if elapsed >= sg.min_green and cur == 0 and other > 0:
            return True
        if elapsed >= sg.base_green and other > 0:
            return True
        return False

    def _arms_of(self, group) -> tuple:
        if group == "ns":
            return ("north", "south")
        if group == "ew":
            return ("east", "west")
        return tuple(group)

    def _group_in_conflict_zone(self, group) -> bool:
        """True while a vehicle of the group ('ns' / 'ew' or a tuple of arms) still occupies the box or the far crosswalk."""
        return self._arms_in_conflict_zone(self._arms_of(group))

    def _arms_in_conflict_zone(self, arms) -> bool:
        for v in self._vehicles.values():
            if v.direction not in arms:
                continue
            crossed = self._dist_to_stop(v) < 0
            if crossed and v.position_m - v.length_m / 2 < self._far_edge(v):
                return True
        return False

    def _far_edge(self, v: Vehicle) -> float:
        """Path coordinate where the vehicle has left the box and the crosswalk behind it."""
        path = self._paths.get(v.path_id)
        return (path.box_exit_s if path else ARM_LENGTH + INTERSECTION_HALF_DEFAULT) + 5.0

    def _dist_to_stop(self, v: Vehicle) -> float:
        lane = self._lanes[v.lane_id]
        return lane.stop_line_m - (v.position_m + v.length_m / 2)

    def _serves(self, stage: int, cid: str) -> bool:
        return stage in self._crossing_stages.get(cid, ())

    def _vehicle_demand(self, stage: int) -> int:
        arms = self._stages[stage]
        if self._perception_usable():
            return sum(self._perception["vehicles"].get(d, 0) for d in arms)
        return sum(1 for v in self._vehicles.values()
                   if v.direction in arms and (v.state == "waiting" or
                   -0.5 < self._dist_to_stop(v) < DEMAND_LOOKAHEAD_M))

    def _pedestrian_demand(self, stage: int) -> int:
        if self._perception_usable():
            return sum(n for cid, n in self._perception["pedestrians_waiting"].items()
                       if cid in self._crossings and self._serves(stage, cid))
        return sum(1 for p in self._pedestrians.values()
                   if p.state == "waiting_for_green" and self._serves(stage, p.crossing_id))

    def _orphan_pedestrian_demand(self) -> int:
        """Waiting pedestrians whose crossing has no vehicle stage that can safely serve it."""
        if self._perception_usable():
            return sum(n for cid, n in self._perception["pedestrians_waiting"].items()
                       if cid in self._orphan_crossings)
        return sum(1 for p in self._pedestrians.values()
                   if p.state == "waiting_for_green" and p.crossing_id in self._orphan_crossings)

    def _total_vehicle_demand(self) -> int:
        if self._perception_usable():
            return sum(n for arm, n in self._perception["vehicles"].items()
                       if arm in self.layout.enabled_arms())
        return sum(self._vehicle_demand(k) for k in range(len(self._stages)))

    def _demand(self, stage: int) -> int:
        """Vehicles queued/approaching on the stage arms plus pedestrians that need its green."""
        return self._vehicle_demand(stage) + self._pedestrian_demand(stage)

    def _ped_priority(self, stage: int) -> bool:
        """Give pedestrians priority only when their total queue exceeds the vehicle queue."""
        if not self._pedestrian_demand(stage):
            return False
        if self._perception_usable():
            pedestrians = sum(n for cid, n in self._perception["pedestrians_waiting"].items()
                              if cid in self._crossings)
            return pedestrians > self._total_vehicle_demand()
        # Keep the established local-simulation queue threshold. Camera mode
        # compares measured totals; the local model does not have equivalent
        # camera observations and must not let a moving roundabout queue make
        # pedestrian priority oscillate from tick to tick.
        return any(sum(p.state == "waiting_for_green" and p.crossing_id == cid
                       for p in self._pedestrians.values()) >= 5
                   for cid in self._crossings if self._serves(stage, cid))

    def _emergency_demand(self, stage: int) -> bool:
        arms = self._stages[stage]
        if self._perception_usable():
            return any(self._perception["emergency"].get(d) for d in arms)
        for v in self._vehicles.values():
            if v.vehicle_type == "emergency" and v.direction in arms:
                if -0.5 < self._dist_to_stop(v) < EMERGENCY_LOOKAHEAD_M:
                    return True
        return False

    def _peds_crossing_for(self, stage: int) -> bool:
        return any(p.state == "crossing" and self._serves(stage, p.crossing_id) for p in self._pedestrians.values())

    def _rebuild_light_hardware(self) -> None:
        """Layout-defined IPs (Arm.light_ip) win over config/traffic_lights.yaml for the same light id."""
        for hw in self._layout_light_hw.values():
            hw.close()
        self._layout_light_hw = {}
        for direction in self.layout.enabled_arms():
            arm = self.layout.arms[direction]
            if arm.light_ip:
                lid = f"TL-{direction[0].upper()}"
                self._layout_light_hw[lid] = UdpMatrixLight(lid, (arm.light_ip, arm.light_port))
        self._light_hw = {**self._default_light_hw, **self._layout_light_hw}

    def _apply_lights(self):
        states, duration = self._phases[self._phase_index]
        for lid, light in self._lights.items():
            if lid in self._overrides:
                light.state = self._overrides[lid]
            else:
                light.state = states.get(light.direction, "RED")
            light.phase_index = self._phase_index
            light.phase_duration = duration
            light.sections = self._light_sections(light.direction, light.state)
            hw = self._light_hw.get(lid)
            if hw is not None:
                hw.send(light.state)          # mirror the main lamp to the real signal; this never feeds back

    def _light_sections(self, direction: str, main_state: str) -> Dict[str, str]:
        """One extra arrow lamp per turning movement this arm's lanes use. RED/YELLOW mirrors the main lamp; on GREEN a
        turn still goes RED on its own while the crosswalk it turns into is walked or about to be (`_ped_occupied` —
        the exact crossings vehicles already yield to in `_update_vehicles`, so a section never shows a movement as
        safer than it really is)."""
        moves = self._arm_sections.get(direction)
        if not moves:
            return {}
        if main_state != "GREEN":
            return {m: main_state for m in moves}
        return {m: ("RED" if f"PC-{target_arm(direction, m)[0].upper()}" in self._ped_occupied else "GREEN") for m in moves}

    # --- traffic

    def _spawn_traffic(self, dt: float):
        for v in self._spawn.try_spawn_vehicles(self.sim_time, dt):
            self._try_place(v)
        for p in self._spawn.try_spawn_pedestrians(self.sim_time, dt, list(self._crossings.keys())):
            self._assign_ped_slot(p)
            self._pedestrians[p.id] = p

    def _assign_ped_slot(self, p: Pedestrian):
        """Pick the emptiest lateral lane on the pedestrian side and queue behind whoever is already there."""
        queued = [q for q in self._pedestrians.values()
                  if q.crossing_id == p.crossing_id and q.direction == p.direction
                  and q.state in ("walking_to_crossing", "waiting_for_green")]
        offset = min(PED_LANES[p.direction], key=lambda o: sum(1 for q in queued if q.offset == o))
        occupied = {round(-q.stand_position / PED_QUEUE_SPACING_M) for q in queued if q.offset == offset}
        slot = 0
        while slot in occupied:
            slot += 1
        p.offset = offset
        p.stand_position = -PED_QUEUE_SPACING_M * slot
        p.position_m = p.stand_position - 2.5
        p.crossing_width = self._crossings[p.crossing_id].geo["width"]
        self._sync_ped_xy(p)

    def _sync_ped_xy(self, p: Pedestrian) -> None:
        cg = self._crossings[p.crossing_id].geo
        p.x, p.z = pedestrian_xz(cg, p.position_m, p.direction, p.offset)

    def _sync_xy(self, v: Vehicle) -> None:
        path = self._paths.get(v.path_id)
        if path is not None:
            v.x, v.z, v.heading = path.pose(v.position_m, v.length_m)

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
        self._sync_xy(v)
        self._vehicles[v.id] = v
        return True

    def _crossing_occupied(self, direction: str) -> bool:
        cid = f"PC-{direction[0].upper()}"
        return any(p.crossing_id == cid and p.state == "crossing" for p in self._pedestrians.values())

    # --- conflict zones: who may enter which part of the box

    def _commit_s(self, v: Vehicle, path) -> float:
        """Path coordinate the front must pass before the vehicle counts as committed (holds priority): the stop line, the
        same point its light gates — a vehicle that got its green and crossed it outranks one still waiting for green."""
        return self._lanes[v.lane_id].stop_line_m

    def _zone_walls(self, vehicles: List[Vehicle]) -> Dict[str, float]:
        """
        Where a vehicle must stop because another one is in, or is about to enter, a zone the two routes share.

        A vehicle that is already inside its zone, or is too close to stop before it, is never asked to give way. Otherwise
        it gives way to a vehicle inside its own zone, and to one that is within its braking distance + 4 m of the zone when
        it has priority (past the stop line / on the ring first, then the older vehicle). Result: distance from the front
        bumper to the zone entrance ('wall').
        """
        by_path: Dict[str, List[Vehicle]] = {}
        info = {}
        for v in vehicles:
            path = self._paths.get(v.path_id)
            if path is None:
                continue
            front = v.position_m + v.length_m / 2
            info[v.id] = (front, v.speed_mps ** 2 / (2 * 0.7 * v.decel), (0 if front > self._commit_s(v, path) else 1, v.seq))
            by_path.setdefault(v.path_id, []).append(v)
        walls: Dict[str, float] = {}
        for v in vehicles:
            foes = self._zones.get(v.path_id)
            if not foes:
                continue
            front, brake, prio = info[v.id]
            rear = front - v.length_m
            wall = None
            for other, a0, a1, b0, b1 in foes:
                if rear >= a1 + 0.5 or front > a0 - 0.5 or a0 - front < brake + 0.5:
                    continue                                       # cleared, inside, or unable to stop: not my turn to wait
                for w in by_path.get(other, ()):
                    wfront, wbrake, wprio = info[w.id]
                    if wfront - w.length_m >= b1 + 0.5:
                        continue                                   # that vehicle has cleared the zone
                    inside = wfront > b0 - 0.5 or b0 - wfront < wbrake + 0.5
                    if inside or (b0 - wfront < wbrake + 4.0 and wprio < prio):
                        gap = max(0.0, a0 - front)
                        wall = gap if wall is None else min(wall, gap)
            if wall is not None:
                walls[v.id] = wall
        if self._roundabout:                                       # a full ring would lock up: entries wait outside
            limit = RING_LOAD_LIMIT * self._ring_length()
            load = self._ring_load(vehicles)
            entering = []
            for v in vehicles:
                path = self._paths.get(v.path_id)
                front = v.position_m + v.length_m / 2
                if path is not None and path.box_entry_s - 10.0 < front < path.box_entry_s - 0.5:
                    entering.append((v.seq, v, path, front))
            for _, v, path, front in sorted(entering, key=lambda t: t[0]):
                if load + v.length_m + 3.0 <= limit:
                    load += v.length_m + 3.0                        # admitted: it will take its share of the ring
                else:
                    walls[v.id] = min(walls.get(v.id, 1e9), max(0.0, path.box_entry_s - 1.5 - front))
        return walls

    def _ring_length(self) -> float:
        return 2 * math.pi * roundabout_dims(self.layout)["ring_center"]

    def _ring_load(self, vehicles: List[Vehicle]) -> float:
        """Metres of the ring taken by vehicles that are on it (length plus a safety gap each)."""
        load = 0.0
        for v in vehicles:
            path = self._paths.get(v.path_id)
            if path is not None and v.position_m + v.length_m / 2 > path.box_entry_s and v.position_m - v.length_m / 2 < path.box_exit_s:
                load += v.length_m + 3.0
        return load

    def _divergence(self, a: str, b: str) -> int:
        """Where two routes of one lane part; until then their vehicles follow each other in a single file."""
        key = (a, b) if a < b else (b, a)
        if key not in self._split:
            pa, pb = self._paths.get(a), self._paths.get(b)
            self._split[key] = divergence(pa, pb) if pa is not None and pb is not None else 0
        return self._split[key]

    def _stretch_gap(self, v: Vehicle, by_path: Dict[str, List[Vehicle]]) -> Optional[float]:
        """Gap to a vehicle ahead on a stretch the two routes share (merging traffic, the ring of a roundabout)."""
        front = v.position_m + v.length_m / 2
        best = None
        for other, a0, a1, b0, b1, off in self._follow.get(v.path_id, ()):
            if front <= a0:
                continue                                           # not on the shared stretch yet
            for w in by_path.get(other, ()):
                ws = w.position_m - off                            # w on my axis
                if w is v or ws <= v.position_m or ws - w.length_m / 2 > a1 + 1.0 or w.position_m + w.length_m / 2 <= b0:
                    continue
                gap = (ws - w.length_m / 2) - front
                if best is None or gap < best:
                    best = gap
        return best

    def _exit_gap(self, v: Vehicle, path, by_exit: Dict[str, list]) -> Optional[float]:
        """Gap to a vehicle of another route ahead of us on the same exit lane (traffic that merged keeps its distance)."""
        half = v.length_m / 2
        ev = v.position_m - path.box_exit_s
        if ev + half < 6.0:
            return None                                            # still in the box: the merge zones decide there
        best = None
        for x, ex in by_exit.get(path.exit_key, ()):
            if x is v or x.lane_id == v.lane_id or ex <= ev:
                continue
            gap = (ex - x.length_m / 2) - (ev + half)
            if best is None or gap < best:
                best = gap
        return best

    def _update_vehicles(self, dt: float):
        finished = []
        by_lane: Dict[str, List[Vehicle]] = {}
        for v in self._vehicles.values():
            by_lane.setdefault(v.lane_id, []).append(v)
        walls: Dict[str, float] = {}
        by_exit: Dict[str, list] = {}
        by_path: Dict[str, List[Vehicle]] = {}
        if self._use_zones:
            walls = self._zone_walls(list(self._vehicles.values()))
            for v in self._vehicles.values():
                by_path.setdefault(v.path_id, []).append(v)
            for v in self._vehicles.values():
                path = self._paths.get(v.path_id)
                if path is not None:
                    by_exit.setdefault(path.exit_key, []).append((v, v.position_m - path.box_exit_s))
        # crosswalks vehicles must give way at: people are on them, or about to step out on their own green (turning
        # traffic yields) — the same set a turn's arrow section already reflects, see `_light_sections`.
        occupied = self._ped_occupied
        for lane_id, vs in by_lane.items():
            lane = self._lanes.get(lane_id)
            if lane is None:
                finished.extend(v.id for v in vs)
                continue
            light = self._lights.get(lane.traffic_light_id)
            light_state = light.state if light else "GREEN"
            if light_state == "GREEN" and self._crossing_occupied(lane.direction):
                light_state = "RED"
            # leaders first, so each follower sees the leader already-updated position
            vs.sort(key=lambda x: -x.position_m)
            done = []
            for v in vs:
                path = self._paths.get(v.path_id)
                ahead, extra = done, None
                if self._use_zones and path is not None:
                    vfront = v.position_m + v.length_m / 2
                    ahead = [x for x in done if x.path_id == v.path_id or vfront < self._divergence(v.path_id, x.path_id)]
                    extra = walls.get(v.id)
                    for eg in (self._exit_gap(v, path, by_exit), self._stretch_gap(v, by_path)):
                        if eg is not None and (extra is None or eg < extra):
                            extra = eg
                if occupied and path is not None and f"PC-{path.exit_arm[0].upper()}" in occupied and not path.dead_end:
                    stop_at = path.box_exit_s + 0.5                   # yield to people on the crosswalk we turn into
                    front = v.position_m + v.length_m / 2
                    if front < stop_at:
                        cw = stop_at - front
                        extra = cw if extra is None else min(extra, cw)
                if update_vehicle(v, dt, lane, light_state, ahead, path=path, extra_gap=extra,
                                  yield_rule=self._use_zones) == "finished":
                    finished.append(v.id)
                    self._newly_passed += 1
                    self._finished_waits.append(v.wait_time)
                else:
                    self._sync_xy(v)
                    done.append(v)
        for vid in finished:
            self._vehicles.pop(vid, None)

    def _crossing_busy(self, crossing_id: str) -> bool:
        """A vehicle is on the crosswalk, or too close to it to stop: nobody may step out yet."""
        arm = self._crossings[crossing_id].direction
        for v in self._vehicles.values():
            path = self._paths.get(v.path_id)
            if path is None:
                continue
            if path.exit_arm == arm and not path.dead_end:
                lo, hi = path.box_exit_s + 1.0, path.box_exit_s + 4.0             # the band on the exit road
            elif v.direction == arm:
                lo, hi = path.box_entry_s - 4.0, path.box_entry_s - 1.0           # the band on the inbound road
            else:
                continue
            front, rear = v.position_m + v.length_m / 2, v.position_m - v.length_m / 2
            if lo < front and rear <= hi:
                return True                                                          # on the crosswalk
            if v.speed_mps > 0.3 and front >= lo - (v.speed_mps ** 2 / (2 * 0.7 * v.decel) + 3.0) and rear <= hi:
                return True                                                          # rolling towards it, cannot stop any more
        return False

    def _update_ped_signals(self) -> None:
        """Decide every pedestrian light, and update the stateful signal object (Task 16: state + switch count)."""
        self._ped_signals = {}
        for cid, crossing in self._crossings.items():
            state = self._ped_overrides.get(cid) or self._ped_signal(cid)
            self._ped_signals[cid] = state
            if crossing.state != state:
                crossing.phase_switches += 1
            crossing.state = state
            crossing.waiting_peds = sum(1 for p in self._pedestrians.values()
                                        if p.crossing_id == cid and p.state == "waiting_for_green")
            crossing.crossing_peds = sum(1 for p in self._pedestrians.values()
                                         if p.crossing_id == cid and p.state == "crossing")
        # crosswalks a vehicle must yield to: someone already on it, or about to step out on their own green
        self._ped_occupied = {p.crossing_id for p in self._pedestrians.values()
                              if p.state == "crossing" or (p.state == "waiting_for_green"
                                                           and self._ped_signals.get(p.crossing_id) == "GREEN")}

    def _ped_signal(self, crossing_id: str) -> str:
        if self._overrides or (self._use_zones and self._crossing_busy(crossing_id)):
            return "RED"
        crossing_time = self._crossings[crossing_id].geo["width"] / 1.4 + PED_MARGIN_S
        if (crossing_id in self._orphan_crossings and self._phase_index % 3 == 2 and
                not self._arms_in_conflict_zone(self._blockers[crossing_id])):
            if self._perception_usable():
                waiting = self._perception["pedestrians_waiting"].get(crossing_id, 0)
            else:
                waiting = any(p.crossing_id == crossing_id and p.state == "waiting_for_green"
                              for p in self._pedestrians.values())
            return "GREEN" if waiting else "RED"
        if self.fixed_program:
            return "GREEN" if self._fixed_window_ok(crossing_id, crossing_time) else "RED"
        stage, kind = divmod(self._phase_index, 3)
        if kind != 0 or not self._serves(stage, crossing_id):
            return "RED"
        limit = FAILSAFE_GREEN if self.failsafe_reason() else self.sig.max_green
        return "GREEN" if self._phase_elapsed + crossing_time <= limit else "RED"

    def _fixed_window_ok(self, crossing_id: str, needed: float) -> bool:
        """User program: walk only while the arms that drive over this crosswalk are red for long enough and have cleared it."""
        blockers = self._blockers[crossing_id]
        closed = lambda ph: any(ph[0].get(a, "RED") != "RED" for a in blockers)
        n, idx = len(self._phases), self._phase_index
        if closed(self._phases[idx]) or self._arms_in_conflict_zone(blockers):
            return False
        window = self._phases[idx][1] - self._phase_elapsed
        for k in range(1, n):
            ph = self._phases[(idx + k) % n]
            if closed(ph):
                break
            window += ph[1]
        else:
            return True                                    # these arms are never given green
        return window >= needed

    def _update_pedestrians(self, dt: float):
        finished = []
        signals = self._ped_signals
        for pid, ped in self._pedestrians.items():
            if update_pedestrian(ped, dt, signals.get(ped.crossing_id, "RED")) == "finished":
                finished.append(pid)
                self._newly_crossed += 1
            else:
                self._sync_ped_xy(ped)
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
        "movement": v.movement,
        "lane_index": v.lane_index,
        "x": round(v.x, 2),
        "z": round(v.z, 2),
        "heading": round(v.heading, 3),
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
        "x": round(p.x, 2),
        "z": round(p.z, 2),
    }


def _light_to_dict(l: SimTrafficLight) -> dict:
    return {
        "id": l.id,
        "direction": l.direction,
        "state": l.state,
        "phase_index": l.phase_index,
        "phase_switches": l.phase_switches,
        "lane_ids": l.lane_ids,
        "sections": dict(l.sections),
    }


def _ped_light_to_dict(c: PedestrianCrossing) -> dict:
    return {
        "id": c.id,
        "direction": c.direction,
        "state": c.state,
        "phase_switches": c.phase_switches,
        "waiting_peds": c.waiting_peds,
        "crossing_peds": c.crossing_peds,
    }
