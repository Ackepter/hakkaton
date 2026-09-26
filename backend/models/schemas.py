from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Dict, Any
from enum import Enum


class LightState(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    FLASHING_YELLOW = "FLASHING_YELLOW"
    OFF = "OFF"


class SystemMode(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    FAILSAFE = "FAILSAFE"


class LaneType(str, Enum):
    CAR = "car"
    BUS = "bus"
    TRAM = "tram"
    BIKE = "bike"
    PEDESTRIAN = "pedestrian"
    REVERSIBLE = "reversible"
    EMERGENCY = "emergency"
    MIXED = "mixed"


class Direction(str, Enum):
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    NORTH_EAST = "north_east"
    NORTH_WEST = "north_west"
    SOUTH_EAST = "south_east"
    SOUTH_WEST = "south_west"


# --- Intersection objects ---

class Position(BaseModel):
    x: float
    y: float


class GridPosition(BaseModel):
    col: int
    row: int


class Lane(BaseModel):
    id: str
    type: LaneType = LaneType.CAR
    direction: Optional[Direction] = None
    start: GridPosition
    end: GridPosition
    width: int = 1
    priority: float = 1.0
    speed_limit: int = 60


class TrafficLightConfig(BaseModel):
    id: str
    position: GridPosition
    direction: Optional[Direction] = None
    lane_ids: List[str] = []
    phase_sequence: List[Dict[str, Any]] = Field(
        default_factory=lambda: [
            {"state": "RED", "duration": 30},
            {"state": "YELLOW", "duration": 3},
            {"state": "GREEN", "duration": 30},
            {"state": "YELLOW", "duration": 3},
        ]
    )
    priority: float = 1.0
    conflict_ids: List[str] = []


class PedestrianCrossing(BaseModel):
    id: str
    start: GridPosition
    end: GridPosition
    traffic_light_id: Optional[str] = None


class Camera(BaseModel):
    id: str
    position: GridPosition
    zone_ids: List[str] = []
    fov_angle: float = 90.0


class DetectionZone(BaseModel):
    id: str
    lane_id: Optional[str] = None
    top_left: GridPosition
    bottom_right: GridPosition
    zone_type: Literal["vehicle", "pedestrian", "mixed"] = "vehicle"


class TramTrack(BaseModel):
    id: str
    start: GridPosition
    end: GridPosition
    direction: Optional[Direction] = None


class IntersectionConfig(BaseModel):
    id: str = "main"
    name: str = "Smart Intersection"
    grid_cols: int = 20
    grid_rows: int = 20
    cell_size: int = 40
    lanes: List[Lane] = []
    traffic_lights: List[TrafficLightConfig] = []
    pedestrian_crossings: List[PedestrianCrossing] = []
    cameras: List[Camera] = []
    detection_zones: List[DetectionZone] = []
    tram_tracks: List[TramTrack] = []
    direction_priorities: Dict[str, float] = {
        "north": 1.0, "south": 1.0, "east": 1.0, "west": 1.0,
        "pedestrian": 1.3,
    }


# --- Traffic light state ---

class TrafficLightState(BaseModel):
    id: str
    state: LightState
    phase_index: int
    time_in_phase: float
    time_remaining: float
    direction: Optional[str] = None
    lane_ids: List[str] = []


# --- Metrics ---

class QueueMetrics(BaseModel):
    lane_id: str
    cars: int = 0
    trucks: int = 0
    buses: int = 0
    pedestrians: int = 0
    avg_wait_time: float = 0.0
    max_wait_time: float = 0.0


class TrafficMetrics(BaseModel):
    total_cars: int = 0
    total_trucks: int = 0
    total_buses: int = 0
    total_pedestrians: int = 0
    cars_per_hour: float = 0.0
    pedestrians_waiting: int = 0
    avg_car_wait: float = 0.0
    avg_pedestrian_wait: float = 0.0
    flow_intensity: float = 0.0
    throughput: int = 0
    queue_lengths: Dict[str, int] = {}


class SystemMetrics(BaseModel):
    camera_fps: float = 0.0
    camera_status: str = "simulation"
    yolo_status: str = "simulation"
    system_mode: SystemMode = SystemMode.AUTO
    uptime_seconds: float = 0.0
    phase_switches: int = 0
    error_count: int = 0
    failsafe_reason: Optional[str] = None


class MetricsSnapshot(BaseModel):
    timestamp: float
    traffic: TrafficMetrics
    system: SystemMetrics
    queues: List[QueueMetrics] = []
    lights: List[TrafficLightState] = []


# --- API request/response models ---

class ModeChangeRequest(BaseModel):
    mode: SystemMode


class ManualLightCommand(BaseModel):
    light_id: str
    state: LightState


class SimulationControl(BaseModel):
    action: Literal["start", "stop", "reset"]
    speed: Optional[float] = None


class LightPhasesUpdate(BaseModel):
    light_id: str
    phases: List[Dict[str, Any]]


class PriorityUpdate(BaseModel):
    direction_priorities: Dict[str, float]
