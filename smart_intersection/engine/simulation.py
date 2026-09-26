"""
SimulationEngine — main asyncio tick loop for the Smart Intersection.
Deterministic with seed=42 by default.
"""
import asyncio
import random
import time
import logging
from typing import Dict, List, Optional

from .models import Vehicle, Pedestrian, SimTrafficLight
from .world import build_world
from .behaviors import update_vehicle, update_pedestrian
from .traffic_generator import SpawnManager
from .metrics import MetricsEngine

logger = logging.getLogger(__name__)

# Phase timing constants (seconds of sim time)
NS_GREEN_DURATION = 30.0
NS_YELLOW_DURATION = 3.0
EW_GREEN_DURATION = 30.0
EW_YELLOW_DURATION = 3.0

# Phase sequence: (ns_state, ew_state, duration)
PHASES = [
    ("GREEN",  "RED",    NS_GREEN_DURATION),
    ("YELLOW", "RED",    NS_YELLOW_DURATION),
    ("RED",    "GREEN",  EW_GREEN_DURATION),
    ("RED",    "YELLOW", EW_YELLOW_DURATION),
]


class SimulationEngine:
    def __init__(self, seed: int = 42, tick_rate: float = 10.0):
        self.seed = seed
        self.tick_rate = tick_rate        # ticks per real second
        self.time_scale = 1.0             # simulation speed multiplier
        self._rng = random.Random(seed)

        self.sim_time: float = 0.0
        self.status: str = "stopped"      # stopped/running/paused
        self.scenario: str = "normal"
        self.intersection_id: str = "SI-001"

        self._vehicles: Dict[str, Vehicle] = {}
        self._pedestrians: Dict[str, Pedestrian] = {}

        self._lanes, self._lights, self._crossings = build_world()
        self._phase_index: int = 0
        self._phase_elapsed: float = 0.0

        self._spawn = SpawnManager(rng=self._rng)
        self._metrics = MetricsEngine()

        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._newly_passed = 0
        self._newly_crossed = 0

    # ------------------------------------------------------------------ public

    async def start(self):
        if self.status == "running":
            return
        self.status = "running"
        self._task = asyncio.create_task(self._loop())
        logger.info("SimulationEngine started (seed=%d)", self.seed)

    async def stop(self):
        self.status = "stopped"
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SimulationEngine stopped")

    async def pause(self):
        self.status = "paused"

    async def resume(self):
        if self.status == "paused":
            self.status = "running"

    async def reset(self, seed: int = None):
        await self.stop()
        if seed is not None:
            self.seed = seed
        self._rng = random.Random(self.seed)
        self.sim_time = 0.0
        self._vehicles.clear()
        self._pedestrians.clear()
        self._lanes, self._lights, self._crossings = build_world()
        self._phase_index = 0
        self._phase_elapsed = 0.0
        self._spawn = SpawnManager(rng=self._rng)
        self._metrics.reset()
        self._newly_passed = 0
        self._newly_crossed = 0
        self.status = "stopped"

    def configure(self, **kwargs):
        """Update spawn rates or time_scale."""
        if "time_scale" in kwargs:
            self.time_scale = float(kwargs["time_scale"])
        if "scenario" in kwargs:
            self.scenario = kwargs["scenario"]
        spawn_kwargs = {k: v for k, v in kwargs.items()
                       if k in ("spawn_rate", "ped_spawn_rate", "type_probs", "direction_probs")}
        if spawn_kwargs:
            self._spawn.update_config(**spawn_kwargs)

    def set_light_state(self, light_id: str, state: str):
        """Manual override of a traffic light."""
        if light_id in self._lights:
            self._lights[light_id].state = state

    def get_state(self) -> dict:
        """Serializable snapshot for XML export and API."""
        vehicles = [_vehicle_to_dict(v) for v in self._vehicles.values()]
        pedestrians = [_ped_to_dict(p) for p in self._pedestrians.values()]
        lights = [_light_to_dict(l) for l in self._lights.values()]
        metrics = self._metrics.get_summary() or {
            "sim_time": self.sim_time,
            "vehicles_active": len(self._vehicles),
            "vehicles_waiting": 0,
            "passed_total": 0,
        }
        return {
            "sim_time": round(self.sim_time, 3),
            "real_time": round(time.time(), 3),
            "time_scale": self.time_scale,
            "status": self.status,
            "scenario": self.scenario,
            "intersection_id": self.intersection_id,
            "vehicles": vehicles,
            "pedestrians": pedestrians,
            "lights": lights,
            "metrics": metrics,
            "seed": self.seed,
        }

    # ---------------------------------------------------------------- internals

    async def _loop(self):
        dt_real = 1.0 / self.tick_rate
        while self.status in ("running", "paused"):
            await asyncio.sleep(dt_real)
            if self.status != "running":
                continue
            async with self._lock:
                dt_sim = dt_real * self.time_scale
                self._tick(dt_sim)

    def _tick(self, dt: float):
        self.sim_time += dt
        self._newly_passed = 0
        self._newly_crossed = 0

        # 1. Advance traffic lights (phase FSM)
        self._phase_elapsed += dt
        ns_state, ew_state, phase_dur = PHASES[self._phase_index]
        if self._phase_elapsed >= phase_dur:
            self._phase_elapsed -= phase_dur
            self._phase_index = (self._phase_index + 1) % len(PHASES)
            ns_state, ew_state, phase_dur = PHASES[self._phase_index]
            # record phase switch
            for lid, light in self._lights.items():
                light.phase_switches += 1

        for lid, light in self._lights.items():
            if light.direction in ("north", "south"):
                light.state = ns_state
            else:
                light.state = ew_state

        # 2. Spawn new vehicles
        new_vehicles = self._spawn.try_spawn_vehicles(self.sim_time, dt)
        for v in new_vehicles:
            # Reject if lane has too many (max 20 waiting)
            lane_count = sum(1 for x in self._vehicles.values()
                             if x.lane_id == v.lane_id and x.state == "waiting")
            if lane_count < 20:
                self._vehicles[v.id] = v

        # 3. Spawn pedestrians
        crossing_ids = list(self._crossings.keys())
        new_peds = self._spawn.try_spawn_pedestrians(self.sim_time, dt, crossing_ids)
        for p in new_peds:
            self._pedestrians[p.id] = p

        # 4. Update vehicles
        to_remove_v = []
        for vid, vehicle in self._vehicles.items():
            lane = self._lanes.get(vehicle.lane_id)
            if not lane:
                to_remove_v.append(vid)
                continue
            light = self._lights.get(lane.traffic_light_id)
            light_state = light.state if light else "GREEN"
            # vehicles ahead (same lane, closer to stop line)
            ahead = [v for v in self._vehicles.values()
                     if v.lane_id == vehicle.lane_id
                     and v.id != vehicle.id
                     and v.position_m > vehicle.position_m]
            result = update_vehicle(vehicle, dt, lane, light_state, ahead)
            if result == "finished":
                to_remove_v.append(vid)
                self._newly_passed += 1

        for vid in to_remove_v:
            self._vehicles.pop(vid, None)

        # 5. Update pedestrians
        to_remove_p = []
        for pid, ped in self._pedestrians.items():
            crossing = self._crossings.get(ped.crossing_id)
            if not crossing:
                to_remove_p.append(pid)
                continue
            light = self._lights.get(crossing.traffic_light_id)
            # Pedestrians get GREEN when perpendicular traffic is RED
            # i.e., NS crossings when EW is green, and vice versa
            light_dir = crossing.direction
            if light_dir in ("north", "south"):
                ped_signal = "GREEN" if PHASES[self._phase_index][1] == "GREEN" else "RED"
            else:
                ped_signal = "GREEN" if PHASES[self._phase_index][0] == "GREEN" else "RED"

            result = update_pedestrian(ped, dt, ped_signal)
            if result == "finished":
                to_remove_p.append(pid)
                self._newly_crossed += 1

        for pid in to_remove_p:
            self._pedestrians.pop(pid, None)

        # 6. Update metrics
        self._metrics.update(
            sim_time=self.sim_time,
            vehicles=list(self._vehicles.values()),
            pedestrians=list(self._pedestrians.values()),
            lights=list(self._lights.values()),
            lanes=self._lanes,
            newly_passed=self._newly_passed,
            newly_crossed=self._newly_crossed,
        )


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
