"""
Application state — single instance shared across all routes.
"""
import json
import logging
import os
from typing import Optional

import yaml

from .config.settings import settings
from .hardware.mock_gpio import MockGPIO
from .models.schemas import IntersectionConfig
from .traffic.controller import TrafficController
from .simulation.simulator import SimulationEngine
from .metrics.collector import MetricsCollector
from .vision import VisionManager, build_manager, load_cameras, perception_payload
from .vision.bridge import SimulationBridge

logger = logging.getLogger(__name__)


class AppState:
    def __init__(self):
        hardware = MockGPIO()
        self.controller = TrafficController(hardware)
        self.simulator = SimulationEngine()
        self.metrics = MetricsCollector()
        self.intersection: Optional[IntersectionConfig] = None
        self._config_path = settings.intersection_config_path
        self.vision: Optional[VisionManager] = None
        self.bridge: Optional[SimulationBridge] = None

    # ---- vision (cameras -> detection -> analysis); optional, never required to run the backend
    async def start_vision(self) -> None:
        if not settings.vision_enabled:
            logger.info("Vision disabled (VISION_ENABLED=false)")
            return
        try:
            configs = load_cameras(settings.vision_config_path, settings)
        except (ValueError, OSError, yaml.YAMLError) as e:
            logger.error("Camera configuration is invalid, vision not started: %s", e)
            return
        for c in configs:
            if c.source == "simulation" and not c.uri:
                c.uri = settings.si_base_url
        if settings.vision_push_to_simulation and any(c.source == "simulation" for c in configs):
            self.bridge = SimulationBridge(settings.si_base_url)
        self.vision = build_manager(configs, ped_priority_threshold=settings.pedestrian_priority_threshold,
                                    on_health=self._vision_health, on_snapshot=self._vision_snapshot)
        await self.vision.start()
        logger.info("Vision started: %s", ", ".join(f"{p.cfg.id}({p.cfg.source}/{p.cfg.detector})"
                                                    for p in self.vision.pipelines.values()) or "no cameras")

    async def stop_vision(self) -> None:
        if self.vision:
            await self.vision.stop()
        if self.bridge:
            await self.bridge.release()
            await self.bridge.close()
        self.vision = self.bridge = None
        self.controller.set_data_health(True)

    async def _vision_health(self, healthy: bool, reason: str) -> None:
        self.controller.set_data_health(healthy, reason)
        if not healthy and self.bridge:
            await self.bridge.push(perception_payload(None, False), force=True)

    async def _vision_snapshot(self, snap, healthy: bool) -> None:
        if self.bridge:
            await self.bridge.push(perception_payload(snap, healthy))

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
