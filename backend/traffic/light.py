import time
import logging
from typing import List, Dict, Optional, Any
from ..models.schemas import LightState

logger = logging.getLogger(__name__)


class Phase:
    def __init__(self, state: LightState, duration: float):
        self.state = state
        self.duration = duration


class TrafficLight:
    """Single traffic light with configurable phase sequence."""

    def __init__(
        self,
        light_id: str,
        phases: Optional[List[Dict[str, Any]]] = None,
        direction: Optional[str] = None,
        lane_ids: Optional[List[str]] = None,
        priority: float = 1.0,
        conflict_ids: Optional[List[str]] = None,
    ):
        self.id = light_id
        self.direction = direction
        self.lane_ids = lane_ids or []
        self.priority = priority
        self.conflict_ids = conflict_ids or []

        self._phases = self._build_phases(phases)
        self._phase_index = 0
        self._phase_start = time.monotonic()
        self._state = self._phases[0].state if self._phases else LightState.RED
        self._phase_switches = 0
        self._total_green_time = 0.0
        self._total_red_time = 0.0

    def _build_phases(self, raw: Optional[List[Dict[str, Any]]]) -> List[Phase]:
        default = [
            {"state": "RED", "duration": 30},
            {"state": "YELLOW", "duration": 3},
            {"state": "GREEN", "duration": 30},
            {"state": "YELLOW", "duration": 3},
        ]
        source = raw if raw else default
        return [Phase(LightState(p["state"]), float(p["duration"])) for p in source]

    @property
    def state(self) -> LightState:
        return self._state

    @property
    def phase_index(self) -> int:
        return self._phase_index

    @property
    def time_in_phase(self) -> float:
        return time.monotonic() - self._phase_start

    @property
    def time_remaining(self) -> float:
        elapsed = self.time_in_phase
        duration = self._phases[self._phase_index].duration
        return max(0.0, duration - elapsed)

    @property
    def phase_switches(self) -> int:
        return self._phase_switches

    def tick(self) -> bool:
        """Advance time. Returns True if phase changed."""
        if not self._phases:
            return False
        elapsed = self.time_in_phase
        current_phase = self._phases[self._phase_index]
        if elapsed >= current_phase.duration:
            self._advance_phase()
            return True
        return False

    def _advance_phase(self):
        prev_state = self._state
        if prev_state == LightState.GREEN:
            self._total_green_time += self._phases[self._phase_index].duration
        elif prev_state == LightState.RED:
            self._total_red_time += self._phases[self._phase_index].duration

        self._phase_index = (self._phase_index + 1) % len(self._phases)
        self._phase_start = time.monotonic()
        self._state = self._phases[self._phase_index].state
        self._phase_switches += 1
        logger.debug(f"Light {self.id}: {prev_state.value} → {self._state.value}")

    def force_state(self, state: LightState) -> None:
        """Force light to specific state (manual mode)."""
        self._state = state
        self._phase_start = time.monotonic()
        logger.info(f"Light {self.id} forced to {state.value}")

    def set_phases(self, phases: List[Dict[str, Any]]) -> None:
        self._phases = self._build_phases(phases)
        self._phase_index = 0
        self._phase_start = time.monotonic()
        self._state = self._phases[0].state if self._phases else LightState.RED

    def set_phase_duration(self, state: LightState, duration: float) -> None:
        for phase in self._phases:
            if phase.state == state:
                phase.duration = duration

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "state": self._state.value,
            "phase_index": self._phase_index,
            "time_in_phase": round(self.time_in_phase, 2),
            "time_remaining": round(self.time_remaining, 2),
            "direction": self.direction,
            "lane_ids": self.lane_ids,
            "phase_switches": self._phase_switches,
            "total_green_time": round(self._total_green_time, 1),
            "total_red_time": round(self._total_red_time, 1),
        }
