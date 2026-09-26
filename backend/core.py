"""
Application state — single instance shared across all routes.
"""
import json
import logging
import os
from typing import Optional

from .config.settings import settings
from .hardware.mock_gpio import MockGPIO
from .models.schemas import IntersectionConfig
from .traffic.controller import TrafficController
from .simulation.simulator import SimulationEngine
from .metrics.collector import MetricsCollector

logger = logging.getLogger(__name__)


class AppState:
    def __init__(self):
        hardware = MockGPIO()
        self.controller = TrafficController(hardware)
        self.simulator = SimulationEngine()
        self.metrics = MetricsCollector()
        self.intersection: Optional[IntersectionConfig] = None
        self._config_path = settings.intersection_config_path

    def load_intersection(self, config: IntersectionConfig) -> None:
        self.intersection = config
        self.controller.load_config(config)

        lane_ids = [l.id for l in config.lanes]
        crossing_ids = [c.id for c in config.pedestrian_crossings]
        lane_to_light: dict = {}
        for tl in config.traffic_lights:
            for lane_id in tl.lane_ids:
                lane_to_light[lane_id] = tl.id
        self.simulator.configure(lane_ids, crossing_ids, lane_to_light)
        logger.info(f"Intersection loaded: {config.name}")

    def save_config_to_file(self) -> None:
        if not self.intersection:
            return
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self.intersection.model_dump(), f, indent=2, ensure_ascii=False)
        logger.info(f"Config saved to {self._config_path}")

    def load_config_from_file(self) -> bool:
        if not os.path.exists(self._config_path):
            return False
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            config = IntersectionConfig(**data)
            self.load_intersection(config)
            logger.info(f"Config loaded from {self._config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return False


app_state = AppState()
