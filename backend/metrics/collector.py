import time
import logging
from collections import deque
from typing import Dict, List, Any, Deque
from ..models.schemas import SystemMode

logger = logging.getLogger(__name__)

MAX_HISTORY = 300  # 5 minutes at 1 sample/sec


class MetricsCollector:
    """Collects and stores traffic metrics for dashboard display."""

    def __init__(self):
        self._start_time = time.monotonic()
        self._history: Deque[Dict] = deque(maxlen=MAX_HISTORY)
        self._latest: Dict = {}
        self._system_mode = SystemMode.AUTO
        self._camera_status = "simulation"
        self._yolo_status = "simulation"
        self._camera_fps = 0.0
        self._error_count = 0
        self._failsafe_reason = None
        self._phase_switches = 0

    def update(
        self,
        traffic_data: Dict[str, Any],
        light_states: List[Dict],
        mode: SystemMode,
        phase_switches: int,
        failsafe_reason: str = None,
    ) -> None:
        now = time.monotonic()
        summary = traffic_data.get("summary", {})
        queues = traffic_data.get("queues", {})

        snapshot = {
            "timestamp": now - self._start_time,
            "ts_abs": time.time(),
            "traffic": {
                "total_cars": summary.get("total_cars", 0),
                "total_trucks": summary.get("total_trucks", 0),
                "total_buses": summary.get("total_buses", 0),
                "total_pedestrians": summary.get("total_pedestrians", 0),
                "pedestrians_waiting": summary.get("pedestrians_waiting", 0),
                "avg_car_wait": summary.get("avg_car_wait", 0.0),
                "avg_pedestrian_wait": summary.get("avg_pedestrian_wait", 0.0),
                "cars_per_hour": summary.get("cars_per_hour", 0.0),
                "throughput": summary.get("throughput", 0),
                "flow_intensity": self._calc_flow_intensity(summary),
                "queue_lengths": {lid: q.get("total", 0) for lid, q in queues.items()},
            },
            "system": {
                "camera_fps": self._camera_fps,
                "camera_status": self._camera_status,
                "yolo_status": self._yolo_status,
                "system_mode": mode.value,
                "uptime_seconds": round(now - self._start_time, 1),
                "phase_switches": phase_switches,
                "error_count": self._error_count,
                "failsafe_reason": failsafe_reason,
            },
            "lights": light_states,
            "queues": [
                {
                    "lane_id": lid,
                    "cars": q.get("cars", 0),
                    "trucks": q.get("trucks", 0),
                    "buses": q.get("buses", 0),
                    "pedestrians": q.get("pedestrians", 0),
                    "avg_wait_time": q.get("avg_wait", 0.0),
                    "max_wait_time": q.get("max_wait", 0.0),
                }
                for lid, q in queues.items()
            ],
            # Additional metrics
            "extra": {
                "efficiency_score": self._calc_efficiency_score(summary),
                "pedestrian_risk": self._calc_pedestrian_risk(summary),
                "congestion_level": self._calc_congestion_level(queues),
            },
        }

        self._latest = snapshot
        self._history.append(snapshot)

    def _calc_flow_intensity(self, summary: Dict) -> float:
        """Vehicles per minute across all lanes."""
        total = summary.get("cars_per_hour", 0.0)
        return round(total / 60, 2)

    def _calc_efficiency_score(self, summary: Dict) -> float:
        """
        0–100 score. Higher = better.
        Based on average wait time: 0s = 100, 60s = 0.
        """
        avg_wait = summary.get("avg_car_wait", 0.0)
        score = max(0.0, 100.0 - avg_wait * 1.67)
        return round(score, 1)

    def _calc_pedestrian_risk(self, summary: Dict) -> str:
        """LOW / MEDIUM / HIGH based on pedestrian wait time."""
        avg_wait = summary.get("avg_pedestrian_wait", 0.0)
        if avg_wait < 20:
            return "LOW"
        elif avg_wait < 45:
            return "MEDIUM"
        return "HIGH"

    def _calc_congestion_level(self, queues: Dict) -> str:
        """CLEAR / MODERATE / CONGESTED / GRIDLOCK."""
        if not queues:
            return "CLEAR"
        total = sum(q.get("total", 0) for q in queues.values())
        avg = total / len(queues)
        if avg < 3:
            return "CLEAR"
        elif avg < 7:
            return "MODERATE"
        elif avg < 12:
            return "CONGESTED"
        return "GRIDLOCK"

    def set_camera_status(self, status: str, fps: float = 0.0) -> None:
        self._camera_status = status
        self._camera_fps = fps

    def set_yolo_status(self, status: str) -> None:
        self._yolo_status = status

    def increment_errors(self) -> None:
        self._error_count += 1

    def get_latest(self) -> Dict:
        return self._latest

    def get_history(self, seconds: int = 60) -> List[Dict]:
        cutoff = (time.monotonic() - self._start_time) - seconds
        return [s for s in self._history if s.get("timestamp", 0) >= cutoff]

    def get_chart_data(self, metric: str, seconds: int = 60) -> List[Dict]:
        """Return time-series data for a specific metric for charts."""
        history = self.get_history(seconds)
        result = []
        for snap in history:
            ts = snap.get("timestamp", 0)
            value = snap.get("traffic", {}).get(metric)
            if value is not None:
                result.append({"t": round(ts, 1), "v": value})
        return result
