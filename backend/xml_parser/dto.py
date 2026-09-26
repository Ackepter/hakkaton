"""
Data Transfer Objects for parsed SI XML.
Plain dataclasses — no FastAPI dependency.
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class VehicleDTO:
    id: str
    vehicle_type: str
    lane_id: str
    direction: str
    position_m: float
    speed_mps: float
    state: str
    wait_time: float


@dataclass
class PedestrianDTO:
    id: str
    crossing_id: str
    state: str
    position_m: float
    wait_time: float


@dataclass
class LightDTO:
    id: str
    direction: str
    state: str
    phase_index: int
    phase_switches: int


@dataclass
class MetricsDTO:
    vehicles_active: int
    vehicles_waiting: int
    passed_total: int
    avg_wait_s: float
    max_wait_s: float
    throughput_per_min: float
    congestion_pct: float
    efficiency_pct: float


@dataclass
class SimulationInfoDTO:
    intersection_id: str
    status: str
    sim_time: float
    time_scale: float
    scenario: str
    seed: int


@dataclass
class IntersectionData:
    simulation: SimulationInfoDTO
    lights: List[LightDTO] = field(default_factory=list)
    vehicles: List[VehicleDTO] = field(default_factory=list)
    pedestrians: List[PedestrianDTO] = field(default_factory=list)
    metrics: Optional[MetricsDTO] = None
