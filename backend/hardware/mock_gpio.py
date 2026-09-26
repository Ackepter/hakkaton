import logging
from typing import Dict
from .base import HardwareInterface

logger = logging.getLogger(__name__)


class MockGPIO(HardwareInterface):
    """Mock GPIO for development without Raspberry Pi hardware."""

    def __init__(self):
        self._states: Dict[str, Dict[str, bool]] = {}

    def initialize(self) -> None:
        logger.info("MockGPIO initialized (no physical hardware)")

    def set_light(self, light_id: str, red: bool, yellow: bool, green: bool) -> None:
        prev = self._states.get(light_id, {})
        self._states[light_id] = {"red": red, "yellow": yellow, "green": green}

        active = [c for c, v in {"RED": red, "YELLOW": yellow, "GREEN": green}.items() if v]
        state_str = ", ".join(active) if active else "OFF"

        if prev != self._states[light_id]:
            logger.debug(f"MockGPIO [{light_id}] → {state_str}")

    def get_light_state(self, light_id: str) -> Dict[str, bool]:
        return self._states.get(light_id, {"red": False, "yellow": False, "green": False})

    def get_all_states(self) -> Dict[str, Dict[str, bool]]:
        return dict(self._states)

    def cleanup(self) -> None:
        for light_id in list(self._states.keys()):
            self._states[light_id] = {"red": False, "yellow": False, "green": False}
        logger.info("MockGPIO cleaned up")
