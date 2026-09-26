"""
Traffic Generator — spawns vehicles and pedestrians with configurable rates.
"""
import math
import random
from typing import Dict, Optional
from .models import Vehicle, Pedestrian, VEHICLE_DEFAULTS


class SpawnManager:
    """
    Spawns vehicles and pedestrians based on configurable rates.
    All rates are in units per minute.
    """

    DEFAULT_TYPE_PROBS = {
        "car": 0.75,
        "truck": 0.10,
        "bus": 0.10,
        "tram": 0.04,
        "emergency": 0.01,
    }

    DEFAULT_DIR_PROBS = {
        "north": 0.25,
        "south": 0.25,
        "east": 0.25,
        "west": 0.25,
    }

    def __init__(
        self,
        spawn_rate: float = 12.0,
        ped_spawn_rate: float = 5.0,
        type_probs: Dict[str, float] = None,
        direction_probs: Dict[str, float] = None,
        rng: random.Random = None,
    ):
        self.spawn_rate = spawn_rate          # vehicles/minute
        self.ped_spawn_rate = ped_spawn_rate  # pedestrians/minute
        self.type_probs = type_probs or dict(self.DEFAULT_TYPE_PROBS)
        self.direction_probs = direction_probs or dict(self.DEFAULT_DIR_PROBS)
        self._rng = rng or random.Random()
        self._vehicle_counter = 0
        self._ped_counter = 0
        self._crossing_counts: Dict[str, int] = {}
        self.arm_weights: Dict[str, float] = {}        # per-arm arrival weight (0 = arm missing)
        self.arm_types: Dict[str, Optional[str]] = {}  # per-arm vehicle type (bus lane / tram track)

    def try_spawn_vehicles(self, sim_time: float, dt: float):
        """
        Poisson-based spawning. Returns list of new Vehicle objects.
        """
        expected = (self.spawn_rate / 60.0) * dt
        count = self._poisson(expected)
        vehicles = []
        for _ in range(count):
            v = self._create_vehicle(sim_time)
            if v:
                vehicles.append(v)
        return vehicles

    def try_spawn_pedestrians(self, sim_time: float, dt: float, crossings: list):
        """Returns list of new Pedestrian objects."""
        expected = (self.ped_spawn_rate / 60.0) * dt
        count = self._poisson(expected)
        peds = []
        for _ in range(count):
            if not crossings:
                break
            crossing_id = self._rng.choice(crossings)
            self._ped_counter += 1
            n = self._crossing_counts.get(crossing_id, 0)
            self._crossing_counts[crossing_id] = n + 1
            # alternate sides; the engine assigns the exact lane / queue slot
            p = Pedestrian(
                id=f"ped-{self._ped_counter:04d}",
                crossing_id=crossing_id,
                state="walking_to_crossing",
                spawn_time=sim_time,
                wait_time=0.0,
                position_m=-2.5,
                direction=1 if n % 2 == 0 else -1,
            )
            peds.append(p)
        return peds

    def _create_vehicle(self, sim_time: float):
        weights = {d: p * self.arm_weights.get(d, 1.0) for d, p in self.direction_probs.items()}
        direction = self._weighted_choice(weights)
        if not direction:
            return None
        vtype = self.arm_types.get(direction) or self._weighted_choice(self.type_probs)
        if not vtype:
            return None
        return self.make_vehicle(direction, vtype, sim_time)

    def make_vehicle(self, direction: str, vtype: str, sim_time: float):
        if vtype not in VEHICLE_DEFAULTS:
            return None
        defaults = VEHICLE_DEFAULTS.get(vtype, VEHICLE_DEFAULTS["car"])
        self._vehicle_counter += 1
        return Vehicle(
            id=f"{vtype}-{self._vehicle_counter:04d}",
            vehicle_type=vtype,
            lane_id=f"{direction}-in",
            direction=direction,
            position_m=0.0,
            speed_mps=defaults["max_speed"] * 0.8,
            max_speed=defaults["max_speed"],
            length_m=defaults["length_m"],
            accel=defaults["accel"],
            decel=defaults["decel"],
            state="driving",
            spawn_time=sim_time,
            wait_time=0.0,
        )

    def _weighted_choice(self, probs: Dict[str, float]) -> str:
        keys = list(probs.keys())
        weights = [probs[k] for k in keys]
        total = sum(weights)
        if total <= 0:
            return None
        r = self._rng.random() * total
        cum = 0.0
        for k, w in zip(keys, weights):
            cum += w
            if r <= cum:
                return k
        return keys[-1]

    def _poisson(self, lam: float) -> int:
        """Approximate Poisson sample."""
        if lam <= 0:
            return 0
        lam = min(lam, 30.0)
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while p > L:
            k += 1
            p *= self._rng.random()
        return k - 1

    def update_config(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def make_pedestrian(self, crossing_id: str, sim_time: float) -> Pedestrian:
        self._ped_counter += 1
        n = self._crossing_counts.get(crossing_id, 0)
        self._crossing_counts[crossing_id] = n + 1
        return Pedestrian(id=f"ped-{self._ped_counter:04d}", crossing_id=crossing_id, state="walking_to_crossing",
                          spawn_time=sim_time, wait_time=0.0, position_m=-2.5, direction=1 if n % 2 == 0 else -1)

    def add_emergency_vehicle(self, sim_time: float, direction: str = "north") -> Vehicle:
        """Spawn a single emergency vehicle immediately."""
        defaults = VEHICLE_DEFAULTS["emergency"]
        self._vehicle_counter += 1
        return Vehicle(
            id=f"emergency-{self._vehicle_counter:04d}",
            vehicle_type="emergency",
            lane_id=f"{direction}-in",
            direction=direction,
            position_m=0.0,
            speed_mps=defaults["max_speed"],
            max_speed=defaults["max_speed"],
            length_m=defaults["length_m"],
            accel=defaults["accel"],
            decel=defaults["decel"],
            state="driving",
            spawn_time=sim_time,
            wait_time=0.0,
        )
