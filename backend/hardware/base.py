from abc import ABC, abstractmethod
from typing import Dict


class HardwareInterface(ABC):
    """Abstract hardware interface for traffic light control."""

    @abstractmethod
    def set_light(self, light_id: str, red: bool, yellow: bool, green: bool) -> None:
        """Set the physical state of a traffic light."""

    @abstractmethod
    def get_light_state(self, light_id: str) -> Dict[str, bool]:
        """Get the physical pin states for a traffic light."""

    @abstractmethod
    def cleanup(self) -> None:
        """Release hardware resources."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize hardware."""
