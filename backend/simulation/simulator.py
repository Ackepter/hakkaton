import asyncio
import random
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from ..config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class Vehicle:
    id: str
    vehicle_type: str  # car, truck, bus, tram, emergency
    lane_id: str
    spawn_time: float
    wait_time: float = 0.0
    passed: bool = False


@dataclass
class Pedestrian:
    id: str
    crossing_id: str
    spawn_time: float
    wait_time: float = 0.0
    passed: bool = False


@dataclass
class LaneQueue:
    lane_id: str
    vehicles: List[Vehicle] = field(default_factory=list)
    throughput: int = 0  # total passed


class SimulationEngine:
    """
    Generates virtual traffic participants for testing without a real camera.
    Simulates vehicle queues, pedestrian crossings, and flow metrics.
    """

    VEHICLE_TYPES = ["car", "car", "car", "car", "truck", "bus"]
    SPAWN_PROBABILITIES = {
        "car": 0.65,
        "truck": 0.15,
        "bus": 0.10,
        "emergency": 0.02,
    }

    def __init__(self):
        self._running = False
        self._lane_queues: Dict[str, LaneQueue] = {}
        self._pedestrian_queues: Dict[str, List[Pedestrian]] = {}
        self._light_states: Dict[str, str] = {}
        self._lane_to_light: Dict[str, str] = {}
        self._spawn_rate = settings.simulation_spawn_rate
        self._speed = settings.simulation_speed
        self._total_spawned = {"car": 0, "truck": 0, "bus": 0, "pedestrian": 0, "emergency": 0}
        self._total_passed = {"car": 0, "truck": 0, "bus": 0, "pedestrian": 0, "emergency": 0}
        self._start_time = time.monotonic()
        self._tick_count = 0
        self._task: Optional[asyncio.Task] = None
        self._vehicle_counter = 0
        self._pedestrian_counter = 0

    def configure(self, lanes: List[str], crossings: List[str], lane_to_light: Dict[str, str]) -> None:
        for lane_id in lanes:
            if lane_id not in self._lane_queues:
                self._lane_queues[lane_id] = LaneQueue(lane_id=lane_id)
        for crossing_id in crossings:
            if crossing_id not in self._pedestrian_queues:
                self._pedestrian_queues[crossing_id] = []
        self._lane_to_light = lane_to_light
        logger.info(f"Simulation configured: {len(lanes)} lanes, {len(crossings)} crossings")

    def update_light_states(self, states: Dict[str, str]) -> None:
        self._light_states = states

    def _next_vehicle_id(self) -> str:
        self._vehicle_counter += 1
        return f"V{self._vehicle_counter:04d}"

    def _next_pedestrian_id(self) -> str:
        self._pedestrian_counter += 1
        return f"P{self._pedestrian_counter:04d}"

    def _spawn_vehicles(self) -> None:
        for lane_id, queue in self._lane_queues.items():
            if len(queue.vehicles) >= 20:
                continue
            for vtype, prob in self.SPAWN_PROBABILITIES.items():
                if random.random() < prob * self._spawn_rate * self._speed:
                    v = Vehicle(
                        id=self._next_vehicle_id(),
                        vehicle_type=vtype,
                        lane_id=lane_id,
                        spawn_time=time.monotonic(),
                    )
                    queue.vehicles.append(v)
                    self._total_spawned[vtype] = self._total_spawned.get(vtype, 0) + 1

    def _spawn_pedestrians(self) -> None:
        for crossing_id, peds in self._pedestrian_queues.items():
            if len(peds) >= 15:
                continue
            if random.random() < self._spawn_rate * 0.4 * self._speed:
                p = Pedestrian(
                    id=self._next_pedestrian_id(),
                    crossing_id=crossing_id,
                    spawn_time=time.monotonic(),
                )
                peds.append(p)
                self._total_spawned["pedestrian"] = self._total_spawned.get("pedestrian", 0) + 1

    def _process_queues(self) -> None:
        now = time.monotonic()
        for lane_id, queue in self._lane_queues.items():
            light_id = self._lane_to_light.get(lane_id)
            light_state = self._light_states.get(light_id, "RED") if light_id else "RED"

            for v in queue.vehicles:
                if not v.passed:
                    v.wait_time = now - v.spawn_time

            if light_state == "GREEN":
                # Let through some vehicles per tick
                max_pass = max(1, int(3 * self._speed))
                passed = 0
                remaining = []
                for v in queue.vehicles:
                    if not v.passed and passed < max_pass:
                        v.passed = True
                        self._total_passed[v.vehicle_type] = self._total_passed.get(v.vehicle_type, 0) + 1
                        queue.throughput += 1
                        passed += 1
                    else:
                        remaining.append(v)
                queue.vehicles = remaining

    def _process_pedestrians(self) -> None:
        now = time.monotonic()
        for crossing_id, peds in self._pedestrian_queues.items():
            for p in peds:
                if not p.passed:
                    p.wait_time = now - p.spawn_time

            # Pedestrians pass if corresponding light is green (simplified)
            remaining = []
            for p in peds:
                if not p.passed and random.random() < 0.1 * self._speed:
                    p.passed = True
                    self._total_passed["pedestrian"] += 1
                else:
                    remaining.append(p)
            self._pedestrian_queues[crossing_id] = remaining

    def get_traffic_data(self) -> Dict[str, Any]:
        """Return current traffic state for the controller and metrics."""
        queues: Dict[str, Dict] = {}
        total_wait_cars = 0.0
        total_cars = 0
        total_trucks = 0
        total_buses = 0

        for lane_id, queue in self._lane_queues.items():
            active = [v for v in queue.vehicles if not v.passed]
            cars = sum(1 for v in active if v.vehicle_type == "car")
            trucks = sum(1 for v in active if v.vehicle_type == "truck")
            buses = sum(1 for v in active if v.vehicle_type == "bus")
            wait_times = [v.wait_time for v in active]
            avg_wait = sum(wait_times) / len(wait_times) if wait_times else 0.0
            max_wait = max(wait_times) if wait_times else 0.0

            queues[lane_id] = {
                "cars": cars,
                "trucks": trucks,
                "buses": buses,
                "total": len(active),
                "avg_wait": round(avg_wait, 2),
                "max_wait": round(max_wait, 2),
                "throughput": queue.throughput,
            }
            total_cars += cars
            total_trucks += trucks
            total_buses += buses
            total_wait_cars += sum(wait_times)

        all_peds = []
        for peds in self._pedestrian_queues.values():
            all_peds.extend(p for p in peds if not p.passed)

        avg_car_wait = total_wait_cars / max(total_cars + total_trucks + total_buses, 1)
        avg_ped_wait = (
            sum(p.wait_time for p in all_peds) / len(all_peds) if all_peds else 0.0
        )

        elapsed = time.monotonic() - self._start_time
        cars_per_hour = self._total_passed.get("car", 0) / max(elapsed / 3600, 1/3600)

        return {
            "queues": queues,
            "summary": {
                "total_cars": total_cars,
                "total_trucks": total_trucks,
                "total_buses": total_buses,
                "total_pedestrians": len(all_peds),
                "pedestrians_waiting": len(all_peds),
                "avg_car_wait": round(avg_car_wait, 2),
                "avg_pedestrian_wait": round(avg_ped_wait, 2),
                "cars_per_hour": round(cars_per_hour, 1),
                "throughput": sum(q.throughput for q in self._lane_queues.values()),
            },
            "spawned": dict(self._total_spawned),
            "passed": dict(self._total_passed),
        }

    async def run(self) -> None:
        self._running = True
        logger.info("Simulation engine started")
        while self._running:
            try:
                self._spawn_vehicles()
                self._spawn_pedestrians()
                self._process_queues()
                self._process_pedestrians()
                self._tick_count += 1
            except Exception as e:
                logger.error(f"Simulation tick error: {e}")
            await asyncio.sleep(1.0 / max(self._speed, 0.1))

    async def start(self) -> None:
        self._start_time = time.monotonic()
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Simulation engine stopped")

    def reset(self) -> None:
        for queue in self._lane_queues.values():
            queue.vehicles.clear()
            queue.throughput = 0
        for peds in self._pedestrian_queues.values():
            peds.clear()
        self._total_spawned = {k: 0 for k in self._total_spawned}
        self._total_passed = {k: 0 for k in self._total_passed}
        self._start_time = time.monotonic()
        self._tick_count = 0
        logger.info("Simulation reset")

    def set_speed(self, speed: float) -> None:
        self._speed = max(0.1, min(10.0, speed))

    @property
    def is_running(self) -> bool:
        return self._running
