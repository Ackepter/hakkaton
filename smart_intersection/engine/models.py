"""
Data models for Smart Intersection simulation.
Pure dataclasses — no dependencies on FastAPI or the main project.
"""
from dataclasses import dataclass, field
from typing import Optional


# ---------- Vehicle ----------

VEHICLE_DEFAULTS = {
    "car":       {"max_speed": 13.9, "length_m": 4.5,  "accel": 3.0, "decel": 5.0, "color": "car"},
    "truck":     {"max_speed": 11.0, "length_m": 12.0, "accel": 1.5, "decel": 3.5, "color": "truck"},
    "bus":       {"max_speed": 11.0, "length_m": 12.0, "accel": 1.5, "decel": 3.5, "color": "bus"},
    "tram":      {"max_speed": 9.0,  "length_m": 20.0, "accel": 1.0, "decel": 2.5, "color": "tram"},
    "emergency": {"max_speed": 16.7, "length_m": 5.5,  "accel": 4.0, "decel": 6.0, "color": "emergency"},
    "taxi":      {"max_speed": 13.9, "length_m": 4.5,  "accel": 3.0, "decel": 5.0, "color": "taxi"},
    "motorcycle":{"max_speed": 16.7, "length_m": 2.2,  "accel": 5.0, "decel": 7.0, "color": "motorcycle"},
    "bicycle":   {"max_speed": 5.5,  "length_m": 1.8,  "accel": 1.5, "decel": 3.0, "color": "bicycle"},
}

VEHICLE_STATES = ("driving", "decelerating", "waiting", "passing", "finished")
PEDESTRIAN_STATES = ("walking_to_crossing", "waiting_for_green", "crossing", "finished")


@dataclass
class Vehicle:
    id: str
    vehicle_type: str        # car/truck/bus/tram/emergency
    lane_id: str             # e.g. "north-in"
    direction: str           # north/south/east/west (incoming direction)
    position_m: float        # meters from entry point (0 = spawn point)
    speed_mps: float         # current speed m/s
    max_speed: float         # max speed m/s
    length_m: float          # vehicle length m
    accel: float             # max acceleration m/s²
    decel: float             # max deceleration m/s²
    state: str               # VEHICLE_STATES
    spawn_time: float        # simulation time at spawn
    wait_time: float         # accumulated wait time
    passed_intersection: bool = False


@dataclass
class Pedestrian:
    id: str
    crossing_id: str          # e.g. "PC-N"
    state: str                # PEDESTRIAN_STATES
    spawn_time: float
    wait_time: float
    position_m: float = 0.0  # meters across the crossing (0 = waiting side, max = other side)
    crossing_width: float = 12.0  # meters to cross (2 lanes × 4m + median)
    speed_mps: float = 1.4   # average walking speed
    direction: int = 1        # +1 / -1: which side of the crosswalk the pedestrian starts from
    offset: float = 0.0       # lateral lane inside the crosswalk band (meters)
    stand_position: float = 0.0  # where the pedestrian waits (0 = curb, negative = queued behind it)


@dataclass
class SimTrafficLight:
    id: str
    direction: str        # north/south/east/west
    state: str            # RED/YELLOW/GREEN
    phase_index: int
    phase_start_time: float
    phase_duration: float
    phase_switches: int
    lane_ids: list        # which lanes this light controls


@dataclass
class Lane:
    id: str
    direction: str        # north/south/east/west
    is_inbound: bool      # True = approaching intersection, False = leaving
    length_m: float       # meters
    width_m: float = 4.0
    stop_line_m: float = 0.0  # meters from entry where stop line is (inbound only)
    traffic_light_id: Optional[str] = None
    spawn_pos: float = 0.0    # position_m where vehicles enter (arms shorter than 80 m start later)
    speed_limit: float = 25.0 # m/s


@dataclass
class PedestrianCrossing:
    id: str
    direction: str        # which road arm: north/south/east/west
    traffic_light_id: str # pedestrian signal (GREEN = walk)
    waiting_peds: int = 0
    crossing_peds: int = 0


@dataclass
class SimulationState:
    """Complete snapshot of simulation state for XML export."""
    sim_time: float
    real_time: float
    time_scale: float
    status: str           # running/paused/stopped
    scenario: str
    intersection_id: str
    vehicles: list        # List[Vehicle]
    pedestrians: list     # List[Pedestrian]
    lights: list          # List[SimTrafficLight]
    metrics: dict
    seed: int
